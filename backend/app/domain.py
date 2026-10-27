import hashlib
import json
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from backend.app.models import Account, Budget, BudgetRule, Category, IdempotencyRecord, Investment, InvestmentEvent, Transaction, TransactionLifecycleEvent, Bill, Goal, GoalAllocation, GoalTrackingAccount, GoalContribution, CreditCard, CreditPurchase, Invoice, Installment, TransactionRevision, InvestmentValuation, NetWorthSnapshot, RecurringPlan, RecurringOccurrence
from backend.app.categories import category_visible_in_budget


def money(value: Decimal | str | int) -> Decimal:
    try:
        raw = Decimal(value)
        if not raw.is_finite() or raw != raw.quantize(Decimal("0.01")):
            raise InvalidOperation()
        result = raw.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "Valor monetário inválido")
    if not result.is_finite() or result <= 0:
        raise HTTPException(422, "O valor deve ser maior que zero")
    return result


def period_for(day: date) -> date:
    return day.replace(day=1)


def request_digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def account_balances(session: Session) -> list[dict]:
    accounts = session.scalars(select(Account).where(Account.is_active.is_(True))).all()
    results = []
    for account in accounts:
        rows = session.scalars(select(Transaction).where(Transaction.account_id == account.id, Transaction.status == "settled", Transaction.deleted_at.is_(None))).all()
        balance = account.opening_balance
        for row in rows:
            if row.kind in ("income", "refund", "transfer_in"):
                balance += row.amount
            elif row.kind in ("expense", "transfer_out", "investment"):
                balance -= row.amount
        results.append({"account_id": str(account.id), "name": account.name, "kind": account.kind, "balance": balance})
    return results


def create_transaction(session: Session, data: dict, idempotency_key: str | None = None, allow_card: bool = False) -> Transaction:
    amount = money(data["amount"])
    kind = data["kind"]
    if kind not in ("income", "expense", "refund"):
        raise HTTPException(422, "Tipo de transação inválido")
    if idempotency_key and (not idempotency_key.strip() or len(idempotency_key) > 120):
        raise HTTPException(422, "Chave de idempotência inválida")
    digest = request_digest(data)
    key_record = session.get(IdempotencyRecord, idempotency_key) if idempotency_key else None
    if key_record:
        if key_record.request_hash != digest:
            raise HTTPException(409, "Chave de idempotência já usada com dados diferentes")
        existing = session.get(Transaction, key_record.result_id)
        if existing:
            if existing.deleted_at is not None:
                raise HTTPException(409, "A operação com esta chave está na lixeira; restaure-a antes de repetir")
            return existing
    account_id = UUID(str(data["account_id"]))
    account = session.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(404, "Conta não encontrada ou inativa")
    if account.kind == "credit_card" and not allow_card:
        raise HTTPException(422, "Compras no cartão devem ser registradas como compra parcelada")
    category_id = UUID(str(data["category_id"])) if data.get("category_id") else None
    if kind == "expense" and category_id is None:
        raise HTTPException(422, "Despesa exige uma categoria")
    related_id = UUID(str(data["related_transaction_id"])) if data.get("related_transaction_id") else None
    if kind == "refund" and related_id:
        original = session.scalar(select(Transaction).where(Transaction.id == related_id).with_for_update())
        if not original or original.kind != "expense" or original.deleted_at is not None:
            raise HTTPException(422, "Reembolso precisa referenciar uma despesa existente")
        refunded = session.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.kind == "refund", Transaction.related_id == related_id, Transaction.status == "settled", Transaction.deleted_at.is_(None)
        )) or Decimal("0")
        if Decimal(refunded) + amount > original.amount:
            raise HTTPException(422, "Reembolso excede o valor restante da despesa original")
        if category_id and category_id != original.category_id:
            raise HTTPException(422, "A categoria do reembolso deve corresponder à despesa original")
        category_id = category_id or original.category_id
    if kind == "refund" and category_id is None:
        raise HTTPException(422, "Reembolso exige categoria ou despesa original")
    if kind == "refund" and data.get("status") == "pending":
        raise HTTPException(422, "Registre o reembolso somente quando ele for recebido")
    category = session.scalar(select(Category).where(Category.id == category_id).with_for_update()) if category_id else None
    if category_id and (not category or not category.is_active):
        raise HTTPException(404, "Categoria não encontrada ou inativa")
    if category and category.kind != ("income" if kind == "income" else "expense"):
        raise HTTPException(422, "Categoria incompatível com o tipo de movimentação")
    description = str(data.get("description", "")).strip()
    if not description or len(description) > 180:
        raise HTTPException(422, "Descrição deve ter entre 1 e 180 caracteres")
    requested_date = data["transaction_date"]
    if isinstance(requested_date, str):
        requested_date = date.fromisoformat(requested_date)
    tx = Transaction(
        kind=kind,
        amount=amount,
        account_id=account_id,
        category_id=category_id,
        description=description,
        transaction_date=requested_date,
        competence_date=data.get("competence_date") or requested_date.replace(day=1),
        status=data.get("status", "settled"),
        settled_date=(data.get("settled_date") or requested_date) if data.get("status", "settled") == "settled" else None,
        notes=data.get("notes"),
        related_id=related_id,
        idempotency_key=idempotency_key,
    )
    if tx.status not in ("settled", "pending"):
        raise HTTPException(422, "Situação inválida")
    session.add(tx)
    session.flush()
    if idempotency_key:
        session.add(IdempotencyRecord(key=idempotency_key, request_hash=digest, result_id=tx.id))
    return tx


def create_transfer(session: Session, source_id: UUID, dest_id: UUID, amount: Decimal, day: date, description: str, key: str | None = None, allow_card: bool = False):
    amount = money(amount)
    if source_id == dest_id:
        raise HTTPException(422, "Origem e destino precisam ser contas diferentes")
    source, target = session.get(Account, source_id), session.get(Account, dest_id)
    if not source or not target or not source.is_active or not target.is_active:
        raise HTTPException(404, "Conta de origem ou destino não encontrada")
    if (source.kind == "credit_card" or target.kind == "credit_card") and not allow_card:
        raise HTTPException(422, "Pagamento de cartão deve usar a fatura correspondente")
    if source.currency != target.currency:
        raise HTTPException(422, "Transferências entre moedas diferentes não são suportadas")
    digest = request_digest({"from": source_id, "to": dest_id, "amount": amount, "day": day, "description": description})
    if key and (record := session.get(IdempotencyRecord, key)):
        if record.request_hash != digest:
            raise HTTPException(409, "Chave de idempotência já usada com dados diferentes")
        existing = session.get(Transaction, record.result_id)
        if existing:
            if existing.deleted_at is not None:
                raise HTTPException(409, "A transferência está na lixeira; restaure-a")
            paired = session.get(Transaction, existing.related_id)
            return existing, paired
    outgoing_id, incoming_id = uuid4(), uuid4()
    outgoing = Transaction(id=outgoing_id, kind="transfer_out", amount=amount, account_id=source_id, description=description, transaction_date=day, competence_date=period_for(day), status="settled", settled_date=day, related_id=incoming_id)
    incoming = Transaction(id=incoming_id, kind="transfer_in", amount=amount, account_id=dest_id, description=description, transaction_date=day, competence_date=period_for(day), status="settled", settled_date=day, related_id=outgoing_id)
    if key:
        outgoing.idempotency_key = key
    session.add_all([outgoing, incoming])
    session.flush()
    if key:
        session.add(IdempotencyRecord(key=key, request_hash=digest, result_id=outgoing.id))
    return outgoing, incoming


def spend_by_category(session: Session, start: date, end: date) -> list[dict]:
    financial_date = func.coalesce(Transaction.settled_date, Transaction.transaction_date)
    rows = session.execute(
        select(Category.id, Category.name, Category.is_entertainment, Category.color, Category.icon, func.coalesce(func.sum(case((Transaction.kind == "refund", -Transaction.amount), else_=Transaction.amount)), 0))
        .join(Transaction, Transaction.category_id == Category.id)
        .where(Transaction.kind.in_(["expense", "refund"]), Transaction.status == "settled", Transaction.deleted_at.is_(None), financial_date >= start, financial_date <= end)
        .group_by(Category.id)
    ).all()
    return [{"category_id": str(row[0]), "category": row[1], "is_entertainment": row[2], "color": row[3], "icon": row[4], "spent": Decimal(row[5])} for row in rows]


def budget_cycle(rule: BudgetRule, day: date) -> tuple[date, date]:
    """Return an inclusive start and exclusive end without cumulative month drift."""
    anchor = rule.effective_start
    if rule.period_type == "calendar_month":
        start = max(anchor, period_for(day))
        return start, shift_month(period_for(day), 1, 1)
    if rule.period_type in ("days", "weeks"):
        length = rule.interval_count * (7 if rule.period_type == "weeks" else 1)
        step = (day - anchor).days // length
        return anchor + timedelta(days=step * length), anchor + timedelta(days=(step + 1) * length)
    if rule.period_type == "monthly_day":
        wanted = rule.renewal_day or anchor.day
        candidate = date(day.year, day.month, min(wanted, monthrange(day.year, day.month)[1]))
        if candidate > day:
            candidate = shift_month(candidate, -1, wanted)
        if candidate >= anchor:
            return candidate, shift_month(candidate, 1, wanted)
        first = date(anchor.year, anchor.month, min(wanted, monthrange(anchor.year, anchor.month)[1]))
        return anchor, first if first > anchor else shift_month(first, 1, wanted)
    # Every N months, anchored to the original effective date (including day 31).
    elapsed = (day.year - anchor.year) * 12 + day.month - anchor.month
    step = max(0, elapsed // rule.interval_count)
    start = shift_month(anchor, step * rule.interval_count, anchor.day)
    if start > day:
        step -= 1
        start = shift_month(anchor, step * rule.interval_count, anchor.day)
    return start, shift_month(anchor, (step + 1) * rule.interval_count, anchor.day)


def preview_budget_cycle(effective_start: date, period_type: str, interval_count: int = 1,
                         renewal_day: int | None = None) -> dict:
    if period_type not in ("calendar_month", "monthly_day", "days", "weeks", "months"):
        raise HTTPException(422, "Periodicidade inválida")
    if not 1 <= interval_count <= 120 or (period_type in ("calendar_month", "monthly_day") and interval_count != 1):
        raise HTTPException(422, "Intervalo de renovação inválido")
    if period_type == "monthly_day" and (renewal_day is None or not 1 <= renewal_day <= 31):
        raise HTTPException(422, "Informe um dia de renovação entre 1 e 31")
    if period_type != "monthly_day" and renewal_day is not None:
        raise HTTPException(422, "Dia de renovação só vale para mensal em dia fixo")
    rule = BudgetRule(effective_start=effective_start, period_type=period_type,
                      interval_count=interval_count, renewal_day=renewal_day, limit_amount=Decimal("0"))
    start, end = budget_cycle(rule, effective_start)
    return {"effective_start": effective_start, "period_start": start,
            "period_end": end - timedelta(days=1), "next_renewal": end}


def active_budget(session: Session, category_id: UUID, day: date) -> tuple[Decimal, date, date, BudgetRule | None] | None:
    rule = session.scalar(select(BudgetRule).where(BudgetRule.category_id == category_id, BudgetRule.effective_start <= day).order_by(BudgetRule.effective_start.desc()).limit(1))
    if rule:
        start, end = budget_cycle(rule, day)
        next_rule = session.scalar(select(BudgetRule.effective_start).where(BudgetRule.category_id == category_id, BudgetRule.effective_start > day).order_by(BudgetRule.effective_start).limit(1))
        if next_rule and next_rule < end:
            end = next_rule
        return rule.limit_amount, start, end, rule
    start = period_for(day)
    legacy = session.scalar(select(Budget).where(Budget.category_id == category_id, Budget.period_start == start))
    if legacy:
        end = shift_month(start, 1, 1)
        next_rule = session.scalar(select(BudgetRule.effective_start).where(BudgetRule.category_id == category_id, BudgetRule.effective_start > day).order_by(BudgetRule.effective_start).limit(1))
        if next_rule and next_rule < end:
            end = next_rule
        return legacy.limit_amount, start, end, None
    return None


def budget_status(session: Session, day: date) -> list[dict]:
    financial_date = func.coalesce(Transaction.settled_date, Transaction.transaction_date)
    out = []
    for category in session.scalars(select(Category).where(Category.kind == "expense").order_by(Category.name)):
        if not category_visible_in_budget(category, day):
            continue
        active = active_budget(session, category.id, day)
        if not active:
            continue
        limit, start, end, rule = active
        spent = session.scalar(select(func.coalesce(func.sum(case((Transaction.kind == "refund", -Transaction.amount), else_=Transaction.amount)), 0)).where(
            Transaction.category_id == category.id,
            Transaction.kind.in_(["expense", "refund"]),
            Transaction.status == "settled",
            Transaction.deleted_at.is_(None),
            financial_date >= start,
            financial_date < end,
        )) or Decimal("0")
        projection = None
        today = date.today()
        elapsed = (today - start).days + 1
        if start <= today < end and elapsed >= 7:
            expense_days = session.scalars(select(financial_date).where(
                Transaction.category_id == category.id, Transaction.kind == "expense",
                Transaction.status == "settled", Transaction.deleted_at.is_(None), financial_date >= start,
                financial_date <= today
            )).all()
            if len(set(expense_days)) >= 3:
                projection = (Decimal(spent) / elapsed * (end - start).days).quantize(Decimal("0.01"))
        out.append({"category_id": str(category.id), "category": category.name, "color": category.color, "icon": category.icon, "is_active": category.is_active, "limit": limit, "spent": Decimal(spent), "remaining": limit - Decimal(spent), "percent_used": (Decimal(spent) / limit * 100) if limit else None, "state": "exceeded" if Decimal(spent) > limit else "at_limit" if Decimal(spent) == limit else "within", "projection": projection, "period_start": start, "period_end": end - timedelta(days=1), "next_renewal": end, "period_type": rule.period_type if rule else "calendar_month", "interval_count": rule.interval_count if rule else 1, "renewal_day": rule.renewal_day if rule else None})
    return out


def set_budget(session: Session, category_id: UUID, effective_start: date, limit_amount: Decimal,
               period_type: str = "calendar_month", interval_count: int = 1,
               renewal_day: int | None = None) -> BudgetRule:
    category = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if not category or not category.is_active or category.kind != "expense":
        raise HTTPException(422, "Selecione uma categoria de despesa ativa")
    try:
        limit_amount = Decimal(limit_amount)
        if not limit_amount.is_finite() or limit_amount < 0 or limit_amount != limit_amount.quantize(Decimal("0.01")):
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "Limite monetário inválido")
    preview_budget_cycle(effective_start, period_type, interval_count, renewal_day)
    row = session.scalar(select(BudgetRule).where(BudgetRule.category_id == category_id, BudgetRule.effective_start == effective_start))
    if row:
        row.limit_amount = limit_amount
        row.period_type = period_type
        row.interval_count = interval_count
        row.renewal_day = renewal_day
        row.is_migrated_seed = False
    else:
        row = BudgetRule(category_id=category_id, effective_start=effective_start, limit_amount=limit_amount,
                         period_type=period_type, interval_count=interval_count, renewal_day=renewal_day)
        session.add(row)
    for obsolete in session.scalars(select(BudgetRule).where(
            BudgetRule.category_id == category_id, BudgetRule.effective_start > effective_start,
            BudgetRule.is_migrated_seed.is_(True))).all():
        session.delete(obsolete)
    session.flush()
    return row


