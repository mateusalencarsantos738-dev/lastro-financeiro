from calendar import monthrange
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from functools import wraps
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.categories import archive_preview, archive_category, restore_category, suggested_color
from backend.app.serialization import wire
from backend.app.domain import (
    account_balances, budget_status, create_investment_event, create_transaction,
    create_transfer, create_credit_card, create_credit_purchase, invoice_status, pay_invoice,
    get_upcoming_bills, goals, net_worth, overview, period_for, entertainment_status,
    spend_by_category, set_budget, active_budget, preview_budget_cycle, monthly_comparison as calculate_monthly_comparison,
    update_transaction, record_investment_valuation, record_net_worth_snapshot,
    create_recurring_plan, recurring_status, realize_recurring_plan, investment_summary,
    delete_transaction, restore_transaction, transaction_deletion_group, calendar_days,
    card_purchase_payload, update_card_purchase,
)
from backend.app.models import Account, Bill, Budget, BudgetRule, Category, Goal, GoalAllocation, GoalTrackingAccount, GoalContribution, Investment, InvestmentEvent, Transaction, TransactionLifecycleEvent, CreditCard, CreditPurchase, Invoice, Installment, TransactionRevision, InvestmentValuation, NetWorthSnapshot, RecurringPlan
from backend.app.schemas import (
    AccountCreate, BillCreate, BudgetCreate, BudgetCyclePreview, CategoryCreate, GoalCreate, GoalContributionCreate,
    InvestmentCreate, InvestmentEventCreate, TransactionCreate, TransferCreate,
    CreditCardCreate, CreditPurchaseCreate, CreditPurchaseUpdate, InvoicePayment, BillPayment,
    TransactionUpdate, InvestmentValuationCreate, RecurringPlanCreate,
)

class DecimalRouter(APIRouter):
    def add_api_route(self, path, endpoint, **kwargs):
        @wraps(endpoint)
        def serialized(**values):
            result = endpoint(**values)
            return result if isinstance(result, Response) else wire(result)
        return super().add_api_route(path, serialized, **kwargs)


router = DecimalRouter(prefix="/api")
ICON_IDS = {"utensils", "coffee", "home", "car", "heart", "book", "school", "film", "music", "bag", "cart", "receipt", "plane", "bank", "wallet", "work", "gift", "pet", "sport", "light", "sparkles", "other"}


