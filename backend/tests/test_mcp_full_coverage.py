"""Testa a cobertura completa das ferramentas MCP e a inicialização STDIO em ambiente restrito no banco de teste."""

import asyncio
import json
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def _unpack(result):
    if result.isError:
        raise AssertionError(f"Ferramenta MCP retornou erro: {result.content}")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured)
    return json.loads(result.content[0].text)


def test_mcp_full_domain_coverage_and_codex_stdio_launcher():
    db_url = os.environ["DATABASE_URL"]
    assert make_url(db_url).database == "meu_financeiro_test", "Os testes devem usar exclusivamente meu_financeiro_test"

    async def _scenario():
        suffix = uuid4().hex[:8]
        today = date.today().isoformat()
        next_week = (date.today() + timedelta(days=7)).isoformat()

        # Simula exatamente o ambiente sanitizado do Codex Desktop (sem DBUS_SESSION_BUS_ADDRESS nem XDG_RUNTIME_DIR)
        stripped_env = {
            "HOME": os.environ["HOME"],
            "PATH": "/usr/bin:/bin",
            "DATABASE_URL": db_url,
        }
        params = StdioServerParameters(
            command=str(ROOT / "scripts/run-mcp.sh"),
            args=[],
            env=stripped_env,
        )

        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                init = await client.initialize()
                assert init.serverInfo.name == "Meu Financeiro"

                tools = await client.list_tools()
                names = {t.name for t in tools.tools}
                assert len(names) >= 85

                # 1. Contas financeiras
                acc1 = _unpack(await client.call_tool("finance_create_account", {
                    "name": f"Conta Principal {suffix}",
                    "kind": "checking",
                    "opening_balance": "2000.00",
                }))
                acc2 = _unpack(await client.call_tool("finance_create_account", {
                    "name": f"Conta Reserva {suffix}",
                    "kind": "savings",
                    "opening_balance": "500.00",
                }))
                assert acc1["balance"] == "2000.00"
                acc1_detail = _unpack(await client.call_tool("finance_get_account", {"account_id": acc1["id"]}))
                assert acc1_detail["name"] == f"Conta Principal {suffix}"

                acc2_updated = _unpack(await client.call_tool("finance_update_account", {
                    "account_id": acc2["id"],
                    "name": f"Reserva Atualizada {suffix}",
                }))
                assert acc2_updated["name"] == f"Reserva Atualizada {suffix}"
                assert acc2_updated["opening_balance"] == "500.00"

                assert (await client.call_tool("finance_archive_account", {
                    "account_id": acc2["id"],
                    "confirmed": False,
                })).isError
                archived_acc = _unpack(await client.call_tool("finance_archive_account", {
                    "account_id": acc2["id"],
                    "confirmed": True,
                }))
                assert archived_acc["is_active"] is False
                restored_acc = _unpack(await client.call_tool("finance_restore_account", {
                    "account_id": acc2["id"],
                    "confirmed": True,
                }))
                assert restored_acc["is_active"] is True

                # 2. Categorias e Orçamentos
                cat = _unpack(await client.call_tool("finance_create_category", {
                    "name": f"Alimentação {suffix}",
                    "kind": "expense",
                    "is_entertainment": False,
                    "icon": "utensils",
                    "color": "#326B50",
                    "budget_limit": "800.00",
                    "budget_period_type": "days",
                    "budget_interval_count": 14,
                    "budget_effective_start": today,
                }))
                assert cat["budget_limit"] == "800.00" and cat["budget_period_type"] == "days"

                cat_updated = _unpack(await client.call_tool("finance_update_category", {
                    "category_id": cat["id"],
                    "budget_limit": "900.00",
                }))
                assert cat_updated["budget_limit"] == "900.00"
                assert cat_updated["name"] == f"Alimentação {suffix}"

                cat_detail = _unpack(await client.call_tool("finance_get_category", {"category_id": cat["id"]}))
                assert cat_detail["id"] == cat["id"]

                cycle_preview = _unpack(await client.call_tool("finance_preview_budget_cycle", {
                    "effective_start": today,
                    "period_type": "weeks",
                    "interval_count": 2,
                }))
                assert cycle_preview["period_start"] == today

                cat_budget = _unpack(await client.call_tool("finance_get_category_budget", {
                    "category_id": cat["id"],
                    "as_of": today,
                }))
                assert cat_budget["active_cycle"]["limit"] == "900.00"

                # 3. Movimentações financeiras (pendente -> liquidada -> atualização parcial -> auditoria)
                pending_tx = _unpack(await client.call_tool("finance_create_transaction", {
                    "kind": "expense",
                    "amount": "45.00",
                    "account_id": acc1["id"],
                    "category_id": cat["id"],
                    "description": f"Almoço {suffix}",
                    "transaction_date": today,
                    "status": "pending",
                    "notes": "Nota inicial",
                    "idempotency_key": f"tx-pending-{suffix}",
                }))
                assert pending_tx["status"] == "pending"

                settled_tx = _unpack(await client.call_tool("finance_settle_transaction", {
                    "transaction_id": pending_tx["id"],
                    "settled_on": today,
                }))
                assert settled_tx["status"] == "settled" and settled_tx["version"] == 2

                # Atualização parcial informando apenas o novo valor!
                partial_corr = _unpack(await client.call_tool("finance_update_transaction", {
                    "transaction_id": pending_tx["id"],
                    "expected_version": 2,
                    "amount": "54.90",
                    "reason": "Correção parcial apenas do valor",
                    "idempotency_key": f"tx-corr-{suffix}",
                    "confirmed": True,
                }))
                assert partial_corr["amount"] == "54.90"
                assert partial_corr["description"] == f"Almoço {suffix}"
                assert partial_corr["category_id"] == cat["id"]

                revisions = _unpack(await client.call_tool("finance_get_transaction_revisions", {
                    "transaction_id": pending_tx["id"],
                }))
                assert len(revisions) == 1 and revisions[0]["after"]["amount"] == "54.90"

                searched_tx = _unpack(await client.call_tool("finance_list_transactions", {
                    "account_id": acc1["id"],
                    "kind": "expense",
                    "query": suffix,
                }))
                assert any(item["id"] == pending_tx["id"] for item in searched_tx)

                # 4. Transferências entre contas (criação, consulta, edição atômica)
                tr = _unpack(await client.call_tool("finance_create_transfer", {
                    "source_account_id": acc1["id"],
                    "destination_account_id": acc2["id"],
                    "amount": "150.00",
                    "transaction_date": today,
                    "description": f"Transferência {suffix}",
                    "idempotency_key": f"tr-{suffix}",
                }))
                tr_detail = _unpack(await client.call_tool("finance_get_transfer", {
                    "transaction_id": tr["outgoing_id"],
                }))
                assert tr_detail["amount"] == "150.00"

                tr_updated = _unpack(await client.call_tool("finance_update_transfer", {
                    "transaction_id": tr["outgoing_id"],
                    "expected_version": tr_detail["version"],
                    "amount": "175.00",
                    "reason": "Ajuste de valor transferido",
                    "idempotency_key": f"tr-upd-{suffix}",
                    "confirmed": True,
                }))
                assert tr_updated["amount"] == "175.00"
                transfers_list = _unpack(await client.call_tool("finance_list_transfers", {"account_id": acc1["id"]}))
                assert any(item["outgoing_id"] == tr["outgoing_id"] and item["amount"] == "175.00" for item in transfers_list)

                # 5. Cartões de crédito, compras, parcelas e faturas
                card = _unpack(await client.call_tool("finance_create_card", {
                    "name": f"Cartão Black {suffix}",
                    "closing_day": 10,
                    "due_day": 20,
                }))
                card_updated = _unpack(await client.call_tool("finance_update_card", {
                    "card_id": card["id"],
                    "closing_day": 12,
                }))
                assert card_updated["closing_day"] == 12

                purchase = _unpack(await client.call_tool("finance_create_card_purchase", {
                    "card_id": card["id"],
                    "category_id": cat["id"],
                    "total_amount": "120.00",
                    "installment_count": 2,
                    "purchase_date": today,
                    "merchant": f"Livraria {suffix}",
                    "idempotency_key": f"cp-{suffix}",
                }))
                installments = _unpack(await client.call_tool("finance_list_installments", {
                    "purchase_id": purchase["id"],
                    "unpaid_only": True,
                }))
                assert len(installments) == 2

                # Cartão com parcelas pendentes não pode ser arquivado
                assert (await client.call_tool("finance_archive_card", {
                    "card_id": card["id"],
                    "confirmed": True,
                })).isError

                invoice_id = installments[0]["invoice_id"]
                invoice_detail = _unpack(await client.call_tool("finance_get_invoice", {"invoice_id": invoice_id}))
                assert invoice_detail["total"] == "60.00" and len(invoice_detail["installments"]) == 1

                # 6. Contas a pagar e Planos recorrentes
                bill = _unpack(await client.call_tool("finance_create_bill", {
                    "description": f"Energia {suffix}",
                    "amount": "210.00",
                    "due_date": next_week,
                    "category_id": cat["id"],
                }))
                bill_updated = _unpack(await client.call_tool("finance_update_bill", {
                    "bill_id": bill["id"],
                    "amount": "225.00",
                }))
                assert bill_updated["amount"] == "225.00"
                bill_paid = _unpack(await client.call_tool("finance_pay_bill", {
                    "bill_id": bill["id"],
                    "source_account_id": acc1["id"],
                    "paid_date": today,
                    "idempotency_key": f"bill-pay-{suffix}",
                }))
                assert bill_paid["amount"] == "225.00"

                plan = _unpack(await client.call_tool("finance_create_recurring_plan", {
                    "description": f"Internet {suffix}",
                    "kind": "expense",
                    "amount": "99.90",
                    "account_id": acc1["id"],
                    "category_id": cat["id"],
                    "start_date": today,
                }))
                plan_updated = _unpack(await client.call_tool("finance_update_recurring_plan", {
                    "plan_id": plan["id"],
                    "amount": "109.90",
                }))
                assert plan_updated["amount"] == "109.90"
                realized = _unpack(await client.call_tool("finance_realize_recurring_plan", {
                    "plan_id": plan["id"],
                    "month": today,
                    "realized_on": today,
                }))
                assert realized["transaction_id"]
                deactivated = _unpack(await client.call_tool("finance_deactivate_recurring_plan", {
                    "plan_id": plan["id"],
                    "confirmed": True,
                }))
                assert deactivated["is_active"] is False
                activated = _unpack(await client.call_tool("finance_activate_recurring_plan", {
                    "plan_id": plan["id"],
                    "confirmed": True,
                }))
                assert activated["is_active"] is True

                # 7. Investimentos
                inv = _unpack(await client.call_tool("finance_create_investment", {
                    "name": f"Tesouro Selic {suffix}",
                    "kind": "renda_fixa",
                    "current_value": "500.00",
                    "valuation_date": today,
                    "institution": "Tesouro Direto",
                }))
                inv_updated = _unpack(await client.call_tool("finance_update_investment", {
                    "investment_id": inv["id"],
                    "notes": "Reserva de liquidez diária",
                }))
                assert inv_updated["id"] == inv["id"]
                _unpack(await client.call_tool("finance_create_investment_event", {
                    "investment_id": inv["id"],
                    "account_id": acc1["id"],
                    "kind": "contribution",
                    "amount": "100.00",
                    "event_date": today,
                    "idempotency_key": f"inv-ev-{suffix}",
                }))
                inv_events = _unpack(await client.call_tool("finance_list_investment_events", {
                    "investment_id": inv["id"],
                }))
                assert len(inv_events) == 1 and inv_events[0]["amount"] == "100.00"
                inv_vals = _unpack(await client.call_tool("finance_list_investment_valuations", {
                    "investment_id": inv["id"],
                }))
                assert len(inv_vals) >= 1
                inv_detail = _unpack(await client.call_tool("finance_get_investment", {"investment_id": inv["id"]}))
                assert inv_detail["current_value"] == "600.00"

                # 8. Metas financeiras
                goal = _unpack(await client.call_tool("finance_create_goal", {
                    "name": f"Viagem {suffix}",
                    "target_amount": "3000.00",
                    "allocated_amount": "100.00",
                    "tracking_mode": "selected",
                    "account_ids": [acc1["id"]],
                }))
                assert goal["allocated_amount"] == "100.00"
                goal_updated = _unpack(await client.call_tool("finance_update_goal", {
                    "goal_id": goal["id"],
                    "target_amount": "3500.00",
                    "allocated_amount": "150.00",
                }))
                assert goal_updated["target_amount"] == "3500.00" and goal_updated["allocated_amount"] == "150.00"
                _unpack(await client.call_tool("finance_add_goal_contribution", {
                    "goal_id": goal["id"],
                    "amount_delta": "250.00",
                    "contributed_on": today,
                    "note": "Primeiro aporte",
                }))
                contribs = _unpack(await client.call_tool("finance_list_goal_contributions", {"goal_id": goal["id"]}))
                allocs = _unpack(await client.call_tool("finance_list_goal_allocations", {"goal_id": goal["id"]}))
                assert len(contribs) == 1 and len(allocs) == 2

                # 9. Comparação de períodos e Calendário financeiro
                comparison = _unpack(await client.call_tool("finance_compare_periods", {
                    "start_a": (date.today() - timedelta(days=30)).isoformat(),
                    "end_a": (date.today() - timedelta(days=15)).isoformat(),
                    "start_b": (date.today() - timedelta(days=14)).isoformat(),
                    "end_b": today,
                }))
                assert "period_a" in comparison and "period_b" in comparison and "category_comparison" in comparison

                calendar = _unpack(await client.call_tool("finance_get_calendar", {
                    "start": today,
                    "end": next_week,
                }))
                assert "days" in calendar and Decimal(calendar["total_expenses"]) > 0

    asyncio.run(_scenario())
