#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/meu-financeiro/backups"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
FILE="$BACKUP_DIR/meu_financeiro_$(date +%Y%m%d_%H%M%S_%N).dump"
umask 077
CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/meu-financeiro/.env"
set -a
source "$CONFIG_FILE"
set +a
SOCKET_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/meu-financeiro/postgres/socket"
"$(dirname "$0")/start-postgres.sh"
PGPASSWORD="$DB_PASSWORD" pg_dump -h "$SOCKET_DIR" -p 55432 -U finance_app -Fc -f "$FILE" meu_financeiro
pg_restore --list "$FILE" >/dev/null
echo "$FILE"
