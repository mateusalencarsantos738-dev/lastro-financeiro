"""Confirma uma escrita MCP pelo próprio Codex apenas no banco sintético de teste."""

import os
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.models import Account, Category, Transaction

root = Path(__file__).resolve().parents[1]
db_url = os.environ["DATABASE_URL"]
if make_url(db_url).database != "meu_financeiro_test":
    raise SystemExit("Prova Codex de escrita exige meu_financeiro_test")

engine = create_engine(db_url)
suffix = uuid4().hex[:8]
key = f"codex-probe-{suffix}"
with Session(engine) as session, session.begin():
    account = Account(name=f"Conta Codex sintética {suffix}", opening_balance=Decimal("100"))
    category = Category(name=f"Lazer Codex sintético {suffix}", kind="expense", is_entertainment=True)
    session.add_all([account, category]); session.flush()
    account_id, category_id = str(account.id), str(category.id)

prompt = (
    "Use somente o servidor MCP meu_financeiro para registrar UMA despesa sintética no banco de teste. "
    f"Chame finance_create_transaction com kind=expense, amount=42.50, account_id={account_id}, "
    f"category_id={category_id}, description='Despesa sintética Codex', transaction_date={date.today().isoformat()}, "
    f"idempotency_key={key}. Não use terminal, não faça outras chamadas e informe o ID retornado."
)
command = [
    "codex", "exec", "--ignore-user-config", "--ephemeral", "-m", "gpt-6-luna", "-s", "read-only",
    "-c", f'mcp_servers.meu_financeiro.command="{root / "scripts/run-mcp-test.sh"}"',
    "-c", 'mcp_servers.meu_financeiro.default_tools_approval_mode="auto"',
    prompt,
]
result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=120)
transcript = result.stderr + "\n" + result.stdout
if result.returncode != 0 or "mcp: meu_financeiro/finance_create_transaction (completed)" not in transcript:
    raise SystemExit("Codex não concluiu a chamada MCP de escrita:\n" + transcript[-3000:])
with Session(engine) as session:
    rows = session.scalars(select(Transaction).where(Transaction.idempotency_key == key)).all()
    assert len(rows) == 1
    assert rows[0].amount == Decimal("42.50")
    assert str(rows[0].account_id) == account_id
    assert str(rows[0].category_id) == category_id
print(f"Codex executou finance_create_transaction no banco de teste; 1 transação de R$ 42,50 persistida com ID {rows[0].id}.")
