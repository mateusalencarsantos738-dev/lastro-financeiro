"""Testes contra banco PostgreSQL dedicado; nunca usa o banco pessoal."""

import os
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg:///meu_financeiro_test")

from backend.app.domain import (
    account_balances, budget_status, create_investment_event, create_transaction,
    create_transfer, create_credit_card, create_credit_purchase, invoice_status,
    pay_invoice, net_worth, overview,
    update_transaction, record_investment_valuation, record_net_worth_snapshot,
    create_recurring_plan, recurring_status, realize_recurring_plan,
    delete_transaction, restore_transaction, update_card_purchase, goals, calendar_days,
)
from backend.app.models import Account, Bill, Budget, Category, Goal, GoalTrackingAccount, Investment, Transaction, TransactionRevision, InvestmentValuation
from backend.app.api import add_goal, edit_goal, add_goal_contribution
from backend.app.schemas import GoalCreate, GoalContributionCreate

TEST_DAY = date(2020, 1, 15)


@pytest.fixture
def session():
    url = os.environ["DATABASE_URL"]
    if make_url(url).database != "meu_financeiro_test":
        pytest.fail("Testes exigem banco meu_financeiro_test; banco pessoal recusado")
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
    engine.dispose()


@pytest.fixture
def setup(session):
    a = Account(id=uuid4(), name=f"Conta sintética A {uuid4()}", kind="checking", opening_balance=Decimal("1000"))
    b = Account(id=uuid4(), name=f"Conta sintética B {uuid4()}", kind="cash", opening_balance=Decimal("0"))
    c = Category(id=uuid4(), name=f"Entretenimento sintético {uuid4()}", kind="expense", is_entertainment=True)
    session.add_all([a, b, c]); session.flush()
    return a, b, c


def test_transfer_preserves_net_worth_and_consumption(session, setup):
    a, b, _ = setup
    before_details = net_worth(session)
    before = before_details["net_worth"]
    out, inc = create_transfer(session, a.id, b.id, Decimal("300"), TEST_DAY, "Transferência sintética", "test-transfer-1")
    session.flush()
    assert out.related_id == inc.id and inc.related_id == out.id
    balances = {x["account_id"]: x["balance"] for x in account_balances(session)}
    assert balances[str(a.id)] == Decimal("700")
    assert balances[str(b.id)] == Decimal("300")
    assert net_worth(session)["net_worth"] == before
    summary = overview(session, TEST_DAY)
    assert summary["income"] == summary["expenses"] == Decimal("0")


def test_expense_refund_budget_and_idempotency(session, setup):
    a, _, c = setup
    session.add(Budget(category_id=c.id, period_start=TEST_DAY.replace(day=1), limit_amount=Decimal("250")))
    data = {"kind": "expense", "amount": "180.00", "account_id": str(a.id), "category_id": str(c.id), "description": "Cinema sintético", "transaction_date": TEST_DAY.isoformat(), "status": "settled"}
    tx = create_transaction(session, data, "test-expense-1")
    session.flush()
    again = create_transaction(session, data, "test-expense-1")
    assert again.id == tx.id
    assert session.scalar(select(Transaction).where(Transaction.idempotency_key == "test-expense-1")).id == tx.id
    refund = create_transaction(session, {"kind": "refund", "amount": "30.00", "account_id": str(a.id), "description": "Estorno sintético", "transaction_date": TEST_DAY.isoformat(), "related_transaction_id": str(tx.id)}, "test-refund-1")
    session.flush()
    assert refund.related_id == tx.id
    status = next(row for row in budget_status(session, TEST_DAY) if row["category_id"] == str(c.id))
    assert status["spent"] == Decimal("150")
    assert status["remaining"] == Decimal("100")
    assert overview(session, TEST_DAY)["income"] == Decimal("0")
    with pytest.raises(HTTPException) as over_refund:
        create_transaction(session, {"kind": "refund", "amount": "151.00", "account_id": str(a.id),
            "description": "Estorno acima da compra", "transaction_date": TEST_DAY.isoformat(),
            "related_transaction_id": str(tx.id)})
    assert over_refund.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        create_transaction(session, {**data, "amount": "181.00"}, "test-expense-1")
    assert error.value.status_code == 409