def monthly_comparison(session: Session, months: int = 6) -> list[dict]:
    if not 2 <= months <= 24:
        raise HTTPException(422, "Período deve ter de 2 a 24 meses")
    today = date.today().replace(day=1)
    out = []
    for delta in reversed(range(months)):
        start = shift_month(today, -delta, 1)
        end = date(start.year, start.month, monthrange(start.year, start.month)[1])
        financial_date = func.coalesce(Transaction.settled_date, Transaction.transaction_date)
        rows = session.scalars(select(Transaction).where(Transaction.status == "settled", Transaction.deleted_at.is_(None), financial_date >= start, financial_date <= end)).all()
        income = sum((t.amount for t in rows if t.kind == "income"), Decimal(0))
        expense = sum((t.amount for t in rows if t.kind == "expense"), Decimal(0)) - sum((t.amount for t in rows if t.kind == "refund"), Decimal(0))
        out.append({"month": start, "income": income, "expenses": expense, "result": income - expense})
    return out


def overview(session: Session, month: date) -> dict:
    start = period_for(month)
    end = start.replace(day=monthrange(start.year, start.month)[1])
    financial_date = func.coalesce(Transaction.settled_date, Transaction.transaction_date)
    totals = session.execute(select(Transaction.kind, func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.status == "settled", Transaction.deleted_at.is_(None), financial_date >= start, financial_date <= end,
        Transaction.kind.in_(["income", "expense", "refund"]),
    ).group_by(Transaction.kind)).all()
    sums = {kind: Decimal(value) for kind, value in totals}
    income = sums.get("income", Decimal(0))
    expense = sums.get("expense", Decimal(0)) - sums.get("refund", Decimal(0))
    balances = account_balances(session)
    cash = sum((b["balance"] for b in balances if b["kind"] != "credit_card"), Decimal(0))
    open_bills = session.scalar(select(func.coalesce(func.sum(Bill.amount), 0)).where(Bill.paid_date.is_(None))) or Decimal("0")
    open_installments = session.scalar(select(func.coalesce(func.sum(Installment.amount), 0)).join(CreditPurchase, Installment.purchase_id == CreditPurchase.id).join(Transaction, CreditPurchase.transaction_id == Transaction.id).where(Installment.paid_date.is_(None), Transaction.deleted_at.is_(None))) or Decimal("0")
    reserved = session.scalar(select(func.coalesce(func.sum(Goal.allocated_amount), 0))) or Decimal("0")
    budget_day = date.today() if start == period_for(date.today()) else start
    return {"month": start, "balances": balances, "cash_total": cash, "card_liability": sum((-b["balance"] for b in balances if b["kind"] == "credit_card"), Decimal(0)), "open_bills": Decimal(open_bills), "open_installments": Decimal(open_installments), "reserved": Decimal(reserved), "cash_after_commitments": cash - Decimal(open_bills) - Decimal(open_installments) - Decimal(reserved), "income": income, "expenses": expense, "result": income - expense, "budget_status": budget_status(session, budget_day)}


def get_upcoming_bills(session: Session, through: date) -> list[Bill]:
    return session.scalars(select(Bill).where(Bill.paid_date.is_(None), Bill.due_date <= through).order_by(Bill.due_date)).all()


def create_recurring_plan(session: Session, data: dict) -> RecurringPlan:
    kind = data["kind"]
    if kind not in ("income", "expense"):
        raise HTTPException(422, "Plano deve ser receita ou despesa")
    account = session.get(Account, data["account_id"])
    if not account or not account.is_active or account.kind == "credit_card":
        raise HTTPException(422, "Selecione uma conta monetária ativa")
    category_id = data.get("category_id")
    category = session.scalar(select(Category).where(Category.id == category_id).with_for_update()) if category_id else None
    if kind == "expense" and not category:
        raise HTTPException(422, "Despesa recorrente exige categoria")
    if category and (not category.is_active or category.kind != kind):
        raise HTTPException(422, "Categoria incompatível com o plano")
    description = data["description"].strip()
    if not description:
        raise HTTPException(422, "Informe a descrição do plano")
    plan = RecurringPlan(description=description, kind=kind, amount=money(data["amount"]),
                         account_id=account.id, category_id=category_id, start_date=data["start_date"], is_active=True)
    session.add(plan); session.flush()
    return plan


def recurring_due_date(plan: RecurringPlan, month: date) -> date | None:
    period = period_for(month)
    if period < period_for(plan.start_date):
        return None
    return date(period.year, period.month, min(plan.start_date.day, monthrange(period.year, period.month)[1]))


def recurring_status(session: Session, month: date) -> list[dict]:
    rows = []
    for plan in session.scalars(select(RecurringPlan).where(RecurringPlan.is_active.is_(True)).order_by(RecurringPlan.description)):
        due = recurring_due_date(plan, month)
        if due is None:
            continue
        occurrence = session.scalar(select(RecurringOccurrence).where(RecurringOccurrence.plan_id == plan.id, RecurringOccurrence.due_date == due))
        rows.append({"id": str(plan.id), "description": plan.description, "kind": plan.kind,
                     "amount": plan.amount, "account_id": str(plan.account_id),
                     "category_id": str(plan.category_id) if plan.category_id else None,
                     "due_date": due, "realized": occurrence is not None and session.get(Transaction, occurrence.transaction_id).deleted_at is None,
                     "in_trash": occurrence is not None and session.get(Transaction, occurrence.transaction_id).deleted_at is not None,
                     "transaction_id": str(occurrence.transaction_id) if occurrence else None})
    return rows


def realize_recurring_plan(session: Session, plan_id: UUID, month: date, realized_on: date) -> RecurringOccurrence:
    plan = session.scalar(select(RecurringPlan).where(RecurringPlan.id == plan_id).with_for_update())
    if not plan or not plan.is_active:
        raise HTTPException(404, "Plano recorrente não encontrado ou inativo")
    due = recurring_due_date(plan, month)
    if due is None:
        raise HTTPException(422, "O plano ainda não começou neste mês")
    occurrence = session.scalar(select(RecurringOccurrence).where(RecurringOccurrence.plan_id == plan.id, RecurringOccurrence.due_date == due))
    if occurrence:
        if session.get(Transaction, occurrence.transaction_id).deleted_at is not None:
            raise HTTPException(409, "A ocorrência está na lixeira; restaure a movimentação original")
        return occurrence
    transaction = create_transaction(session, {"kind": plan.kind, "amount": plan.amount,
        "account_id": plan.account_id, "category_id": plan.category_id,
        "description": plan.description, "transaction_date": realized_on, "status": "settled",
        "notes": f"Plano recorrente previsto para {due.isoformat()}"},
        f"recurring:{plan.id}:{due.isoformat()}")
    occurrence = RecurringOccurrence(plan_id=plan.id, due_date=due,
                                    transaction_id=transaction.id, realized_at=realized_on)
    session.add(occurrence); session.flush()
    return occurrence


def create_investment_event(session: Session, investment_id: UUID, account_id: UUID, kind: str, amount: Decimal, day: date, key: str | None = None):
    amount = money(amount)
    investment, account = session.get(Investment, investment_id), session.get(Account, account_id)
    if not investment or not account:
        raise HTTPException(404, "Investimento ou conta não encontrado")
    if kind not in ("contribution", "withdrawal", "income", "fee"):
        raise HTTPException(422, "Tipo de evento de investimento inválido")
    existing = session.scalar(select(InvestmentEvent).where(InvestmentEvent.idempotency_key == key)) if key else None
    if existing:
        if existing.investment_id != investment_id or existing.account_id != account_id or existing.kind != kind or existing.amount != amount or existing.event_date != day:
            raise HTTPException(409, "Chave de idempotência já usada com dados diferentes")
        return existing
    event = InvestmentEvent(id=uuid4(), investment_id=investment_id, account_id=account_id, kind=kind, amount=amount, event_date=day, idempotency_key=key)
    session.add(event)
    if kind == "contribution":
        investment.current_value += amount
        session.add(Transaction(kind="investment", amount=amount, account_id=account_id, description=f"Aporte: {investment.name}", transaction_date=day, competence_date=period_for(day), status="settled", settled_date=day, related_id=event.id))
    elif kind == "withdrawal":
        if investment.current_value < amount:
            raise HTTPException(422, "Resgate excede o valor registrado do investimento")
        investment.current_value -= amount
        session.add(Transaction(kind="transfer_in", amount=amount, account_id=account_id, description=f"Resgate: {investment.name}", transaction_date=day, competence_date=period_for(day), status="settled", settled_date=day, related_id=event.id))
    elif kind == "income":
        investment.current_value += amount
    elif kind == "fee":
        investment.current_value = max(Decimal("0"), investment.current_value - amount)
    session.flush()
    return event


def net_worth(session: Session) -> dict:
    balances = account_balances(session)
    cash = sum((b["balance"] for b in balances if b["kind"] != "credit_card"), Decimal(0))
    card_liability = sum((-b["balance"] for b in balances if b["kind"] == "credit_card"), Decimal(0))
    investments = session.scalar(select(func.coalesce(func.sum(Investment.current_value), 0))) or Decimal(0)
    bills = session.scalar(select(func.coalesce(func.sum(Bill.amount), 0)).where(Bill.paid_date.is_(None))) or Decimal(0)
    return {"cash": cash, "investments": Decimal(investments), "card_liability": card_liability, "bill_liability": Decimal(bills), "liabilities": card_liability + Decimal(bills), "net_worth": cash + Decimal(investments) - card_liability - Decimal(bills)}


def investment_summary(session: Session, investment: Investment) -> dict:
    events = session.scalars(select(InvestmentEvent).where(InvestmentEvent.investment_id == investment.id)).all()
    totals = {kind: sum((row.amount for row in events if row.kind == kind), Decimal("0"))
              for kind in ("contribution", "withdrawal", "income", "fee")}
    net_invested = (investment.opening_contribution + totals["contribution"] - totals["withdrawal"]
                    if investment.opening_contribution is not None else None)
    return {"id": str(investment.id), "name": investment.name, "kind": investment.kind,
            "institution": investment.institution, "quantity": investment.quantity,
            "opening_contribution": investment.opening_contribution, "acquired_on": investment.acquired_on,
            "current_value": investment.current_value, "valuation_date": investment.valuation_date,
            "contributions": totals["contribution"], "withdrawals": totals["withdrawal"],
            "income_recorded": totals["income"], "fees": totals["fee"],
            "net_invested": net_invested,
            "difference_vs_net_invested": investment.current_value - net_invested if net_invested is not None else None}


def goals(session: Session) -> list[dict]:
    rows = session.scalars(select(Goal).order_by(Goal.name)).all()
    balances = {b["account_id"]: b for b in account_balances(session) if b["kind"] != "credit_card"}
    all_reserves = sum((g.allocated_amount for g in rows), Decimal("0"))
    open_bills = session.scalar(select(func.coalesce(func.sum(Bill.amount), 0)).where(Bill.paid_date.is_(None))) or Decimal("0")
    open_installments = session.scalar(select(func.coalesce(func.sum(Installment.amount), 0)).join(CreditPurchase, Installment.purchase_id == CreditPurchase.id).join(Transaction, CreditPurchase.transaction_id == Transaction.id).where(Installment.paid_date.is_(None), Transaction.deleted_at.is_(None))) or Decimal("0")
    results = []
    for goal in rows:
        selected = {str(aid) for aid in session.scalars(select(GoalTrackingAccount.account_id).where(GoalTrackingAccount.goal_id == goal.id))}
        tracked = set(balances) if goal.tracking_mode == "all" else selected if goal.tracking_mode == "selected" else set()
        tracked_balance = sum((balances[aid]["balance"] for aid in tracked if aid in balances), Decimal("0"))
        contributed = session.scalar(select(func.coalesce(func.sum(GoalContribution.amount_delta), 0)).where(GoalContribution.goal_id == goal.id)) or Decimal("0")
        # Contas a pagar e reservas não estão vinculadas a uma conta. Exibimos a dedução global uma vez
        # por estimativa, sem somar as disponibilidades de metas entre si.
        obligations = Decimal(open_bills) + Decimal(open_installments) if tracked else Decimal("0")
        reserved = all_reserves if tracked else Decimal("0")
        results.append({"id": str(goal.id), "name": goal.name, "target_amount": goal.target_amount,
                        "contributed_amount": Decimal(contributed), "allocated_amount": goal.allocated_amount,
                        "remaining": max(Decimal("0"), goal.target_amount - Decimal(contributed)),
                        "target_date": goal.target_date, "tracking_mode": goal.tracking_mode,
                        "account_ids": sorted(selected), "tracked_account_ids": sorted(tracked),
                        "tracked_balance": tracked_balance, "other_reserves": reserved - goal.allocated_amount if tracked else Decimal("0"),
                        "open_obligations": obligations,
                        "available_estimate": tracked_balance - obligations - reserved if tracked else None})
    return results


