"""Fluxo HTTP isolado por transação no banco de teste."""
import os
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.main import app


def test_api_write_read_audit_and_local_origin():
    url = os.environ["DATABASE_URL"]
    assert make_url(url).database == "meu_financeiro_test"
    engine = create_engine(url)
    with engine.connect() as connection:
        outer = connection.begin()

        def test_session():
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = test_session
        try:
            with TestClient(app, headers={"Host": "127.0.0.1:8765"}) as client:
                suffix = uuid4().hex[:8]
                account = client.post("/api/accounts", json={"name": f"Conta HTTP sintética {suffix}", "kind": "checking", "opening_balance": "1000.00"})
                assert account.status_code == 201, account.text
                category = client.post("/api/categories", json={"name": f"Lazer HTTP sintético {suffix}", "kind": "expense", "is_entertainment": True})
                assert category.status_code == 201, category.text
                aid, cid = account.json()["id"], category.json()["id"]
                body = {"kind": "expense", "amount": "42.50", "account_id": aid, "category_id": cid,
                        "description": "Cinema HTTP sintético", "transaction_date": "2020-01-15"}
                headers = {"Idempotency-Key": f"api-expense-{suffix}"}
                first = client.post("/api/transactions", json=body, headers=headers)
                assert first.status_code == 201, first.text
                repeated = client.post("/api/transactions", json=body, headers=headers)
                assert repeated.json()["id"] == first.json()["id"]
                tid = first.json()["id"]
                update = {"expected_version": 1, "amount": "43.50", "category_id": cid,
                          "description": "Cinema HTTP corrigido", "transaction_date": "2020-01-15",
                          "reason": "Valor digitado incorretamente", "confirmed": True}
                denied = client.put(f"/api/transactions/{tid}", json={**update, "confirmed": False})
                assert denied.status_code == 422
                corrected = client.put(f"/api/transactions/{tid}", json=update, headers={"Idempotency-Key": f"api-correction-{suffix}"})
                assert corrected.status_code == 200, corrected.text
                assert corrected.json()["version"] == 2 and corrected.json()["amount"] == "43.50"
                assert len(client.get(f"/api/transactions/{tid}/revisions").json()) == 1
                assert client.get("/api/overview?month=2020-01-01").json()["expenses"] == "43.50"
                planned = client.post("/api/transactions", json={"kind": "income", "amount": "100.00",
                    "account_id": aid, "description": "Receita esperada sintética", "transaction_date": "2020-01-15",
                    "status": "pending", "notes": "Aguardando confirmação"})
                assert planned.status_code == 201, planned.text
                assert client.get("/api/overview?month=2020-01-01").json()["income"] == "0"
                planned_id = planned.json()["id"]
                assert client.post(f"/api/transactions/{planned_id}/settle?settled_on=2020-01-15").json()["status"] == "settled"
                assert client.post(f"/api/transactions/{planned_id}/settle?settled_on=2020-01-15").json()["status"] == "settled"
                assert client.get("/api/overview?month=2020-01-01").json()["income"] == "100.00"
                bill = client.post("/api/bills", json={"description": "Conta sintética", "amount": "20.00",
                                   "due_date": "2020-01-20", "category_id": cid})
                assert bill.status_code == 201, bill.text
                payment = {"source_account_id": aid, "paid_date": "2020-01-20"}
                pay_headers = {"Idempotency-Key": f"api-bill-{suffix}"}
                paid = client.post(f"/api/bills/{bill.json()['id']}/pay", json=payment, headers=pay_headers)
                assert paid.status_code == 200, paid.text
                assert client.post(f"/api/bills/{bill.json()['id']}/pay", json=payment, headers=pay_headers).json()["transaction_id"] == paid.json()["transaction_id"]
                investment = client.post("/api/investments", json={"name": f"Ativo HTTP {suffix}",
                    "kind": "renda_fixa", "institution": "Instituição sintética", "quantity": "1.25000000",
                    "opening_contribution": "200.00", "acquired_on": "2020-01-01",
                    "current_value": "210.00", "valuation_date": "2020-01-15"})
                assert investment.status_code == 201, investment.text
                listed_investment = next(row for row in client.get("/api/investments").json() if row["id"] == investment.json()["id"])
                assert listed_investment["institution"] == "Instituição sintética"
                assert listed_investment["difference_vs_net_invested"] == "10.00"
                goal = client.post("/api/goals", json={"name": f"Meta HTTP {suffix}",
                    "target_amount": "500.00", "allocated_amount": "50.00"})
                assert goal.status_code == 201, goal.text
                contribution = client.post(f"/api/goals/{goal.json()['id']}/contributions", json={"amount_delta":"30.00", "contributed_on":"2020-01-15", "note":"Contribuição sintética"})
                assert contribution.status_code == 201, contribution.text
                assert next(row for row in client.get("/api/goals").json() if row["id"] == goal.json()["id"])["contributed_amount"] == "30.00"
                updated_goal = client.put(f"/api/goals/{goal.json()['id']}", json={"name": f"Meta HTTP {suffix}",
                    "target_amount": "500.00", "allocated_amount": "75.00"})
                assert updated_goal.status_code == 200, updated_goal.text
                allocations = client.get(f"/api/goals/{goal.json()['id']}/allocations").json()
                assert [row["amount_delta"] for row in allocations] == ["50.00", "25.00"]
                edited_category = client.put(f"/api/categories/{cid}", json={"name": f"Lazer ajustado {suffix}",
                    "kind": "expense", "is_entertainment": True, "icon": "film"})
                assert edited_category.status_code == 200, edited_category.text
                assert edited_category.json()["name"] == f"Lazer ajustado {suffix}"
                assert next(row for row in client.get("/api/categories").json() if row["id"] == cid)["icon"] == "film"
                assert client.put(f"/api/categories/{cid}", json={"name": f"Lazer ajustado {suffix}", "kind": "expense", "is_entertainment": True}).json()["icon"] == "film"
                calendar = client.get("/api/calendar?start=2020-01-15&end=2020-01-15")
                assert calendar.status_code == 200, calendar.text
                assert any(row["date"] == "2020-01-15" and any(tx["id"] == tid for tx in row["transactions"]) for row in calendar.json())
                assert client.put(f"/api/categories/{cid}", json={"name": f"Lazer ajustado {suffix}",
                    "kind": "income", "is_entertainment": False}).status_code == 422
                denied_delete = client.delete(f"/api/transactions/{tid}?expected_version=2")
                assert denied_delete.status_code == 422
                assert client.get("/api/overview?month=2020-01-01").json()["expenses"] == "63.50"
                deleted = client.delete(f"/api/transactions/{tid}?expected_version=2&confirmed=true")
                assert deleted.status_code == 200, deleted.text
                assert tid in deleted.json()["deleted_ids"]
                assert client.get("/api/overview?month=2020-01-01").json()["expenses"] == "20.00"
                assert any(row["id"] == tid for row in client.get("/api/transactions/trash").json())
                assert not any(row["id"] == tid for row in client.get("/api/transactions").json())
                restored = client.post(f"/api/transactions/{tid}/restore")
                assert restored.status_code == 200, restored.text
                assert client.post(f"/api/transactions/{tid}/restore").status_code == 200
                assert client.get("/api/overview?month=2020-01-01").json()["expenses"] == "63.50"
                rejected_origin = client.post("/api/categories", json={"name": "Bloqueada"}, headers={"Origin": "https://evil.example"})
                assert rejected_origin.status_code == 403
                assert client.get("/api/overview", headers={"Host": "evil.example"}).status_code == 400
                assert client.get("/api/transactions", params={"q": "%' OR 1=1 --"}).status_code == 200
        finally:
            app.dependency_overrides.clear()
            outer.rollback()
    engine.dispose()


