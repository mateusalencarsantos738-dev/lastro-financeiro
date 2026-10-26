#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "Uso: scripts/restore.sh /caminho/backup.dump" >&2
  exit 2
fi
BACKUP_FILE="$(realpath "$1")"
pg_restore --list "$BACKUP_FILE" >/dev/null
RESTORE_DB="meu_financeiro_restore_$(date +%Y%m%d_%H%M%S)_$$"
SOCKET_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/meu-financeiro/postgres/socket"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/meu-financeiro"
"$(dirname "$0")/start-postgres.sh"
PGPASSWORD="$(cat "$CONFIG_DIR/admin-password")" /usr/lib/postgresql/18/bin/createdb -h "$SOCKET_DIR" -p 55432 -U finance_admin --owner=finance_app "$RESTORE_DB"
cleanup_failed_restore() {
  PGPASSWORD="$(cat "$CONFIG_DIR/admin-password")" /usr/lib/postgresql/18/bin/dropdb -h "$SOCKET_DIR" -p 55432 -U finance_admin --if-exists "$RESTORE_DB" || true
}
trap cleanup_failed_restore ERR
PGPASSWORD="$(cat "$CONFIG_DIR/app-password")" pg_restore --exit-on-error -h "$SOCKET_DIR" -p 55432 -U finance_app --no-owner --no-acl -d "$RESTORE_DB" "$BACKUP_FILE"
trap - ERR
echo "Restauração concluída em banco separado: $RESTORE_DB"
