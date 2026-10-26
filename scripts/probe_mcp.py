"""Prova MCP STDIO com dados sintéticos persistidos somente no banco de teste."""

import asyncio
import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.domain import budget_status
from backend.app.models import Account, Category, CreditCard, CreditPurchase, Investment, InvestmentEvent, Transaction, TransactionRevision, InvestmentValuation

ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.environ["DATABASE_URL"]
if make_url(DB_URL).database != "meu_financeiro_test":
    raise SystemExit("A prova MCP exige exclusivamente meu_financeiro_test")


def payload(result):
    if result.isError:
        raise AssertionError(f"Ferramenta MCP retornou erro: {result.content}")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured)
    return json.loads(result.content[0].text)


async def run():
    engine = create_engine(DB_URL)
    suffix = uuid4().hex[:8]
    with Session(engine) as session, session.begin():
        a = Account(name=f"Conta MCP sintética A {suffix}", opening_balance=Decimal("1000"))
        b = Account(name=f"Conta MCP sintética B {suffix}", opening_balance=Decimal("0"))
        c = Category(name=f"Lazer MCP sintético {suffix}", kind="expense", is_entertainment=True)
        investment = Investment(name=f"Ativo MCP sintético {suffix}", kind="renda_fixa", current_value=Decimal("0"))
        card_account = Account(name=f"Cartão MCP sintético {suffix}", kind="credit_card", opening_balance=Decimal("0"))
        session.add_all([a, b, c, investment, card_account]); session.flush()
        card = CreditCard(account_id=card_account.id, closing_day=10, due_day=17)
        session.add(card); session.flush()
        a_id, b_id, c_id, investment_id = map(str, [a.id, b.id, c.id, investment.id])
        card_id = str(card.id)

    params = StdioServerParameters(command=str(ROOT / ".venv/bin/python"), args=["-m", "mcp_server.server"], cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL})
    expense_key = f"probe-expense-{suffix}"
    expense_data = {"kind": "expense", "amount": "42.50", "account_id": a_id, "category_id": c_id, "description": "Cinema sintético MCP", "transaction_date": date.today().isoformat(), "idempotency_key": expense_key}
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {"finance_get_balances", "finance_create_transaction", "finance_create_transfer", "finance_create_investment_event", "finance_get_net_worth", "finance_list_categories", "finance_update_transaction", "finance_record_investment_valuation", "finance_get_net_worth_history", "finance_delete_transaction", "finance_restore_transaction", "finance_get_transaction_trash", "finance_get_transaction", "finance_list_card_purchases", "finance_get_card_purchase", "finance_update_card_purchase", "finance_delete_card_purchase", "finance_restore_card_purchase", "finance_get_invoices"}
            assert required <= names, required - names
            assert any(item["id"] == c_id for item in payload(await client.call_tool("finance_list_categories")))
            created = payload(await client.call_tool("finance_create_transaction", expense_data))
            repeated = payload(await client.call_tool("finance_create_transaction", expense_data))
            assert created["id"] == repeated["id"]
            transfer = payload(await client.call_tool("finance_create_transfer", {"source_account_id": a_id, "destination_account_id": b_id, "amount": "300", "transaction_date": date.today().isoformat(), "description": "Transferência sintética MCP", "idempotency_key": f"probe-transfer-{suffix}"}))
            assert transfer["outgoing_id"] != transfer["incoming_id"]
            contribution = payload(await client.call_tool("finance_create_investment_event", {"investment_id": investment_id, "account_id": a_id, "kind": "contribution", "amount": "350", "event_date": date.today().isoformat(), "idempotency_key": f"probe-investment-{suffix}"}))
            assert contribution["amount"] == "350.00"
            balances = payload(await client.call_tool("finance_get_balances"))
            by_id = {item["account_id"]: Decimal(item["balance"]) for item in balances}
            assert by_id[a_id] == Decimal("307.50")
            assert by_id[b_id] == Decimal("300.00")
            invalid = await client.call_tool("finance_create_transaction", {**expense_data, "amount": "-1", "idempotency_key": f"probe-invalid-{suffix}"})
            assert invalid.isError
            correction_data = {"transaction_id": created["id"], "expected_version": created["version"], "amount": "43.50",
                               "category_id": c_id, "description": "Cinema corrigido MCP", "transaction_date": date.today().isoformat(),
                               "reason": "Valor sintético digitado incorretamente", "idempotency_key": f"probe-correction-{suffix}", "confirmed": True}
            corrected = payload(await client.call_tool("finance_update_transaction", correction_data))
            assert corrected["version"] == 2 and corrected["amount"] == "43.50"
            assert payload(await client.call_tool("finance_update_transaction", correction_data))["id"] == created["id"]
            configured = payload(await client.call_tool("finance_set_budget", {"category_id": c_id,
                "month": date.today().isoformat(), "limit_amount": "100.00",
                "period_type": "days", "interval_count": 7}))
            assert configured["period_type"] == "days" and configured["interval_count"] == 7
            budget = next(item for item in payload(await client.call_tool("finance_get_budget_status", {"month": date.today().isoformat()})) if item["category_id"] == c_id)
            assert budget["spent"] == "43.50" and budget["remaining"] == "56.50"
            assert budget["period_start"] == date.today().isoformat()
            category_mcp = next(item for item in payload(await client.call_tool("finance_list_categories")) if item["id"] == c_id)
            assert category_mcp["budget_period_type"] == "days" and category_mcp["budget_interval_count"] == 7
            preview = payload(await client.call_tool("finance_get_deletion_preview", {"transaction_id": created["id"]}))
            assert preview["can_delete"]
            denied_delete = await client.call_tool("finance_delete_transaction", {"transaction_id": created["id"], "expected_version": 2, "confirmed": False})
            assert denied_delete.isError
            deleted = payload(await client.call_tool("finance_delete_transaction", {"transaction_id": created["id"], "expected_version": 2, "confirmed": True}))
            assert created["id"] in deleted["deleted_ids"]
            assert not any(item["id"] == created["id"] for item in payload(await client.call_tool("finance_list_transactions", {"limit": 500})))
            assert any(item["id"] == created["id"] for item in payload(await client.call_tool("finance_get_transaction_trash")))
            restored = payload(await client.call_tool("finance_restore_transaction", {"transaction_id": created["id"], "confirmed": True}))
            assert created["id"] in restored["restored_ids"]
            assert any(item["id"] == created["id"] for item in payload(await client.call_tool("finance_list_transactions", {"limit": 500})))
            valuation = payload(await client.call_tool("finance_record_investment_valuation", {"investment_id": investment_id,
                                "value": "355.00", "valuation_date": date.today().isoformat(), "idempotency_key": f"probe-valuation-{suffix}"}))
            assert valuation["value"] == "355.00"
            card_purchase = payload(await client.call_tool("finance_create_card_purchase", {"card_id": card_id,
                "category_id": c_id, "total_amount": "89.90", "installment_count": 2,
                "purchase_date": date.today().isoformat(), "merchant": f"Compra MCP sintética {suffix}",
                "idempotency_key": f"probe-card-{suffix}"}))
            purchase_id = card_purchase["id"]
            detail = payload(await client.call_tool("finance_get_card_purchase", {"purchase_id": purchase_id}))
            assert detail["version"] == 1 and detail["total_amount"] == "89.90"
            searched = payload(await client.call_tool("finance_list_card_purchases", {"card_id": card_id,
                "total_amount": "89.90", "merchant": f"Compra MCP sintética {suffix}"}))
            assert [item["id"] for item in searched] == [purchase_id]
            second = payload(await client.call_tool("finance_create_card_purchase", {"card_id": card_id,
                "category_id": c_id, "total_amount": "89.90", "installment_count": 2,
                "purchase_date": date.today().isoformat(), "merchant": f"Compra MCP sintética {suffix}",
                "idempotency_key": f"probe-card-second-{suffix}"}))
            ambiguous = payload(await client.call_tool("finance_list_card_purchases", {"card_id": card_id,
                "total_amount": "89.90", "merchant": f"Compra MCP sintética {suffix}"}))
            assert len(ambiguous) == 2 and {item["id"] for item in ambiguous} == {purchase_id, second["id"]}
            assert (await client.call_tool("finance_get_card_purchase", {"purchase_id": str(uuid4())})).isError
            invoice_id = detail["installments"][0]["invoice_id"]
            paid = payload(await client.call_tool("finance_pay_invoice", {"invoice_id": invoice_id,
                "source_account_id": a_id, "paid_date": date.today().isoformat(),
                "idempotency_key": f"probe-card-payment-{suffix}"}))
            assert paid["amount"] == "89.90"
            changed = payload(await client.call_tool("finance_update_card_purchase", {"purchase_id": purchase_id,
                "expected_version": 1, "total_amount": "100.00", "merchant": "Compra MCP corrigida"}))
            assert changed["version"] == 2 and changed["total_amount"] == "100.00"
            assert changed["category_id"] == c_id and changed["card_id"] == card_id
            assert next(item for item in changed["invoice_totals_after"] if item["id"] == invoice_id)["total"] == "94.95"
            assert (await client.call_tool("finance_update_card_purchase", {"purchase_id": purchase_id,
                "expected_version": 1, "merchant": "Versão antiga"})).isError
            assert payload(await client.call_tool("finance_get_transaction", {"transaction_id": changed["transaction_id"]}))["amount"] == "100.00"
            assert next(item for item in payload(await client.call_tool("finance_get_invoices")) if item["id"] == invoice_id)["total"] == "94.95"
            deleted_card = payload(await client.call_tool("finance_delete_card_purchase", {"purchase_id": purchase_id,
                "expected_version": 2}))
            assert deleted_card["id"] == purchase_id and deleted_card["deleted_at"]
            assert next(item for item in deleted_card["invoice_totals_after"] if item["id"] == invoice_id)["total"] == "44.95"
            assert not any(item["id"] == purchase_id for item in payload(await client.call_tool("finance_list_card_purchases", {"card_id": card_id})))
            assert (await client.call_tool("finance_delete_card_purchase", {"purchase_id": purchase_id,
                "expected_version": 2})).isError
            assert next(item for item in payload(await client.call_tool("finance_get_invoices")) if item["id"] == invoice_id)["total"] == "44.95"
            restored_card = payload(await client.call_tool("finance_restore_card_purchase", {"purchase_id": purchase_id}))
            assert restored_card["deleted_at"] is None
            assert next(item for item in payload(await client.call_tool("finance_get_invoices")) if item["id"] == invoice_id)["total"] == "94.95"
            other_invoice_id = detail["installments"][1]["invoice_id"]
            payload(await client.call_tool("finance_pay_invoice", {"invoice_id": other_invoice_id,
                "source_account_id": a_id, "paid_date": date.today().isoformat(),
                "idempotency_key": f"probe-card-payment-second-{suffix}"}))
            final_budget = next(item for item in payload(await client.call_tool("finance_get_budget_status", {"month": date.today().isoformat()})) if item["category_id"] == c_id)
            snapshot = payload(await client.call_tool("finance_save_net_worth_snapshot"))
            assert "net_worth" in snapshot
            print(f"MCP: {len(names)} ferramentas descobertas; leitura, escrita, idempotência e entrada inválida verificados")

    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            rows = payload(await client.call_tool("finance_list_transactions", {"limit": 500}))
            assert any(row["id"] == created["id"] and row["amount"] == "43.50" for row in rows)
            assert payload(await client.call_tool("finance_get_net_worth_history"))

    with Session(engine) as session:
        direct_budget = next(item for item in budget_status(session, date.today()) if item["category_id"] == c_id)
        assert direct_budget["spent"] == Decimal(final_budget["spent"]) and direct_budget["period_type"] == "days"
        assert session.scalar(select(func.count()).select_from(Transaction).where(Transaction.idempotency_key == expense_key)) == 1
        assert session.scalar(select(func.count()).select_from(InvestmentEvent).where(InvestmentEvent.id == contribution["id"])) == 1
        assert session.scalar(select(func.count()).select_from(TransactionRevision).where(TransactionRevision.transaction_id == created["id"])) == 1
        assert session.scalar(select(func.count()).select_from(InvestmentValuation).where(InvestmentValuation.id == valuation["id"])) == 1
        assert session.scalar(select(func.count()).select_from(CreditPurchase).where(CreditPurchase.id == purchase_id)) == 1
        assert session.scalar(select(Transaction).where(Transaction.id == changed["transaction_id"])).amount == Decimal("100.00")
    broken_url = make_url(DB_URL).set(database=f"meu_financeiro_missing_{suffix}").render_as_string(hide_password=False)
    broken_params = StdioServerParameters(command=str(ROOT / ".venv/bin/python"), args=["-m", "mcp_server.server"], cwd=str(ROOT), env={**os.environ, "DATABASE_URL": broken_url})
    async with stdio_client(broken_params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            unavailable = await client.call_tool("finance_get_balances")
            assert unavailable.isError
    print("MCP: persistência conferida após reiniciar o processo e diretamente no PostgreSQL de teste")
    print("MCP: banco indisponível gera erro de ferramenta, sem resposta financeira fictícia")


if __name__ == "__main__":
    asyncio.run(run())
