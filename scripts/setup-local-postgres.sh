#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/meu-financeiro/postgres"
DATA_DIR="$DATA_ROOT/data"
SOCKET_DIR="$DATA_ROOT/socket"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/meu-financeiro"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/meu-financeiro"
PG_BIN="/usr/lib/postgresql/18/bin"
umask 077
mkdir -p "$DATA_ROOT" "$SOCKET_DIR" "$CONFIG_DIR" "$STATE_DIR"
chmod 700 "$DATA_ROOT" "$SOCKET_DIR" "$CONFIG_DIR" "$STATE_DIR"
if [[ ! -f "$DATA_DIR/PG_VERSION" ]]; then
  if [[ -e "$DATA_DIR" ]]; then echo "Diretório de banco existente sem PG_VERSION; não será alterado: $DATA_DIR" >&2; exit 1; fi
  "$PROJECT_DIR/.venv/bin/python" -c 'import secrets,sys; open(sys.argv[1],"w").write(secrets.token_hex(32)+"\n")' "$CONFIG_DIR/admin-password"
  chmod 600 "$CONFIG_DIR/admin-password"
  "$PG_BIN/initdb" -D "$DATA_DIR" --auth-local=scram-sha-256 --auth-host=scram-sha-256 --username=finance_admin --pwfile="$CONFIG_DIR/admin-password" --no-instructions
fi
if [[ ! -f "$CONFIG_DIR/admin-password" ]]; then echo "Senha administrativa ausente; banco preservado. Restaure o segredo antes de continuar." >&2; exit 1; fi
"$PROJECT_DIR/scripts/start-postgres.sh"
export PGPASSWORD="$(cat "$CONFIG_DIR/admin-password")"
if [[ "$(psql -h "$SOCKET_DIR" -p 55432 -U finance_admin -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='finance_app'" | tr -d '[:space:]')" != "1" ]]; then
  APP_PASSWORD="$($PROJECT_DIR/.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
  psql -h "$SOCKET_DIR" -p 55432 -U finance_admin -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE finance_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '$APP_PASSWORD'"
  printf '%s\n' "$APP_PASSWORD" > "$CONFIG_DIR/app-password"
  chmod 600 "$CONFIG_DIR/app-password"
fi
if [[ ! -f "$CONFIG_DIR/app-password" ]]; then echo "Senha da aplicação ausente; banco preservado. Restaure o segredo antes de continuar." >&2; exit 1; fi
for DB_NAME in meu_financeiro meu_financeiro_test; do
  if [[ "$(psql -h "$SOCKET_DIR" -p 55432 -U finance_admin -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | tr -d '[:space:]')" != "1" ]]; then
    "$PG_BIN/createdb" -h "$SOCKET_DIR" -p 55432 -U finance_admin --owner=finance_app "$DB_NAME"
  fi
done
if [[ ! -e "$CONFIG_DIR/.env" ]]; then
  APP_PASSWORD="$(cat "$CONFIG_DIR/app-password")"
  printf "DATABASE_URL='postgresql+psycopg://finance_app:%s@/meu_financeiro?host=%s&port=55432'\nAPP_HOST=127.0.0.1\nAPP_PORT=8765\nDB_PASSWORD='%s'\n" "$APP_PASSWORD" "$SOCKET_DIR" "$APP_PASSWORD" > "$CONFIG_DIR/.env"
  chmod 600 "$CONFIG_DIR/.env"
fi
echo "Banco privado inicializado em $DATA_DIR; bancos pessoais e de teste separados."
