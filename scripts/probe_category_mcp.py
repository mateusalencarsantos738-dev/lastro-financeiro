"""Exercise the category lifecycle through the real MCP STDIO protocol in the test DB."""

import asyncio
import json
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.domain import set_budget
from backend.app.models import Account, BudgetRule, Category, Transaction


ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.environ["DATABASE_URL"]
if make_url(DB_URL).database != "meu_financeiro_test":
    raise SystemExit("A prova MCP exige exclusivamente meu_financeiro_test")


def unpack(result):
    if result.isError:
        raise AssertionError(f"MCP retornou erro: {result.content}")
    structured = getattr(result, "structuredContent", None)
    return structured.get("result", structured) if structured is not None else json.loads(result.content[0].text)


async def run():
    engine = create_engine(DB_URL)
    today = date.today()
    with Session(engine) as session, session.begin():
        account = Account(name=f"Conta ciclo MCP {uuid4()}", kind="checking", opening_balance=Decimal("500"))
        category = Category(name=f"Categoria ciclo MCP {uuid4()}", kind="expense", icon="cart", color="#315C96")
        session.add_all([account, category]); session.flush()
        rule = set_budget(session, category.id, today, Decimal("300"), "days", 10)
        account_id, category_id, rule_id = str(account.id), str(category.id), rule.id

    params = StdioServerParameters(command=str(ROOT / ".venv/bin/python"), args=["-m", "mcp_server.server"],
                                   cwd=str(ROOT), env={**os.environ, "DATABASE_URL": DB_URL})
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {"finance_list_categories", "finance_preview_category_archive", "finance_archive_category",
                    "finance_restore_category", "finance_get_category_spending", "finance_get_budget_status"} <= names
            created = unpack(await client.call_tool("finance_create_transaction", {"kind": "expense", "amount": "120.00",
                "account_id": account_id, "category_id": category_id, "description": "Gasto sintético MCP",
                "transaction_date": today.isoformat(), "idempotency_key": f"category-mcp-{uuid4()}"}))
            preview = unpack(await client.call_tool("finance_preview_category_archive", {"category_id": category_id}))
            assert preview["current_spending_count"] == 1
            assert preview["visible_until"] == (today + timedelta(days=9)).isoformat()
            assert (await client.call_tool("finance_archive_category", {"category_id": category_id, "confirmed": False})).isError
            archived = unpack(await client.call_tool("finance_archive_category", {"category_id": category_id, "confirmed": True}))
            assert archived["category_id"] == category_id
            assert not any(c["id"] == category_id for c in unpack(await client.call_tool("finance_list_categories")))
            stored = next(c for c in unpack(await client.call_tool("finance_list_categories", {"scope": "archived"})) if c["id"] == category_id)
            assert stored["color"] == "#315C96" and stored["icon"] == "cart" and stored["is_active"] is False
            denied = await client.call_tool("finance_create_transaction", {"kind": "expense", "amount": "1.00",
                "account_id": account_id, "category_id": category_id, "description": "Recusado",
                "transaction_date": today.isoformat(), "idempotency_key": f"category-denied-{uuid4()}"})
            assert denied.isError
            spending = next(row for row in unpack(await client.call_tool("finance_get_category_spending", {
                "start": today.isoformat(), "end": today.isoformat()})) if row["category_id"] == category_id)
            assert spending["spent"] == "120.00" and spending["color"] == "#315C96"
            status = next(row for row in unpack(await client.call_tool("finance_get_budget_status", {"month": today.isoformat()})) if row["category_id"] == category_id)
            assert status["spent"] == "120.00" and status["is_active"] is False
            restored = unpack(await client.call_tool("finance_restore_category", {"category_id": category_id, "confirmed": True}))
            assert restored["id"] == category_id and restored["color"] == "#315C96"
            assert any(c["id"] == category_id for c in unpack(await client.call_tool("finance_list_categories")))

    with Session(engine) as session:
        assert session.get(Transaction, UUID(created["id"])).category_id == UUID(category_id)
        assert session.get(BudgetRule, rule_id).limit_amount == Decimal("300")
        assert session.get(Category, UUID(category_id)).is_active
    engine.dispose()
    print("MCP categoria: lista, prévia, arquivamento, bloqueio, histórico e restauração OK")


if __name__ == "__main__":
    asyncio.run(run())