def calendar_days(session: Session, start: date, end: date) -> list[dict]:
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "O calendário aceita até 367 dias por consulta")
    by_day: dict[date, dict] = {}
    def item(day: date) -> dict:
        return by_day.setdefault(day, {"date": day, "income": Decimal("0"), "expenses": Decimal("0"),
                                      "result": Decimal("0"), "transactions": [], "bills": [], "invoices": [], "recurring": []})
    effective_date = case((Transaction.status == "settled", func.coalesce(Transaction.settled_date, Transaction.transaction_date)), else_=Transaction.transaction_date)
    rows = session.scalars(select(Transaction).where(Transaction.deleted_at.is_(None),
        effective_date >= start, effective_date <= end,
        Transaction.kind.in_(["income", "expense", "refund"])).order_by(effective_date, Transaction.created_at)).all()
    for tx in rows:
        day = item(tx.settled_date or tx.transaction_date if tx.status == "settled" else tx.transaction_date)
        day["transactions"].append({"id": str(tx.id), "description": tx.description, "kind": tx.kind,
                                    "amount": tx.amount, "status": tx.status, "category_id": str(tx.category_id) if tx.category_id else None})
        if tx.status == "settled":
            if tx.kind == "income":
                day["income"] += tx.amount
            elif tx.kind == "expense":
                day["expenses"] += tx.amount
            else:
                day["expenses"] -= tx.amount
    bills = session.scalars(select(Bill).where(Bill.due_date >= start, Bill.due_date <= end).order_by(Bill.due_date)).all()
    for bill in bills:
        item(bill.due_date)["bills"].append({"id": str(bill.id), "description": bill.description,
                                              "amount": bill.amount, "paid": bill.paid_date is not None})
    for invoice in invoice_status(session):
        if start <= invoice["due_date"] <= end:
            item(invoice["due_date"])["invoices"].append({"id": invoice["id"], "card": invoice["card"],
                                                              "amount": invoice["total"] if invoice["paid_date"] else invoice["open_amount"],
                                                              "paid": invoice["paid_date"] is not None})
    month_cursor = period_for(start)
    while month_cursor <= period_for(end):
        for plan in recurring_status(session, month_cursor):
            if start <= plan["due_date"] <= end and not plan["realized"]:
                item(plan["due_date"])["recurring"].append({"id": plan["id"], "description": plan["description"],
                                                               "kind": plan["kind"], "amount": plan["amount"],
                                                               "in_trash": plan["in_trash"]})
        month_cursor = shift_month(month_cursor, 1, 1)
    for day in by_day.values():
        day["result"] = day["income"] - day["expenses"]
    return [by_day[key] for key in sorted(by_day)]


def shift_month(day: date, n: int, desired_day: int | None = None) -> date:
    total = day.year * 12 + (day.month - 1) + n
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    return date(year, month, min(desired_day or day.day, monthrange(year, month)[1]))


def first_card_due(purchase_day: date, closing_day: int, due_day: int) -> date:
    closing = date(purchase_day.year, purchase_day.month, min(closing_day, monthrange(purchase_day.year, purchase_day.month)[1]))
    if purchase_day > closing:
        closing = shift_month(closing, 1, closing_day)
    due = date(closing.year, closing.month, min(due_day, monthrange(closing.year, closing.month)[1]))
    if due <= closing:
        due = shift_month(due, 1, due_day)
    return due


def create_credit_card(session: Session, name: str, closing_day: int, due_day: int) -> CreditCard:
    if not 1 <= closing_day <= 31 or not 1 <= due_day <= 31:
        raise HTTPException(422, "Dias de fechamento e vencimento devem ficar entre 1 e 31")
    if not name.strip() or len(name.strip()) > 80:
        raise HTTPException(422, "Nome do cartão inválido")
    if session.scalar(select(Account).where(Account.name == name.strip())):
        raise HTTPException(409, "Já existe uma conta ou cartão com esse nome")
    account = Account(name=name.strip(), kind="credit_card", opening_balance=Decimal("0"))
    session.add(account); session.flush()
    card = CreditCard(account_id=account.id, closing_day=closing_day, due_day=due_day)
    session.add(card); session.flush()
    return card


def create_credit_purchase(session: Session, card_id: UUID, category_id: UUID, total: Decimal, count: int, day: date, merchant: str, key: str | None = None) -> CreditPurchase:
    total = money(total)
    if not 1 <= count <= 120:
        raise HTTPException(422, "Número de parcelas deve ficar entre 1 e 120")
    if not merchant.strip() or len(merchant.strip()) > 180:
        raise HTTPException(422, "Descrição da compra inválida")
    card = session.get(CreditCard, card_id)
    category = session.get(Category, category_id)
    if not card or not category or not category.is_active or category.kind != "expense":
        raise HTTPException(404, "Cartão ou categoria de despesa não encontrado")
    if key:
        existing = session.scalar(select(CreditPurchase).join(Transaction, CreditPurchase.transaction_id == Transaction.id).where(Transaction.idempotency_key == key))
        if existing:
            tx = session.get(Transaction, existing.transaction_id)
            if tx.deleted_at is not None:
                raise HTTPException(409, "A compra está na lixeira; restaure-a")
            if existing.card_id != card_id or tx.category_id != category_id or existing.total_amount != total or existing.installment_count != count or existing.purchase_date != day or existing.merchant != merchant.strip():
                raise HTTPException(409, "Chave de idempotência já usada com compra diferente")
            return existing
    cents = int(total * 100)
    if count > cents:
        raise HTTPException(422, "O valor não comporta parcelas positivas")
    tx = create_transaction(session, {"kind": "expense", "amount": total, "account_id": card.account_id, "category_id": category_id, "description": merchant.strip(), "transaction_date": day, "status": "settled"}, key, allow_card=True)
    purchase = CreditPurchase(card_id=card_id, transaction_id=tx.id, total_amount=total, installment_count=count, purchase_date=day, merchant=merchant.strip())
    session.add(purchase); session.flush()
    first_due = first_card_due(day, card.closing_day, card.due_day)
    base, extra = divmod(cents, count)
    for index in range(count):
        due = shift_month(first_due, index, card.due_day)
        invoice = session.scalar(select(Invoice).where(Invoice.card_id == card_id, Invoice.due_date == due))
        if not invoice:
            invoice = Invoice(card_id=card_id, due_date=due)
            session.add(invoice); session.flush()
        if invoice.paid_date is not None:
            raise HTTPException(409, "Esta fatura já foi paga; escolha uma data de compra em outro ciclo")
        amount = Decimal(base + (1 if index < extra else 0)) / 100
        session.add(Installment(purchase_id=purchase.id, invoice_id=invoice.id, sequence=index+1, amount=amount, due_date=due))
    session.flush()
    return purchase


def card_purchase_payload(session: Session, purchase: CreditPurchase) -> dict:
    tx = session.get(Transaction, purchase.transaction_id)
    card = session.get(CreditCard, purchase.card_id)
    account = session.get(Account, card.account_id)
    installments = session.scalars(select(Installment).where(Installment.purchase_id == purchase.id).order_by(Installment.sequence)).all()
    return {"id": str(purchase.id), "transaction_id": str(tx.id), "version": tx.version,
            "card_id": str(card.id), "card": account.name, "category_id": str(tx.category_id),
            "total_amount": purchase.total_amount, "installment_count": purchase.installment_count,
            "purchase_date": purchase.purchase_date, "merchant": purchase.merchant,
            "deleted_at": tx.deleted_at,
            "installments": [{"id": str(item.id), "sequence": item.sequence, "amount": item.amount,
                              "invoice_id": str(item.invoice_id), "due_date": item.due_date,
                              "paid_date": item.paid_date} for item in installments]}


def invoice_payment_pair(session: Session, invoice: Invoice, deleted_at: datetime | None = None) -> tuple[Transaction, Transaction] | None:
    card = session.get(CreditCard, invoice.card_id)
    description = f"Pagamento de fatura {invoice.due_date.isoformat()}"
    stmt = select(Transaction).where(Transaction.kind == "transfer_in", Transaction.account_id == card.account_id,
                                     Transaction.description == description)
    stmt = stmt.where(Transaction.deleted_at.is_(None) if deleted_at is None else Transaction.deleted_at == deleted_at)
    matches = session.scalars(stmt.with_for_update()).all()
    if len(matches) > 1:
        raise HTTPException(409, "Fatura possui mais de um pagamento vinculado; correção automática recusada")
    if not matches:
        return None
    incoming = matches[0]
    outgoing = session.scalar(select(Transaction).where(Transaction.id == incoming.related_id).with_for_update()) if incoming.related_id else None
    if not outgoing or outgoing.kind != "transfer_out" or outgoing.related_id != incoming.id or outgoing.amount != incoming.amount or outgoing.deleted_at != incoming.deleted_at:
        raise HTTPException(409, "Pagamento da fatura está inconsistente; nenhuma alteração foi feita")
    return outgoing, incoming


def reconcile_invoice_payment(session: Session, invoice: Invoice, deleted_at: datetime | None = None) -> list[Transaction]:
    """Mantém o pagamento manual coerente com as parcelas ativas da fatura."""
    installments = session.scalars(select(Installment).join(CreditPurchase, Installment.purchase_id == CreditPurchase.id)
        .join(Transaction, CreditPurchase.transaction_id == Transaction.id)
        .where(Installment.invoice_id == invoice.id, Transaction.deleted_at.is_(None))).all()
    total = sum((item.amount for item in installments), Decimal("0"))
    pair = invoice_payment_pair(session, invoice)
    if invoice.paid_date is not None and pair is None:
        raise HTTPException(409, "Pagamento da fatura não encontrado; nenhuma alteração foi feita")
    if pair is None and deleted_at is not None and total > 0:
        pair = invoice_payment_pair(session, invoice, deleted_at)
        if pair:
            for row in pair:
                row.deleted_at = None
                row.version += 1
                session.add(TransactionLifecycleEvent(transaction_id=row.id, action="restore"))
            invoice.paid_date = pair[0].transaction_date
    if pair is None:
        return []
    if total == 0:
        stamp = deleted_at or datetime.now(timezone.utc)
        for row in pair:
            row.deleted_at = stamp
            row.version += 1
            session.add(TransactionLifecycleEvent(transaction_id=row.id, action="delete"))
        invoice.paid_date = None
        return list(pair)
    for row in pair:
        if row.amount != total:
            before = transaction_state(row)
            row.amount = total
            row.version += 1
            session.add(TransactionRevision(transaction_id=row.id, version=row.version,
                reason="Ajuste automático de fatura após correção de compra manual",
                before_state=before, after_state=transaction_state(row),
                request_hash=request_digest({"invoice": invoice.id, "transaction": row.id, "version": row.version, "amount": total})))
    for item in installments:
        item.paid_date = invoice.paid_date
    return list(pair)


def update_card_purchase(session: Session, purchase_id: UUID, expected_version: int, changes: dict) -> CreditPurchase:
    purchase = session.scalar(select(CreditPurchase).where(CreditPurchase.id == purchase_id).with_for_update())
    if not purchase:
        raise HTTPException(404, "Compra no cartão não encontrada")
    tx = session.scalar(select(Transaction).where(Transaction.id == purchase.transaction_id).with_for_update())
    if tx.deleted_at is not None:
        raise HTTPException(409, "Compra está na lixeira; restaure-a antes de editar")
    if tx.version != expected_version:
        raise HTTPException(409, "Compra foi alterada; recarregue antes de editar")
    if not changes:
        raise HTTPException(422, "Informe ao menos um campo para corrigir")
    allowed = {"total_amount", "merchant", "category_id", "purchase_date", "card_id", "installment_count"}
    if set(changes) - allowed or any(value is None for value in changes.values()):
        raise HTTPException(422, "Campo de compra inválido")
    if session.scalar(select(Transaction.id).where(Transaction.kind == "refund", Transaction.related_id == tx.id,
                                                   Transaction.deleted_at.is_(None))):
        raise HTTPException(409, "Exclua primeiro os reembolsos vinculados à compra")
    total = money(changes.get("total_amount", purchase.total_amount))
    count = changes.get("installment_count", purchase.installment_count)
    if not isinstance(count, int) or not 1 <= count <= 120 or count > int(total * 100):
        raise HTTPException(422, "Parcelamento incompatível com o valor")
    merchant = str(changes.get("merchant", purchase.merchant)).strip()
    if not merchant or len(merchant) > 180:
        raise HTTPException(422, "Descrição da compra inválida")
    category_id = changes.get("category_id", tx.category_id)
    category = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if not category or (not category.is_active and category_id != tx.category_id) or category.kind != "expense":
        raise HTTPException(422, "Categoria de despesa inválida")
    card_id = changes.get("card_id", purchase.card_id)
    card = session.get(CreditCard, card_id)
    if not card or not session.get(Account, card.account_id).is_active:
        raise HTTPException(422, "Cartão inválido")
    day = changes.get("purchase_date", purchase.purchase_date)
    if not isinstance(day, date):
        raise HTTPException(422, "Data da compra inválida")
    old_items = session.scalars(select(Installment).where(Installment.purchase_id == purchase.id).order_by(Installment.sequence).with_for_update()).all()
    old_invoices = {item.invoice_id: session.get(Invoice, item.invoice_id) for item in old_items}
    first_due = first_card_due(day, card.closing_day, card.due_day)
    new_due_dates = [shift_month(first_due, index, card.due_day) for index in range(count)]
    schedule_changed = card_id != purchase.card_id or count != purchase.installment_count or [item.due_date for item in old_items] != new_due_dates
    if schedule_changed and any(invoice.paid_date is not None for invoice in old_invoices.values()):
        raise HTTPException(409, "Cartão ou ciclo de parcelas já pago não pode ser movido; valor, categoria e descrição podem ser corrigidos")
    if (total, count, merchant, category_id, day, card_id) == (purchase.total_amount, purchase.installment_count, purchase.merchant, tx.category_id, purchase.purchase_date, purchase.card_id):
        raise HTTPException(422, "Nenhuma alteração informada")
    before = transaction_state(tx)
    purchase.total_amount, purchase.installment_count, purchase.merchant, purchase.purchase_date, purchase.card_id = total, count, merchant, day, card_id
    tx.amount, tx.description, tx.category_id, tx.transaction_date = total, merchant, category_id, day
    tx.competence_date = period_for(day)
    tx.settled_date = day
    tx.account_id = card.account_id
    tx.version += 1
    cents = int(total * 100)
    base, extra = divmod(cents, count)
    for index, due in enumerate(new_due_dates):
        invoice = session.scalar(select(Invoice).where(Invoice.card_id == card_id, Invoice.due_date == due))
        if not invoice:
            invoice = Invoice(card_id=card_id, due_date=due)
            session.add(invoice); session.flush()
        if invoice.paid_date is not None and invoice.id not in old_invoices:
            raise HTTPException(409, "A fatura de destino já foi paga")
        amount = Decimal(base + (1 if index < extra else 0)) / 100
        if index < len(old_items):
            item = old_items[index]
            item.invoice_id, item.amount, item.due_date = invoice.id, amount, due
        else:
            session.add(Installment(purchase_id=purchase.id, invoice_id=invoice.id,
                                    sequence=index + 1, amount=amount, due_date=due))
    for item in old_items[count:]:
        session.delete(item)
    session.add(TransactionRevision(transaction_id=tx.id, version=tx.version,
        reason="Correção de compra manual", before_state=before, after_state=transaction_state(tx),
        request_hash=request_digest({"purchase": purchase.id, "version": tx.version, "changes": changes})))
    session.flush()
    for invoice in old_invoices.values():
        if invoice.paid_date is not None:
            reconcile_invoice_payment(session, invoice)
    session.flush()
    return purchase


