"""Controlled cycle and boundary tests against the isolated PostgreSQL test DB."""
import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.api import router
from backend.app.db import get_session
from backend.app.domain import budget_cycle, budget_status, set_budget, spend_by_category
from backend.app.main import app
from backend.app.models import Account, Budget, BudgetRule, Category, Transaction


@pytest.mark.parametrize("kind,count,day,anchor,query,start,end", [
    ("calendar_month", 1, None, "2026-10-26", "2026-10-26", "2026-10-26", "2026-11-01"),
    ("calendar_month", 1, None, "2026-10-26", "2026-11-10", "2026-11-01", "2026-12-01"),
    ("monthly_day", 1, 5, "2026-10-26", "2026-10-26", "2026-10-26", "2026-11-05"),
    ("monthly_day", 1, 10, "2026-10-26", "2026-11-09", "2026-10-26", "2026-11-10"),
    ("monthly_day", 1, 10, "2026-10-26", "2026-11-10", "2026-11-10", "2026-12-10"),
    ("monthly_day", 1, 31, "2023-01-26", "2023-02-27", "2023-01-31", "2023-02-28"),
    ("monthly_day", 1, 31, "2023-01-26", "2023-02-28", "2023-02-28", "2023-03-31"),
    ("monthly_day", 1, 31, "2024-01-26", "2024-02-28", "2024-01-31", "2024-02-29"),
    ("monthly_day", 1, 31, "2024-01-26", "2024-02-29", "2024-02-29", "2024-03-31"),
    ("days", 7, None, "2026-10-26", "2026-11-01", "2026-10-26", "2026-11-02"),
    ("days", 7, None, "2026-10-26", "2026-11-02", "2026-11-02", "2026-11-09"),
    ("days", 10, None, "2026-12-26", "2027-01-05", "2027-01-05", "2027-01-15"),
    ("days", 13, None, "2026-10-26", "2026-11-08", "2026-11-08", "2026-11-21"),
    ("weeks", 2, None, "2026-10-26", "2026-11-09", "2026-11-09", "2026-11-23"),
    ("months", 2, None, "2026-10-26", "2026-12-26", "2026-12-26", "2027-02-26"),
    ("months", 6, None, "2026-10-26", "2027-04-26", "2027-04-26", "2027-10-26"),
    ("months", 1, None, "2024-01-31", "2024-02-29", "2024-02-29", "2024-03-31"),
    ("months", 1, None, "2023-01-31", "2023-02-28", "2023-02-28", "2023-03-31"),
])
def test_cycle_boundaries(kind, count, day, anchor, query, start, end):
    rule = BudgetRule(effective_start=date.fromisoformat(anchor), period_type=kind,
                      interval_count=count, renewal_day=day, limit_amount=Decimal("100"))
    assert budget_cycle(rule, date.fromisoformat(query)) == (date.fromisoformat(start), date.fromisoformat(end))


@pytest.fixture
def session():
    url = os.environ["DATABASE_URL"]
    assert make_url(url).database == "meu_financeiro_test"
    engine = create_engine(url)
    with engine.connect() as connection:
        outer = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db
        outer.rollback()
    engine.dispose()


