#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/meu-financeiro/.env"
if [[ ! -x "$PROJECT_DIR/.venv/bin/uvicorn" || ! -r "$CONFIG_FILE" ]]; then
  echo "Meu Financeiro não instalado/configurado. Execute scripts/install.sh." >&2
  exit 1
fi
set -a
source "$CONFIG_FILE"
set +a
cd "$PROJECT_DIR"
"$PROJECT_DIR/scripts/start-postgres.sh"
"$PROJECT_DIR/.venv/bin/alembic" current --check-heads >/dev/null || { echo "Banco precisa de migração. Execute scripts/install.sh." >&2; exit 1; }
exec "$PROJECT_DIR/.venv/bin/uvicorn" backend.app.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8765}"
