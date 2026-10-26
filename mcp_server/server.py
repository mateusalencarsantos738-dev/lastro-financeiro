"""Servidor MCP STDIO; toda escrita usa os mesmos serviços de domínio da API."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.serialization import wire
from backend.app.domain import (
    account_balances, budget_status, create_investment_event,
    create_transaction, create_transfer, create_credit_purchase, invoice_status, pay_invoice,
    get_upcoming_bills, goals, entertainment_status,
    net_worth, overview, spend_by_category, set_budget, active_budget, monthly_comparison,
    update_transaction, record_investment_valuation, record_net_worth_snapshot,
    recurring_status, investment_summary, delete_transaction, restore_transaction, transaction_deletion_group,
    card_purchase_payload, update_card_purchase,
)
from backend.app.models import Account, BudgetRule, Category, CreditCard, CreditPurchase, Invoice, Investment, Installment, Transaction, NetWorthSnapshot

mcp = FastMCP("Meu Financeiro")
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
IDEMPOTENT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
CORRECTION_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=READ_ONLY)
def finance_get_overview(month: str | None = None) -> dict:
    """Resumo do mês: caixa, receitas, despesas, resultado e status dos orçamentos. Mês no formato AAAA-MM-DD."""
    period = date.fromisoformat(month) if month else date.today()
    with SessionLocal() as session:
        return wire(overview(session, period))


@mcp.tool(annotations=READ_ONLY)
def finance_get_balances() -> list[dict]:
    """Lista saldos realizados das contas ativas, sem incluir investimentos ou receitas previstas."""
    with SessionLocal() as session:
        return wire(account_balances(session))


@mcp.tool(annotations=READ_ONLY)
def finance_list_categories() -> list[dict]:
    """Lista categorias, IDs e configuração do limite ativo no dia atual."""
    with SessionLocal() as session:
        result = []
        for c in session.scalars(select(Category).where(Category.is_active.is_(True)).order_by(Category.name)):
            active = active_budget(session, c.id, date.today()) if c.kind == "expense" else None
            rule = active[3] if active else None
            future = session.scalar(select(BudgetRule).where(BudgetRule.category_id == c.id, BudgetRule.effective_start > date.today()).order_by(BudgetRule.effective_start).limit(1)) if c.kind == "expense" else None
            display = rule or (future if not active else None)
            result.append({"id": c.id, "name": c.name, "kind": c.kind, "is_entertainment": c.is_entertainment,
                           "icon": c.icon, "budget_limit": active[0] if active else future.limit_amount if future else None,
                           "budget_period_type": display.period_type if display else "calendar_month",
                           "budget_interval_count": display.interval_count if display else 1,
                           "budget_renewal_day": display.renewal_day if display else None,
                           "budget_effective_start": display.effective_start if display else None,
                           "budget_scheduled_start": future.effective_start if future else None,
                           "budget_next_renewal": active[2] if active else None})
        return wire(result)


@mcp.tool(annotations=READ_ONLY)
def finance_list_transactions(start: str | None = None, end: str | None = None, category_id: str | None = None, limit: int = 100) -> list[dict]:
    """Lista movimentações por data e categoria. Limite máximo de 500; datas no formato AAAA-MM-DD."""
    if not 1 <= limit <= 500: raise ValueError("limit deve ficar entre 1 e 500")
    with SessionLocal() as session:
        stmt = select(Transaction).where(Transaction.deleted_at.is_(None)).order_by(Transaction.transaction_date.desc()).limit(limit)
        if start: stmt = stmt.where(Transaction.transaction_date >= date.fromisoformat(start))
        if end: stmt = stmt.where(Transaction.transaction_date <= date.fromisoformat(end))
        if category_id: stmt = stmt.where(Transaction.category_id == UUID(category_id))
        return wire([{"id": t.id, "version": t.version, "kind": t.kind, "amount": t.amount, "description": t.description, "transaction_date": t.transaction_date, "competence_date": t.competence_date, "status": t.status, "category_id": t.category_id, "account_id": t.account_id} for t in session.scalars(stmt)])


@mcp.tool(annotations=READ_ONLY)
def finance_get_transaction(transaction_id: str) -> dict:
    """Consulta os detalhes de uma movimentação por ID, inclusive se está na lixeira."""
    with SessionLocal() as session:
        row = session.get(Transaction, UUID(transaction_id))
        if not row: raise ValueError("Movimentação não encontrada")
        return wire({"id": row.id, "version": row.version, "kind": row.kind, "amount": row.amount,
                     "description": row.description, "transaction_date": row.transaction_date,
                     "account_id": row.account_id, "category_id": row.category_id,
                     "status": row.status, "deleted_at": row.deleted_at})


@mcp.tool(annotations=READ_ONLY)
def finance_get_transaction_trash(limit: int = 100) -> list[dict]:
    """Lista movimentações removidas logicamente, recuperáveis pelo identificador estável; limite de 1 a 500."""
    if not 1 <= limit <= 500: raise ValueError("limit deve ficar entre 1 e 500")
    with SessionLocal() as session:
        rows = session.scalars(select(Transaction).where(Transaction.deleted_at.is_not(None)).order_by(Transaction.deleted_at.desc()).limit(limit)).all()
        return wire([{"id": row.id, "version": row.version, "kind": row.kind, "amount": row.amount,
                      "description": row.description, "transaction_date": row.transaction_date,
                      "account_id": row.account_id, "category_id": row.category_id,
                      "deleted_at": row.deleted_at} for row in rows])


@mcp.tool(annotations=READ_ONLY)
def finance_get_deletion_preview(transaction_id: str) -> dict:
    """Explica o efeito e informa se a exclusão reversível de uma movimentação é segura."""
    from fastapi import HTTPException
    with SessionLocal() as session:
        row = session.get(Transaction, UUID(transaction_id))
        if not row: raise ValueError("Movimentação não encontrada")
        try:
            group, bill, purchase = transaction_deletion_group(session, row)
            paid = bool(purchase and session.scalar(select(Installment.id).join(Invoice, Installment.invoice_id == Invoice.id)
                .where(Installment.purchase_id == purchase.id, Invoice.paid_date.is_not(None)).limit(1)))
            return wire({"can_delete": True, "affected_ids": [item.id for item in group],
                         "effect": "transferência completa" if len(group) == 2 else
                         "compra, parcelas e pagamento de fatura ajustado" if paid else
                         "compra e parcelas" if purchase else "pagamento de conta a pagar" if bill else "movimentação simples"})
        except HTTPException as error:
            return {"can_delete": False, "affected_ids": [], "effect": str(error.detail)}


@mcp.tool(annotations=CORRECTION_WRITE)
def finance_delete_transaction(transaction_id: str, expected_version: int, confirmed: bool) -> dict:
    """Envia uma movimentação à lixeira após confirmação explícita. Transferências próprias saem em par; operações perigosas são recusadas."""
    if not confirmed: raise ValueError("Confirme explicitamente a exclusão após consultar o impacto")
    with SessionLocal.begin() as session:
        rows = delete_transaction(session, UUID(transaction_id), expected_version)
        result = {"deleted_ids": [row.id for row in rows], "deleted_at": rows[0].deleted_at}
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
def finance_restore_transaction(transaction_id: str, confirmed: bool) -> dict:
    """Restaura uma operação da lixeira, sem criar outra transação nem duplicar valores; requer confirmação explícita."""
    if not confirmed: raise ValueError("Confirme explicitamente a restauração")
    with SessionLocal.begin() as session:
        rows = restore_transaction(session, UUID(transaction_id))
        result = {"restored_ids": [row.id for row in rows]}
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_create_transaction(kind: str, amount: str, account_id: str, description: str, transaction_date: str, idempotency_key: str, category_id: str | None = None, related_transaction_id: str | None = None) -> dict:
    """Registra receita, despesa ou reembolso. Despesa exige categoria e conta já cadastradas. Repetições precisam reutilizar a mesma chave."""
    if not idempotency_key.strip(): raise ValueError("idempotency_key é obrigatório")
    data = {"kind": kind, "amount": amount, "account_id": account_id, "category_id": category_id, "description": description, "transaction_date": transaction_date, "related_transaction_id": related_transaction_id, "status": "settled"}
    with SessionLocal.begin() as session:
        row = create_transaction(session, data, idempotency_key)
        result = {"id": row.id, "version": row.version, "kind": row.kind, "amount": row.amount, "category_id": row.category_id, "account_id": row.account_id, "description": row.description, "transaction_date": row.transaction_date, "status": row.status}
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
def finance_update_transaction(transaction_id: str, expected_version: int, amount: str, category_id: str | None,
                               description: str, transaction_date: str, reason: str,
                               idempotency_key: str, confirmed: bool) -> dict:
    """Corrige receita, despesa ou reembolso realizado; exige confirmação explícita, versão atual e motivo. Mantém revisão auditável. Compras no cartão e pagamentos vinculados não podem ser corrigidos por esta ferramenta."""
    if not confirmed: raise ValueError("Confirme explicitamente a correção antes de chamar a ferramenta")
    if not idempotency_key.strip(): raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        row = update_transaction(session, UUID(transaction_id), expected_version, Decimal(amount),
                                 UUID(category_id) if category_id else None, description,
                                 date.fromisoformat(transaction_date), reason, idempotency_key)
        result = {"id": row.id, "version": row.version, "kind": row.kind, "amount": row.amount,
                  "category_id": row.category_id, "account_id": row.account_id,
                  "description": row.description, "transaction_date": row.transaction_date, "status": row.status}
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_create_transfer(source_account_id: str, destination_account_id: str, amount: str, transaction_date: str, description: str, idempotency_key: str) -> dict:
    """Transfere entre duas contas próprias; não é receita nem despesa de consumo."""
    if not idempotency_key.strip(): raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        out, inc = create_transfer(session, UUID(source_account_id), UUID(destination_account_id), Decimal(amount), date.fromisoformat(transaction_date), description, idempotency_key)
        result = {"outgoing_id": out.id, "incoming_id": inc.id, "amount": out.amount, "description": description}
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
def finance_get_budget_status(month: str | None = None) -> list[dict]:
    """Consulta limites, gasto realizado e saldo restante por categoria no mês."""
    with SessionLocal() as session: return wire(budget_status(session, date.fromisoformat(month) if month else date.today()))


@mcp.tool(annotations=READ_ONLY)
def finance_get_entertainment(month: str | None = None) -> dict:
    """Consulta gasto, limite, histórico e projeção prudente de entretenimento. Mês opcional AAAA-MM-DD."""
    with SessionLocal() as session: return wire(entertainment_status(session, date.fromisoformat(month) if month else date.today()))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_set_budget(category_id: str, month: str, limit_amount: str, period_type: str = "calendar_month",
                       interval_count: int = 1, renewal_day: int | None = None,
                       effective_start: str | None = None) -> dict:
    """Configura limite renovável. month/effective_start: AAAA-MM-DD; period_type: calendar_month, monthly_day, days, weeks ou months. Para days/weeks/months, interval_count é livre de 1 a 120. Lançamentos acima do limite continuam permitidos."""
    with SessionLocal.begin() as session:
        row = set_budget(session, UUID(category_id), date.fromisoformat(effective_start or month), Decimal(limit_amount),
                         period_type, interval_count, renewal_day)
        category = session.get(Category, row.category_id)
        result = {"category_id": category.id, "category": category.name, "effective_start": row.effective_start,
                  "limit": row.limit_amount, "period_type": row.period_type, "interval_count": row.interval_count,
                  "renewal_day": row.renewal_day}
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
def finance_get_category_spending(start: str, end: str) -> list[dict]:
    """Soma despesas realizadas por competência e categoria no intervalo inclusivo."""
    with SessionLocal() as session: return wire(spend_by_category(session, date.fromisoformat(start), date.fromisoformat(end)))


@mcp.tool(annotations=READ_ONLY)
def finance_get_upcoming_bills(through: str) -> list[dict]:
    """Lista contas e faturas ainda abertas até a data informada; não inclui receitas previstas no caixa."""
    with SessionLocal() as session:
        bills = [{"kind": "bill", "id": b.id, "description": b.description, "amount": b.amount, "due_date": b.due_date} for b in get_upcoming_bills(session, date.fromisoformat(through))]
        invoices = [{"kind": "invoice", "id": i["id"], "description": f"Fatura {i['card']}", "amount": i["open_amount"], "due_date": i["due_date"]} for i in invoice_status(session, date.fromisoformat(through)) if i["open_amount"] > 0]
        return wire(sorted(bills + invoices, key=lambda row: row["due_date"]))


@mcp.tool(annotations=READ_ONLY)
def finance_get_recurring_plans(month: str | None = None) -> list[dict]:
    """Lista receitas e despesas previstas mensalmente e se cada ocorrência foi realizada; previsões não são caixa nem consumo."""
    with SessionLocal() as session:
        return wire(recurring_status(session, date.fromisoformat(month) if month else date.today()))


@mcp.tool(annotations=READ_ONLY)
def finance_get_cards() -> list[dict]:
    """Lista cartões cadastrados, seus IDs e dias de fechamento e vencimento."""
    with SessionLocal() as session:
        return wire([{"id": c.id, "name": session.get(Account, c.account_id).name, "closing_day": c.closing_day, "due_day": c.due_day} for c in session.scalars(select(CreditCard))])


@mcp.tool(annotations=READ_ONLY)
def finance_list_card_purchases(card_id: str | None = None, category_id: str | None = None,
                                start: str | None = None, end: str | None = None,
                                merchant: str | None = None, total_amount: str | None = None,
                                include_deleted: bool = False,
                                limit: int = 100) -> list[dict]:
    """Pesquisa compras manuais de cartão por cartão, categoria, data e descrição. Use IDs para distinguir compras parecidas antes de alterar ou excluir."""
    if not 1 <= limit <= 500: raise ValueError("limit deve ficar entre 1 e 500")
    with SessionLocal() as session:
        stmt = select(CreditPurchase).join(Transaction, CreditPurchase.transaction_id == Transaction.id)
        if not include_deleted: stmt = stmt.where(Transaction.deleted_at.is_(None))
        if card_id: stmt = stmt.where(CreditPurchase.card_id == UUID(card_id))
        if category_id: stmt = stmt.where(Transaction.category_id == UUID(category_id))
        if start: stmt = stmt.where(CreditPurchase.purchase_date >= date.fromisoformat(start))
        if end: stmt = stmt.where(CreditPurchase.purchase_date <= date.fromisoformat(end))
        if merchant: stmt = stmt.where(CreditPurchase.merchant.ilike(f"%{merchant}%"))
        if total_amount is not None: stmt = stmt.where(CreditPurchase.total_amount == Decimal(total_amount))
        return wire([card_purchase_payload(session, row) for row in session.scalars(stmt.order_by(CreditPurchase.purchase_date.desc()).limit(limit))])


@mcp.tool(annotations=READ_ONLY)
def finance_get_card_purchase(purchase_id: str) -> dict:
    """Consulta compra manual, versão atual, parcelas e IDs das faturas por ID."""
    with SessionLocal() as session:
        row = session.get(CreditPurchase, UUID(purchase_id))
        if not row: raise ValueError("Compra no cartão não encontrada")
        return wire(card_purchase_payload(session, row))


@mcp.tool(annotations=CORRECTION_WRITE)
def finance_update_card_purchase(purchase_id: str, expected_version: int,
                                 total_amount: str | None = None, merchant: str | None = None,
                                 category_id: str | None = None, purchase_date: str | None = None,
                                 card_id: str | None = None, installment_count: int | None = None) -> dict:
    """Corrige somente os campos informados de uma compra manual de cartão. Não exige justificativa. Consulte a compra antes para obter sua versão."""
    changes = {}
    if total_amount is not None: changes["total_amount"] = Decimal(total_amount)
    if merchant is not None: changes["merchant"] = merchant
    if category_id is not None: changes["category_id"] = UUID(category_id)
    if purchase_date is not None: changes["purchase_date"] = date.fromisoformat(purchase_date)
    if card_id is not None: changes["card_id"] = UUID(card_id)
    if installment_count is not None: changes["installment_count"] = installment_count
    with SessionLocal.begin() as session:
        row = update_card_purchase(session, UUID(purchase_id), expected_version, changes)
        result = card_purchase_payload(session, row)
        result["affected_invoices"] = sorted({item["invoice_id"] for item in result["installments"]})
        current = {item["id"]: item for item in invoice_status(session)}
        result["invoice_totals_after"] = [current.get(identifier, {"id": identifier, "total": Decimal("0"), "open_amount": Decimal("0")}) for identifier in result["affected_invoices"]]
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
def finance_delete_card_purchase(purchase_id: str, expected_version: int) -> dict:
    """Envia uma compra manual inteira à lixeira e ajusta parcelas e pagamentos vinculados em uma transação. Use após identificar uma única compra pelo ID."""
    with SessionLocal.begin() as session:
        purchase = session.get(CreditPurchase, UUID(purchase_id))
        if not purchase: raise ValueError("Compra no cartão não encontrada")
        tx = session.get(Transaction, purchase.transaction_id)
        if tx.deleted_at is not None: raise ValueError("Compra já está na lixeira")
        result = card_purchase_payload(session, purchase)
        delete_transaction(session, tx.id, expected_version)
        result["deleted_at"] = tx.deleted_at
        result["affected_invoices"] = sorted({item["invoice_id"] for item in result["installments"]})
        current = {item["id"]: item for item in invoice_status(session)}
        result["invoice_totals_after"] = [current.get(identifier, {"id": identifier, "total": Decimal("0"), "open_amount": Decimal("0")}) for identifier in result["affected_invoices"]]
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
def finance_restore_card_purchase(purchase_id: str) -> dict:
    """Restaura a mesma compra manual da lixeira, com parcelas e pagamento da fatura reconciliados, sem duplicar valores."""
    with SessionLocal.begin() as session:
        purchase = session.get(CreditPurchase, UUID(purchase_id))
        if not purchase: raise ValueError("Compra no cartão não encontrada")
        restore_transaction(session, purchase.transaction_id)
        result = card_purchase_payload(session, purchase)
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
def finance_get_invoices(through: str | None = None) -> list[dict]:
    """Lista faturas, valor total, saldo aberto e vencimento. Data opcional no formato AAAA-MM-DD."""
    with SessionLocal() as session: return wire(invoice_status(session, date.fromisoformat(through) if through else None))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_create_card_purchase(card_id: str, category_id: str, total_amount: str, installment_count: int, purchase_date: str, merchant: str, idempotency_key: str) -> dict:
    """Registra compra no cartão como consumo único e cria parcelas futuras exatas. Requer chave idempotente."""
    if not idempotency_key.strip(): raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        purchase = create_credit_purchase(session, UUID(card_id), UUID(category_id), Decimal(total_amount), installment_count, date.fromisoformat(purchase_date), merchant, idempotency_key)
        installments = session.scalars(select(Installment).where(Installment.purchase_id == purchase.id).order_by(Installment.sequence)).all()
        result = {"id": purchase.id, "transaction_id": purchase.transaction_id, "total_amount": purchase.total_amount, "installments": [{"sequence": i.sequence, "amount": i.amount, "due_date": i.due_date, "paid_date": i.paid_date} for i in installments]}
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_pay_invoice(invoice_id: str, source_account_id: str, paid_date: str, idempotency_key: str) -> dict:
    """Liquida uma fatura em uma transferência da conta de pagamento para o cartão; não cria nova despesa."""
    if not idempotency_key.strip(): raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        result = pay_invoice(session, UUID(invoice_id), UUID(source_account_id), date.fromisoformat(paid_date), idempotency_key)
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
def finance_get_investments() -> list[dict]:
    """Lista ativos e seus valores manuais, aportes, resgates, rendimentos e taxas registrados; diferença frente ao capital líquido não é rentabilidade percentual."""
    with SessionLocal() as session:
        return wire([investment_summary(session, row) for row in session.scalars(select(Investment).order_by(Investment.name))])


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_record_investment_valuation(investment_id: str, value: str, valuation_date: str, idempotency_key: str) -> dict:
    """Registra valor manual datado de um investimento e preserva o histórico; não busca preços externos."""
    if not idempotency_key.strip(): raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        row = record_investment_valuation(session, UUID(investment_id), Decimal(value),
                                          date.fromisoformat(valuation_date), idempotency_key)
        result = {"id": row.id, "investment_id": row.investment_id, "value": row.value,
                  "valuation_date": row.valuation_date}
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_create_investment_event(investment_id: str, account_id: str, kind: str, amount: str, event_date: str, idempotency_key: str) -> dict:
    """Registra aporte, resgate, rendimento ou taxa. Aporte/resgate são transferências de patrimônio, não consumo."""
    if not idempotency_key.strip(): raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        event = create_investment_event(session, UUID(investment_id), UUID(account_id), kind, Decimal(amount), date.fromisoformat(event_date), idempotency_key)
        result = {"id": event.id, "investment_id": event.investment_id, "kind": event.kind, "amount": event.amount, "event_date": event.event_date}
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
def finance_get_net_worth() -> dict:
    """Calcula caixa + valor atual informado dos investimentos − contas a pagar cadastradas."""
    with SessionLocal() as session: return wire(net_worth(session))


@mcp.tool(annotations=READ_ONLY)
def finance_get_net_worth_history() -> list[dict]:
    """Consulta fotografias patrimoniais registradas; dias sem fotografia não são interpolados."""
    with SessionLocal() as session:
        return wire([{"as_of_date": row.as_of_date, "cash": row.cash, "investments": row.investments,
                      "liabilities": row.liabilities, "net_worth": row.net_worth}
                     for row in session.scalars(select(NetWorthSnapshot).order_by(NetWorthSnapshot.as_of_date))])


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def finance_save_net_worth_snapshot() -> dict:
    """Salva ou atualiza a fotografia patrimonial de hoje, calculada com os registros atuais."""
    with SessionLocal.begin() as session:
        row = record_net_worth_snapshot(session)
        result = {"as_of_date": row.as_of_date, "cash": row.cash,
                  "investments": row.investments, "liabilities": row.liabilities,
                  "net_worth": row.net_worth}
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
def finance_get_monthly_comparison(months: int = 6) -> list[dict]:
    """Compara receitas, despesas líquidas e resultado por competência nos últimos 2 a 24 meses."""
    if not 2 <= months <= 24: raise ValueError("months deve ficar entre 2 e 24")
    with SessionLocal() as session: return wire(monthly_comparison(session, months))


@mcp.tool(annotations=READ_ONLY)
def finance_get_goals() -> list[dict]:
    """Lista metas e progresso informado sem somar alocações ao patrimônio uma segunda vez."""
    with SessionLocal() as session: return wire(goals(session))


if __name__ == "__main__":
    mcp.run(transport="stdio")