def test_investment_contribution_moves_cash_without_consumption(session, setup):
    a, _, _ = setup
    asset = Investment(id=uuid4(), name=f"Renda fixa sintética {uuid4()}", kind="renda_fixa", current_value=Decimal("0"))
    session.add(asset); session.flush()
    before_details = net_worth(session)
    before = before_details["net_worth"]
    event = create_investment_event(session, asset.id, a.id, "contribution", Decimal("350"), TEST_DAY, "test-investment-1")
    session.flush()
    assert event.amount == Decimal("350")
    assert next(row for row in account_balances(session) if row["account_id"] == str(a.id))["balance"] == Decimal("650")
    assert net_worth(session)["investments"] == before_details["investments"] + Decimal("350")
    assert net_worth(session)["net_worth"] == before
    assert overview(session, TEST_DAY)["expenses"] == Decimal("0")
    again = create_investment_event(session, asset.id, a.id, "contribution", Decimal("350"), TEST_DAY, "test-investment-1")
    assert again.id == event.id


def test_invalid_amount_rejected(session, setup):
    a, _, c = setup
    with pytest.raises(HTTPException) as error:
        create_transaction(session, {"kind": "expense", "amount": "-1", "account_id": str(a.id), "category_id": str(c.id), "description": "Inválido", "transaction_date": TEST_DAY.isoformat()})
    assert error.value.status_code == 422


def test_goal_without_reserve_allows_zero_and_negative_cash(session):
    empty = GoalCreate(name=f"Meta zerada {uuid4()}", target_amount=Decimal("3000"))
    created = add_goal(empty, session)
    state = next(g for g in goals(session) if g["id"] == created["id"])
    assert state["contributed_amount"] == state["allocated_amount"] == Decimal("0")
    assert state["remaining"] == Decimal("3000")
    account = Account(name=f"Conta negativa {uuid4()}", kind="checking", opening_balance=Decimal("-150"))
    session.add(account); session.flush()
    account_id = account.id
    second = add_goal(GoalCreate(name=f"Reserva futura {uuid4()}", target_amount=Decimal("5000"), tracking_mode="selected", account_ids=[account_id]), session)
    state = next(g for g in goals(session) if g["id"] == second["id"])
    assert state["tracked_balance"] == state["available_estimate"] == Decimal("-150")
    assert state["contributed_amount"] == Decimal("0")
    session.commit()
    edit_goal(UUID(second["id"]), GoalCreate(name=state["name"], target_amount=Decimal("6000"), tracking_mode="all"), session)
    all_state = next(g for g in goals(session) if g["id"] == second["id"])
    assert str(account_id) in all_state["tracked_account_ids"]
    assert all_state["tracked_balance"] == sum((b["balance"] for b in account_balances(session) if b["kind"] != "credit_card"), Decimal("0"))
    session.commit()
    edit_goal(UUID(second["id"]), GoalCreate(name=state["name"], target_amount=Decimal("6000"), tracking_mode="selected", account_ids=[account_id]), session)
    assert next(g for g in goals(session) if g["id"] == second["id"])["tracking_mode"] == "selected"
    assert session.scalar(select(GoalTrackingAccount).where(GoalTrackingAccount.goal_id == UUID(second["id"]))).account_id == account_id


def test_goal_contribution_does_not_change_account_balance(session, setup):
    account, _, _ = setup
    created = add_goal(GoalCreate(name=f"Contribuições {uuid4()}", target_amount=Decimal("500"), tracking_mode="selected", account_ids=[account.id]), session)
    before = next(b for b in account_balances(session) if b["account_id"] == str(account.id))["balance"]
    session.commit()
    add_goal_contribution(UUID(created["id"]), GoalContributionCreate(amount_delta=Decimal("125"), contributed_on=TEST_DAY, note="Valor destinado"), session)
    state = next(g for g in goals(session) if g["id"] == created["id"])
    assert state["contributed_amount"] == Decimal("125")
    assert state["allocated_amount"] == Decimal("0")
    assert state["remaining"] == Decimal("375")
    assert next(b for b in account_balances(session) if b["account_id"] == str(account.id))["balance"] == before


