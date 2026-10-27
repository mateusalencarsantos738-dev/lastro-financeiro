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


def invoice_status(session: Session, through: date | None = None) -> list[dict]:
    stmt = select(Invoice).order_by(Invoice.due_date)
    if through: stmt = stmt.where(Invoice.due_date <= through)
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
                       amount: Decimal, category_id: UUID | None, description: str,
                       transaction_date: date, reason: str, key: str | None = None) -> Transaction:
    if not reason.strip() or len(reason.strip()) > 180:
        raise HTTPException(422, "Informe o motivo da correção (até 180 caracteres)")
    if key and (not key.strip() or len(key) > 120):
        raise HTTPException(422, "Chave de idempotência inválida")
    amount = money(amount)
    digest = request_digest({"transaction_id": transaction_id, "expected_version": expected_version,
                             "amount": amount, "category_id": category_id, "description": description.strip(),
                             "transaction_date": transaction_date, "reason": reason.strip()})
    if key and (previous := session.scalar(select(TransactionRevision).where(TransactionRevision.idempotency_key == key))):
        if previous.request_hash != digest or previous.transaction_id != transaction_id:
            raise HTTPException(409, "Chave de idempotência já usada com correção diferente")
        existing = session.get(Transaction, transaction_id)
        if not existing or existing.version != previous.version:
            raise HTTPException(409, "Correção já aplicada; o registro foi alterado depois")
        return existing
    row = session.scalar(select(Transaction).where(Transaction.id == transaction_id).with_for_update())
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
    category = session.scalar(select(Category).where(Category.id == category_id).with_for_update()) if category_id else None
    if row.kind in ("expense", "refund") and category is None:
        raise HTTPException(422, "Despesa ou reembolso exige categoria")
    if category and ((not category.is_active and category_id != row.category_id) or category.kind != ("income" if row.kind == "income" else "expense")):
        raise HTTPException(422, "Categoria incompatível")
    if not description.strip() or len(description.strip()) > 180:
        raise HTTPException(422, "Descrição inválida")
    before = transaction_state(row)
    row.amount = amount
    row.category_id = category_id
    row.description = description.strip()
    row.transaction_date = transaction_date
    row.competence_date = period_for(transaction_date)
    row.settled_date = transaction_date
    row.version += 1
    after = transaction_state(row)
    unchanged = dict(after, version=before["version"])
    if before == unchanged:
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
