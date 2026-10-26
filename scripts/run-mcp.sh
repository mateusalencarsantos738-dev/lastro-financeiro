#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/meu-financeiro/.env"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Ambiente Python do Meu Financeiro não encontrado. Execute scripts/install.sh." >&2
  exit 1
fi
if [[ ! -r "$CONFIG_FILE" ]]; then
  echo "Configuração local ausente: $CONFIG_FILE" >&2
  exit 1
fi
set -a
source "$CONFIG_FILE"
set +a
cd "$PROJECT_DIR"
"$PROJECT_DIR/scripts/start-postgres.sh" >&2
exec "$PROJECT_DIR/.venv/bin/python" -m mcp_server.server