def test_calendar_uses_realized_entries_and_recalculates_after_trash(session, setup):
    account, _, category = setup
    leap = date(2032, 2, 29)
    expense = create_transaction(session, {"kind":"expense", "amount":"80.00", "account_id":str(account.id),
        "category_id":str(category.id), "description":"Despesa em dia bissexto", "transaction_date":leap.isoformat()}, f"calendar-expense-{uuid4()}")
    income = create_transaction(session, {"kind":"income", "amount":"50.00", "account_id":str(account.id),
        "description":"Receita em dia bissexto", "transaction_date":leap.isoformat()}, f"calendar-income-{uuid4()}")
    pending = create_transaction(session, {"kind":"income", "amount":"500.00", "account_id":str(account.id),
        "description":"Receita apenas prevista", "transaction_date":leap.isoformat(), "status":"pending"}, f"calendar-pending-{uuid4()}")
    plan = create_recurring_plan(session, {"kind":"expense", "amount":"20.00", "account_id":account.id,
        "category_id":category.id, "description":"Plano futuro sintético", "start_date":leap})
    session.add(Bill(description="Conta futura sintética", amount=Decimal("35"), due_date=leap, category_id=category.id))
    session.flush()
    day = next(row for row in calendar_days(session, leap, leap) if row["date"] == leap)
    assert day["income"] == Decimal("50") and day["expenses"] == Decimal("80") and day["result"] == Decimal("-30")
    assert len(day["transactions"]) == 3
    assert day["recurring"][0]["id"] == str(plan.id)
    assert day["bills"][0]["amount"] == Decimal("35") and day["bills"][0]["paid"] is False
    delete_transaction(session, expense.id, expense.version)
    day = next(row for row in calendar_days(session, leap, leap) if row["date"] == leap)
    assert day["result"] == Decimal("50") and len(day["transactions"]) == 2
    restore_transaction(session, expense.id)
    assert next(row for row in calendar_days(session, leap, leap) if row["date"] == leap)["result"] == Decimal("-30")
    assert calendar_days(session, date(2032, 3, 1), date(2032, 3, 1)) == []
    assert income.id != pending.id


def test_credit_purchase_installments_and_invoice_payment(session, setup):
    a, _, c = setup
    before = net_worth(session)["net_worth"]
    card = create_credit_card(session, f"Cartão sintético {uuid4()}", closing_day=10, due_day=17)
    purchase = create_credit_purchase(session, card.id, c.id, Decimal("600"), 3, date(2020, 1, 5), "Compra sintética", "test-credit-purchase-1")
    session.flush()
    again = create_credit_purchase(session, card.id, c.id, Decimal("600"), 3, date(2020, 1, 5), "Compra sintética", "test-credit-purchase-1")
    assert again.id == purchase.id
    invoices = [row for row in invoice_status(session) if row["card_id"] == str(card.id)]
    assert [row["due_date"] for row in invoices] == [date(2020, 1, 17), date(2020, 2, 17), date(2020, 3, 17)]
    assert [row["total"] for row in invoices] == [Decimal("200.00")] * 3
    summary = overview(session, TEST_DAY)
    assert summary["expenses"] == Decimal("600")
    assert summary["cash_total"] >= Decimal("1000")
    assert net_worth(session)["net_worth"] == before - Decimal("600")
    result = pay_invoice(session, UUID(invoices[0]["id"]), a.id, TEST_DAY, "test-invoice-payment-1")
    session.flush()
    assert result["amount"] == Decimal("200")
    assert pay_invoice(session, UUID(invoices[0]["id"]), a.id, TEST_DAY, "test-invoice-payment-1")["transfer_id"] == result["transfer_id"]
    assert overview(session, TEST_DAY)["expenses"] == Decimal("600")
    assert net_worth(session)["net_worth"] == before - Decimal("600")


