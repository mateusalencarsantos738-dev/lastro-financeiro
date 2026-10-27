"""Servidor MCP STDIO; toda escrita usa os mesmos serviços de domínio da API."""

from calendar import monthrange
from datetime import date
from decimal import Decimal
from functools import wraps
from uuid import UUID

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.categories import archive_preview, archive_category, restore_category
from backend.app.serialization import wire
from backend.app.domain import (
    account_balances,
    archive_account_domain,
    archive_credit_card_domain,
    budget_status,
    calendar_summary_domain,
    card_purchase_payload,
    category_payload_domain,
    compare_periods_domain,
    create_account_domain,
    create_bill_domain,
    create_category_domain,
    create_credit_card,
    create_credit_purchase,
    create_goal_domain,
    create_investment_domain,
    create_investment_event,
    create_recurring_plan,
    create_transaction,
    create_transfer,
    delete_transaction,
    entertainment_status,
    get_account_domain,
    get_bill_domain,
    get_card_domain,
    get_category_budget_domain,
    get_category_domain,
    get_goal_domain,
    get_investment_domain,
    get_invoice_domain,
    get_transaction_lifecycle_domain,
    get_transaction_revisions_domain,
    get_transfer_domain,
    get_upcoming_bills,
    goals,
    investment_summary,
    invoice_status,
    list_accounts_domain,
    list_bills_domain,
    list_cards_domain,
    list_goal_allocations_domain,
    list_goal_contributions_domain,
    list_installments_domain,
    list_investment_events_domain,
    list_investment_valuations_domain,
    list_transfers_domain,
    monthly_comparison,
    net_worth,
    overview,
    pay_bill_domain,
    pay_invoice,
    preview_budget_cycle,
    realize_recurring_plan,
    record_investment_valuation,
    record_net_worth_snapshot,
    recurring_status,
    restore_account_domain,
    restore_credit_card_domain,
    restore_transaction,
    set_budget,
    set_recurring_plan_active_domain,
    settle_transaction_domain,
    spend_by_category,
    transaction_deletion_group,
    update_account_domain,
    update_bill_domain,
    update_card_purchase,
    update_category_domain,
    update_credit_card_domain,
    update_goal_domain,
    update_investment_domain,
    update_recurring_plan_domain,
    update_transaction,
    update_transfer_domain,
    add_goal_contribution_domain,
)
from backend.app.models import (
    Account,
    Category,
    CreditCard,
    CreditPurchase,
    Installment,
    Investment,
    Invoice,
    NetWorthSnapshot,
    Transaction,
)

mcp = FastMCP("Meu Financeiro")
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
IDEMPOTENT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
CORRECTION_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


def _uuid(value: str, label: str = "identificador") -> UUID:
    try:
        return UUID(str(value).strip())
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{label} inválido: {value}") from exc


def _date(value: str, label: str = "data") -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{label} inválida (use AAAA-MM-DD): {value}") from exc


