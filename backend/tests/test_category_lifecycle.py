"""Category lifecycle checks use synthetic rows in the isolated test database."""

import os
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.categories import archive_category, archive_preview, restore_category
from backend.app.db import get_session
from backend.app.domain import budget_status, create_transaction, set_budget, spend_by_category
from backend.app.main import app
from backend.app.models import Account, BudgetRule, Category, Transaction


@pytest.fixture
def isolated():
    url = os.environ["DATABASE_URL"]
    assert make_url(url).database == "meu_financeiro_test"
    engine = create_engine(url)
    with engine.connect() as connection:
        outer = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session, connection
        outer.rollback()
    engine.dispose()


def test_empty_category_archive_and_restore_keep_identity_and_appearance(isolated):
    session, _ = isolated
    category = Category(name=f"Vazia {uuid4()}", kind="expense", icon="cart", color="#315C96")
    session.add(category)
    session.flush()
    original_id = category.id
    preview = archive_preview(session, category, date(2026, 10, 26))
    assert preview["transaction_count"] == 0
    assert preview["visible_until"] is None
    archive_category(session, original_id, date(2026, 10, 26))
    assert category.is_active is False
    assert category.id == original_id
    assert category not in session.scalars(select(Category).where(Category.is_active.is_(True))).all()
    restored = restore_category(session, original_id)
    assert restored.id == original_id
    assert (restored.icon, restored.color, restored.visible_until) == ("cart", "#315C96", None)
    assert session.scalars(select(Category).where(Category.id == original_id)).all() == [restored]


def test_archive_with_spending_budget_keeps_history_and_blocks_new_writes(isolated):
    session, _ = isolated
    today = date(2026, 10, 26)
    account = Account(name=f"Conta {uuid4()}", kind="checking", opening_balance=Decimal("500"))
    category = Category(name=f"Mercado {uuid4()}", kind="expense", icon="cart", color="#326B50")
    other = Category(name=f"Lanches {uuid4()}", kind="expense", icon="cart", color="#B65F3C")
    session.add_all([account, category, other]); session.flush()
    rule = set_budget(session, category.id, today, Decimal("300"), "days", 10)
    first = create_transaction(session, {"kind": "expense", "amount": "120.00", "account_id": account.id,
        "category_id": category.id, "description": "Gasto sintético", "transaction_date": today, "status": "settled"})
    another = create_transaction(session, {"kind": "expense", "amount": "40.00", "account_id": account.id,
        "category_id": other.id, "description": "Outro gasto sintético", "transaction_date": today, "status": "settled"})
    before = (first.id, first.category_id, first.amount, rule.id, rule.limit_amount)
    preview = archive_preview(session, category, today)
    assert (preview["current_spending_count"], preview["current_spent"], preview["visible_until"]) == (1, Decimal("120.00"), today + timedelta(days=9))
    archive_category(session, category.id, today)
    assert category.is_active is False
    assert category.visible_until == today + timedelta(days=9)
    current = next(row for row in budget_status(session, today + timedelta(days=9)) if row["category_id"] == str(category.id))
    assert (current["spent"], current["color"], current["is_active"]) == (Decimal("120.00"), "#326B50", False)
    assert not any(row["category_id"] == str(category.id) for row in budget_status(session, today + timedelta(days=10)))
    for day in (today, today + timedelta(days=10)):
        spending = {row["category_id"]: row for row in spend_by_category(session, today, day)}
        assert (spending[str(category.id)]["spent"], spending[str(other.id)]["spent"]) == (Decimal("120.00"), Decimal("40.00"))
        assert spending[str(category.id)]["color"] == "#326B50"
    with pytest.raises(Exception) as error:
        create_transaction(session, {"kind": "expense", "amount": "1.00", "account_id": account.id,
            "category_id": category.id, "description": "Bloqueado", "transaction_date": today, "status": "settled"})
    assert "inativa" in str(error.value)
    assert (first.id, first.category_id, first.amount, rule.id, rule.limit_amount) == before
    assert session.get(Transaction, first.id) is first
    assert session.get(Transaction, another.id) is another
    assert session.get(BudgetRule, rule.id) is rule
    restore_category(session, category.id)
    assert category.is_active and category.visible_until is None
    assert next(row for row in budget_status(session, today + timedelta(days=10)) if row["category_id"] == str(category.id))["limit"] == Decimal("300")
    new = create_transaction(session, {"kind": "expense", "amount": "1.00", "account_id": account.id,
        "category_id": category.id, "description": "Novo gasto sintético", "transaction_date": today, "status": "settled"})
    assert new.category_id == category.id and new.id != first.id