def test_correction_keeps_audit_and_prevents_stale_write(session, setup):
    a, _, c = setup
    tx = create_transaction(session, {"kind": "expense", "amount": "40.00", "account_id": str(a.id),
                                      "category_id": str(c.id), "description": "Descrição anterior",
                                      "transaction_date": TEST_DAY.isoformat()}, "test-correct-create")
    session.flush()
    corrected = update_transaction(session, tx.id, 1, Decimal("42.50"), c.id, "Descrição corrigida",
                                   TEST_DAY, "Valor digitado incorretamente", "test-correction-1")
    assert corrected.version == 2 and corrected.amount == Decimal("42.50")
    assert overview(session, TEST_DAY)["expenses"] == Decimal("42.50")
    revision = session.scalar(select(TransactionRevision).where(TransactionRevision.transaction_id == tx.id))
    assert revision.before_state["amount"] == "40.00"
    assert revision.after_state["amount"] == "42.50"
    assert update_transaction(session, tx.id, 1, Decimal("42.50"), c.id, "Descrição corrigida",
                              TEST_DAY, "Valor digitado incorretamente", "test-correction-1").id == tx.id
    with pytest.raises(HTTPException) as error:
        update_transaction(session, tx.id, 1, Decimal("50"), c.id, "Nova", TEST_DAY, "Outro", "test-correction-2")
    assert error.value.status_code == 409


def test_valuation_and_snapshot_are_dated(session, setup):
    a, _, _ = setup
    asset = Investment(id=uuid4(), name=f"Ativo sintético {uuid4()}", kind="renda_fixa", current_value=Decimal("0"))
    session.add(asset); session.flush()
    valuation = record_investment_valuation(session, asset.id, Decimal("250.00"), TEST_DAY, "test-valuation-1")
    session.flush()
    assert asset.current_value == Decimal("250.00")
    assert asset.valuation_date == TEST_DAY
    assert record_investment_valuation(session, asset.id, Decimal("250.00"), TEST_DAY, "test-valuation-1").id == valuation.id
    assert session.scalar(select(InvestmentValuation).where(InvestmentValuation.investment_id == asset.id)).value == Decimal("250.00")
    snapshot = record_net_worth_snapshot(session)
    assert snapshot.net_worth == net_worth(session)["net_worth"]
    assert snapshot.cash >= a.opening_balance
    assert record_net_worth_snapshot(session).id == snapshot.id


def test_monthly_recurring_income_is_only_counted_after_realization(session, setup):
    a, _, _ = setup
    plan = create_recurring_plan(session, {"kind": "income", "amount": Decimal("100.00"),
        "account_id": a.id, "category_id": None, "description": "Receita recorrente sintética",
        "start_date": date(2020, 1, 31)})
    assert overview(session, date(2020, 2, 1))["income"] == Decimal("0")
    february = recurring_status(session, date(2020, 2, 1))
    item = next(row for row in february if row["id"] == str(plan.id))
    assert item["due_date"] == date(2020, 2, 29) and not item["realized"]
    realized = realize_recurring_plan(session, plan.id, date(2020, 2, 1), date(2020, 2, 28))
    again = realize_recurring_plan(session, plan.id, date(2020, 2, 1), date(2020, 2, 28))
    assert realized.id == again.id
    assert overview(session, date(2020, 2, 1))["income"] == Decimal("100.00")
    assert next(row for row in recurring_status(session, date(2020, 2, 1)) if row["id"] == str(plan.id))["realized"]
    assert not next(row for row in recurring_status(session, date(2020, 3, 1)) if row["id"] == str(plan.id))["realized"]


