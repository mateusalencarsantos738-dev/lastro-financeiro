#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_CONFIG="${CODEX_HOME:-$HOME/.codex}/config.toml"
if [[ ! -f "$CODEX_CONFIG" ]]; then echo "Configuração do Codex não encontrada: $CODEX_CONFIG" >&2; exit 1; fi
python3 - "$CODEX_CONFIG" <<'PY'
import sys, tomllib
with open(sys.argv[1], 'rb') as file:
    data = tomllib.load(file)
existing = data.get('mcp_servers', {}).get('meu_financeiro')
if existing:
    print('Entrada MCP meu_financeiro já existe; confira manualmente antes de alterar.')
    raise SystemExit(2)
PY
BACKUP_FILE="$CODEX_CONFIG.backup-meu-financeiro-$(date +%Y%m%d_%H%M%S)"
cp -p "$CODEX_CONFIG" "$BACKUP_FILE"
chmod 600 "$BACKUP_FILE"
codex mcp add meu_financeiro --env "XDG_RUNTIME_DIR=/run/user/$(id -u)" --env "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus" -- "$PROJECT_DIR/scripts/run-mcp.sh"
python3 - "$CODEX_CONFIG" <<'PY'
import sys, tomllib
with open(sys.argv[1], 'rb') as file:
    data = tomllib.load(file)
assert data.get('mcp_servers', {}).get('meu_financeiro', {}).get('command'), 'MCP não configurado'
print('TOML do Codex válido; servidores existentes preservados.')
PY
codex mcp get meu_financeiro
echo "Backup: $BACKUP_FILE"