def invoice_status(session: Session, through: date | None = None,
                   card_id: UUID | None = None, unpaid_only: bool = False) -> list[dict]:
    stmt = select(Invoice).order_by(Invoice.due_date)
    if through: stmt = stmt.where(Invoice.due_date <= through)
    if card_id: stmt = stmt.where(Invoice.card_id == card_id)
    if unpaid_only: stmt = stmt.where(Invoice.paid_date.is_(None))
    rows = session.scalars(stmt).all()
    result = []
    for invoice in rows:
        card = session.get(CreditCard, invoice.card_id)
        account = session.get(Account, card.account_id)
        installments = session.scalars(select(Installment).join(CreditPurchase, Installment.purchase_id == CreditPurchase.id).join(Transaction, CreditPurchase.transaction_id == Transaction.id).where(Installment.invoice_id == invoice.id, Transaction.deleted_at.is_(None))).all()
        if not installments:
            continue
        total = sum((item.amount for item in installments), Decimal("0"))
        open_amount = sum((item.amount for item in installments if item.paid_date is None), Decimal("0"))
        if unpaid_only and open_amount <= 0:
            continue
        result.append({"id": str(invoice.id), "card_id": str(card.id), "card": account.name, "due_date": invoice.due_date, "total": total, "open_amount": open_amount, "paid_date": invoice.paid_date, "installment_count": len(installments)})
    return result


def pay_invoice(session: Session, invoice_id: UUID, source_account_id: UUID, day: date, key: str | None = None) -> dict:
    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(404, "Fatura não encontrada")
    card = session.get(CreditCard, invoice.card_id)
    source = session.get(Account, source_account_id)
    if not source or source.kind == "credit_card":
        raise HTTPException(422, "Selecione uma conta de pagamento válida")
    installments = session.scalars(select(Installment).join(CreditPurchase, Installment.purchase_id == CreditPurchase.id).join(Transaction, CreditPurchase.transaction_id == Transaction.id).where(Installment.invoice_id == invoice_id, Transaction.deleted_at.is_(None))).all()
    amount = sum((item.amount for item in installments), Decimal("0"))
    if invoice.paid_date is not None:
        if key and (record := session.get(IdempotencyRecord, key)):
            transfer = session.get(Transaction, record.result_id)
            paired = session.get(Transaction, transfer.related_id) if transfer and transfer.related_id else None
            if transfer and paired and transfer.account_id == source_account_id and paired.account_id == card.account_id and transfer.amount == amount and transfer.transaction_date == day and transfer.idempotency_key == key:
                return {"invoice_id": str(invoice.id), "transfer_id": str(transfer.id), "amount": amount, "paid_date": invoice.paid_date}
        raise HTTPException(409, "Fatura já está paga")
    if amount <= 0:
        raise HTTPException(422, "Fatura sem parcelas")
    out, _ = create_transfer(session, source_account_id, card.account_id, amount, day, f"Pagamento de fatura {invoice.due_date.isoformat()}", key, allow_card=True)
    for item in installments: item.paid_date = day
    invoice.paid_date = day
    session.flush()
    return {"invoice_id": str(invoice.id), "transfer_id": str(out.id), "amount": amount, "paid_date": day}


def entertainment_status(session: Session, month: date) -> dict:
    period = period_for(month)
    financial_date = func.coalesce(Transaction.settled_date, Transaction.transaction_date)
    category_ids = [c.id for c in session.scalars(select(Category).where(Category.is_entertainment.is_(True)))]
    if not category_ids:
        return {"month": period, "spent": Decimal("0"), "cycle_spent": Decimal("0"), "limit": None, "remaining": None, "history": [], "average_completed_months": None, "projection": None, "top_expenses": []}
    history = []
    for offset in range(6, -1, -1):
        start = shift_month(period, -offset, 1)
        end = date(start.year, start.month, monthrange(start.year, start.month)[1])
        rows = session.scalars(select(Transaction).where(Transaction.category_id.in_(category_ids), Transaction.kind.in_(["expense", "refund"]), Transaction.status == "settled", Transaction.deleted_at.is_(None), financial_date >= start, financial_date <= end)).all()
        value = sum((row.amount if row.kind == "expense" else -row.amount for row in rows), Decimal("0"))
        history.append({"month": start, "spent": value, "records": len(rows)})
    spent = history[-1]["spent"]
    budget_day = date.today() if period == period_for(date.today()) else month
    cycle_rows = [row for row in budget_status(session, budget_day) if UUID(row["category_id"]) in category_ids]
    limit = sum((row["limit"] for row in cycle_rows), Decimal("0")) if cycle_rows else None
    cycle_spent = sum((row["spent"] for row in cycle_rows), Decimal("0"))
    completed = [item["spent"] for item in history[:-1] if item["records"] > 0]
    average = (sum(completed[-3:], Decimal("0")) / len(completed[-3:])) if len(completed) >= 2 else None
    today = date.today()
    projection = None
    if period == period_for(today) and today.day >= 7:
        current_rows = session.scalars(select(Transaction).where(Transaction.category_id.in_(category_ids), Transaction.kind == "expense", Transaction.status == "settled", Transaction.deleted_at.is_(None), financial_date >= period, financial_date <= today)).all()
        if len({row.settled_date or row.transaction_date for row in current_rows}) >= 3:
            projection = (spent / today.day * monthrange(today.year, today.month)[1]).quantize(Decimal("0.01"))
    current = session.scalars(select(Transaction).where(Transaction.category_id.in_(category_ids), Transaction.kind == "expense", Transaction.status == "settled", Transaction.deleted_at.is_(None), financial_date >= period, financial_date <= date(period.year, period.month, monthrange(period.year, period.month)[1]))).all()
    grouped: dict[str, Decimal] = {}
    for row in current:
        grouped[row.description] = grouped.get(row.description, Decimal("0")) + row.amount
    top = [{"description": name, "amount": amount} for name, amount in sorted(grouped.items(), key=lambda pair: pair[1], reverse=True)[:5]]
    return {"month": period, "spent": spent, "cycle_spent": cycle_spent, "limit": limit, "remaining": limit - cycle_spent if limit is not None else None, "history": history, "average_completed_months": average, "projection": projection, "top_expenses": top}


def transaction_state(row: Transaction) -> dict:
    return {
        "id": str(row.id), "version": row.version, "kind": row.kind,
        "amount": str(row.amount), "account_id": str(row.account_id),
        "category_id": str(row.category_id) if row.category_id else None,
        "description": row.description, "transaction_date": row.transaction_date.isoformat(),
        "competence_date": row.competence_date.isoformat(), "status": row.status,
    }


def update_transaction(session: Session, transaction_id: UUID, expected_version: int,
                       amount: Decimal | None = None, category_id: UUID | None = None,
                       description: str | None = None, transaction_date: date | None = None,
                       reason: str = "", key: str | None = None,
                       preserve_category_if_none: bool = False,
                       account_id: UUID | None = None,
                       notes: str | None = None) -> Transaction:
    if not reason.strip() or len(reason.strip()) > 180:
        raise HTTPException(422, "Informe o motivo da correção (até 180 caracteres)")
    if key and (not key.strip() or len(key) > 120):
        raise HTTPException(422, "Chave de idempotência inválida")
    previous = session.scalar(select(TransactionRevision).where(TransactionRevision.idempotency_key == key)) if key else None
    row = session.scalar(select(Transaction).where(Transaction.id == transaction_id).with_for_update())
    if not row and not previous:
        raise HTTPException(404, "Movimentação não encontrada")
    base_state = previous.before_state if previous else (transaction_state(row) if row else {})
    resolved_amount = money(amount) if amount is not None else money(base_state["amount"])
    if category_id is None and preserve_category_if_none:
        resolved_category_id = UUID(base_state["category_id"]) if base_state.get("category_id") else None
    else:
        resolved_category_id = category_id
    resolved_description = description.strip() if description is not None else str(base_state.get("description", "")).strip()
    resolved_date = transaction_date if transaction_date is not None else date.fromisoformat(base_state["transaction_date"])
    digest_payload = {
        "transaction_id": transaction_id, "expected_version": expected_version,
        "amount": resolved_amount, "category_id": resolved_category_id,
        "description": resolved_description, "transaction_date": resolved_date,
        "reason": reason.strip(),
    }
    if account_id is not None:
        digest_payload["account_id"] = account_id
    if notes is not None:
        digest_payload["notes"] = notes
    digest = request_digest(digest_payload)
    if previous:
        if previous.request_hash != digest or previous.transaction_id != transaction_id:
            raise HTTPException(409, "Chave de idempotência já usada com correção diferente")
        existing = session.get(Transaction, transaction_id)
        if not existing or existing.version != previous.version:
            raise HTTPException(409, "Correção já aplicada; o registro foi alterado depois")
        return existing
    if not row:
        raise HTTPException(404, "Movimentação não encontrada")
    if row.deleted_at is not None:
        raise HTTPException(409, "Movimentação está na lixeira; restaure-a antes de corrigir")
    if row.version != expected_version:
        raise HTTPException(409, "Movimentação foi alterada; consulte a versão atual")
    if row.kind not in ("income", "expense", "refund") or row.status != "settled":
        raise HTTPException(422, "Somente receitas, despesas e reembolsos realizados podem ser corrigidos")
    if session.scalar(select(CreditPurchase).where(CreditPurchase.transaction_id == row.id)) or session.scalar(select(Bill).where(Bill.payment_transaction_id == row.id)):
        raise HTTPException(422, "Corrija a operação vinculada à compra ou conta a pagar")
    if session.scalar(select(Transaction).where(Transaction.related_id == row.id, Transaction.kind == "refund", Transaction.deleted_at.is_(None))):
        raise HTTPException(422, "Movimentação com reembolso vinculado não pode ser corrigida diretamente")
    if account_id is not None and account_id != row.account_id:
        target_account = session.get(Account, account_id)
        if not target_account or not target_account.is_active or target_account.kind == "credit_card":
            raise HTTPException(422, "Conta de destino inválida para esta movimentação")
    category = session.scalar(select(Category).where(Category.id == resolved_category_id).with_for_update()) if resolved_category_id else None
    if row.kind in ("expense", "refund") and category is None:
        raise HTTPException(422, "Despesa ou reembolso exige categoria")
    if category and ((not category.is_active and resolved_category_id != row.category_id) or category.kind != ("income" if row.kind == "income" else "expense")):
        raise HTTPException(422, "Categoria incompatível")
    if not resolved_description or len(resolved_description) > 180:
        raise HTTPException(422, "Descrição inválida")
    before = transaction_state(row)
    notes_changed = notes is not None and notes != row.notes
    row.amount = resolved_amount
    row.category_id = resolved_category_id
    row.description = resolved_description
    row.transaction_date = resolved_date
    row.competence_date = period_for(resolved_date)
    row.settled_date = resolved_date
    if account_id is not None:
        row.account_id = account_id
    if notes is not None:
        row.notes = notes
    row.version += 1
    after = transaction_state(row)
    unchanged = dict(after, version=before["version"])
    if before == unchanged and not notes_changed:
        raise HTTPException(422, "Nenhuma alteração informada")
    session.add(TransactionRevision(transaction_id=row.id, version=row.version, reason=reason.strip(),
                                    before_state=before, after_state=after, idempotency_key=key, request_hash=digest))
    session.flush()
    return row


def transaction_deletion_group(session: Session, row: Transaction) -> tuple[list[Transaction], Bill | None, CreditPurchase | None]:
    """Resolve operações compostas antes de mudar qualquer estado financeiro."""
    bill = session.scalar(select(Bill).where(Bill.payment_transaction_id == row.id))
    if not bill and row.kind == "expense" and row.related_id:
        bill = session.get(Bill, row.related_id)
    purchase = session.scalar(select(CreditPurchase).where(CreditPurchase.transaction_id == row.id))
    if row.kind == "expense" and session.scalar(select(Transaction.id).where(
            Transaction.kind == "refund", Transaction.related_id == row.id,
            Transaction.deleted_at.is_(None)).limit(1)):
        raise HTTPException(409, "Exclua primeiro os reembolsos vinculados à despesa")
    if row.kind in ("investment", "transfer_in") and row.related_id and session.get(InvestmentEvent, row.related_id):
        raise HTTPException(409, "Movimentação de investimento exige reversão do evento completo; exclusão isolada recusada")
    if row.kind in ("transfer_out", "transfer_in"):
        pair = session.get(Transaction, row.related_id) if row.related_id else None
        if not pair or pair.related_id != row.id or pair.amount != row.amount or {row.kind, pair.kind} != {"transfer_out", "transfer_in"}:
            raise HTTPException(409, "Transferência sem par íntegro; exclusão recusada")
        if session.get(Account, row.account_id).kind == "credit_card" or session.get(Account, pair.account_id).kind == "credit_card":
            raise HTTPException(409, "Pagamento de fatura precisa de estorno da fatura completa; exclusão pelo histórico recusada")
        return [row, pair], None, None
    if row.kind not in ("income", "expense", "refund"):
        raise HTTPException(409, "Esta operação composta não pode ser excluída isoladamente")
    return [row], bill, purchase


def delete_transaction(session: Session, transaction_id: UUID, expected_version: int) -> list[Transaction]:
    row = session.scalar(select(Transaction).where(Transaction.id == transaction_id).with_for_update())
    if not row:
        raise HTTPException(404, "Movimentação não encontrada")
    if row.deleted_at is not None:
        return [row]
    if row.version != expected_version:
        raise HTTPException(409, "Movimentação foi alterada; recarregue antes de excluir")
    group, bill, purchase = transaction_deletion_group(session, row)
    if any(item.deleted_at is not None for item in group):
        raise HTTPException(409, "Operação composta está parcialmente excluída; nenhuma alteração foi feita")
    deleted_at = datetime.now(timezone.utc)
    for item in group:
        item.deleted_at = deleted_at
        item.version += 1
        session.add(TransactionLifecycleEvent(transaction_id=item.id, action="delete"))
    if bill and bill.payment_transaction_id == row.id:
        row.related_id = bill.id
        bill.paid_date = None
    if purchase:
        invoice_ids = set(session.scalars(select(Installment.invoice_id).where(Installment.purchase_id == purchase.id)))
        for invoice_id in invoice_ids:
            reconcile_invoice_payment(session, session.get(Invoice, invoice_id), deleted_at)
    session.flush()
    return group