def test_trash_expense_income_budget_and_restore_without_duplication(session, setup):
    a, _, c = setup
    session.add(Budget(category_id=c.id, period_start=TEST_DAY.replace(day=1), limit_amount=Decimal("250")))
    expense = create_transaction(session, {"kind": "expense", "amount": "45.00", "account_id": a.id,
        "category_id": c.id, "description": "Gasto sintético", "transaction_date": TEST_DAY})
    income = create_transaction(session, {"kind": "income", "amount": "100.00", "account_id": a.id,
        "description": "Receita sintética", "transaction_date": TEST_DAY})
    session.flush()
    assert overview(session, TEST_DAY)["expenses"] == Decimal("45")
    assert overview(session, TEST_DAY)["income"] == Decimal("100")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("1055")
    assert [row.id for row in delete_transaction(session, expense.id, expense.version)] == [expense.id]
    assert overview(session, TEST_DAY)["expenses"] == Decimal("0")
    assert budget_status(session, TEST_DAY)[0]["remaining"] == Decimal("250")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("1100")
    delete_transaction(session, income.id, income.version)
    assert overview(session, TEST_DAY)["income"] == Decimal("0")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("1000")
    restore_transaction(session, expense.id)
    restore_transaction(session, expense.id)
    restore_transaction(session, income.id)
    assert overview(session, TEST_DAY)["expenses"] == Decimal("45")
    assert overview(session, TEST_DAY)["income"] == Decimal("100")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("1055")


def test_trash_transfer_moves_both_legs_and_restores_together(session, setup):
    a, b, _ = setup
    out, inc = create_transfer(session, a.id, b.id, Decimal("300"), TEST_DAY, "Transferência sintética")
    session.flush()
    before = net_worth(session)["net_worth"]
    rows = delete_transaction(session, inc.id, inc.version)
    assert {row.id for row in rows} == {out.id, inc.id}
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("1000")
    assert next(item for item in account_balances(session) if item["account_id"] == str(b.id))["balance"] == Decimal("0")
    assert net_worth(session)["net_worth"] == before
    restored = restore_transaction(session, out.id)
    assert {row.id for row in restored} == {out.id, inc.id}
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("700")


def test_card_purchase_trash_before_and_after_payment(session, setup):
    a, _, c = setup
    card = create_credit_card(session, f"Cartão descarte {uuid4()}", 10, 17)
    purchase = create_credit_purchase(session, card.id, c.id, Decimal("120"), 2, TEST_DAY, "Compra sintética")
    session.flush()
    row = session.get(Transaction, purchase.transaction_id)
    assert overview(session, TEST_DAY)["open_installments"] == Decimal("120")
    delete_transaction(session, row.id, row.version)
    assert overview(session, TEST_DAY)["open_installments"] == Decimal("0")
    assert overview(session, TEST_DAY)["expenses"] == Decimal("0")
    assert not [item for item in invoice_status(session) if item["card_id"] == str(card.id)]
    restore_transaction(session, row.id)
    assert overview(session, TEST_DAY)["open_installments"] == Decimal("120")
    invoice = next(item for item in invoice_status(session) if item["card_id"] == str(card.id))
    paid = pay_invoice(session, UUID(invoice["id"]), a.id, TEST_DAY)
    delete_transaction(session, row.id, row.version)
    assert row.deleted_at is not None
    assert overview(session, TEST_DAY)["expenses"] == Decimal("0")
    assert overview(session, TEST_DAY)["open_installments"] == Decimal("0")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("1000")
    restored_group = restore_transaction(session, UUID(paid["transfer_id"]))
    assert row.id in {item.id for item in restored_group}
    assert overview(session, TEST_DAY)["expenses"] == Decimal("120")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("940")
    assert next(item for item in invoice_status(session) if item["id"] == invoice["id"])["paid_date"] is not None