def test_card_purchase_http_edit_delete_restore_after_paid_invoice():
    url = os.environ["DATABASE_URL"]
    assert make_url(url).database == "meu_financeiro_test"
    engine = create_engine(url)
    with engine.connect() as connection:
        outer = connection.begin()
        def test_session():
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                yield session
        app.dependency_overrides[get_session] = test_session
        try:
            with TestClient(app, headers={"Host": "127.0.0.1:8765"}) as client:
                suffix = uuid4().hex[:8]
                account = client.post("/api/accounts", json={"name": f"Conta cartão HTTP {suffix}", "opening_balance": "1000"}).json()
                category = client.post("/api/categories", json={"name": f"Categoria cartão HTTP {suffix}", "kind": "expense"}).json()
                card = client.post("/api/cards", json={"name": f"Cartão HTTP {suffix}", "closing_day": 10, "due_day": 17}).json()
                created = client.post("/api/card-purchases", json={"card_id": card["id"], "category_id": category["id"],
                    "total_amount": "80.00", "installment_count": 1, "purchase_date": "2020-01-15", "merchant": "Compra HTTP"})
                assert created.status_code == 201, created.text
                purchase_id = created.json()["id"]
                detail = client.get(f"/api/card-purchases/{purchase_id}").json()
                assert detail["version"] == 1 and detail["total_amount"] == "80.00"
                invoice_id = detail["installments"][0]["invoice_id"]
                paid = client.post(f"/api/invoices/{invoice_id}/pay", json={"source_account_id": account["id"], "paid_date": "2020-01-20"})
                assert paid.status_code == 200, paid.text
                edited = client.patch(f"/api/card-purchases/{purchase_id}", json={"expected_version": 1,
                    "total_amount": "95.00", "merchant": "Compra HTTP corrigida"})
                assert edited.status_code == 200, edited.text
                assert edited.json()["version"] == 2 and edited.json()["category_id"] == category["id"]
                assert next(item for item in client.get("/api/invoices").json() if item["id"] == invoice_id)["total"] == "95.00"
                assert client.get("/api/overview?month=2020-01-01").json()["expenses"] == "95.00"
                assert client.get("/api/calendar?start=2020-01-15&end=2020-01-15").json()[0]["expenses"] == "95.00"
                assert next(item for item in client.get("/api/balances").json() if item["account_id"] == account["id"])["balance"] == "905.00"
                assert client.get(f"/api/transactions/{detail['transaction_id']}/deletion-preview").json()["can_delete"]
                deleted = client.delete(f"/api/card-purchases/{purchase_id}?expected_version=2&confirmed=true")
                assert deleted.status_code == 200, deleted.text
                assert not any(item["id"] == purchase_id for item in client.get("/api/card-purchases").json())
                assert not any(item["id"] == invoice_id for item in client.get("/api/invoices").json())
                assert client.get("/api/overview?month=2020-01-01").json()["expenses"] == "0"
                assert client.delete(f"/api/card-purchases/{purchase_id}?expected_version=2&confirmed=true").status_code == 409
                restored = client.post(f"/api/card-purchases/{purchase_id}/restore")
                assert restored.status_code == 200, restored.text
                assert restored.json()["deleted_at"] is None
                assert next(item for item in client.get("/api/invoices").json() if item["id"] == invoice_id)["total"] == "95.00"
        finally:
            app.dependency_overrides.clear()
            outer.rollback()
    engine.dispose()
