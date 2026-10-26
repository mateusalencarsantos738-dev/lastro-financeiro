#!/usr/bin/env bash
set -euo pipefail
DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/meu-financeiro/postgres"
DATA_DIR="$DATA_ROOT/data"
SOCKET_DIR="$DATA_ROOT/socket"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/meu-financeiro"
PG_BIN="/usr/lib/postgresql/18/bin"
if [[ ! -f "$DATA_DIR/PG_VERSION" ]]; then
  echo "Banco privado ainda não foi inicializado. Execute scripts/setup-local-postgres.sh." >&2
  exit 1
fi
mkdir -p "$SOCKET_DIR" "$STATE_DIR"
chmod 700 "$SOCKET_DIR" "$STATE_DIR"
if [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/meu-financeiro-postgres.service" ]]; then
  systemctl --user start meu-financeiro-postgres.service
  "$PG_BIN/pg_isready" -q -h "$SOCKET_DIR" -p 55432
  exit
fi
if "$PG_BIN/pg_isready" -q -h "$SOCKET_DIR" -p 55432; then exit 0; fi
"$PG_BIN/pg_ctl" -D "$DATA_DIR" -l "$STATE_DIR/postgres.log" -o "-c listen_addresses= -c unix_socket_directories=$SOCKET_DIR -p 55432" start