def test_card_purchase_edit_recalculates_paid_invoice_and_keeps_audit(session, setup):
    a, _, c = setup
    other = Category(name=f"Outra categoria {uuid4()}", kind="expense")
    session.add(other); session.flush()
    card = create_credit_card(session, f"Cartão edição {uuid4()}", 10, 17)
    purchase = create_credit_purchase(session, card.id, c.id, Decimal("120"), 2, TEST_DAY, "Valor incorreto")
    session.flush()
    invoice = next(item for item in invoice_status(session) if item["card_id"] == str(card.id))
    pay_invoice(session, UUID(invoice["id"]), a.id, TEST_DAY)
    tx = session.get(Transaction, purchase.transaction_id)
    updated = update_card_purchase(session, purchase.id, tx.version,
        {"total_amount": Decimal("90"), "merchant": "Compra corrigida", "category_id": other.id})
    session.flush()
    assert updated.total_amount == Decimal("90") and tx.description == "Compra corrigida" and tx.category_id == other.id
    assert next(item for item in invoice_status(session) if item["id"] == invoice["id"])["total"] == Decimal("45")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == Decimal("955")
    assert overview(session, TEST_DAY)["expenses"] == Decimal("90")
    assert overview(session, TEST_DAY)["open_installments"] == Decimal("45")
    assert session.scalar(select(TransactionRevision).where(TransactionRevision.transaction_id == tx.id)) is not None
    with pytest.raises(HTTPException) as stale:
        update_card_purchase(session, purchase.id, 1, {"merchant": "Valor obsoleto"})
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as invalid:
        update_card_purchase(session, purchase.id, tx.version, {"installment_count": 3})
    assert invalid.value.status_code == 409
    assert purchase.installment_count == 2 and tx.amount == Decimal("90")


def test_card_purchase_unpaid_schedule_can_change_and_rollback(session, setup, monkeypatch):
    a, _, c = setup
    card = create_credit_card(session, f"Cartão parcelas {uuid4()}", 10, 17)
    purchase = create_credit_purchase(session, card.id, c.id, Decimal("90"), 3, TEST_DAY, "Parcelada")
    session.flush()
    tx = session.get(Transaction, purchase.transaction_id)
    update_card_purchase(session, purchase.id, tx.version, {"installment_count": 2, "total_amount": Decimal("91")})
    session.flush()
    assert [row["total"] for row in invoice_status(session) if row["card_id"] == str(card.id)] == [Decimal("45.50"), Decimal("45.50")]
    other_card = create_credit_card(session, f"Cartão de destino {uuid4()}", 10, 17)
    update_card_purchase(session, purchase.id, tx.version,
        {"card_id": other_card.id, "purchase_date": date(2020, 2, 15)})
    session.flush()
    assert purchase.card_id == other_card.id
    assert not any(item["card_id"] == str(card.id) for item in invoice_status(session))
    assert overview(session, TEST_DAY)["expenses"] == Decimal("0")
    assert overview(session, date(2020, 2, 15))["expenses"] == Decimal("91")
    original_balance = next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"]
    original_version = tx.version
    def fail_flush(*args, **kwargs): raise RuntimeError("Falha simulada")
    with pytest.raises(RuntimeError):
        with session.begin_nested():
            with monkeypatch.context() as patcher:
                patcher.setattr(session, "flush", fail_flush)
                update_card_purchase(session, purchase.id, original_version, {"total_amount": Decimal("99")})
    session.expire_all()
    assert session.get(Transaction, tx.id).amount == Decimal("91")
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == original_balance


def test_trash_rolls_back_when_database_write_fails(session, setup, monkeypatch):
    a, _, c = setup
    row = create_transaction(session, {"kind": "expense", "amount": "30.00", "account_id": a.id,
        "category_id": c.id, "description": "Falha sintética", "transaction_date": TEST_DAY})
    session.flush()
    original_balance = next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"]
    def fail_flush(*args, **kwargs):
        raise RuntimeError("Falha simulada de escrita")
    with pytest.raises(RuntimeError):
        with session.begin_nested():
            with monkeypatch.context() as patcher:
                patcher.setattr(session, "flush", fail_flush)
                delete_transaction(session, row.id, row.version)
    session.expire_all()
    assert session.get(Transaction, row.id).deleted_at is None
    assert next(item for item in account_balances(session) if item["account_id"] == str(a.id))["balance"] == original_balance