def restore_transaction(session: Session, transaction_id: UUID) -> list[Transaction]:
    row = session.scalar(select(Transaction).where(Transaction.id == transaction_id).with_for_update())
    if not row:
        raise HTTPException(404, "Movimentação não encontrada")
    if row.deleted_at is None:
        return [row]
    original_deleted_at = row.deleted_at
    if row.kind in ("transfer_in", "transfer_out"):
        pair = session.get(Transaction, row.related_id) if row.related_id else None
        card_account = next((account for account in (session.get(Account, row.account_id),
            session.get(Account, pair.account_id) if pair else None) if account and account.kind == "credit_card"), None)
        if card_account:
            card = session.scalar(select(CreditCard).where(CreditCard.account_id == card_account.id))
            try:
                due = date.fromisoformat(row.description.removeprefix("Pagamento de fatura "))
            except ValueError:
                raise HTTPException(409, "Restaure a compra que originou este pagamento de fatura")
            invoice = session.scalar(select(Invoice).where(Invoice.card_id == card.id, Invoice.due_date == due)) if card else None
            candidates = session.scalars(select(Transaction).join(CreditPurchase, CreditPurchase.transaction_id == Transaction.id)
                .join(Installment, Installment.purchase_id == CreditPurchase.id)
                .where(Installment.invoice_id == invoice.id, Transaction.deleted_at == original_deleted_at)) .all() if invoice else []
            if len(candidates) != 1:
                raise HTTPException(409, "Restaure primeiro a compra vinculada a este pagamento de fatura")
            restored = restore_transaction(session, candidates[0].id)
            return restored + [row, pair]
    group, bill, purchase = transaction_deletion_group(session, row)
    if any(item.deleted_at is None for item in group):
        raise HTTPException(409, "Operação composta está parcialmente restaurada; nenhuma alteração foi feita")
    if row.kind == "refund" and row.related_id:
        original = session.get(Transaction, row.related_id)
        if not original or original.deleted_at is not None:
            raise HTTPException(409, "Restaure primeiro a despesa original")
        refunded = session.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.kind == "refund", Transaction.related_id == row.related_id,
            Transaction.deleted_at.is_(None))) or Decimal("0")
        if Decimal(refunded) + row.amount > original.amount:
            raise HTTPException(409, "Restaurar este reembolso excederia o valor da despesa original")
    if bill:
        if bill.payment_transaction_id != row.id or bill.paid_date is not None:
            raise HTTPException(409, "Conta a pagar já foi quitada novamente; restauração recusada")
        bill.paid_date = row.settled_date or row.transaction_date
    for item in group:
        item.deleted_at = None
        item.version += 1
        session.add(TransactionLifecycleEvent(transaction_id=item.id, action="restore"))
    if purchase:
        session.flush()
        invoice_ids = set(session.scalars(select(Installment.invoice_id).where(Installment.purchase_id == purchase.id)))
        for invoice_id in invoice_ids:
            reconcile_invoice_payment(session, session.get(Invoice, invoice_id), original_deleted_at)
    session.flush()
    return group


def record_investment_valuation(session: Session, investment_id: UUID, value: Decimal,
                                valuation_date: date, key: str | None = None) -> InvestmentValuation:
    try:
        value = Decimal(value)
        if not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.01")):
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "Valor de avaliação inválido")
    if key and (existing := session.scalar(select(InvestmentValuation).where(InvestmentValuation.idempotency_key == key))):
        if existing.investment_id != investment_id or existing.value != value or existing.valuation_date != valuation_date:
            raise HTTPException(409, "Chave de idempotência já usada com avaliação diferente")
        return existing
    investment = session.get(Investment, investment_id)
    if not investment:
        raise HTTPException(404, "Investimento não encontrado")
    investment.current_value = value
    investment.valuation_date = valuation_date
    row = InvestmentValuation(investment_id=investment_id, value=value, valuation_date=valuation_date, idempotency_key=key)
    session.add(row)
    session.flush()
    return row


def record_net_worth_snapshot(session: Session) -> NetWorthSnapshot:
    figures = net_worth(session)
    today = date.today()
    row = session.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.as_of_date == today))
    if not row:
        row = NetWorthSnapshot(as_of_date=today)
        session.add(row)
    row.cash = figures["cash"]
    row.investments = figures["investments"]
    row.liabilities = figures["liabilities"]
    row.net_worth = figures["net_worth"]
    session.flush()
    return row


ICON_IDS = {
    "utensils", "coffee", "home", "car", "heart", "book", "school", "film",
    "music", "bag", "cart", "receipt", "plane", "bank", "wallet", "work",
    "gift", "pet", "sport", "light", "sparkles", "other",
}
ACCOUNT_KINDS = ("checking", "savings", "cash", "investment")


def signed_decimal(value: Decimal | str | int, allow_zero: bool = True, allow_negative: bool = True) -> Decimal:
    try:
        raw = Decimal(value)
        if not raw.is_finite() or raw != raw.quantize(Decimal("0.01")):
            raise InvalidOperation()
        result = raw.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "Valor monetário inválido")
    if not allow_zero and result == 0:
        raise HTTPException(422, "O valor não pode ser zero")
    if not allow_negative and result < 0:
        raise HTTPException(422, "O valor não pode ser negativo")
    return result


def account_balance_for(session: Session, account: Account) -> Decimal:
    rows = session.scalars(select(Transaction).where(
        Transaction.account_id == account.id,
        Transaction.status == "settled",
        Transaction.deleted_at.is_(None),
    )).all()
    balance = account.opening_balance
    for row in rows:
        if row.kind in ("income", "refund", "transfer_in"):
            balance += row.amount
        elif row.kind in ("expense", "transfer_out", "investment"):
            balance -= row.amount
    return balance


def account_payload(session: Session, account: Account) -> dict:
    balance = account_balance_for(session, account)
    tx_count = session.scalar(select(func.count(Transaction.id)).where(
        Transaction.account_id == account.id,
        Transaction.deleted_at.is_(None),
    )) or 0
    card = session.scalar(select(CreditCard).where(CreditCard.account_id == account.id)) if account.kind == "credit_card" else None
    return {
        "id": str(account.id),
        "name": account.name,
        "kind": account.kind,
        "currency": account.currency,
        "opening_balance": account.opening_balance,
        "balance": balance,
        "is_active": account.is_active,
        "transaction_count": int(tx_count),
        "card_id": str(card.id) if card else None,
        "created_at": account.created_at,
    }


def list_accounts_domain(session: Session, scope: str = "active") -> list[dict]:
    if scope not in ("active", "archived", "all"):
        raise HTTPException(422, "Escopo de contas inválido; use active, archived ou all")
    stmt = select(Account).order_by(Account.name)
    if scope != "all":
        stmt = stmt.where(Account.is_active.is_(scope == "active"))
    return [account_payload(session, row) for row in session.scalars(stmt).all()]


def get_account_domain(session: Session, account_id: UUID) -> dict:
    row = session.get(Account, account_id)
    if not row:
        raise HTTPException(404, "Conta não encontrada")
    return account_payload(session, row)


def create_account_domain(session: Session, name: str, kind: str = "checking",
                          opening_balance: Decimal | str = Decimal("0.00")) -> dict:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 80:
        raise HTTPException(422, "Nome da conta deve ter entre 1 e 80 caracteres")
    if kind == "credit_card":
        raise HTTPException(422, "Para criar um cartão de crédito, utilize a operação específica de cartão")
    if kind not in ACCOUNT_KINDS:
        raise HTTPException(422, "Tipo de conta inválido; use checking, savings, cash ou investment")
    opening = signed_decimal(opening_balance, allow_zero=True, allow_negative=True)
    if session.scalar(select(Account).where(Account.name == clean_name)):
        raise HTTPException(409, "Já existe uma conta com esse nome")
    row = Account(name=clean_name, kind=kind, opening_balance=opening, is_active=True)
    session.add(row)
    session.flush()
    return account_payload(session, row)


def update_account_domain(session: Session, account_id: UUID, name: str | None = None,
                          kind: str | None = None, opening_balance: Decimal | str | None = None) -> dict:
    row = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
    if not row:
        raise HTTPException(404, "Conta não encontrada")
    if name is None and kind is None and opening_balance is None:
        raise HTTPException(422, "Informe ao menos um campo para atualizar a conta")
    if name is not None:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 80:
            raise HTTPException(422, "Nome da conta deve ter entre 1 e 80 caracteres")
        if session.scalar(select(Account).where(Account.name == clean_name, Account.id != account_id)):
            raise HTTPException(409, "Já existe uma conta com esse nome")
        row.name = clean_name
    if kind is not None and kind != row.kind:
        if row.kind == "credit_card" or kind == "credit_card":
            raise HTTPException(422, "Não é permitido converter conta comum em cartão de crédito ou vice-versa")
        if kind not in ACCOUNT_KINDS:
            raise HTTPException(422, "Tipo de conta inválido; use checking, savings, cash ou investment")
        row.kind = kind
    if opening_balance is not None:
        if row.kind == "credit_card":
            raise HTTPException(422, "Cartão de crédito não possui saldo inicial editável")
        row.opening_balance = signed_decimal(opening_balance, allow_zero=True, allow_negative=True)
    session.flush()
    return account_payload(session, row)


def archive_account_domain(session: Session, account_id: UUID) -> dict:
    row = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
    if not row:
        raise HTTPException(404, "Conta não encontrada")
    if not row.is_active:
        raise HTTPException(409, "Conta já está arquivada")
    if row.kind == "credit_card":
        card = session.scalar(select(CreditCard).where(CreditCard.account_id == row.id))
        if card:
            unpaid = session.scalar(
                select(Installment.id)
                .join(CreditPurchase, Installment.purchase_id == CreditPurchase.id)
                .join(Transaction, CreditPurchase.transaction_id == Transaction.id)
                .where(CreditPurchase.card_id == card.id, Installment.paid_date.is_(None), Transaction.deleted_at.is_(None))
                .limit(1)
            )
            if unpaid:
                raise HTTPException(409, "Cartão possui parcelas em aberto; quite ou exclua as compras antes de arquivar")
    active_plan = session.scalar(select(RecurringPlan.id).where(
        RecurringPlan.account_id == row.id,
        RecurringPlan.is_active.is_(True),
    ).limit(1))
    if active_plan:
        raise HTTPException(409, "Desative ou altere os planos recorrentes vinculados antes de arquivar a conta")
    row.is_active = False
    session.flush()
    return account_payload(session, row)


def restore_account_domain(session: Session, account_id: UUID) -> dict:
    row = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
    if not row:
        raise HTTPException(404, "Conta não encontrada")
    if row.is_active:
        raise HTTPException(409, "Conta já está ativa")
    row.is_active = True
    session.flush()
    return account_payload(session, row)


def category_payload_domain(session: Session, category: Category) -> dict:
    active = active_budget(session, category.id, date.today()) if category.kind == "expense" else None
    rule = active[3] if active else None
    future = session.scalar(
        select(BudgetRule)
        .where(BudgetRule.category_id == category.id, BudgetRule.effective_start > date.today())
        .order_by(BudgetRule.effective_start)
        .limit(1)
    ) if category.kind == "expense" else None
    display = rule or (future if not active else None)
    return {
        "id": str(category.id),
        "name": category.name,
        "kind": category.kind,
        "is_entertainment": category.is_entertainment,
        "icon": category.icon,
        "color": category.color,
        "is_active": category.is_active,
        "archived_on": category.archived_on,
        "visible_until": category.visible_until,
        "budget_limit": active[0] if active else future.limit_amount if future else None,
        "budget_period_type": display.period_type if display else "calendar_month",
        "budget_interval_count": display.interval_count if display else 1,
        "budget_renewal_day": display.renewal_day if display else None,
        "budget_effective_start": display.effective_start if display else None,
        "budget_scheduled_start": future.effective_start if future else None,
        "budget_period_start": active[1] if active else None,
        "budget_next_renewal": active[2] if active else None,
    }


def get_category_domain(session: Session, category_id: UUID) -> dict:
    from backend.app.categories import archive_preview
    row = session.get(Category, category_id)
    if not row:
        raise HTTPException(404, "Categoria não encontrada")
    payload = category_payload_domain(session, row)
    preview = archive_preview(session, row, date.today())
    payload["transaction_count"] = preview["transaction_count"]
    payload["current_spending_count"] = preview["current_spending_count"]
    payload["current_spent"] = preview["current_spent"]
    return payload


def create_category_domain(
    session: Session,
    name: str,
    kind: str = "expense",
    is_entertainment: bool = False,
    icon: str | None = None,
    color: str | None = None,
    budget_limit: Decimal | str | None = None,
    budget_period_type: str = "calendar_month",
    budget_interval_count: int = 1,
    budget_renewal_day: int | None = None,
    budget_effective_start: date | None = None,
) -> dict:
    from backend.app.categories import suggested_color
    import re
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 80:
        raise HTTPException(422, "Nome da categoria deve ter entre 1 e 80 caracteres")
    if kind not in ("income", "expense"):
        raise HTTPException(422, "Tipo de categoria inválido; use income ou expense")
    if icon and icon not in ICON_IDS:
        raise HTTPException(422, "Ícone de categoria inválido")
    if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise HTTPException(422, "Cor de categoria inválida; use formato #RRGGBB")
    if is_entertainment and kind != "expense":
        raise HTTPException(422, "Entretenimento precisa ser uma categoria de despesa")
    if session.scalar(select(Category).where(Category.name == clean_name)):
        raise HTTPException(409, "Já existe uma categoria com esse nome")
    category = Category(
        name=clean_name,
        kind=kind,
        is_entertainment=is_entertainment,
        icon=icon or None,
        color=color.upper() if color else suggested_color(session),
    )
    session.add(category)
    session.flush()
    if budget_limit is not None:
        if category.kind != "expense":
            raise HTTPException(422, "Limite só pode ser definido para categoria de despesa")
        set_budget(
            session,
            category.id,
            budget_effective_start or date.today(),
            Decimal(budget_limit),
            budget_period_type,
            budget_interval_count,
            budget_renewal_day,
        )
    return category_payload_domain(session, category)