def key_header(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return idempotency_key


def transaction_payload(row: Transaction) -> dict:
    return {"id": str(row.id), "version": row.version, "kind": row.kind, "amount": row.amount,
            "account_id": str(row.account_id), "category_id": str(row.category_id) if row.category_id else None,
            "description": row.description, "transaction_date": row.transaction_date,
            "competence_date": row.competence_date, "settled_date": row.settled_date,
            "status": row.status, "notes": row.notes, "deleted_at": row.deleted_at}


@router.get("/accounts")
def list_accounts(session: Session = Depends(get_session)):
    return [{"id": str(a.id), "name": a.name, "kind": a.kind, "currency": a.currency, "is_active": a.is_active} for a in session.scalars(select(Account).order_by(Account.name))]


@router.post("/accounts", status_code=201)
def add_account(data: AccountCreate, session: Session = Depends(get_session)):
    if session.scalar(select(Account).where(Account.name == data.name.strip())):
        raise HTTPException(409, "Já existe uma conta com esse nome")
    account = Account(name=data.name.strip(), kind=data.kind, opening_balance=data.opening_balance)
    session.add(account)
    session.commit()
    return {"id": str(account.id), "name": account.name, "kind": account.kind}


@router.get("/categories")
def list_categories(scope: str = "active", session: Session = Depends(get_session)):
    if scope not in ("active", "archived", "all"):
        raise HTTPException(422, "Filtro de categorias inválido")
    stmt = select(Category).order_by(Category.name)
    if scope != "all":
        stmt = stmt.where(Category.is_active.is_(scope == "active"))
    return [category_payload(session, c) for c in session.scalars(stmt)]


def category_payload(session: Session, category: Category) -> dict:
    active = active_budget(session, category.id, date.today()) if category.kind == "expense" else None
    rule = active[3] if active else None
    future = session.scalar(select(BudgetRule).where(BudgetRule.category_id == category.id, BudgetRule.effective_start > date.today()).order_by(BudgetRule.effective_start).limit(1)) if category.kind == "expense" else None
    display = rule or (future if not active else None)
    return {"id": str(category.id), "name": category.name, "kind": category.kind,
            "is_entertainment": category.is_entertainment, "icon": category.icon,
            "color": category.color, "is_active": category.is_active,
            "archived_on": category.archived_on, "visible_until": category.visible_until,
            "budget_limit": active[0] if active else future.limit_amount if future else None,
            "budget_period_type": display.period_type if display else "calendar_month",
            "budget_interval_count": display.interval_count if display else 1,
            "budget_renewal_day": display.renewal_day if display else None,
            "budget_effective_start": display.effective_start if display else None,
            "budget_scheduled_start": future.effective_start if future else None,
            "budget_period_start": active[1] if active else None,
            "budget_next_renewal": active[2] if active else None}


def apply_category_budget(session: Session, category: Category, data: CategoryCreate) -> None:
    if data.budget_limit is None:
        return
    if category.kind != "expense":
        raise HTTPException(422, "Limite só pode ser definido para categoria de despesa")
    active = active_budget(session, category.id, date.today())
    same = active and active[0] == data.budget_limit and (active[3].period_type if active[3] else "calendar_month") == data.budget_period_type and (active[3].interval_count if active[3] else 1) == data.budget_interval_count and (active[3].renewal_day if active[3] else None) == data.budget_renewal_day
    if not same or data.budget_effective_start is not None:
        set_budget(session, category.id, data.budget_effective_start or date.today(), data.budget_limit,
                   data.budget_period_type, data.budget_interval_count, data.budget_renewal_day)


@router.post("/categories", status_code=201)
def add_category(data: CategoryCreate, session: Session = Depends(get_session)):
    if data.icon and data.icon not in ICON_IDS:
        raise HTTPException(422, "Ícone de categoria inválido")
    if data.is_entertainment and data.kind != "expense":
        raise HTTPException(422, "Entretenimento precisa ser uma categoria de despesa")
    with session.begin():
        if session.scalar(select(Category).where(Category.name == data.name.strip())):
            raise HTTPException(409, "Já existe uma categoria com esse nome")
        category = Category(name=data.name.strip(), kind=data.kind, is_entertainment=data.is_entertainment,
                            icon=data.icon or None, color=data.color.upper() if data.color else suggested_color(session))
        session.add(category)
        session.flush()
        apply_category_budget(session, category, data)
    return category_payload(session, category)


@router.put("/categories/{category_id}")
def edit_category(category_id: UUID, data: CategoryCreate, session: Session = Depends(get_session)):
    if data.icon and data.icon not in ICON_IDS:
        raise HTTPException(422, "Ícone de categoria inválido")
    with session.begin():
        row = session.scalar(select(Category).where(Category.id == category_id).with_for_update())
        if not row or not row.is_active:
            raise HTTPException(404, "Categoria não encontrada")
        if data.is_entertainment and data.kind != "expense":
            raise HTTPException(422, "Entretenimento precisa ser uma categoria de despesa")
        name = data.name.strip()
        other = session.scalar(select(Category).where(Category.name == name, Category.id != category_id))
        if other:
            raise HTTPException(409, "Já existe uma categoria com esse nome")
        if row.kind != data.kind and (session.scalar(select(Transaction.id).where(Transaction.category_id == category_id).limit(1)) or session.scalar(select(Budget.id).where(Budget.category_id == category_id).limit(1)) or active_budget(session, category_id, date.today())):
            raise HTTPException(422, "O tipo de categoria com movimentações ou orçamento não pode ser alterado")
        row.name = name
        row.kind = data.kind
        row.is_entertainment = data.is_entertainment
        if data.icon is not None:
            row.icon = data.icon or None
        if data.color is not None:
            row.color = data.color.upper()
        apply_category_budget(session, row, data)
        result = category_payload(session, row)
    return result


@router.get("/categories/{category_id}/archive-preview")
def get_category_archive_preview(category_id: UUID, session: Session = Depends(get_session)):
    row = session.get(Category, category_id)
    if not row:
        raise HTTPException(404, "Categoria não encontrada")
    return archive_preview(session, row, date.today())


@router.post("/categories/{category_id}/archive")
def archive_category_endpoint(category_id: UUID, session: Session = Depends(get_session)):
    with session.begin():
        result = archive_category(session, category_id, date.today())
    return result


@router.post("/categories/{category_id}/restore")
def restore_category_endpoint(category_id: UUID, session: Session = Depends(get_session)):
    with session.begin():
        row = restore_category(session, category_id)
        result = category_payload(session, row)
    return result


@router.get("/transactions")
def list_transactions(start: date | None = None, end: date | None = None, category_id: UUID | None = None,
                      account_id: UUID | None = None, kind: str | None = None, q: str | None = None,
                      limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
    stmt = select(Transaction).where(Transaction.deleted_at.is_(None)).order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(limit)
    if start: stmt = stmt.where(Transaction.transaction_date >= start)
    if end: stmt = stmt.where(Transaction.transaction_date <= end)
    if category_id: stmt = stmt.where(Transaction.category_id == category_id)
    if account_id: stmt = stmt.where(Transaction.account_id == account_id)
    if kind: stmt = stmt.where(Transaction.kind == kind)
    if q: stmt = stmt.where(Transaction.description.ilike(f"%{q}%"))
    rows = session.scalars(stmt).all()
    return [transaction_payload(row) for row in rows]


@router.get("/transactions/trash")
def transaction_trash(session: Session = Depends(get_session)):
    rows = session.scalars(select(Transaction).where(Transaction.deleted_at.is_not(None)).order_by(Transaction.deleted_at.desc()).limit(500)).all()
    return [transaction_payload(row) for row in rows]


@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: UUID, session: Session = Depends(get_session)):
    row = session.get(Transaction, transaction_id)
    if not row:
        raise HTTPException(404, "Movimentação não encontrada")
    return transaction_payload(row)


@router.get("/transactions/{transaction_id}/deletion-preview")
def deletion_preview(transaction_id: UUID, session: Session = Depends(get_session)):
    row = session.get(Transaction, transaction_id)
    if not row:
        raise HTTPException(404, "Movimentação não encontrada")
    try:
        group, bill, purchase = transaction_deletion_group(session, row)
        effect = "A movimentação sairá dos saldos, orçamentos e relatórios ativos. Ela poderá ser restaurada na lixeira."
        if len(group) == 2:
            effect = "As duas pontas da transferência sairão dos saldos juntas; ela poderá ser restaurada na lixeira."
        elif purchase:
            paid = session.scalar(select(Installment.id).join(Invoice, Installment.invoice_id == Invoice.id)
                .where(Installment.purchase_id == purchase.id, Invoice.paid_date.is_not(None)).limit(1))
            effect = ("A compra e todas as suas parcelas sairão dos totais ativos. O pagamento manual da fatura será ajustado ao novo total, inclusive no saldo da conta de origem. A compra poderá ser restaurada na lixeira."
                      if paid else "A compra e todas as suas parcelas sairão dos totais ativos; a operação poderá ser restaurada na lixeira.")
        elif bill:
            effect = "O pagamento será desfeito e a conta voltará a ficar pendente; a movimentação poderá ser restaurada."
        return {"can_delete": True, "effect": effect, "affected_ids": [str(item.id) for item in group]}
    except HTTPException as error:
        return {"can_delete": False, "effect": str(error.detail), "affected_ids": []}


@router.delete("/transactions/{transaction_id}")
def trash_transaction(transaction_id: UUID, expected_version: int = Query(ge=1), confirmed: bool = False,
                      session: Session = Depends(get_session)):
    if not confirmed:
        raise HTTPException(422, "Confirme a exclusão antes de gravar")
    with session.begin():
        rows = delete_transaction(session, transaction_id, expected_version)
        result = {"deleted_ids": [str(row.id) for row in rows], "deleted_at": rows[0].deleted_at}
    return result


@router.post("/transactions/{transaction_id}/restore")
def restore_trashed_transaction(transaction_id: UUID, session: Session = Depends(get_session)):
    with session.begin():
        rows = restore_transaction(session, transaction_id)
        result = {"restored_ids": [str(row.id) for row in rows]}
    return result


@router.get("/transactions/{transaction_id}/lifecycle")
def transaction_lifecycle(transaction_id: UUID, session: Session = Depends(get_session)):
    rows = session.scalars(select(TransactionLifecycleEvent).where(TransactionLifecycleEvent.transaction_id == transaction_id).order_by(TransactionLifecycleEvent.occurred_at)).all()
    return [{"id": str(row.id), "action": row.action, "occurred_at": row.occurred_at} for row in rows]


@router.post("/transactions", status_code=201)
def add_transaction(data: TransactionCreate, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    try:
        with session.begin():
            row = create_transaction(session, data.model_dump(), key)
        return {"id": str(row.id), "version": row.version, "kind": row.kind, "amount": row.amount, "category_id": str(row.category_id) if row.category_id else None, "account_id": str(row.account_id), "description": row.description, "transaction_date": row.transaction_date, "status": row.status}
    except HTTPException:
        raise


@router.put("/transactions/{transaction_id}")
def correct_transaction(transaction_id: UUID, data: TransactionUpdate, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    if not data.confirmed:
        raise HTTPException(422, "Confirme a correção antes de gravar")
    with session.begin():
        row = update_transaction(session, transaction_id, data.expected_version, data.amount, data.category_id,
                                 data.description, data.transaction_date, data.reason, key)
        result = {"id": str(row.id), "version": row.version, "amount": row.amount, "category_id": str(row.category_id) if row.category_id else None,
                  "description": row.description, "transaction_date": row.transaction_date, "status": row.status}
    return result


@router.post("/transactions/{transaction_id}/settle")
def settle_transaction(transaction_id: UUID, settled_on: date | None = None, session: Session = Depends(get_session)):
    with session.begin():
        row = session.scalar(select(Transaction).where(Transaction.id == transaction_id).with_for_update())
        if not row:
            raise HTTPException(404, "Movimentação não encontrada")
        if row.deleted_at is not None:
            raise HTTPException(409, "Restaure a movimentação antes de marcá-la como realizada")
        if row.kind not in ("income", "expense", "refund"):
            raise HTTPException(422, "Este tipo de movimentação não pode ser liquidado aqui")
        if row.status == "settled":
            return {"id": str(row.id), "status": row.status, "settled_date": row.settled_date}
        row.status = "settled"
        row.settled_date = settled_on or date.today()
        row.competence_date = period_for(row.settled_date)
        row.version += 1
        result = {"id": str(row.id), "status": row.status, "settled_date": row.settled_date}
    return result


@router.get("/transactions/{transaction_id}/revisions")
def transaction_revisions(transaction_id: UUID, session: Session = Depends(get_session)):
    rows = session.scalars(select(TransactionRevision).where(TransactionRevision.transaction_id == transaction_id).order_by(TransactionRevision.version)).all()
    return [{"id": str(row.id), "version": row.version, "reason": row.reason, "before": row.before_state,
             "after": row.after_state, "changed_at": row.changed_at} for row in rows]


@router.post("/transfers", status_code=201)
def add_transfer(data: TransferCreate, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    with session.begin():
        out, inc = create_transfer(session, data.source_account_id, data.destination_account_id, data.amount, data.transaction_date, data.description, key)
    return {"outgoing_id": str(out.id), "incoming_id": str(inc.id), "amount": out.amount, "description": out.description}


@router.get("/overview")
def get_overview(month: date | None = None, session: Session = Depends(get_session)):
    return overview(session, month or date.today())


@router.get("/balances")
def get_balances(session: Session = Depends(get_session)):
    return account_balances(session)


@router.get("/spending")
def get_spending(start: date, end: date, session: Session = Depends(get_session)):
    if start > end: raise HTTPException(422, "Data inicial posterior à data final")
    return spend_by_category(session, start, end)


@router.get("/budgets")
def get_budgets(month: date | None = None, session: Session = Depends(get_session)):
    return budget_status(session, month or date.today())


@router.post("/budgets/preview")
def preview_budget(data: BudgetCyclePreview):
    return preview_budget_cycle(data.effective_start, data.period_type, data.interval_count, data.renewal_day)


@router.get("/entertainment")
def get_entertainment(month: date | None = None, session: Session = Depends(get_session)):
    return entertainment_status(session, month or date.today())


@router.put("/budgets", status_code=201)
def put_budget(data: BudgetCreate, session: Session = Depends(get_session)):
    with session.begin():
        row = set_budget(session, data.category_id, data.effective_start or data.period_start or date.today(), data.limit_amount,
                         data.period_type, data.interval_count, data.renewal_day)
    return {"category_id": str(row.category_id), "effective_start": row.effective_start, "limit": row.limit_amount,
            "period_type": row.period_type, "interval_count": row.interval_count, "renewal_day": row.renewal_day}


@router.get("/bills")
def get_bills(through: date | None = None, session: Session = Depends(get_session)):
    rows = get_upcoming_bills(session, through or date.today().replace(day=monthrange(date.today().year, date.today().month)[1]))
    return [{"id": str(b.id), "description": b.description, "amount": b.amount, "due_date": b.due_date, "category_id": str(b.category_id) if b.category_id else None} for b in rows]


@router.get("/recurring-plans")
def list_recurring_plans(month: date | None = None, session: Session = Depends(get_session)):
    return recurring_status(session, month or date.today())


@router.post("/recurring-plans", status_code=201)
def add_recurring_plan(data: RecurringPlanCreate, session: Session = Depends(get_session)):
    with session.begin():
        row = create_recurring_plan(session, data.model_dump())
        result = {"id": str(row.id), "description": row.description, "kind": row.kind, "amount": row.amount,
                  "start_date": row.start_date}
    return result


@router.post("/recurring-plans/{plan_id}/realize")
def realize_recurring(plan_id: UUID, month: date, realized_on: date | None = None,
                      session: Session = Depends(get_session)):
    with session.begin():
        row = realize_recurring_plan(session, plan_id, month, realized_on or date.today())
        result = {"id": str(row.id), "plan_id": str(row.plan_id), "due_date": row.due_date,
                  "transaction_id": str(row.transaction_id), "realized_at": row.realized_at}
    return result


@router.post("/recurring-plans/{plan_id}/deactivate")
def deactivate_recurring(plan_id: UUID, session: Session = Depends(get_session)):
    with session.begin():
        row = session.scalar(select(RecurringPlan).where(RecurringPlan.id == plan_id).with_for_update())
        if not row:
            raise HTTPException(404, "Plano recorrente não encontrado")
        row.is_active = False
        result = {"id": str(row.id), "is_active": row.is_active}
    return result


@router.post("/bills", status_code=201)
def add_bill(data: BillCreate, session: Session = Depends(get_session)):
    with session.begin():
        if data.category_id:
            category = session.scalar(select(Category).where(Category.id == data.category_id).with_for_update())
            if not category or not category.is_active or category.kind != "expense":
                raise HTTPException(422, "Selecione uma categoria de despesa ativa")
        row = Bill(**data.model_dump())
        session.add(row)
    return {"id": str(row.id), "description": row.description, "amount": row.amount, "due_date": row.due_date}


@router.post("/bills/{bill_id}/pay")
def pay_bill(bill_id: UUID, data: BillPayment, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    with session.begin():
        bill = session.get(Bill, bill_id)
        if not bill: raise HTTPException(404, "Conta a pagar não encontrada")
        scoped_key = f"bill:{bill_id}:{key}" if key else None
        if bill.paid_date:
            tx = session.get(Transaction, bill.payment_transaction_id) if bill.payment_transaction_id else None
            if tx and scoped_key and tx.idempotency_key == scoped_key and tx.account_id == data.source_account_id and bill.paid_date == data.paid_date:
                return {"bill_id": str(bill.id), "transaction_id": str(tx.id), "amount": tx.amount, "paid_date": bill.paid_date}
            raise HTTPException(409, "Conta já está paga")
        if not bill.category_id: raise HTTPException(422, "Defina uma categoria para pagar esta conta")
        tx = create_transaction(session, {"kind": "expense", "amount": bill.amount, "account_id": data.source_account_id, "category_id": bill.category_id, "description": bill.description, "transaction_date": data.paid_date, "status": "settled", "related_transaction_id": bill.id}, scoped_key)
        bill.paid_date = data.paid_date
        bill.payment_transaction_id = tx.id
    return {"bill_id": str(bill.id), "transaction_id": str(tx.id), "amount": tx.amount, "paid_date": bill.paid_date}


@router.get("/cards")
def list_cards(session: Session = Depends(get_session)):
    result = []
    for card in session.scalars(select(CreditCard)):
        account = session.get(Account, card.account_id)
        result.append({"id": str(card.id), "name": account.name, "account_id": str(account.id), "closing_day": card.closing_day, "due_day": card.due_day})
    return result


@router.post("/cards", status_code=201)
def add_card(data: CreditCardCreate, session: Session = Depends(get_session)):
    with session.begin():
        card = create_credit_card(session, data.name, data.closing_day, data.due_day)
        account = session.get(Account, card.account_id)
        result = {"id": str(card.id), "name": account.name, "account_id": str(account.id), "closing_day": card.closing_day, "due_day": card.due_day}
    return result


@router.post("/card-purchases", status_code=201)
def add_credit_purchase(data: CreditPurchaseCreate, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    with session.begin():
        purchase = create_credit_purchase(session, data.card_id, data.category_id, data.total_amount, data.installment_count, data.purchase_date, data.merchant, key)
        installments = session.scalars(select(Installment).where(Installment.purchase_id == purchase.id).order_by(Installment.sequence)).all()
        result = {"id": str(purchase.id), "transaction_id": str(purchase.transaction_id), "total_amount": purchase.total_amount, "installment_count": purchase.installment_count, "installments": [{"id": str(i.id), "sequence": i.sequence, "amount": i.amount, "due_date": i.due_date, "paid_date": i.paid_date} for i in installments]}
    return result


@router.get("/card-purchases")
def list_card_purchases(card_id: UUID | None = None, invoice_id: UUID | None = None,
                        session: Session = Depends(get_session)):
    stmt = select(CreditPurchase).join(Transaction, CreditPurchase.transaction_id == Transaction.id).where(Transaction.deleted_at.is_(None))
    if card_id: stmt = stmt.where(CreditPurchase.card_id == card_id)
    if invoice_id: stmt = stmt.join(Installment, Installment.purchase_id == CreditPurchase.id).where(Installment.invoice_id == invoice_id)
    rows = session.scalars(stmt.order_by(CreditPurchase.purchase_date.desc())).all()
    return [card_purchase_payload(session, row) for row in rows]


@router.get("/card-purchases/{purchase_id}")
def get_card_purchase(purchase_id: UUID, session: Session = Depends(get_session)):
    row = session.get(CreditPurchase, purchase_id)
    if not row: raise HTTPException(404, "Compra no cartão não encontrada")
    return card_purchase_payload(session, row)


@router.patch("/card-purchases/{purchase_id}")
def edit_card_purchase(purchase_id: UUID, data: CreditPurchaseUpdate, session: Session = Depends(get_session)):
    changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    with session.begin():
        row = update_card_purchase(session, purchase_id, data.expected_version, changes)
        result = card_purchase_payload(session, row)
        result["affected_invoices"] = [item["invoice_id"] for item in result["installments"]]
        current = {item["id"]: item for item in invoice_status(session)}
        result["invoice_totals_after"] = [current.get(identifier, {"id": identifier, "total": Decimal("0"), "open_amount": Decimal("0")}) for identifier in sorted(set(result["affected_invoices"]))]
    return result


@router.delete("/card-purchases/{purchase_id}")
def remove_card_purchase(purchase_id: UUID, expected_version: int = Query(ge=1), confirmed: bool = False,
                         session: Session = Depends(get_session)):
    if not confirmed: raise HTTPException(422, "Confirme a exclusão antes de gravar")
    with session.begin():
        purchase = session.get(CreditPurchase, purchase_id)
        if not purchase: raise HTTPException(404, "Compra no cartão não encontrada")
        tx = session.get(Transaction, purchase.transaction_id)
        if tx.deleted_at is not None: raise HTTPException(409, "Compra já está na lixeira")
        before = card_purchase_payload(session, purchase)
        delete_transaction(session, tx.id, expected_version)
        result = {**before, "deleted_at": tx.deleted_at,
                  "affected_invoices": [item["invoice_id"] for item in before["installments"]]}
        current = {item["id"]: item for item in invoice_status(session)}
        result["invoice_totals_after"] = [current.get(identifier, {"id": identifier, "total": Decimal("0"), "open_amount": Decimal("0")}) for identifier in sorted(set(result["affected_invoices"]))]
    return result


@router.post("/card-purchases/{purchase_id}/restore")
def restore_card_purchase(purchase_id: UUID, session: Session = Depends(get_session)):
    with session.begin():
        purchase = session.get(CreditPurchase, purchase_id)
        if not purchase: raise HTTPException(404, "Compra no cartão não encontrada")
        restore_transaction(session, purchase.transaction_id)
        result = card_purchase_payload(session, purchase)
    return result


@router.get("/invoices")
def get_invoices(through: date | None = None, session: Session = Depends(get_session)):
    return invoice_status(session, through)


@router.post("/invoices/{invoice_id}/pay")
def settle_invoice(invoice_id: UUID, data: InvoicePayment, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    with session.begin():
        result = pay_invoice(session, invoice_id, data.source_account_id, data.paid_date, key)
    return result


@router.get("/investments")
def get_investments(session: Session = Depends(get_session)):
    rows = session.scalars(select(Investment).order_by(Investment.name)).all()
    return [investment_summary(session, row) for row in rows]


@router.post("/investments", status_code=201)
def add_investment(data: InvestmentCreate, session: Session = Depends(get_session)):
    if not data.current_value.is_finite() or data.current_value < 0 or data.current_value != data.current_value.quantize(Decimal("0.01")):
        raise HTTPException(422, "Valor atual inválido")
    if data.current_value > 0 and not data.valuation_date:
        raise HTTPException(422, "Informe a data da avaliação inicial")
    if data.quantity is not None and (not data.quantity.is_finite() or data.quantity <= 0 or data.quantity != data.quantity.quantize(Decimal("0.00000001"))):
        raise HTTPException(422, "Quantidade do investimento inválida")
    if data.opening_contribution is not None and (not data.opening_contribution.is_finite() or data.opening_contribution < 0 or data.opening_contribution != data.opening_contribution.quantize(Decimal("0.01"))):
        raise HTTPException(422, "Capital inicial aportado inválido")
    with session.begin():
        row = Investment(**data.model_dump())
        session.add(row); session.flush()
        if data.valuation_date:
            record_investment_valuation(session, row.id, data.current_value, data.valuation_date)
    return {"id": str(row.id), "name": row.name, "kind": row.kind, "current_value": row.current_value}


@router.post("/investments/{investment_id}/valuations", status_code=201)
def add_investment_valuation(investment_id: UUID, data: InvestmentValuationCreate, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    with session.begin():
        row = record_investment_valuation(session, investment_id, data.value, data.valuation_date, key)
        result = {"id": str(row.id), "investment_id": str(row.investment_id), "value": row.value, "valuation_date": row.valuation_date}
    return result


@router.get("/investments/{investment_id}/valuations")
def investment_valuations(investment_id: UUID, session: Session = Depends(get_session)):
    rows = session.scalars(select(InvestmentValuation).where(InvestmentValuation.investment_id == investment_id).order_by(InvestmentValuation.valuation_date, InvestmentValuation.recorded_at)).all()
    return [{"id": str(row.id), "value": row.value, "valuation_date": row.valuation_date, "recorded_at": row.recorded_at} for row in rows]


@router.post("/investment-events", status_code=201)
def add_investment_event(data: InvestmentEventCreate, session: Session = Depends(get_session), key: str | None = Depends(key_header)):
    with session.begin():
        event = create_investment_event(session, data.investment_id, data.account_id, data.kind, data.amount, data.event_date, key)
    return {"id": str(event.id), "investment_id": str(event.investment_id), "kind": event.kind, "amount": event.amount}


@router.get("/net-worth")
def get_net_worth(session: Session = Depends(get_session)):
    return net_worth(session)


@router.post("/net-worth/snapshots", status_code=201)
def save_net_worth_snapshot(session: Session = Depends(get_session)):
    with session.begin():
        row = record_net_worth_snapshot(session)
        result = {"id": str(row.id), "as_of_date": row.as_of_date, "cash": row.cash, "investments": row.investments,
                  "liabilities": row.liabilities, "net_worth": row.net_worth}
    return result


@router.get("/net-worth/history")
def net_worth_history(session: Session = Depends(get_session)):
    rows = session.scalars(select(NetWorthSnapshot).order_by(NetWorthSnapshot.as_of_date)).all()
    return [{"id": str(row.id), "as_of_date": row.as_of_date, "cash": row.cash, "investments": row.investments,
             "liabilities": row.liabilities, "net_worth": row.net_worth} for row in rows]


@router.get("/goals")
def get_goals(session: Session = Depends(get_session)):
    return goals(session)


def validate_goal_amounts(data: GoalCreate) -> None:
    for value in (data.target_amount, data.allocated_amount):
        if not value.is_finite() or value != value.quantize(Decimal("0.01")):
            raise HTTPException(422, "Valores da meta inválidos")
    if data.target_amount <= 0 or data.allocated_amount < 0 or data.allocated_amount > data.target_amount:
        raise HTTPException(422, "Valores da meta inválidos")


@router.post("/goals", status_code=201)
def add_goal(data: GoalCreate, session: Session = Depends(get_session)):
    validate_goal_amounts(data)
    if not data.name.strip():
        raise HTTPException(422, "Informe o nome da meta")
    if session.scalar(select(Goal.id).where(Goal.name == data.name.strip())):
        raise HTTPException(409, "Já existe uma meta com esse nome")
    validate_goal_tracking(session, data)
    if data.allocated_amount > 0:
        validate_reserve_increase(session, data.allocated_amount)
    row = Goal(name=data.name.strip(), target_amount=data.target_amount,
               allocated_amount=data.allocated_amount, target_date=data.target_date,
               tracking_mode=data.tracking_mode)
    session.add(row); session.flush()
    if data.tracking_mode == "selected":
        session.add_all(GoalTrackingAccount(goal_id=row.id, account_id=aid) for aid in set(data.account_ids))
    if row.allocated_amount > 0:
        session.add(GoalAllocation(goal_id=row.id, amount_delta=row.allocated_amount,
                                   allocated_on=date.today(), note="Reserva inicial"))
    session.commit()
    return {"id": str(row.id), "name": row.name}


@router.put("/goals/{goal_id}")
def edit_goal(goal_id: UUID, data: GoalCreate, session: Session = Depends(get_session)):
    with session.begin():
        row = session.scalar(select(Goal).where(Goal.id == goal_id).with_for_update())
        if not row:
            raise HTTPException(404, "Meta não encontrada")
        validate_goal_amounts(data)
        if not data.name.strip():
            raise HTTPException(422, "Informe o nome da meta")
        if session.scalar(select(Goal.id).where(Goal.name == data.name.strip(), Goal.id != goal_id)):
            raise HTTPException(409, "Já existe uma meta com esse nome")
        validate_goal_tracking(session, data)
        if data.allocated_amount > row.allocated_amount:
            validate_reserve_increase(session, data.allocated_amount - row.allocated_amount)
        row.name = data.name.strip()
        row.target_amount = data.target_amount
        difference = data.allocated_amount - row.allocated_amount
        row.allocated_amount = data.allocated_amount
        row.target_date = data.target_date
        row.tracking_mode = data.tracking_mode
        session.query(GoalTrackingAccount).filter(GoalTrackingAccount.goal_id == row.id).delete(synchronize_session=False)
        if data.tracking_mode == "selected":
            session.add_all(GoalTrackingAccount(goal_id=row.id, account_id=aid) for aid in set(data.account_ids))
        if difference:
            session.add(GoalAllocation(goal_id=row.id, amount_delta=difference,
                                       allocated_on=date.today(), note="Atualização da reserva"))
        result = {"id": str(row.id), "name": row.name, "allocated_amount": row.allocated_amount}
    return result


def validate_goal_tracking(session: Session, data: GoalCreate) -> None:
    if data.tracking_mode != "selected" and data.account_ids:
        raise HTTPException(422, "Selecione contas apenas no modo de acompanhamento específico")
    if data.tracking_mode == "selected" and not data.account_ids:
        raise HTTPException(422, "Selecione ao menos uma conta")
    for aid in set(data.account_ids):
        account = session.get(Account, aid)
        if not account or not account.is_active or account.kind == "credit_card":
            raise HTTPException(422, "Conta de acompanhamento inválida")


def validate_reserve_increase(session: Session, increase: Decimal) -> None:
    cash = sum((row["balance"] for row in account_balances(session) if row["kind"] != "credit_card"), Decimal("0"))
    reserved = session.scalar(select(func.coalesce(func.sum(Goal.allocated_amount), 0))) or Decimal("0")
    if Decimal(reserved) + increase > cash:
        raise HTTPException(422, "Não há saldo para aumentar a reserva; a meta pode existir sem reserva")


@router.get("/goals/{goal_id}/contributions")
def goal_contributions(goal_id: UUID, session: Session = Depends(get_session)):
    if not session.get(Goal, goal_id):
        raise HTTPException(404, "Meta não encontrada")
    rows = session.scalars(select(GoalContribution).where(GoalContribution.goal_id == goal_id).order_by(GoalContribution.contributed_on, GoalContribution.created_at)).all()
    return [{"id": str(row.id), "amount_delta": row.amount_delta, "contributed_on": row.contributed_on, "note": row.note} for row in rows]


@router.post("/goals/{goal_id}/contributions", status_code=201)
def add_goal_contribution(goal_id: UUID, data: GoalContributionCreate, session: Session = Depends(get_session)):
    with session.begin():
        goal = session.scalar(select(Goal).where(Goal.id == goal_id).with_for_update())
        if not goal:
            raise HTTPException(404, "Meta não encontrada")
        if not data.amount_delta.is_finite() or data.amount_delta == 0 or data.amount_delta != data.amount_delta.quantize(Decimal("0.01")):
            raise HTTPException(422, "Contribuição inválida")
        if not data.note.strip():
            raise HTTPException(422, "Informe a nota da contribuição")
        contributed = session.scalar(select(func.coalesce(func.sum(GoalContribution.amount_delta), 0)).where(GoalContribution.goal_id == goal_id)) or Decimal("0")
        if Decimal(contributed) + data.amount_delta < 0:
            raise HTTPException(422, "A contribuição acumulada não pode ser negativa")
        entry = GoalContribution(goal_id=goal_id, amount_delta=data.amount_delta,
                                 contributed_on=data.contributed_on, note=data.note.strip())
        session.add(entry); session.flush()
        result = {"id": str(entry.id), "goal_id": str(goal_id), "amount_delta": entry.amount_delta,
                  "contributed_on": entry.contributed_on}
    return result


@router.get("/goals/{goal_id}/allocations")
def goal_allocations(goal_id: UUID, session: Session = Depends(get_session)):
    if not session.get(Goal, goal_id):
        raise HTTPException(404, "Meta não encontrada")
    rows = session.scalars(select(GoalAllocation).where(GoalAllocation.goal_id == goal_id).order_by(GoalAllocation.allocated_on, GoalAllocation.created_at)).all()
    return [{"id": str(row.id), "amount_delta": row.amount_delta, "allocated_on": row.allocated_on,
             "note": row.note} for row in rows]


@router.get("/monthly-comparison")
def monthly_comparison(months: int = Query(6, ge=2, le=24), session: Session = Depends(get_session)):
    return calculate_monthly_comparison(session, months)


@router.get("/calendar")
def get_calendar(start: date, end: date, session: Session = Depends(get_session)):
    return calendar_days(session, start, end)


@router.get("/export.csv")
def export_csv(session: Session = Depends(get_session)):
    import csv
    import io
    from fastapi.responses import StreamingResponse
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "tipo", "valor", "conta", "categoria", "descrição", "data prevista", "competência", "data realizada", "situação"])
    for row in session.scalars(select(Transaction).where(Transaction.deleted_at.is_(None)).order_by(Transaction.transaction_date)):
        writer.writerow([row.id, row.kind, row.amount, row.account_id, row.category_id or "", row.description, row.transaction_date, row.competence_date, row.settled_date or "", row.status])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=meu-financeiro.csv"})
