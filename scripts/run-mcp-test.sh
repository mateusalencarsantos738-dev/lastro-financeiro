#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "${XDG_CONFIG_HOME:-$HOME/.config}/meu-financeiro/.env"
set +a
export DATABASE_URL="$("$PROJECT_DIR/.venv/bin/python" -c 'import os; from sqlalchemy.engine import make_url; print(make_url(os.environ["DATABASE_URL"]).set(database="meu_financeiro_test").render_as_string(hide_password=False))')"
cd "$PROJECT_DIR"
"$PROJECT_DIR/scripts/start-postgres.sh" >&2
exec "$PROJECT_DIR/.venv/bin/python" -m mcp_server.server