def update_category_domain(
    session: Session,
    category_id: UUID,
    name: str | None = None,
    kind: str | None = None,
    is_entertainment: bool | None = None,
    icon: str | None = None,
    color: str | None = None,
    budget_limit: Decimal | str | None = None,
    budget_period_type: str | None = None,
    budget_interval_count: int | None = None,
    budget_renewal_day: int | None = None,
    budget_effective_start: date | None = None,
) -> dict:
    import re
    row = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if not row or not row.is_active:
        raise HTTPException(404, "Categoria não encontrada ou arquivada")
    if icon and icon not in ICON_IDS:
        raise HTTPException(422, "Ícone de categoria inválido")
    if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise HTTPException(422, "Cor de categoria inválida; use formato #RRGGBB")
    target_kind = kind if kind is not None else row.kind
    if target_kind not in ("income", "expense"):
        raise HTTPException(422, "Tipo de categoria inválido; use income ou expense")
    target_entertainment = is_entertainment if is_entertainment is not None else row.is_entertainment
    if target_entertainment and target_kind != "expense":
        raise HTTPException(422, "Entretenimento precisa ser uma categoria de despesa")
    if name is not None:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 80:
            raise HTTPException(422, "Nome da categoria deve ter entre 1 e 80 caracteres")
        other = session.scalar(select(Category).where(Category.name == clean_name, Category.id != category_id))
        if other:
            raise HTTPException(409, "Já existe uma categoria com esse nome")
        row.name = clean_name
    if row.kind != target_kind:
        has_tx = session.scalar(select(Transaction.id).where(Transaction.category_id == category_id).limit(1))
        has_budget = session.scalar(select(Budget.id).where(Budget.category_id == category_id).limit(1))
        if has_tx or has_budget or active_budget(session, category_id, date.today()):
            raise HTTPException(422, "O tipo de categoria com movimentações ou orçamento não pode ser alterado")
        row.kind = target_kind
    row.is_entertainment = target_entertainment
    if icon is not None:
        row.icon = icon or None
    if color is not None:
        row.color = color.upper()
    if budget_limit is not None:
        if row.kind != "expense":
            raise HTTPException(422, "Limite só pode ser definido para categoria de despesa")
        active = active_budget(session, row.id, date.today())
        current_rule = active[3] if active else None
        resolved_period_type = budget_period_type or (current_rule.period_type if current_rule else "calendar_month")
        resolved_interval = budget_interval_count if budget_interval_count is not None else (current_rule.interval_count if current_rule else 1)
        resolved_renewal_day = budget_renewal_day if budget_renewal_day is not None else (current_rule.renewal_day if current_rule else None)
        if resolved_period_type != "monthly_day":
            resolved_renewal_day = None
        limit_dec = Decimal(budget_limit)
        same = (
            active
            and active[0] == limit_dec
            and (current_rule.period_type if current_rule else "calendar_month") == resolved_period_type
            and (current_rule.interval_count if current_rule else 1) == resolved_interval
            and (current_rule.renewal_day if current_rule else None) == resolved_renewal_day
        )
        if not same or budget_effective_start is not None:
            set_budget(
                session,
                row.id,
                budget_effective_start or date.today(),
                limit_dec,
                resolved_period_type,
                resolved_interval,
                resolved_renewal_day,
            )
    session.flush()
    return category_payload_domain(session, row)


def settle_transaction_domain(session: Session, transaction_id: UUID, settled_on: date | None = None) -> dict:
    row = session.scalar(select(Transaction).where(Transaction.id == transaction_id).with_for_update())
    if not row:
        raise HTTPException(404, "Movimentação não encontrada")
    if row.deleted_at is not None:
        raise HTTPException(409, "Restaure a movimentação antes de marcá-la como realizada")
    if row.kind not in ("income", "expense", "refund"):
        raise HTTPException(422, "Este tipo de movimentação não pode ser liquidado aqui")
    if row.status == "settled":
        return {"id": str(row.id), "status": row.status, "settled_date": row.settled_date, "version": row.version}
    row.status = "settled"
    row.settled_date = settled_on or date.today()
    row.competence_date = period_for(row.settled_date)
    row.version += 1
    session.flush()
    return {"id": str(row.id), "status": row.status, "settled_date": row.settled_date, "version": row.version}


def get_transaction_revisions_domain(session: Session, transaction_id: UUID) -> list[dict]:
    if not session.get(Transaction, transaction_id):
        raise HTTPException(404, "Movimentação não encontrada")
    rows = session.scalars(
        select(TransactionRevision)
        .where(TransactionRevision.transaction_id == transaction_id)
        .order_by(TransactionRevision.version)
    ).all()
    return [
        {
            "id": str(row.id),
            "version": row.version,
            "reason": row.reason,
            "before": row.before_state,
            "after": row.after_state,
            "changed_at": row.changed_at,
        }
        for row in rows
    ]


def get_transaction_lifecycle_domain(session: Session, transaction_id: UUID) -> list[dict]:
    if not session.get(Transaction, transaction_id):
        raise HTTPException(404, "Movimentação não encontrada")
    rows = session.scalars(
        select(TransactionLifecycleEvent)
        .where(TransactionLifecycleEvent.transaction_id == transaction_id)
        .order_by(TransactionLifecycleEvent.occurred_at)
    ).all()
    return [{"id": str(row.id), "action": row.action, "occurred_at": row.occurred_at} for row in rows]


def _resolve_transfer_pair(session: Session, transaction_id: UUID, lock: bool = False) -> tuple[Transaction, Transaction]:
    stmt = select(Transaction).where(Transaction.id == transaction_id)
    if lock:
        stmt = stmt.with_for_update()
    row = session.scalar(stmt)
    if not row or row.kind not in ("transfer_out", "transfer_in") or not row.related_id:
        raise HTTPException(404, "Transferência não encontrada")
    pair_stmt = select(Transaction).where(Transaction.id == row.related_id)
    if lock:
        pair_stmt = pair_stmt.with_for_update()
    pair = session.scalar(pair_stmt)
    if not pair or pair.related_id != row.id or {row.kind, pair.kind} != {"transfer_out", "transfer_in"}:
        raise HTTPException(409, "Transferência sem par íntegro")
    outgoing, incoming = (row, pair) if row.kind == "transfer_out" else (pair, row)
    return outgoing, incoming


def transfer_payload_domain(session: Session, outgoing: Transaction, incoming: Transaction) -> dict:
    source = session.get(Account, outgoing.account_id)
    target = session.get(Account, incoming.account_id)
    is_invoice = bool((source and source.kind == "credit_card") or (target and target.kind == "credit_card"))
    return {
        "outgoing_id": str(outgoing.id),
        "incoming_id": str(incoming.id),
        "version": outgoing.version,
        "source_account_id": str(outgoing.account_id),
        "source_account": source.name if source else None,
        "destination_account_id": str(incoming.account_id),
        "destination_account": target.name if target else None,
        "amount": outgoing.amount,
        "transaction_date": outgoing.transaction_date,
        "description": outgoing.description,
        "status": outgoing.status,
        "is_invoice_payment": is_invoice,
        "deleted_at": outgoing.deleted_at,
    }