def test_api_archive_rejects_direct_write_and_preserves_historical_chart_data(isolated):
    _, connection = isolated
    def test_session():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
    app.dependency_overrides[get_session] = test_session
    try:
        with TestClient(app, headers={"Host": "127.0.0.1:8765"}) as client:
            suffix = uuid4().hex[:8]
            account = client.post("/api/accounts", json={"name": f"Conta ciclo {suffix}", "kind": "checking"}).json()
            category = client.post("/api/categories", json={"name": f"Categoria ciclo {suffix}", "kind": "expense", "icon": "cart", "color": "#315C96"}).json()
            cid = category["id"]
            assert category["color"] == "#315C96"
            body = {"kind": "expense", "amount": "120.00", "account_id": account["id"], "category_id": cid,
                    "description": "Despesa de teste", "transaction_date": date.today().isoformat()}
            created = client.post("/api/transactions", json=body, headers={"Idempotency-Key": f"category-{suffix}"})
            assert created.status_code == 201, created.text
            tid = created.json()["id"]
            preview = client.get(f"/api/categories/{cid}/archive-preview")
            assert preview.status_code == 200 and preview.json()["current_spending_count"] == 1
            archived = client.post(f"/api/categories/{cid}/archive")
            assert archived.status_code == 200 and archived.json()["category_id"] == cid
            assert all(row["id"] != cid for row in client.get("/api/categories").json())
            assert any(row["id"] == cid for row in client.get("/api/categories?scope=archived").json())
            blocked = client.post("/api/transactions", json={**body, "description": "Recusada"}, headers={"Idempotency-Key": f"blocked-{suffix}"})
            assert blocked.status_code in (404, 422), blocked.text
            historical = client.get(f"/api/spending?start={date.today()}&end={date.today()}").json()
            assert next(row for row in historical if row["category_id"] == cid)["spent"] == "120.00"
            assert next(row for row in historical if row["category_id"] == cid)["color"] == "#315C96"
            assert client.get(f"/api/transactions?category_id={cid}").json()[0]["id"] == tid
            restored = client.post(f"/api/categories/{cid}/restore")
            assert restored.status_code == 200 and restored.json()["id"] == cid
            assert restored.json()["color"] == "#315C96" and restored.json()["icon"] == "cart"
    finally:
        app.dependency_overrides.clear()


def test_database_failure_rolls_back_archive(isolated):
    session, _ = isolated
    category = Category(name=f"Falha {uuid4()}", kind="expense", color="#315C96")
    session.add(category); session.commit()
    category_id = category.id
    def fail_flush(_session, _context, _instances):
        raise RuntimeError("Falha sintética de banco")
    event.listen(session, "before_flush", fail_flush)
    try:
        with pytest.raises(RuntimeError, match="Falha sintética"):
            archive_category(session, category_id, date(2026, 10, 26))
    finally:
        event.remove(session, "before_flush", fail_flush)
        session.rollback()
    session.expire_all()
    assert session.get(Category, category_id).is_active is True


def test_calendar_fallback_and_historical_only_visibility(isolated):
    session, _ = isolated
    today = date(2026, 10, 26)
    account = Account(name=f"Conta sem limite {uuid4()}", kind="checking", opening_balance=Decimal("100"))
    recent = Category(name=f"Sem limite atual {uuid4()}", kind="expense", color="#315C96")
    old = Category(name=f"Somente histórico {uuid4()}", kind="expense", color="#B65F3C")
    session.add_all([account, recent, old]); session.flush()
    create_transaction(session, {"kind": "expense", "amount": "12.00", "account_id": account.id,
        "category_id": recent.id, "description": "Gasto do mês", "transaction_date": today, "status": "settled"})
    create_transaction(session, {"kind": "expense", "amount": "8.00", "account_id": account.id,
        "category_id": old.id, "description": "Gasto antigo", "transaction_date": date(2026, 9, 15), "status": "settled"})
    assert archive_category(session, recent.id, today)["visible_until"] == date(2026, 10, 31)
    assert archive_category(session, old.id, today)["visible_until"] is None
    september = {row["category_id"]: row for row in spend_by_category(session, date(2026, 9, 1), date(2026, 9, 30))}
    assert september[str(old.id)]["spent"] == Decimal("8.00")
    october = {row["category_id"]: row for row in spend_by_category(session, date(2026, 10, 1), date(2026, 10, 31))}
    assert october[str(recent.id)]["spent"] == Decimal("12.00")
    assert str(old.id) not in october


def test_database_failure_rolls_back_restore(isolated):
    session, _ = isolated
    category = Category(name=f"Restauração com falha {uuid4()}", kind="expense", color="#315C96")
    session.add(category); session.flush()
    category_id = category.id
    archive_category(session, category_id, date(2026, 10, 26))
    session.commit()
    def fail_flush(_session, _context, _instances):
        raise RuntimeError("Falha sintética de banco")
    event.listen(session, "before_flush", fail_flush)
    try:
        with pytest.raises(RuntimeError, match="Falha sintética"):
            restore_category(session, category_id)
    finally:
        event.remove(session, "before_flush", fail_flush)
        session.rollback()
    session.expire_all()
    assert session.get(Category, category_id).is_active is False


def test_api_auto_color_unique_and_manual_color_validated(isolated):
    _, connection = isolated
    def test_session():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
    app.dependency_overrides[get_session] = test_session
    try:
        with TestClient(app, headers={"Host": "127.0.0.1:8765"}) as client:
            suffix = uuid4().hex[:8]
            a = client.post("/api/categories", json={"name": f"Mesmo ícone A {suffix}", "kind": "expense", "icon": "cart"})
            b = client.post("/api/categories", json={"name": f"Mesmo ícone B {suffix}", "kind": "expense", "icon": "cart"})
            assert a.status_code == b.status_code == 201
            assert a.json()["color"] != b.json()["color"]
            invalid = client.put(f"/api/categories/{a.json()['id']}", json={"name": a.json()["name"], "kind": "expense", "color": "red"})
            assert invalid.status_code == 422
            edited = client.put(f"/api/categories/{a.json()['id']}", json={"name": a.json()["name"], "kind": "expense", "color": "#ABCDEF"})
            assert edited.status_code == 200 and edited.json()["color"] == "#ABCDEF"
            assert edited.json()["icon"] == "cart"
    finally:
        app.dependency_overrides.clear()