def _domain_guard(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc
    return wrapper


# ============================================================================
# 1. VISÃO GERAL, SALDOS E CONTAS FINANCEIRAS
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_overview(month: str | None = None) -> dict:
    """Resumo do mês: caixa, receitas, despesas, resultado e status dos orçamentos. Mês no formato AAAA-MM-DD."""
    period = _date(month, "month") if month else date.today()
    with SessionLocal() as session:
        return wire(overview(session, period))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_balances() -> list[dict]:
    """Lista saldos realizados das contas ativas, sem incluir investimentos ou receitas previstas."""
    with SessionLocal() as session:
        return wire(account_balances(session))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_accounts(scope: str = "active") -> list[dict]:
    """Lista contas financeiras (scope=active, archived ou all) com tipo, saldo inicial, saldo atual realizado e status."""
    with SessionLocal() as session:
        return wire(list_accounts_domain(session, scope))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_account(account_id: str) -> dict:
    """Consulta detalhes de uma conta financeira por ID, incluindo saldo atual e contagem de movimentações."""
    with SessionLocal() as session:
        return wire(get_account_domain(session, _uuid(account_id, "account_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_account(name: str, kind: str = "checking", opening_balance: str = "0.00") -> dict:
    """Cria uma conta monetária (kind: checking, savings, cash ou investment) com saldo inicial opcional."""
    with SessionLocal.begin() as session:
        result = create_account_domain(session, name, kind, opening_balance)
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_account(
    account_id: str,
    name: str | None = None,
    kind: str | None = None,
    opening_balance: str | None = None,
) -> dict:
    """Atualiza nome, tipo ou saldo inicial de uma conta existente (atualização parcial suportada)."""
    with SessionLocal.begin() as session:
        result = update_account_domain(session, _uuid(account_id, "account_id"), name, kind, opening_balance)
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_archive_account(account_id: str, confirmed: bool = False) -> dict:
    """Arquiva (inativa) uma conta sem apagar seu histórico de movimentações. Exige confirmed=True."""
    if not confirmed:
        raise ValueError("Confirme o arquivamento da conta (confirmed=True)")
    with SessionLocal.begin() as session:
        result = archive_account_domain(session, _uuid(account_id, "account_id"))
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_restore_account(account_id: str, confirmed: bool = False) -> dict:
    """Reativa uma conta arquivada preservando todo o histórico. Exige confirmed=True."""
    if not confirmed:
        raise ValueError("Confirme a restauração da conta (confirmed=True)")
    with SessionLocal.begin() as session:
        result = restore_account_domain(session, _uuid(account_id, "account_id"))
    return wire(result)


# ============================================================================
# 2. CATEGORIAS
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_categories(scope: str = "active") -> list[dict]:
    """Lista categorias ativas, arquivadas ou todas (scope=active, archived, all), com cor, ícone, estado e ciclo de orçamento."""
    if scope not in ("active", "archived", "all"):
        raise ValueError("scope deve ser active, archived ou all")
    with SessionLocal() as session:
        stmt = select(Category).order_by(Category.name)
        if scope != "all":
            stmt = stmt.where(Category.is_active.is_(scope == "active"))
        return wire([category_payload_domain(session, c) for c in session.scalars(stmt)])


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_category(category_id: str) -> dict:
    """Consulta detalhes completos de uma categoria por ID, incluindo orçamento vigente e gastos no ciclo atual."""
    with SessionLocal() as session:
        return wire(get_category_domain(session, _uuid(category_id, "category_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_category(
    name: str,
    kind: str = "expense",
    is_entertainment: bool = False,
    icon: str | None = None,
    color: str | None = None,
    budget_limit: str | None = None,
    budget_period_type: str = "calendar_month",
    budget_interval_count: int = 1,
    budget_renewal_day: int | None = None,
    budget_effective_start: str | None = None,
) -> dict:
    """Cria uma categoria de receita (income) ou despesa (expense), com cor, ícone e limite opcional configurável."""
    eff_start = _date(budget_effective_start, "budget_effective_start") if budget_effective_start else None
    with SessionLocal.begin() as session:
        result = create_category_domain(
            session,
            name=name,
            kind=kind,
            is_entertainment=is_entertainment,
            icon=icon,
            color=color,
            budget_limit=budget_limit,
            budget_period_type=budget_period_type,
            budget_interval_count=budget_interval_count,
            budget_renewal_day=budget_renewal_day,
            budget_effective_start=eff_start,
        )
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_category(
    category_id: str,
    name: str | None = None,
    kind: str | None = None,
    is_entertainment: bool | None = None,
    icon: str | None = None,
    color: str | None = None,
    budget_limit: str | None = None,
    budget_period_type: str | None = None,
    budget_interval_count: int | None = None,
    budget_renewal_day: int | None = None,
    budget_effective_start: str | None = None,
) -> dict:
    """Atualiza parcialmente uma categoria ativa (nome, cor, ícone, flag de entretenimento e/ou regra de orçamento)."""
    eff_start = _date(budget_effective_start, "budget_effective_start") if budget_effective_start else None
    with SessionLocal.begin() as session:
        result = update_category_domain(
            session,
            category_id=_uuid(category_id, "category_id"),
            name=name,
            kind=kind,
            is_entertainment=is_entertainment,
            icon=icon,
            color=color,
            budget_limit=budget_limit,
            budget_period_type=budget_period_type,
            budget_interval_count=budget_interval_count,
            budget_renewal_day=budget_renewal_day,
            budget_effective_start=eff_start,
        )
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_preview_category_archive(category_id: str) -> dict:
    """Mostra gastos e data de saída dos indicadores antes de arquivar; não modifica dados."""
    with SessionLocal() as session:
        category = session.get(Category, _uuid(category_id, "category_id"))
        if not category:
            raise ValueError("Categoria não encontrada")
        return wire(archive_preview(session, category, date.today()))


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_archive_category(category_id: str, confirmed: bool) -> dict:
    """Arquiva uma categoria sem apagar gastos, orçamento ou vínculos; consulte a prévia e confirme."""
    if not confirmed:
        raise ValueError("Confirme o arquivamento após consultar a prévia")
    with SessionLocal.begin() as session:
        result = archive_category(session, _uuid(category_id, "category_id"), date.today())
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_restore_category(category_id: str, confirmed: bool) -> dict:
    """Restaura o mesmo registro e ID; preserva cor, ícone, histórico e ciclos de orçamento."""
    if not confirmed:
        raise ValueError("Confirme a restauração")
    with SessionLocal.begin() as session:
        category = restore_category(session, _uuid(category_id, "category_id"))
        result = category_payload_domain(session, category)
    return wire(result)


# ============================================================================
# 3. MOVIMENTAÇÕES FINANCEIRAS (RECEITAS, DESPESAS, REEMBOLSOS, LIXEIRA)
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_transactions(
    start: str | None = None,
    end: str | None = None,
    category_id: str | None = None,
    limit: int = 100,
    account_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    query: str | None = None,
) -> list[dict]:
    """Lista movimentações ativas com filtros por data, categoria, conta, tipo (kind), status e texto (query). Limite máximo 500."""
    if not 1 <= limit <= 500:
        raise ValueError("limit deve ficar entre 1 e 500")
    with SessionLocal() as session:
        stmt = (
            select(Transaction)
            .where(Transaction.deleted_at.is_(None))
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .limit(limit)
        )
        if start:
            stmt = stmt.where(Transaction.transaction_date >= _date(start, "start"))
        if end:
            stmt = stmt.where(Transaction.transaction_date <= _date(end, "end"))
        if category_id:
            stmt = stmt.where(Transaction.category_id == _uuid(category_id, "category_id"))
        if account_id:
            stmt = stmt.where(Transaction.account_id == _uuid(account_id, "account_id"))
        if kind:
            stmt = stmt.where(Transaction.kind == kind)
        if status:
            stmt = stmt.where(Transaction.status == status)
        if query:
            stmt = stmt.where(Transaction.description.ilike(f"%{query.strip()}%"))
        return wire([
            {
                "id": t.id,
                "version": t.version,
                "kind": t.kind,
                "amount": t.amount,
                "description": t.description,
                "transaction_date": t.transaction_date,
                "competence_date": t.competence_date,
                "settled_date": t.settled_date,
                "status": t.status,
                "category_id": t.category_id,
                "account_id": t.account_id,
                "notes": t.notes,
                "related_id": t.related_id,
            }
            for t in session.scalars(stmt)
        ])


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_transaction(transaction_id: str) -> dict:
    """Consulta os detalhes de uma movimentação por ID, inclusive se está na lixeira."""
    with SessionLocal() as session:
        row = session.get(Transaction, _uuid(transaction_id, "transaction_id"))
        if not row:
            raise ValueError("Movimentação não encontrada")
        return wire({
            "id": row.id,
            "version": row.version,
            "kind": row.kind,
            "amount": row.amount,
            "description": row.description,
            "transaction_date": row.transaction_date,
            "competence_date": row.competence_date,
            "settled_date": row.settled_date,
            "account_id": row.account_id,
            "category_id": row.category_id,
            "status": row.status,
            "notes": row.notes,
            "related_id": row.related_id,
            "deleted_at": row.deleted_at,
        })


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_transaction_trash(limit: int = 100) -> list[dict]:
    """Lista movimentações removidas logicamente, recuperáveis pelo identificador estável; limite de 1 a 500."""
    if not 1 <= limit <= 500:
        raise ValueError("limit deve ficar entre 1 e 500")
    with SessionLocal() as session:
        rows = session.scalars(
            select(Transaction)
            .where(Transaction.deleted_at.is_not(None))
            .order_by(Transaction.deleted_at.desc())
            .limit(limit)
        ).all()
        return wire([
            {
                "id": row.id,
                "version": row.version,
                "kind": row.kind,
                "amount": row.amount,
                "description": row.description,
                "transaction_date": row.transaction_date,
                "account_id": row.account_id,
                "category_id": row.category_id,
                "deleted_at": row.deleted_at,
            }
            for row in rows
        ])


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_deletion_preview(transaction_id: str) -> dict:
    """Explica o efeito e informa se a exclusão reversível de uma movimentação é segura."""
    with SessionLocal() as session:
        row = session.get(Transaction, _uuid(transaction_id, "transaction_id"))
        if not row:
            raise ValueError("Movimentação não encontrada")
        try:
            group, bill, purchase = transaction_deletion_group(session, row)
            paid = bool(
                purchase
                and session.scalar(
                    select(Installment.id)
                    .join(Invoice, Installment.invoice_id == Invoice.id)
                    .where(Installment.purchase_id == purchase.id, Invoice.paid_date.is_not(None))
                    .limit(1)
                )
            )
            return wire({
                "can_delete": True,
                "affected_ids": [item.id for item in group],
                "effect": (
                    "transferência completa"
                    if len(group) == 2
                    else "compra, parcelas e pagamento de fatura ajustado"
                    if paid
                    else "compra e parcelas"
                    if purchase
                    else "pagamento de conta a pagar"
                    if bill
                    else "movimentação simples"
                ),
            })
        except HTTPException as error:
            return {"can_delete": False, "affected_ids": [], "effect": str(error.detail)}


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_delete_transaction(transaction_id: str, expected_version: int, confirmed: bool) -> dict:
    """Envia uma movimentação à lixeira após confirmação explícita. Transferências próprias saem em par; operações perigosas são recusadas."""
    if not confirmed:
        raise ValueError("Confirme explicitamente a exclusão após consultar o impacto")
    with SessionLocal.begin() as session:
        rows = delete_transaction(session, _uuid(transaction_id, "transaction_id"), expected_version)
        result = {"deleted_ids": [row.id for row in rows], "deleted_at": rows[0].deleted_at}
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_restore_transaction(transaction_id: str, confirmed: bool) -> dict:
    """Restaura uma operação da lixeira, sem criar outra transação nem duplicar valores; requer confirmação explícita."""
    if not confirmed:
        raise ValueError("Confirme explicitamente a restauração")
    with SessionLocal.begin() as session:
        rows = restore_transaction(session, _uuid(transaction_id, "transaction_id"))
        result = {"restored_ids": [row.id for row in rows]}
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_transaction(
    kind: str,
    amount: str,
    account_id: str,
    description: str,
    transaction_date: str,
    idempotency_key: str,
    category_id: str | None = None,
    related_transaction_id: str | None = None,
    status: str = "settled",
    notes: str | None = None,
) -> dict:
    """Registra receita (income), despesa (expense) ou reembolso (refund). Despesa exige categoria e conta ativa. Repetições devem reutilizar idempotency_key."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    data = {
        "kind": kind,
        "amount": amount,
        "account_id": account_id,
        "category_id": category_id,
        "description": description,
        "transaction_date": transaction_date,
        "related_transaction_id": related_transaction_id,
        "status": status,
        "notes": notes,
    }
    with SessionLocal.begin() as session:
        row = create_transaction(session, data, idempotency_key)
        result = {
            "id": row.id,
            "version": row.version,
            "kind": row.kind,
            "amount": row.amount,
            "category_id": row.category_id,
            "account_id": row.account_id,
            "description": row.description,
            "transaction_date": row.transaction_date,
            "status": row.status,
            "notes": row.notes,
        }
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_transaction(
    transaction_id: str,
    expected_version: int,
    reason: str,
    idempotency_key: str,
    confirmed: bool,
    amount: str | None = None,
    category_id: str | None = None,
    description: str | None = None,
    transaction_date: str | None = None,
    account_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """Corrige receita, despesa ou reembolso realizado (suporta atualização parcial dos campos informados); exige confirmação explícita, versão atual e motivo."""
    if not confirmed:
        raise ValueError("Confirme explicitamente a correção antes de chamar a ferramenta")
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        row = update_transaction(
            session,
            _uuid(transaction_id, "transaction_id"),
            expected_version,
            Decimal(amount) if amount is not None else None,
            _uuid(category_id, "category_id") if category_id else None,
            description,
            _date(transaction_date, "transaction_date") if transaction_date else None,
            reason,
            idempotency_key,
            preserve_category_if_none=(category_id is None),
            account_id=_uuid(account_id, "account_id") if account_id else None,
            notes=notes,
        )
        result = {
            "id": row.id,
            "version": row.version,
            "kind": row.kind,
            "amount": row.amount,
            "category_id": row.category_id,
            "account_id": row.account_id,
            "description": row.description,
            "transaction_date": row.transaction_date,
            "status": row.status,
            "notes": row.notes,
        }
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_settle_transaction(transaction_id: str, settled_on: str | None = None) -> dict:
    """Liquida (marca como settled) uma movimentação pendente na data informada (ou hoje)."""
    with SessionLocal.begin() as session:
        result = settle_transaction_domain(
            session,
            _uuid(transaction_id, "transaction_id"),
            _date(settled_on, "settled_on") if settled_on else None,
        )
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_transaction_revisions(transaction_id: str) -> list[dict]:
    """Consulta o histórico de revisões auditáveis (antes/depois e motivo) de uma movimentação."""
    with SessionLocal() as session:
        return wire(get_transaction_revisions_domain(session, _uuid(transaction_id, "transaction_id")))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_transaction_lifecycle(transaction_id: str) -> list[dict]:
    """Consulta os eventos de ciclo de vida (envio à lixeira e restauração) de uma movimentação."""
    with SessionLocal() as session:
        return wire(get_transaction_lifecycle_domain(session, _uuid(transaction_id, "transaction_id")))


# ============================================================================
# 4. TRANSFERÊNCIAS ENTRE CONTAS
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_transfers(
    start: str | None = None,
    end: str | None = None,
    account_id: str | None = None,
    include_invoice_payments: bool = False,
    limit: int = 100,
) -> list[dict]:
    """Lista transferências entre contas pareadas (saída e entrada), filtráveis por período e conta."""
    with SessionLocal() as session:
        return wire(list_transfers_domain(
            session,
            start=_date(start, "start") if start else None,
            end=_date(end, "end") if end else None,
            account_id=_uuid(account_id, "account_id") if account_id else None,
            include_invoice_payments=include_invoice_payments,
            limit=limit,
        ))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_transfer(transaction_id: str) -> dict:
    """Consulta uma transferência entre contas a partir do ID de qualquer uma das pontas (outgoing_id ou incoming_id)."""
    with SessionLocal() as session:
        return wire(get_transfer_domain(session, _uuid(transaction_id, "transaction_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_transfer(
    source_account_id: str,
    destination_account_id: str,
    amount: str,
    transaction_date: str,
    description: str,
    idempotency_key: str,
) -> dict:
    """Transfere entre duas contas próprias; não é receita nem despesa de consumo."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        out, inc = create_transfer(
            session,
            _uuid(source_account_id, "source_account_id"),
            _uuid(destination_account_id, "destination_account_id"),
            Decimal(amount),
            _date(transaction_date, "transaction_date"),
            description,
            idempotency_key,
        )
        result = {"outgoing_id": out.id, "incoming_id": inc.id, "amount": out.amount, "description": description}
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_transfer(
    transaction_id: str,
    expected_version: int,
    reason: str,
    idempotency_key: str,
    confirmed: bool,
    amount: str | None = None,
    source_account_id: str | None = None,
    destination_account_id: str | None = None,
    transaction_date: str | None = None,
    description: str | None = None,
) -> dict:
    """Corrige ambas as pontas de uma transferência entre contas próprias de forma atômica, registrando revisão auditável."""
    if not confirmed:
        raise ValueError("Confirme explicitamente a correção da transferência (confirmed=True)")
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        result = update_transfer_domain(
            session,
            transaction_id=_uuid(transaction_id, "transaction_id"),
            expected_version=expected_version,
            amount=Decimal(amount) if amount is not None else None,
            source_account_id=_uuid(source_account_id, "source_account_id") if source_account_id else None,
            destination_account_id=_uuid(destination_account_id, "destination_account_id") if destination_account_id else None,
            transaction_date=_date(transaction_date, "transaction_date") if transaction_date else None,
            description=description,
            reason=reason,
            key=idempotency_key,
        )
    return wire(result)


# ============================================================================
# 5. ORÇAMENTOS, CICLOS RENOVÁVEIS E ENTRETENIMENTO
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_budget_status(month: str | None = None) -> list[dict]:
    """Consulta o ciclo do limite que contém a data informada em month (AAAA-MM-DD), ou hoje. Retorna periodicidade, início, fim, próxima renovação, gasto e restante."""
    with SessionLocal() as session:
        return wire(budget_status(session, _date(month, "month") if month else date.today()))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_category_budget(category_id: str, as_of: str | None = None) -> dict:
    """Consulta o orçamento de uma categoria específica (ciclo vigente, valor gasto, saldo restante e histórico de regras)."""
    with SessionLocal() as session:
        return wire(get_category_budget_domain(
            session,
            _uuid(category_id, "category_id"),
            _date(as_of, "as_of") if as_of else None,
        ))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_preview_budget_cycle(
    effective_start: str,
    period_type: str = "calendar_month",
    interval_count: int = 1,
    renewal_day: int | None = None,
) -> dict:
    """Simula as datas de início, fim e próxima renovação de um ciclo de orçamento antes de salvá-lo."""
    return wire(preview_budget_cycle(_date(effective_start, "effective_start"), period_type, interval_count, renewal_day))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_set_budget(
    category_id: str,
    limit_amount: str,
    month: str | None = None,
    period_type: str = "calendar_month",
    interval_count: int = 1,
    renewal_day: int | None = None,
    effective_start: str | None = None,
) -> dict:
    """Configura limite renovável. month/effective_start: AAAA-MM-DD; period_type: calendar_month, monthly_day, days, weeks ou months. Para days/weeks/months, interval_count é livre de 1 a 120. Lançamentos acima do limite continuam permitidos."""
    start_date = _date(effective_start or month, "effective_start") if (effective_start or month) else date.today()
    with SessionLocal.begin() as session:
        row = set_budget(
            session,
            _uuid(category_id, "category_id"),
            start_date,
            Decimal(limit_amount),
            period_type,
            interval_count,
            renewal_day,
        )
        category = session.get(Category, row.category_id)
        result = {
            "category_id": category.id,
            "category": category.name,
            "effective_start": row.effective_start,
            "limit": row.limit_amount,
            "period_type": row.period_type,
            "interval_count": row.interval_count,
            "renewal_day": row.renewal_day,
        }
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_entertainment(month: str | None = None) -> dict:
    """Consulta gasto, limite, histórico e projeção prudente de entretenimento. Mês opcional AAAA-MM-DD."""
    with SessionLocal() as session:
        return wire(entertainment_status(session, _date(month, "month") if month else date.today()))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_category_spending(start: str, end: str) -> list[dict]:
    """Soma despesas realizadas pela data financeira e categoria no intervalo inclusivo, independentemente do ciclo do limite."""
    with SessionLocal() as session:
        return wire(spend_by_category(session, _date(start, "start"), _date(end, "end")))


# ============================================================================
# 6. CARTÕES DE CRÉDITO, COMPRAS PARCELADAS, PARCELAS E FATURAS
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_cards(scope: str = "active") -> list[dict]:
    """Lista cartões cadastrados (scope=active, archived ou all), seus IDs, dias de fechamento e vencimento e passivo em aberto."""
    with SessionLocal() as session:
        return wire(list_cards_domain(session, scope))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_card(card_id: str) -> dict:
    """Consulta detalhes de um cartão de crédito por ID, incluindo passivo aberto e faturas associadas."""
    with SessionLocal() as session:
        return wire(get_card_domain(session, _uuid(card_id, "card_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_card(name: str, closing_day: int, due_day: int) -> dict:
    """Cadastra um novo cartão de crédito com dia de fechamento e dia de vencimento (1 a 31)."""
    with SessionLocal.begin() as session:
        card = create_credit_card(session, name, closing_day, due_day)
        result = get_card_domain(session, card.id)
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_card(
    card_id: str,
    name: str | None = None,
    closing_day: int | None = None,
    due_day: int | None = None,
) -> dict:
    """Atualiza nome, dia de fechamento e/ou dia de vencimento de um cartão de crédito."""
    with SessionLocal.begin() as session:
        result = update_credit_card_domain(session, _uuid(card_id, "card_id"), name, closing_day, due_day)
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_archive_card(card_id: str, confirmed: bool = False) -> dict:
    """Arquiva um cartão de crédito sem parcelas pendentes, preservando o histórico. Exige confirmed=True."""
    if not confirmed:
        raise ValueError("Confirme o arquivamento do cartão (confirmed=True)")
    with SessionLocal.begin() as session:
        result = archive_credit_card_domain(session, _uuid(card_id, "card_id"))
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_restore_card(card_id: str, confirmed: bool = False) -> dict:
    """Reativa um cartão de crédito arquivado. Exige confirmed=True."""
    if not confirmed:
        raise ValueError("Confirme a restauração do cartão (confirmed=True)")
    with SessionLocal.begin() as session:
        result = restore_credit_card_domain(session, _uuid(card_id, "card_id"))
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_card_purchases(
    card_id: str | None = None,
    category_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    merchant: str | None = None,
    total_amount: str | None = None,
    include_deleted: bool = False,
    limit: int = 100,
) -> list[dict]:
    """Pesquisa compras manuais de cartão por cartão, categoria, data e descrição. Use IDs para distinguir compras parecidas antes de alterar ou excluir."""
    if not 1 <= limit <= 500:
        raise ValueError("limit deve ficar entre 1 e 500")
    with SessionLocal() as session:
        stmt = select(CreditPurchase).join(Transaction, CreditPurchase.transaction_id == Transaction.id)
        if not include_deleted:
            stmt = stmt.where(Transaction.deleted_at.is_(None))
        if card_id:
            stmt = stmt.where(CreditPurchase.card_id == _uuid(card_id, "card_id"))
        if category_id:
            stmt = stmt.where(Transaction.category_id == _uuid(category_id, "category_id"))
        if start:
            stmt = stmt.where(CreditPurchase.purchase_date >= _date(start, "start"))
        if end:
            stmt = stmt.where(CreditPurchase.purchase_date <= _date(end, "end"))
        if merchant:
            stmt = stmt.where(CreditPurchase.merchant.ilike(f"%{merchant}%"))
        if total_amount is not None:
            stmt = stmt.where(CreditPurchase.total_amount == Decimal(total_amount))
        return wire([
            card_purchase_payload(session, row)
            for row in session.scalars(stmt.order_by(CreditPurchase.purchase_date.desc()).limit(limit))
        ])


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_card_purchase(purchase_id: str) -> dict:
    """Consulta compra manual, versão atual, parcelas e IDs das faturas por ID."""
    with SessionLocal() as session:
        row = session.get(CreditPurchase, _uuid(purchase_id, "purchase_id"))
        if not row:
            raise ValueError("Compra no cartão não encontrada")
        return wire(card_purchase_payload(session, row))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_card_purchase(
    card_id: str,
    category_id: str,
    total_amount: str,
    installment_count: int,
    purchase_date: str,
    merchant: str,
    idempotency_key: str,
) -> dict:
    """Registra compra no cartão como consumo único e cria parcelas futuras exatas. Requer chave idempotente."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        purchase = create_credit_purchase(
            session,
            _uuid(card_id, "card_id"),
            _uuid(category_id, "category_id"),
            Decimal(total_amount),
            installment_count,
            _date(purchase_date, "purchase_date"),
            merchant,
            idempotency_key,
        )
        installments = session.scalars(
            select(Installment).where(Installment.purchase_id == purchase.id).order_by(Installment.sequence)
        ).all()
        result = {
            "id": purchase.id,
            "transaction_id": purchase.transaction_id,
            "total_amount": purchase.total_amount,
            "installments": [
                {"sequence": i.sequence, "amount": i.amount, "due_date": i.due_date, "paid_date": i.paid_date}
                for i in installments
            ],
        }
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_card_purchase(
    purchase_id: str,
    expected_version: int,
    total_amount: str | None = None,
    merchant: str | None = None,
    category_id: str | None = None,
    purchase_date: str | None = None,
    card_id: str | None = None,
    installment_count: int | None = None,
) -> dict:
    """Corrige somente os campos informados de uma compra manual de cartão. Não exige justificativa. Consulte a compra antes para obter sua versão."""
    changes = {}
    if total_amount is not None:
        changes["total_amount"] = Decimal(total_amount)
    if merchant is not None:
        changes["merchant"] = merchant
    if category_id is not None:
        changes["category_id"] = _uuid(category_id, "category_id")
    if purchase_date is not None:
        changes["purchase_date"] = _date(purchase_date, "purchase_date")
    if card_id is not None:
        changes["card_id"] = _uuid(card_id, "card_id")
    if installment_count is not None:
        changes["installment_count"] = installment_count
    with SessionLocal.begin() as session:
        row = update_card_purchase(session, _uuid(purchase_id, "purchase_id"), expected_version, changes)
        result = card_purchase_payload(session, row)
        result["affected_invoices"] = sorted({item["invoice_id"] for item in result["installments"]})
        current = {item["id"]: item for item in invoice_status(session)}
        result["invoice_totals_after"] = [
            current.get(identifier, {"id": identifier, "total": Decimal("0"), "open_amount": Decimal("0")})
            for identifier in result["affected_invoices"]
        ]
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_delete_card_purchase(purchase_id: str, expected_version: int) -> dict:
    """Envia uma compra manual inteira à lixeira e ajusta parcelas e pagamentos vinculados em uma transação. Use após identificar uma única compra pelo ID."""
    with SessionLocal.begin() as session:
        purchase = session.get(CreditPurchase, _uuid(purchase_id, "purchase_id"))
        if not purchase:
            raise ValueError("Compra no cartão não encontrada")
        tx = session.get(Transaction, purchase.transaction_id)
        if tx.deleted_at is not None:
            raise ValueError("Compra já está na lixeira")
        result = card_purchase_payload(session, purchase)
        delete_transaction(session, tx.id, expected_version)
        result["deleted_at"] = tx.deleted_at
        result["affected_invoices"] = sorted({item["invoice_id"] for item in result["installments"]})
        current = {item["id"]: item for item in invoice_status(session)}
        result["invoice_totals_after"] = [
            current.get(identifier, {"id": identifier, "total": Decimal("0"), "open_amount": Decimal("0")})
            for identifier in result["affected_invoices"]
        ]
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_restore_card_purchase(purchase_id: str) -> dict:
    """Restaura a mesma compra manual da lixeira, com parcelas e pagamento da fatura reconciliados, sem duplicar valores."""
    with SessionLocal.begin() as session:
        purchase = session.get(CreditPurchase, _uuid(purchase_id, "purchase_id"))
        if not purchase:
            raise ValueError("Compra no cartão não encontrada")
        restore_transaction(session, purchase.transaction_id)
        result = card_purchase_payload(session, purchase)
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_invoices(
    through: str | None = None,
    card_id: str | None = None,
    unpaid_only: bool = False,
) -> list[dict]:
    """Lista faturas, valor total, saldo aberto e vencimento. Filtros opcionais: through (AAAA-MM-DD), card_id e unpaid_only."""
    with SessionLocal() as session:
        return wire(invoice_status(
            session,
            through=_date(through, "through") if through else None,
            card_id=_uuid(card_id, "card_id") if card_id else None,
            unpaid_only=unpaid_only,
        ))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_invoice(invoice_id: str) -> dict:
    """Consulta detalhes de uma fatura específica por ID, incluindo todas as parcelas e compras vinculadas."""
    with SessionLocal() as session:
        return wire(get_invoice_domain(session, _uuid(invoice_id, "invoice_id")))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_installments(
    card_id: str | None = None,
    invoice_id: str | None = None,
    purchase_id: str | None = None,
    unpaid_only: bool = False,
    through: str | None = None,
) -> list[dict]:
    """Lista parcelas de cartão de crédito filtradas por cartão, fatura, compra, status de pagamento e data limite."""
    with SessionLocal() as session:
        return wire(list_installments_domain(
            session,
            card_id=_uuid(card_id, "card_id") if card_id else None,
            invoice_id=_uuid(invoice_id, "invoice_id") if invoice_id else None,
            purchase_id=_uuid(purchase_id, "purchase_id") if purchase_id else None,
            unpaid_only=unpaid_only,
            through=_date(through, "through") if through else None,
        ))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_pay_invoice(invoice_id: str, source_account_id: str, paid_date: str, idempotency_key: str) -> dict:
    """Liquida uma fatura em uma transferência da conta de pagamento para o cartão; não cria nova despesa."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        result = pay_invoice(
            session,
            _uuid(invoice_id, "invoice_id"),
            _uuid(source_account_id, "source_account_id"),
            _date(paid_date, "paid_date"),
            idempotency_key,
        )
    return wire(result)


# ============================================================================
# 7. CONTAS A PAGAR E OBRIGAÇÕES FUTURAS
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_upcoming_bills(through: str | None = None) -> list[dict]:
    """Lista contas e faturas ainda abertas até a data informada (ou fim do mês atual); não inclui receitas previstas no caixa."""
    today = date.today()
    limit_date = _date(through, "through") if through else today.replace(day=monthrange(today.year, today.month)[1])
    with SessionLocal() as session:
        bills = [
            {"kind": "bill", "id": b.id, "description": b.description, "amount": b.amount, "due_date": b.due_date, "category_id": b.category_id}
            for b in get_upcoming_bills(session, limit_date)
        ]
        invoices = [
            {"kind": "invoice", "id": i["id"], "description": f"Fatura {i['card']}", "amount": i["open_amount"], "due_date": i["due_date"], "card_id": i["card_id"]}
            for i in invoice_status(session, limit_date)
            if i["open_amount"] > 0
        ]
        return wire(sorted(bills + invoices, key=lambda row: row["due_date"]))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_bills(
    through: str | None = None,
    include_paid: bool = False,
    category_id: str | None = None,
) -> list[dict]:
    """Lista contas a pagar cadastradas (pendentes por padrão, ou incluindo pagas com include_paid=True)."""
    with SessionLocal() as session:
        return wire(list_bills_domain(
            session,
            through=_date(through, "through") if through else None,
            include_paid=include_paid,
            category_id=_uuid(category_id, "category_id") if category_id else None,
        ))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_bill(bill_id: str) -> dict:
    """Consulta detalhes de uma conta a pagar por ID."""
    with SessionLocal() as session:
        return wire(get_bill_domain(session, _uuid(bill_id, "bill_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_bill(
    description: str,
    amount: str,
    due_date: str,
    category_id: str | None = None,
) -> dict:
    """Registra uma conta a pagar futura (compromisso financeiro). Não reduz o caixa até ser paga."""
    with SessionLocal.begin() as session:
        result = create_bill_domain(
            session,
            description=description,
            amount=amount,
            due_date=_date(due_date, "due_date"),
            category_id=_uuid(category_id, "category_id") if category_id else None,
        )
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_bill(
    bill_id: str,
    description: str | None = None,
    amount: str | None = None,
    due_date: str | None = None,
    category_id: str | None = None,
) -> dict:
    """Atualiza descrição, valor, vencimento ou categoria de uma conta a pagar ainda pendente."""
    with SessionLocal.begin() as session:
        result = update_bill_domain(
            session,
            bill_id=_uuid(bill_id, "bill_id"),
            description=description,
            amount=amount,
            due_date=_date(due_date, "due_date") if due_date else None,
            category_id=_uuid(category_id, "category_id") if category_id else None,
        )
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_pay_bill(
    bill_id: str,
    source_account_id: str,
    paid_date: str,
    idempotency_key: str,
) -> dict:
    """Paga uma conta a pagar criando a despesa correspondente na conta selecionada."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        result = pay_bill_domain(
            session,
            bill_id=_uuid(bill_id, "bill_id"),
            source_account_id=_uuid(source_account_id, "source_account_id"),
            paid_date=_date(paid_date, "paid_date"),
            key=idempotency_key,
        )
    return wire(result)


# ============================================================================
# 8. PLANOS RECORRENTES (RECEITAS E DESPESAS PREVISTAS MENSALMENTE)
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_recurring_plans(month: str | None = None) -> list[dict]:
    """Lista receitas e despesas previstas mensalmente e se cada ocorrência foi realizada; previsões não são caixa nem consumo."""
    with SessionLocal() as session:
        return wire(recurring_status(session, _date(month, "month") if month else date.today()))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_recurring_plan(
    description: str,
    kind: str,
    amount: str,
    account_id: str,
    start_date: str,
    category_id: str | None = None,
) -> dict:
    """Cria um plano recorrente mensal de receita (income) ou despesa (expense)."""
    with SessionLocal.begin() as session:
        row = create_recurring_plan(session, {
            "description": description,
            "kind": kind,
            "amount": amount,
            "account_id": _uuid(account_id, "account_id"),
            "category_id": _uuid(category_id, "category_id") if category_id else None,
            "start_date": _date(start_date, "start_date"),
        })
        result = {
            "id": row.id,
            "description": row.description,
            "kind": row.kind,
            "amount": row.amount,
            "account_id": row.account_id,
            "category_id": row.category_id,
            "start_date": row.start_date,
            "is_active": row.is_active,
        }
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_recurring_plan(
    plan_id: str,
    description: str | None = None,
    amount: str | None = None,
    account_id: str | None = None,
    category_id: str | None = None,
    start_date: str | None = None,
) -> dict:
    """Atualiza parcialmente um plano recorrente mensal."""
    with SessionLocal.begin() as session:
        result = update_recurring_plan_domain(
            session,
            plan_id=_uuid(plan_id, "plan_id"),
            description=description,
            amount=amount,
            account_id=_uuid(account_id, "account_id") if account_id else None,
            category_id=_uuid(category_id, "category_id") if category_id else None,
            start_date=_date(start_date, "start_date") if start_date else None,
        )
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_realize_recurring_plan(plan_id: str, month: str, realized_on: str | None = None) -> dict:
    """Realiza a ocorrência de um plano recorrente no mês (AAAA-MM-DD), gerando a movimentação financeira efetiva."""
    with SessionLocal.begin() as session:
        row = realize_recurring_plan(
            session,
            _uuid(plan_id, "plan_id"),
            _date(month, "month"),
            _date(realized_on, "realized_on") if realized_on else date.today(),
        )
        result = {
            "id": row.id,
            "plan_id": row.plan_id,
            "due_date": row.due_date,
            "transaction_id": row.transaction_id,
            "realized_at": row.realized_at,
        }
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_deactivate_recurring_plan(plan_id: str, confirmed: bool = False) -> dict:
    """Desativa um plano recorrente sem apagar ocorrências nem transações já realizadas. Exige confirmed=True."""
    if not confirmed:
        raise ValueError("Confirme a desativação do plano recorrente (confirmed=True)")
    with SessionLocal.begin() as session:
        result = set_recurring_plan_active_domain(session, _uuid(plan_id, "plan_id"), False)
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_activate_recurring_plan(plan_id: str, confirmed: bool = False) -> dict:
    """Reativa um plano recorrente desativado. Exige confirmed=True."""
    if not confirmed:
        raise ValueError("Confirme a reativação do plano recorrente (confirmed=True)")
    with SessionLocal.begin() as session:
        result = set_recurring_plan_active_domain(session, _uuid(plan_id, "plan_id"), True)
    return wire(result)


# ============================================================================
# 9. INVESTIMENTOS E PATRIMÔNIO
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_investments() -> list[dict]:
    """Lista ativos e seus valores manuais, aportes, resgates, rendimentos e taxas registrados; diferença frente ao capital líquido não é rentabilidade percentual."""
    with SessionLocal() as session:
        return wire([investment_summary(session, row) for row in session.scalars(select(Investment).order_by(Investment.name))])


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_investment(investment_id: str) -> dict:
    """Consulta detalhes completos de um investimento por ID, incluindo histórico de eventos e avaliações."""
    with SessionLocal() as session:
        return wire(get_investment_domain(session, _uuid(investment_id, "investment_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_investment(
    name: str,
    kind: str,
    current_value: str = "0.00",
    valuation_date: str | None = None,
    institution: str | None = None,
    quantity: str | None = None,
    opening_contribution: str | None = None,
    acquired_on: str | None = None,
    notes: str | None = None,
) -> dict:
    """Cadastra um novo ativo de investimento (ex.: renda_fixa, acoes, fii, reserva, cripto) com valor inicial opcional."""
    with SessionLocal.begin() as session:
        result = create_investment_domain(
            session,
            name=name,
            kind=kind,
            current_value=current_value,
            valuation_date=_date(valuation_date, "valuation_date") if valuation_date else None,
            institution=institution,
            quantity=quantity,
            opening_contribution=opening_contribution,
            acquired_on=_date(acquired_on, "acquired_on") if acquired_on else None,
            notes=notes,
        )
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_investment(
    investment_id: str,
    name: str | None = None,
    kind: str | None = None,
    institution: str | None = None,
    quantity: str | None = None,
    opening_contribution: str | None = None,
    acquired_on: str | None = None,
    notes: str | None = None,
) -> dict:
    """Atualiza metadados cadastrais de um investimento (nome, tipo, instituição, quantidade, capital inicial, data de aquisição ou notas)."""
    with SessionLocal.begin() as session:
        result = update_investment_domain(
            session,
            investment_id=_uuid(investment_id, "investment_id"),
            name=name,
            kind=kind,
            institution=institution,
            quantity=quantity,
            opening_contribution=opening_contribution,
            acquired_on=_date(acquired_on, "acquired_on") if acquired_on else None,
            notes=notes,
        )
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_investment_events(
    investment_id: str | None = None,
    kind: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Lista eventos de investimento (contribution, withdrawal, income, fee) filtráveis por ativo, tipo e período."""
    with SessionLocal() as session:
        return wire(list_investment_events_domain(
            session,
            investment_id=_uuid(investment_id, "investment_id") if investment_id else None,
            kind=kind,
            start=_date(start, "start") if start else None,
            end=_date(end, "end") if end else None,
        ))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_investment_event(
    investment_id: str,
    account_id: str,
    kind: str,
    amount: str,
    event_date: str,
    idempotency_key: str,
) -> dict:
    """Registra aporte, resgate, rendimento ou taxa. Aporte/resgate são transferências de patrimônio, não consumo."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        event = create_investment_event(
            session,
            _uuid(investment_id, "investment_id"),
            _uuid(account_id, "account_id"),
            kind,
            Decimal(amount),
            _date(event_date, "event_date"),
            idempotency_key,
        )
        result = {
            "id": event.id,
            "investment_id": event.investment_id,
            "kind": event.kind,
            "amount": event.amount,
            "event_date": event.event_date,
        }
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_investment_valuations(investment_id: str) -> list[dict]:
    """Lista o histórico de avaliações manuais registradas para um investimento."""
    with SessionLocal() as session:
        return wire(list_investment_valuations_domain(session, _uuid(investment_id, "investment_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_record_investment_valuation(
    investment_id: str,
    value: str,
    valuation_date: str,
    idempotency_key: str,
) -> dict:
    """Registra valor manual datado de um investimento e preserva o histórico; não busca preços externos."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key é obrigatório")
    with SessionLocal.begin() as session:
        row = record_investment_valuation(
            session,
            _uuid(investment_id, "investment_id"),
            Decimal(value),
            _date(valuation_date, "valuation_date"),
            idempotency_key,
        )
        result = {
            "id": row.id,
            "investment_id": row.investment_id,
            "value": row.value,
            "valuation_date": row.valuation_date,
        }
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_net_worth() -> dict:
    """Calcula caixa + valor atual informado dos investimentos − passivos abertos (cartões e contas a pagar)."""
    with SessionLocal() as session:
        return wire(net_worth(session))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_net_worth_history() -> list[dict]:
    """Consulta fotografias patrimoniais registradas; dias sem fotografia não são interpolados."""
    with SessionLocal() as session:
        return wire([
            {
                "as_of_date": row.as_of_date,
                "cash": row.cash,
                "investments": row.investments,
                "liabilities": row.liabilities,
                "net_worth": row.net_worth,
            }
            for row in session.scalars(select(NetWorthSnapshot).order_by(NetWorthSnapshot.as_of_date))
        ])


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_save_net_worth_snapshot() -> dict:
    """Salva ou atualiza a fotografia patrimonial de hoje, calculada com os registros atuais."""
    with SessionLocal.begin() as session:
        row = record_net_worth_snapshot(session)
        result = {
            "as_of_date": row.as_of_date,
            "cash": row.cash,
            "investments": row.investments,
            "liabilities": row.liabilities,
            "net_worth": row.net_worth,
        }
    return wire(result)


# ============================================================================
# 10. METAS FINANCEIRAS
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_goals() -> list[dict]:
    """Lista metas e progresso informado sem somar alocações ao patrimônio uma segunda vez."""
    with SessionLocal() as session:
        return wire(goals(session))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_goal(goal_id: str) -> dict:
    """Consulta detalhes de uma meta financeira por ID, incluindo contribuições e alocações de reserva."""
    with SessionLocal() as session:
        return wire(get_goal_domain(session, _uuid(goal_id, "goal_id")))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_create_goal(
    name: str,
    target_amount: str,
    allocated_amount: str = "0.00",
    target_date: str | None = None,
    tracking_mode: str = "none",
    account_ids: list[str] | None = None,
) -> dict:
    """Cria uma meta financeira (tracking_mode: none, all ou selected) com valor alvo e reserva inicial opcional."""
    parsed_accounts = [_uuid(aid, "account_id") for aid in (account_ids or [])]
    with SessionLocal.begin() as session:
        result = create_goal_domain(
            session,
            name=name,
            target_amount=target_amount,
            allocated_amount=allocated_amount,
            target_date=_date(target_date, "target_date") if target_date else None,
            tracking_mode=tracking_mode,
            account_ids=parsed_accounts,
        )
    return wire(result)


@mcp.tool(annotations=CORRECTION_WRITE)
@_domain_guard
def finance_update_goal(
    goal_id: str,
    name: str | None = None,
    target_amount: str | None = None,
    allocated_amount: str | None = None,
    target_date: str | None = None,
    clear_target_date: bool = False,
    tracking_mode: str | None = None,
    account_ids: list[str] | None = None,
) -> dict:
    """Atualiza parcialmente uma meta financeira (nome, valor alvo, reserva alocada, data alvo ou contas acompanhadas)."""
    parsed_accounts = [_uuid(aid, "account_id") for aid in account_ids] if account_ids is not None else None
    with SessionLocal.begin() as session:
        result = update_goal_domain(
            session,
            goal_id=_uuid(goal_id, "goal_id"),
            name=name,
            target_amount=target_amount,
            allocated_amount=allocated_amount,
            target_date=_date(target_date, "target_date") if target_date else None,
            clear_target_date=clear_target_date,
            tracking_mode=tracking_mode,
            account_ids=parsed_accounts,
        )
    return wire(result)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
@_domain_guard
def finance_add_goal_contribution(
    goal_id: str,
    amount_delta: str,
    contributed_on: str,
    note: str,
) -> dict:
    """Registra um aporte ou ajuste de progresso em uma meta financeira (amount_delta positivo ou negativo)."""
    with SessionLocal.begin() as session:
        result = add_goal_contribution_domain(
            session,
            goal_id=_uuid(goal_id, "goal_id"),
            amount_delta=amount_delta,
            contributed_on=_date(contributed_on, "contributed_on"),
            note=note,
        )
    return wire(result)


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_goal_contributions(goal_id: str) -> list[dict]:
    """Lista o histórico de contribuições registradas em uma meta financeira."""
    with SessionLocal() as session:
        return wire(list_goal_contributions_domain(session, _uuid(goal_id, "goal_id")))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_list_goal_allocations(goal_id: str) -> list[dict]:
    """Lista o histórico de alocações de reserva de caixa vinculadas a uma meta financeira."""
    with SessionLocal() as session:
        return wire(list_goal_allocations_domain(session, _uuid(goal_id, "goal_id")))


# ============================================================================
# 11. RELATÓRIOS, COMPARAÇÃO DE PERÍODOS E CALENDÁRIO FINANCEIRO
# ============================================================================

@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_monthly_comparison(months: int = 6) -> list[dict]:
    """Compara receitas, despesas líquidas e resultado por competência nos últimos 2 a 24 meses."""
    if not 2 <= months <= 24:
        raise ValueError("months deve ficar entre 2 e 24")
    with SessionLocal() as session:
        return wire(monthly_comparison(session, months))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_compare_periods(start_a: str, end_a: str, start_b: str, end_b: str) -> dict:
    """Compara receitas, despesas líquidas, resultado e gastos por categoria entre dois intervalos de datas arbitrários."""
    with SessionLocal() as session:
        return wire(compare_periods_domain(
            session,
            _date(start_a, "start_a"),
            _date(end_a, "end_a"),
            _date(start_b, "start_b"),
            _date(end_b, "end_b"),
        ))


@mcp.tool(annotations=READ_ONLY)
@_domain_guard
def finance_get_calendar(start: str, end: str) -> dict:
    """Consulta o calendário financeiro diário no intervalo (até 367 dias), incluindo transações, contas a pagar, faturas e recorrências."""
    with SessionLocal() as session:
        return wire(calendar_summary_domain(session, _date(start, "start"), _date(end, "end")))


if __name__ == "__main__":
    mcp.run(transport="stdio")