def list_transfers_domain(
    session: Session,
    start: date | None = None,
    end: date | None = None,
    account_id: UUID | None = None,
    include_invoice_payments: bool = False,
    limit: int = 100,
) -> list[dict]:
    stmt = (
        select(Transaction)
        .where(Transaction.kind == "transfer_out", Transaction.deleted_at.is_(None))
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    if start:
        stmt = stmt.where(Transaction.transaction_date >= start)
    if end:
        stmt = stmt.where(Transaction.transaction_date <= end)
    results = []
    for outgoing in session.scalars(stmt).all():
        if not outgoing.related_id:
            continue
        incoming = session.get(Transaction, outgoing.related_id)
        if not incoming or incoming.deleted_at is not None:
            continue
        if account_id and outgoing.account_id != account_id and incoming.account_id != account_id:
            continue
        payload = transfer_payload_domain(session, outgoing, incoming)
        if not include_invoice_payments and payload["is_invoice_payment"]:
            continue
        results.append(payload)
    return results


def get_transfer_domain(session: Session, transaction_id: UUID) -> dict:
    outgoing, incoming = _resolve_transfer_pair(session, transaction_id, lock=False)
    return transfer_payload_domain(session, outgoing, incoming)


def update_transfer_domain(
    session: Session,
    transaction_id: UUID,
    expected_version: int,
    amount: Decimal | str | None = None,
    source_account_id: UUID | None = None,
    destination_account_id: UUID | None = None,
    transaction_date: date | None = None,
    description: str | None = None,
    reason: str = "",
    key: str | None = None,
) -> dict:
    if not reason.strip() or len(reason.strip()) > 180:
        raise HTTPException(422, "Informe o motivo da correção da transferência (até 180 caracteres)")
    if key and (not key.strip() or len(key) > 120):
        raise HTTPException(422, "Chave de idempotência inválida")
    outgoing, incoming = _resolve_transfer_pair(session, transaction_id, lock=True)
    if outgoing.deleted_at is not None or incoming.deleted_at is not None:
        raise HTTPException(409, "Transferência está na lixeira; restaure-a antes de corrigir")
    source_current = session.get(Account, outgoing.account_id)
    target_current = session.get(Account, incoming.account_id)
    if (source_current and source_current.kind == "credit_card") or (target_current and target_current.kind == "credit_card"):
        raise HTTPException(422, "Pagamento de fatura de cartão não pode ser editado como transferência comum")
    previous = session.scalar(select(TransactionRevision).where(TransactionRevision.idempotency_key == key)) if key else None
    base_out = previous.before_state if previous else transaction_state(outgoing)
    resolved_amount = money(amount) if amount is not None else money(base_out["amount"])
    resolved_source_id = source_account_id or UUID(base_out["account_id"])
    resolved_dest_id = destination_account_id or incoming.account_id
    resolved_date = transaction_date or date.fromisoformat(base_out["transaction_date"])
    resolved_desc = description.strip() if description is not None else str(base_out["description"]).strip()
    digest = request_digest({
        "outgoing_id": outgoing.id,
        "expected_version": expected_version,
        "amount": resolved_amount,
        "source_account_id": resolved_source_id,
        "destination_account_id": resolved_dest_id,
        "transaction_date": resolved_date,
        "description": resolved_desc,
        "reason": reason.strip(),
    })
    if previous:
        if previous.request_hash != digest or previous.transaction_id != outgoing.id:
            raise HTTPException(409, "Chave de idempotência já usada com correção diferente")
        return transfer_payload_domain(session, outgoing, incoming)
    if outgoing.version != expected_version and incoming.version != expected_version:
        raise HTTPException(409, "Transferência foi alterada; consulte a versão atual antes de corrigir")
    if resolved_source_id == resolved_dest_id:
        raise HTTPException(422, "Origem e destino precisam ser contas diferentes")
    new_source = session.get(Account, resolved_source_id)
    new_target = session.get(Account, resolved_dest_id)
    if not new_source or not new_target or not new_source.is_active or not new_target.is_active:
        raise HTTPException(404, "Conta de origem ou destino não encontrada ou inativa")
    if new_source.kind == "credit_card" or new_target.kind == "credit_card":
        raise HTTPException(422, "Transferência comum não pode usar conta de cartão de crédito")
    if not resolved_desc or len(resolved_desc) > 180:
        raise HTTPException(422, "Descrição da transferência inválida")
    if (
        resolved_amount == outgoing.amount
        and resolved_source_id == outgoing.account_id
        and resolved_dest_id == incoming.account_id
        and resolved_date == outgoing.transaction_date
        and resolved_desc == outgoing.description
    ):
        raise HTTPException(422, "Nenhuma alteração informada")
    before_out = transaction_state(outgoing)
    before_in = transaction_state(incoming)
    outgoing.amount = incoming.amount = resolved_amount
    outgoing.account_id = resolved_source_id
    incoming.account_id = resolved_dest_id
    outgoing.transaction_date = incoming.transaction_date = resolved_date
    outgoing.competence_date = incoming.competence_date = period_for(resolved_date)
    outgoing.settled_date = incoming.settled_date = resolved_date
    outgoing.description = incoming.description = resolved_desc
    outgoing.version += 1
    incoming.version += 1
    session.add(TransactionRevision(
        transaction_id=outgoing.id,
        version=outgoing.version,
        reason=reason.strip(),
        before_state=before_out,
        after_state=transaction_state(outgoing),
        idempotency_key=key,
        request_hash=digest,
    ))
    session.add(TransactionRevision(
        transaction_id=incoming.id,
        version=incoming.version,
        reason=reason.strip(),
        before_state=before_in,
        after_state=transaction_state(incoming),
        idempotency_key=None,
        request_hash=request_digest({"incoming_id": incoming.id, "digest": digest}),
    ))
    session.flush()
    return transfer_payload_domain(session, outgoing, incoming)


def card_payload_domain(session: Session, card: CreditCard) -> dict:
    account = session.get(Account, card.account_id)
    invoices = invoice_status(session, card_id=card.id)
    open_liability = sum((inv["open_amount"] for inv in invoices), Decimal("0"))
    unpaid_invoices = [inv for inv in invoices if inv["paid_date"] is None and inv["open_amount"] > 0]
    purchase_count = session.scalar(
        select(func.count(CreditPurchase.id))
        .join(Transaction, CreditPurchase.transaction_id == Transaction.id)
        .where(CreditPurchase.card_id == card.id, Transaction.deleted_at.is_(None))
    ) or 0
    return {
        "id": str(card.id),
        "name": account.name,
        "account_id": str(account.id),
        "closing_day": card.closing_day,
        "due_day": card.due_day,
        "is_active": account.is_active,
        "open_liability": open_liability,
        "unpaid_invoices_count": len(unpaid_invoices),
        "purchase_count": int(purchase_count),
    }


def list_cards_domain(session: Session, scope: str = "active") -> list[dict]:
    if scope not in ("active", "archived", "all"):
        raise HTTPException(422, "Escopo de cartões inválido; use active, archived ou all")
    stmt = select(CreditCard).join(Account, CreditCard.account_id == Account.id).order_by(Account.name)
    if scope != "all":
        stmt = stmt.where(Account.is_active.is_(scope == "active"))
    return [card_payload_domain(session, card) for card in session.scalars(stmt).all()]


def get_card_domain(session: Session, card_id: UUID) -> dict:
    card = session.get(CreditCard, card_id)
    if not card:
        raise HTTPException(404, "Cartão não encontrado")
    payload = card_payload_domain(session, card)
    payload["invoices"] = invoice_status(session, card_id=card.id)
    return payload


def update_credit_card_domain(
    session: Session,
    card_id: UUID,
    name: str | None = None,
    closing_day: int | None = None,
    due_day: int | None = None,
) -> dict:
    card = session.scalar(select(CreditCard).where(CreditCard.id == card_id).with_for_update())
    if not card:
        raise HTTPException(404, "Cartão não encontrado")
    account = session.scalar(select(Account).where(Account.id == card.account_id).with_for_update())
    if name is None and closing_day is None and due_day is None:
        raise HTTPException(422, "Informe ao menos um campo para atualizar o cartão")
    if name is not None:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 80:
            raise HTTPException(422, "Nome do cartão inválido")
        if session.scalar(select(Account).where(Account.name == clean_name, Account.id != account.id)):
            raise HTTPException(409, "Já existe uma conta ou cartão com esse nome")
        account.name = clean_name
    if closing_day is not None:
        if not 1 <= closing_day <= 31:
            raise HTTPException(422, "Dia de fechamento deve ficar entre 1 e 31")
        card.closing_day = closing_day
    if due_day is not None:
        if not 1 <= due_day <= 31:
            raise HTTPException(422, "Dia de vencimento deve ficar entre 1 e 31")
        card.due_day = due_day
    session.flush()
    return card_payload_domain(session, card)


def archive_credit_card_domain(session: Session, card_id: UUID) -> dict:
    card = session.get(CreditCard, card_id)
    if not card:
        raise HTTPException(404, "Cartão não encontrado")
    archive_account_domain(session, card.account_id)
    return card_payload_domain(session, card)


def restore_credit_card_domain(session: Session, card_id: UUID) -> dict:
    card = session.get(CreditCard, card_id)
    if not card:
        raise HTTPException(404, "Cartão não encontrado")
    restore_account_domain(session, card.account_id)
    return card_payload_domain(session, card)


def get_invoice_domain(session: Session, invoice_id: UUID) -> dict:
    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(404, "Fatura não encontrada")
    card = session.get(CreditCard, invoice.card_id)
    account = session.get(Account, card.account_id)
    rows = session.execute(
        select(Installment, CreditPurchase, Transaction)
        .join(CreditPurchase, Installment.purchase_id == CreditPurchase.id)
        .join(Transaction, CreditPurchase.transaction_id == Transaction.id)
        .where(Installment.invoice_id == invoice.id, Transaction.deleted_at.is_(None))
        .order_by(CreditPurchase.purchase_date, Installment.sequence)
    ).all()
    items = [
        {
            "installment_id": str(inst.id),
            "purchase_id": str(purchase.id),
            "transaction_id": str(tx.id),
            "merchant": purchase.merchant,
            "purchase_date": purchase.purchase_date,
            "category_id": str(tx.category_id) if tx.category_id else None,
            "sequence": inst.sequence,
            "installment_count": purchase.installment_count,
            "amount": inst.amount,
            "due_date": inst.due_date,
            "paid_date": inst.paid_date,
        }
        for inst, purchase, tx in rows
    ]
    total = sum((item["amount"] for item in items), Decimal("0"))
    open_amount = sum((item["amount"] for item in items if item["paid_date"] is None), Decimal("0"))
    return {
        "id": str(invoice.id),
        "card_id": str(card.id),
        "card": account.name,
        "due_date": invoice.due_date,
        "total": total,
        "open_amount": open_amount,
        "paid_date": invoice.paid_date,
        "installment_count": len(items),
        "installments": items,
    }


def list_installments_domain(
    session: Session,
    card_id: UUID | None = None,
    invoice_id: UUID | None = None,
    purchase_id: UUID | None = None,
    unpaid_only: bool = False,
    through: date | None = None,
) -> list[dict]:
    stmt = (
        select(Installment, CreditPurchase, Transaction, CreditCard, Account)
        .join(CreditPurchase, Installment.purchase_id == CreditPurchase.id)
        .join(Transaction, CreditPurchase.transaction_id == Transaction.id)
        .join(CreditCard, CreditPurchase.card_id == CreditCard.id)
        .join(Account, CreditCard.account_id == Account.id)
        .where(Transaction.deleted_at.is_(None))
        .order_by(Installment.due_date, CreditPurchase.purchase_date, Installment.sequence)
    )
    if card_id:
        stmt = stmt.where(CreditPurchase.card_id == card_id)
    if invoice_id:
        stmt = stmt.where(Installment.invoice_id == invoice_id)
    if purchase_id:
        stmt = stmt.where(Installment.purchase_id == purchase_id)
    if unpaid_only:
        stmt = stmt.where(Installment.paid_date.is_(None))
    if through:
        stmt = stmt.where(Installment.due_date <= through)
    return [
        {
            "id": str(inst.id),
            "purchase_id": str(purchase.id),
            "invoice_id": str(inst.invoice_id),
            "card_id": str(card.id),
            "card": account.name,
            "merchant": purchase.merchant,
            "category_id": str(tx.category_id) if tx.category_id else None,
            "sequence": inst.sequence,
            "installment_count": purchase.installment_count,
            "amount": inst.amount,
            "due_date": inst.due_date,
            "paid_date": inst.paid_date,
        }
        for inst, purchase, tx, card, account in session.execute(stmt).all()
    ]


def bill_payload_domain(bill: Bill) -> dict:
    return {
        "id": str(bill.id),
        "description": bill.description,
        "amount": bill.amount,
        "due_date": bill.due_date,
        "paid_date": bill.paid_date,
        "category_id": str(bill.category_id) if bill.category_id else None,
        "payment_transaction_id": str(bill.payment_transaction_id) if bill.payment_transaction_id else None,
    }


def list_bills_domain(
    session: Session,
    through: date | None = None,
    include_paid: bool = False,
    category_id: UUID | None = None,
) -> list[dict]:
    stmt = select(Bill).order_by(Bill.due_date, Bill.description)
    if not include_paid:
        stmt = stmt.where(Bill.paid_date.is_(None))
    if through:
        stmt = stmt.where(Bill.due_date <= through)
    if category_id:
        stmt = stmt.where(Bill.category_id == category_id)
    return [bill_payload_domain(row) for row in session.scalars(stmt).all()]


def get_bill_domain(session: Session, bill_id: UUID) -> dict:
    row = session.get(Bill, bill_id)
    if not row:
        raise HTTPException(404, "Conta a pagar não encontrada")
    return bill_payload_domain(row)


def create_bill_domain(
    session: Session,
    description: str,
    amount: Decimal | str,
    due_date: date,
    category_id: UUID | None = None,
) -> dict:
    clean_desc = description.strip()
    if not clean_desc or len(clean_desc) > 180:
        raise HTTPException(422, "Descrição da conta a pagar deve ter entre 1 e 180 caracteres")
    valid_amount = money(amount)
    if category_id:
        category = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
        if not category or not category.is_active or category.kind != "expense":
            raise HTTPException(422, "Selecione uma categoria de despesa ativa")
    row = Bill(description=clean_desc, amount=valid_amount, due_date=due_date, category_id=category_id)
    session.add(row)
    session.flush()
    return bill_payload_domain(row)


def update_bill_domain(
    session: Session,
    bill_id: UUID,
    description: str | None = None,
    amount: Decimal | str | None = None,
    due_date: date | None = None,
    category_id: UUID | None = None,
) -> dict:
    row = session.scalar(select(Bill).where(Bill.id == bill_id).with_for_update())
    if not row:
        raise HTTPException(404, "Conta a pagar não encontrada")
    if row.paid_date is not None:
        raise HTTPException(409, "Conta já está paga; para alterá-la, exclua primeiro o pagamento na lixeira")
    if description is None and amount is None and due_date is None and category_id is None:
        raise HTTPException(422, "Informe ao menos um campo para atualizar a conta a pagar")
    if description is not None:
        clean_desc = description.strip()
        if not clean_desc or len(clean_desc) > 180:
            raise HTTPException(422, "Descrição da conta a pagar deve ter entre 1 e 180 caracteres")
        row.description = clean_desc
    if amount is not None:
        row.amount = money(amount)
    if due_date is not None:
        row.due_date = due_date
    if category_id is not None:
        category = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
        if not category or not category.is_active or category.kind != "expense":
            raise HTTPException(422, "Selecione uma categoria de despesa ativa")
        row.category_id = category_id
    session.flush()
    return bill_payload_domain(row)


def pay_bill_domain(
    session: Session,
    bill_id: UUID,
    source_account_id: UUID,
    paid_date: date,
    key: str | None = None,
) -> dict:
    bill = session.scalar(select(Bill).where(Bill.id == bill_id).with_for_update())
    if not bill:
        raise HTTPException(404, "Conta a pagar não encontrada")
    scoped_key = f"bill:{bill_id}:{key}" if key else None
    if bill.paid_date:
        tx = session.get(Transaction, bill.payment_transaction_id) if bill.payment_transaction_id else None
        if tx and scoped_key and tx.idempotency_key == scoped_key and tx.account_id == source_account_id and bill.paid_date == paid_date:
            return {"bill_id": str(bill.id), "transaction_id": str(tx.id), "amount": tx.amount, "paid_date": bill.paid_date}
        raise HTTPException(409, "Conta já está paga")
    if not bill.category_id:
        raise HTTPException(422, "Defina uma categoria para pagar esta conta")
    tx = create_transaction(
        session,
        {
            "kind": "expense",
            "amount": bill.amount,
            "account_id": source_account_id,
            "category_id": bill.category_id,
            "description": bill.description,
            "transaction_date": paid_date,
            "status": "settled",
            "related_transaction_id": bill.id,
        },
        scoped_key,
    )
    bill.paid_date = paid_date
    bill.payment_transaction_id = tx.id
    session.flush()
    return {"bill_id": str(bill.id), "transaction_id": str(tx.id), "amount": tx.amount, "paid_date": bill.paid_date}


def update_recurring_plan_domain(
    session: Session,
    plan_id: UUID,
    description: str | None = None,
    amount: Decimal | str | None = None,
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    start_date: date | None = None,
) -> dict:
    plan = session.scalar(select(RecurringPlan).where(RecurringPlan.id == plan_id).with_for_update())
    if not plan:
        raise HTTPException(404, "Plano recorrente não encontrado")
    if description is None and amount is None and account_id is None and category_id is None and start_date is None:
        raise HTTPException(422, "Informe ao menos um campo para atualizar o plano recorrente")
    if description is not None:
        clean_desc = description.strip()
        if not clean_desc or len(clean_desc) > 180:
            raise HTTPException(422, "Descrição do plano deve ter entre 1 e 180 caracteres")
        plan.description = clean_desc
    if amount is not None:
        plan.amount = money(amount)
    if account_id is not None:
        account = session.get(Account, account_id)
        if not account or not account.is_active or account.kind == "credit_card":
            raise HTTPException(422, "Selecione uma conta monetária ativa")
        plan.account_id = account.id
    if category_id is not None:
        category = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
        if not category or not category.is_active or category.kind != plan.kind:
            raise HTTPException(422, "Categoria incompatível com o plano")
        plan.category_id = category.id
    if start_date is not None:
        plan.start_date = start_date
    session.flush()
    return {
        "id": str(plan.id),
        "description": plan.description,
        "kind": plan.kind,
        "amount": plan.amount,
        "account_id": str(plan.account_id),
        "category_id": str(plan.category_id) if plan.category_id else None,
        "start_date": plan.start_date,
        "is_active": plan.is_active,
    }


def set_recurring_plan_active_domain(session: Session, plan_id: UUID, is_active: bool) -> dict:
    plan = session.scalar(select(RecurringPlan).where(RecurringPlan.id == plan_id).with_for_update())
    if not plan:
        raise HTTPException(404, "Plano recorrente não encontrado")
    plan.is_active = is_active
    session.flush()
    return {
        "id": str(plan.id),
        "description": plan.description,
        "kind": plan.kind,
        "amount": plan.amount,
        "is_active": plan.is_active,
    }


def get_category_budget_domain(session: Session, category_id: UUID, day: date | None = None) -> dict:
    target_day = day or date.today()
    category = session.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Categoria não encontrada")
    if category.kind != "expense":
        raise HTTPException(422, "Apenas categorias de despesa possuem orçamento")
    status_rows = [row for row in budget_status(session, target_day) if UUID(row["category_id"]) == category_id]
    active_status = status_rows[0] if status_rows else None
    rules = session.scalars(
        select(BudgetRule)
        .where(BudgetRule.category_id == category_id)
        .order_by(BudgetRule.effective_start.desc())
    ).all()
    return {
        "category_id": str(category.id),
        "category": category.name,
        "is_active": category.is_active,
        "as_of": target_day,
        "active_cycle": active_status,
        "rules": [
            {
                "id": str(r.id),
                "effective_start": r.effective_start,
                "limit_amount": r.limit_amount,
                "period_type": r.period_type,
                "interval_count": r.interval_count,
                "renewal_day": r.renewal_day,
            }
            for r in rules
        ],
    }


def get_investment_domain(session: Session, investment_id: UUID) -> dict:
    row = session.get(Investment, investment_id)
    if not row:
        raise HTTPException(404, "Investimento não encontrado")
    summary = investment_summary(session, row)
    summary["notes"] = row.notes
    summary["events"] = list_investment_events_domain(session, investment_id=investment_id)
    summary["valuations"] = list_investment_valuations_domain(session, investment_id=investment_id)
    return summary


def create_investment_domain(
    session: Session,
    name: str,
    kind: str,
    current_value: Decimal | str = Decimal("0.00"),
    valuation_date: date | None = None,
    institution: str | None = None,
    quantity: Decimal | str | None = None,
    opening_contribution: Decimal | str | None = None,
    acquired_on: date | None = None,
    notes: str | None = None,
) -> dict:
    clean_name = name.strip()
    clean_kind = kind.strip()
    if not clean_name or len(clean_name) > 80:
        raise HTTPException(422, "Nome do investimento inválido")
    if not clean_kind or len(clean_kind) > 40:
        raise HTTPException(422, "Tipo do investimento inválido")
    val_dec = signed_decimal(current_value, allow_zero=True, allow_negative=False)
    if val_dec > 0 and not valuation_date:
        raise HTTPException(422, "Informe a data da avaliação inicial")
    qty_dec = None
    if quantity is not None:
        try:
            qty_dec = Decimal(quantity)
            if not qty_dec.is_finite() or qty_dec <= 0 or qty_dec != qty_dec.quantize(Decimal("0.00000001")):
                raise ValueError()
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(422, "Quantidade do investimento inválida")
    opening_dec = None
    if opening_contribution is not None:
        opening_dec = signed_decimal(opening_contribution, allow_zero=True, allow_negative=False)
    row = Investment(
        name=clean_name,
        kind=clean_kind,
        institution=institution.strip() if institution else None,
        quantity=qty_dec,
        opening_contribution=opening_dec,
        acquired_on=acquired_on,
        current_value=val_dec,
        valuation_date=valuation_date,
        notes=notes,
    )
    session.add(row)
    session.flush()
    if valuation_date:
        record_investment_valuation(session, row.id, val_dec, valuation_date)
    return investment_summary(session, row)


def update_investment_domain(
    session: Session,
    investment_id: UUID,
    name: str | None = None,
    kind: str | None = None,
    institution: str | None = None,
    quantity: Decimal | str | None = None,
    opening_contribution: Decimal | str | None = None,
    acquired_on: date | None = None,
    notes: str | None = None,
) -> dict:
    row = session.scalar(select(Investment).where(Investment.id == investment_id).with_for_update())
    if not row:
        raise HTTPException(404, "Investimento não encontrado")
    if all(v is None for v in (name, kind, institution, quantity, opening_contribution, acquired_on, notes)):
        raise HTTPException(422, "Informe ao menos um campo para atualizar o investimento")
    if name is not None:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 80:
            raise HTTPException(422, "Nome do investimento inválido")
        row.name = clean_name
    if kind is not None:
        clean_kind = kind.strip()
        if not clean_kind or len(clean_kind) > 40:
            raise HTTPException(422, "Tipo do investimento inválido")
        row.kind = clean_kind
    if institution is not None:
        row.institution = institution.strip() or None
    if quantity is not None:
        try:
            qty_dec = Decimal(quantity)
            if not qty_dec.is_finite() or qty_dec <= 0 or qty_dec != qty_dec.quantize(Decimal("0.00000001")):
                raise ValueError()
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(422, "Quantidade do investimento inválida")
        row.quantity = qty_dec
    if opening_contribution is not None:
        row.opening_contribution = signed_decimal(opening_contribution, allow_zero=True, allow_negative=False)
    if acquired_on is not None:
        row.acquired_on = acquired_on
    if notes is not None:
        row.notes = notes
    session.flush()
    return investment_summary(session, row)


def list_investment_events_domain(
    session: Session,
    investment_id: UUID | None = None,
    kind: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    stmt = (
        select(InvestmentEvent, Investment.name)
        .join(Investment, InvestmentEvent.investment_id == Investment.id)
        .order_by(InvestmentEvent.event_date.desc())
    )
    if investment_id:
        stmt = stmt.where(InvestmentEvent.investment_id == investment_id)
    if kind:
        stmt = stmt.where(InvestmentEvent.kind == kind)
    if start:
        stmt = stmt.where(InvestmentEvent.event_date >= start)
    if end:
        stmt = stmt.where(InvestmentEvent.event_date <= end)
    return [
        {
            "id": str(ev.id),
            "investment_id": str(ev.investment_id),
            "investment": inv_name,
            "account_id": str(ev.account_id),
            "kind": ev.kind,
            "amount": ev.amount,
            "event_date": ev.event_date,
        }
        for ev, inv_name in session.execute(stmt).all()
    ]


def list_investment_valuations_domain(session: Session, investment_id: UUID) -> list[dict]:
    if not session.get(Investment, investment_id):
        raise HTTPException(404, "Investimento não encontrado")
    rows = session.scalars(
        select(InvestmentValuation)
        .where(InvestmentValuation.investment_id == investment_id)
        .order_by(InvestmentValuation.valuation_date, InvestmentValuation.recorded_at)
    ).all()
    return [
        {
            "id": str(row.id),
            "investment_id": str(row.investment_id),
            "value": row.value,
            "valuation_date": row.valuation_date,
            "recorded_at": row.recorded_at,
        }
        for row in rows
    ]


def _validate_goal_fields(
    session: Session,
    target_amount: Decimal,
    allocated_amount: Decimal,
    tracking_mode: str,
    account_ids: list[UUID],
) -> None:
    for value in (target_amount, allocated_amount):
        if not value.is_finite() or value != value.quantize(Decimal("0.01")):
            raise HTTPException(422, "Valores da meta inválidos")
    if target_amount <= 0 or allocated_amount < 0 or allocated_amount > target_amount:
        raise HTTPException(422, "Valores da meta inválidos")
    if tracking_mode not in ("none", "all", "selected"):
        raise HTTPException(422, "Modo de acompanhamento inválido; use none, all ou selected")
    if tracking_mode != "selected" and account_ids:
        raise HTTPException(422, "Selecione contas apenas no modo de acompanhamento específico")
    if tracking_mode == "selected" and not account_ids:
        raise HTTPException(422, "Selecione ao menos uma conta")
    for aid in set(account_ids):
        account = session.get(Account, aid)
        if not account or not account.is_active or account.kind == "credit_card":
            raise HTTPException(422, "Conta de acompanhamento inválida")


def _validate_reserve_increase_domain(session: Session, increase: Decimal) -> None:
    cash = sum((row["balance"] for row in account_balances(session) if row["kind"] != "credit_card"), Decimal("0"))
    reserved = session.scalar(select(func.coalesce(func.sum(Goal.allocated_amount), 0))) or Decimal("0")
    if Decimal(reserved) + increase > cash:
        raise HTTPException(422, "Não há saldo para aumentar a reserva; a meta pode existir sem reserva")


def get_goal_domain(session: Session, goal_id: UUID) -> dict:
    if not session.get(Goal, goal_id):
        raise HTTPException(404, "Meta não encontrada")
    all_goals = goals(session)
    match = next((g for g in all_goals if UUID(g["id"]) == goal_id), None)
    if not match:
        raise HTTPException(404, "Meta não encontrada")
    match["contributions"] = list_goal_contributions_domain(session, goal_id)
    match["allocations"] = list_goal_allocations_domain(session, goal_id)
    return match


def create_goal_domain(
    session: Session,
    name: str,
    target_amount: Decimal | str,
    allocated_amount: Decimal | str = Decimal("0.00"),
    target_date: date | None = None,
    tracking_mode: str = "none",
    account_ids: list[UUID] | None = None,
) -> dict:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 120:
        raise HTTPException(422, "Informe o nome da meta")
    target_dec = signed_decimal(target_amount, allow_zero=False, allow_negative=False)
    alloc_dec = signed_decimal(allocated_amount, allow_zero=True, allow_negative=False)
    acc_ids = list(account_ids or [])
    _validate_goal_fields(session, target_dec, alloc_dec, tracking_mode, acc_ids)
    if session.scalar(select(Goal.id).where(Goal.name == clean_name)):
        raise HTTPException(409, "Já existe uma meta com esse nome")
    if alloc_dec > 0:
        _validate_reserve_increase_domain(session, alloc_dec)
    row = Goal(
        name=clean_name,
        target_amount=target_dec,
        allocated_amount=alloc_dec,
        target_date=target_date,
        tracking_mode=tracking_mode,
    )
    session.add(row)
    session.flush()
    if tracking_mode == "selected":
        session.add_all(GoalTrackingAccount(goal_id=row.id, account_id=aid) for aid in set(acc_ids))
    if row.allocated_amount > 0:
        session.add(GoalAllocation(
            goal_id=row.id,
            amount_delta=row.allocated_amount,
            allocated_on=date.today(),
            note="Reserva inicial",
        ))
    session.flush()
    return get_goal_domain(session, row.id)


def update_goal_domain(
    session: Session,
    goal_id: UUID,
    name: str | None = None,
    target_amount: Decimal | str | None = None,
    allocated_amount: Decimal | str | None = None,
    target_date: date | None = None,
    clear_target_date: bool = False,
    tracking_mode: str | None = None,
    account_ids: list[UUID] | None = None,
) -> dict:
    row = session.scalar(select(Goal).where(Goal.id == goal_id).with_for_update())
    if not row:
        raise HTTPException(404, "Meta não encontrada")
    clean_name = name.strip() if name is not None else row.name
    if not clean_name or len(clean_name) > 120:
        raise HTTPException(422, "Informe o nome da meta")
    if session.scalar(select(Goal.id).where(Goal.name == clean_name, Goal.id != goal_id)):
        raise HTTPException(409, "Já existe uma meta com esse nome")
    target_dec = signed_decimal(target_amount, allow_zero=False, allow_negative=False) if target_amount is not None else row.target_amount
    alloc_dec = signed_decimal(allocated_amount, allow_zero=True, allow_negative=False) if allocated_amount is not None else row.allocated_amount
    resolved_mode = tracking_mode if tracking_mode is not None else row.tracking_mode
    existing_links = session.scalars(select(GoalTrackingAccount).where(GoalTrackingAccount.goal_id == row.id)).all()
    if account_ids is not None:
        resolved_accounts = list(account_ids)
    elif resolved_mode == "selected":
        resolved_accounts = [link.account_id for link in existing_links]
    else:
        resolved_accounts = []
    _validate_goal_fields(session, target_dec, alloc_dec, resolved_mode, resolved_accounts)
    if alloc_dec > row.allocated_amount:
        _validate_reserve_increase_domain(session, alloc_dec - row.allocated_amount)
    difference = alloc_dec - row.allocated_amount
    row.name = clean_name
    row.target_amount = target_dec
    row.allocated_amount = alloc_dec
    if clear_target_date:
        row.target_date = None
    elif target_date is not None:
        row.target_date = target_date
    row.tracking_mode = resolved_mode
    wanted_set = set(resolved_accounts) if resolved_mode == "selected" else set()
    existing_set = {link.account_id for link in existing_links}
    for link in existing_links:
        if link.account_id not in wanted_set:
            session.delete(link)
    for aid in wanted_set - existing_set:
        session.add(GoalTrackingAccount(goal_id=row.id, account_id=aid))
    if difference:
        session.add(GoalAllocation(
            goal_id=row.id,
            amount_delta=difference,
            allocated_on=date.today(),
            note="Atualização da reserva",
        ))
    session.flush()
    return get_goal_domain(session, row.id)


def add_goal_contribution_domain(
    session: Session,
    goal_id: UUID,
    amount_delta: Decimal | str,
    contributed_on: date,
    note: str,
) -> dict:
    goal = session.scalar(select(Goal).where(Goal.id == goal_id).with_for_update())
    if not goal:
        raise HTTPException(404, "Meta não encontrada")
    delta_dec = signed_decimal(amount_delta, allow_zero=False, allow_negative=True)
    if not note.strip() or len(note.strip()) > 180:
        raise HTTPException(422, "Informe a nota da contribuição")
    contributed = session.scalar(
        select(func.coalesce(func.sum(GoalContribution.amount_delta), 0))
        .where(GoalContribution.goal_id == goal_id)
    ) or Decimal("0")
    if Decimal(contributed) + delta_dec < 0:
        raise HTTPException(422, "A contribuição acumulada não pode ser negativa")
    entry = GoalContribution(
        goal_id=goal_id,
        amount_delta=delta_dec,
        contributed_on=contributed_on,
        note=note.strip(),
    )
    session.add(entry)
    session.flush()
    return {
        "id": str(entry.id),
        "goal_id": str(goal_id),
        "amount_delta": entry.amount_delta,
        "contributed_on": entry.contributed_on,
        "note": entry.note,
    }


def list_goal_contributions_domain(session: Session, goal_id: UUID) -> list[dict]:
    if not session.get(Goal, goal_id):
        raise HTTPException(404, "Meta não encontrada")
    rows = session.scalars(
        select(GoalContribution)
        .where(GoalContribution.goal_id == goal_id)
        .order_by(GoalContribution.contributed_on, GoalContribution.created_at)
    ).all()
    return [
        {
            "id": str(row.id),
            "amount_delta": row.amount_delta,
            "contributed_on": row.contributed_on,
            "note": row.note,
        }
        for row in rows
    ]


def list_goal_allocations_domain(session: Session, goal_id: UUID) -> list[dict]:
    if not session.get(Goal, goal_id):
        raise HTTPException(404, "Meta não encontrada")
    rows = session.scalars(
        select(GoalAllocation)
        .where(GoalAllocation.goal_id == goal_id)
        .order_by(GoalAllocation.allocated_on, GoalAllocation.created_at)
    ).all()
    return [
        {
            "id": str(row.id),
            "amount_delta": row.amount_delta,
            "allocated_on": row.allocated_on,
            "note": row.note,
        }
        for row in rows
    ]


def _period_metrics(session: Session, start: date, end: date) -> dict:
    if start > end:
        raise HTTPException(422, "Data inicial posterior à data final")
    financial_date = func.coalesce(Transaction.settled_date, Transaction.transaction_date)
    totals = session.execute(
        select(Transaction.kind, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.status == "settled",
            Transaction.deleted_at.is_(None),
            financial_date >= start,
            financial_date <= end,
            Transaction.kind.in_(["income", "expense", "refund"]),
        )
        .group_by(Transaction.kind)
    ).all()
    sums = {kind: Decimal(value) for kind, value in totals}
    income = sums.get("income", Decimal("0"))
    expenses = sums.get("expense", Decimal("0")) - sums.get("refund", Decimal("0"))
    by_category = spend_by_category(session, start, end)
    return {
        "start": start,
        "end": end,
        "income": income,
        "expenses": expenses,
        "result": income - expenses,
        "by_category": by_category,
    }


def compare_periods_domain(session: Session, start_a: date, end_a: date, start_b: date, end_b: date) -> dict:
    period_a = _period_metrics(session, start_a, end_a)
    period_b = _period_metrics(session, start_b, end_b)
    cat_a = {row["category_id"]: row for row in period_a["by_category"]}
    cat_b = {row["category_id"]: row for row in period_b["by_category"]}
    all_cat_ids = sorted(set(cat_a) | set(cat_b), key=lambda cid: (cat_a.get(cid) or cat_b.get(cid))["category"])
    category_deltas = []
    for cid in all_cat_ids:
        row_a = cat_a.get(cid)
        row_b = cat_b.get(cid)
        spent_a = row_a["spent"] if row_a else Decimal("0")
        spent_b = row_b["spent"] if row_b else Decimal("0")
        category_deltas.append({
            "category_id": cid,
            "category": (row_a or row_b)["category"],
            "spent_a": spent_a,
            "spent_b": spent_b,
            "difference": spent_b - spent_a,
        })
    exp_a = period_a["expenses"]
    exp_b = period_b["expenses"]
    pct_change = ((exp_b - exp_a) / exp_a * 100).quantize(Decimal("0.01")) if exp_a > 0 else None
    return {
        "period_a": period_a,
        "period_b": period_b,
        "difference": {
            "income_diff": period_b["income"] - period_a["income"],
            "expenses_diff": exp_b - exp_a,
            "result_diff": period_b["result"] - period_a["result"],
            "expenses_percent_change": pct_change,
        },
        "category_comparison": category_deltas,
    }


def calendar_summary_domain(session: Session, start: date, end: date) -> dict:
    days = calendar_days(session, start, end)
    total_income = sum((d["income"] for d in days), Decimal("0"))
    total_expenses = sum((d["expenses"] for d in days), Decimal("0"))
    pending_bills = sum(
        (b["amount"] for d in days for b in d["bills"] if not b["paid"]),
        Decimal("0"),
    )
    unpaid_invoices = sum(
        (inv["amount"] for d in days for inv in d["invoices"] if not inv["paid"]),
        Decimal("0"),
    )
    unrealized_recurring = sum(
        (rec["amount"] if rec["kind"] == "expense" else -rec["amount"] for d in days for rec in d["recurring"]),
        Decimal("0"),
    )
    return {
        "start": start,
        "end": end,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_result": total_income - total_expenses,
        "pending_bills_total": pending_bills,
        "unpaid_invoices_total": unpaid_invoices,
        "days": days,
    }