def test_budget_spending_transitions_and_historical_calendar_report(session):
    account = Account(name=f"Conta ciclos {uuid4()}", kind="checking", opening_balance=Decimal("1000"))
    category = Category(name=f"Categoria ciclos {uuid4()}", kind="expense")
    session.add_all([account, category]); session.flush()
    session.add(Budget(category_id=category.id, period_start=date(2026, 10, 1), limit_amount=Decimal("200")))
    session.add(BudgetRule(category_id=category.id, effective_start=date(2026, 11, 1),
        period_type="calendar_month", interval_count=1, limit_amount=Decimal("200"), is_migrated_seed=True))
    for day, amount in [(date(2026, 10, 25), "20"), (date(2026, 10, 26), "70"),
                        (date(2026, 11, 9), "30"), (date(2026, 11, 10), "250")]:
        session.add(Transaction(kind="expense", amount=Decimal(amount), account_id=account.id,
            category_id=category.id, description="Gasto sintético", transaction_date=day,
            competence_date=day.replace(day=1), status="settled", settled_date=day))
    session.flush()
    before_ids = set(session.scalars(select(Transaction.id).where(Transaction.category_id == category.id)))
    def current(day):
        return next(row for row in budget_status(session, day) if row["category_id"] == str(category.id))
    assert current(date(2026, 10, 25))["spent"] == Decimal("90")  # legacy month before the new rule
    set_budget(session, category.id, date(2026, 10, 26), Decimal("250"), "monthly_day", 1, 10)
    assert session.scalar(select(BudgetRule).where(BudgetRule.category_id == category.id,
        BudgetRule.effective_start == date(2026, 11, 1))) is None
    assert current(date(2026, 10, 25))["spent"] == Decimal("20")
    first = current(date(2026, 11, 9))
    assert (first["period_start"], first["next_renewal"], first["spent"], first["remaining"], first["state"]) == (
        date(2026, 10, 26), date(2026, 11, 10), Decimal("100"), Decimal("150"), "within")
    renewed = current(date(2026, 11, 10))
    assert (renewed["spent"], renewed["remaining"], renewed["state"]) == (Decimal("250"), Decimal("0"), "at_limit")
    set_budget(session, category.id, date(2026, 11, 20), Decimal("100"), "days", 7)
    assert current(date(2026, 11, 10))["next_renewal"] == date(2026, 11, 20)
    set_budget(session, category.id, date(2026, 12, 1), Decimal("200"), "calendar_month")
    assert current(date(2026, 12, 1))["period_start"] == date(2026, 12, 1)
    assert current(date(2026, 11, 25))["period_type"] == "days"
    assert set(session.scalars(select(Transaction.id).where(Transaction.category_id == category.id))) == before_ids
    october = next(row for row in spend_by_category(session, date(2026, 10, 1), date(2026, 10, 31)) if row["category_id"] == str(category.id))
    assert october["spent"] == Decimal("90")  # calendar report differs from cycle spending


def test_future_start_and_exceeded_without_changing_transactions(session):
    account = Account(name=f"Conta futura {uuid4()}", kind="checking", opening_balance=Decimal("1000"))
    category = Category(name=f"Categoria futura {uuid4()}", kind="expense")
    session.add_all([account, category]); session.flush()
    set_budget(session, category.id, date(2027, 1, 10), Decimal("50"), "weeks", 2)
    assert not any(row["category_id"] == str(category.id) for row in budget_status(session, date(2027, 1, 9)))
    for day, amount in [(date(2027, 1, 9), "40"), (date(2027, 1, 10), "50"), (date(2027, 1, 23), "1"), (date(2027, 1, 24), "10")]:
        session.add(Transaction(kind="expense", amount=Decimal(amount), account_id=account.id,
            category_id=category.id, description="Gasto futuro sintético", transaction_date=day,
            competence_date=day.replace(day=1), status="settled", settled_date=day))
    session.flush()
    first = next(row for row in budget_status(session, date(2027, 1, 23)) if row["category_id"] == str(category.id))
    assert (first["spent"], first["remaining"], first["state"]) == (Decimal("51"), Decimal("-1"), "exceeded")
    second = next(row for row in budget_status(session, date(2027, 1, 24)) if row["category_id"] == str(category.id))
    assert (second["spent"], second["remaining"]) == (Decimal("10"), Decimal("40"))


def test_api_create_edit_and_preview_share_domain(session):
    def test_session():
        with Session(bind=session.get_bind(), join_transaction_mode="create_savepoint") as request_session:
            yield request_session
    app.dependency_overrides[get_session] = test_session
    try:
        with TestClient(app, headers={"Host": "127.0.0.1:8765"}) as client:
            preview = client.post("/api/budgets/preview", json={"effective_start": "2026-10-26",
                "period_type": "monthly_day", "renewal_day": 10})
            assert preview.status_code == 200, preview.text
            assert preview.json()["next_renewal"] == "2026-11-10"
            name = f"Categoria HTTP ciclos {uuid4()}"
            created = client.post("/api/categories", json={"name": name, "kind": "expense",
                "budget_limit": "250.00", "budget_period_type": "days", "budget_interval_count": 7,
                "budget_effective_start": "2026-10-26"})
            assert created.status_code == 201, created.text
            cid = created.json()["id"]
            status = client.get("/api/budgets?month=2026-11-02").json()
            assert next(row for row in status if row["category_id"] == cid)["period_start"] == "2026-11-02"
            updated = client.put(f"/api/categories/{cid}", json={"name": name, "kind": "expense",
                "budget_limit": "250.00", "budget_period_type": "monthly_day", "budget_renewal_day": 10,
                "budget_effective_start": "2026-11-15"})
            assert updated.status_code == 200, updated.text
            assert next(row for row in client.get("/api/budgets?month=2026-11-16").json() if row["category_id"] == cid)["next_renewal"] == "2026-12-10"
    finally:
        app.dependency_overrides.clear()
