#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/meu-financeiro.service"
PG_UNIT_FILE="$UNIT_DIR/meu-financeiro-postgres.service"
PG_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/meu-financeiro/postgres"
mkdir -p "$UNIT_DIR"
if [[ -e "$UNIT_FILE" ]] && ! grep -Fxq "ExecStart=\"$PROJECT_DIR/scripts/run-api.sh\"" "$UNIT_FILE"; then
  echo "Já existe outro serviço em $UNIT_FILE; não foi substituído." >&2
  exit 1
fi
if [[ -e "$PG_UNIT_FILE" ]] && ! grep -Fxq "Description=PostgreSQL privado do Meu Financeiro" "$PG_UNIT_FILE"; then
  echo "Já existe outro serviço em $PG_UNIT_FILE; não foi substituído." >&2
  exit 1
fi
cat > "$PG_UNIT_FILE" <<EOF
[Unit]
Description=PostgreSQL privado do Meu Financeiro

[Service]
Type=exec
ExecStart=/usr/lib/postgresql/18/bin/postgres -D "$PG_ROOT/data" -c "listen_addresses=" -c "unix_socket_directories=$PG_ROOT/socket" -p 55432
ExecStop=/usr/lib/postgresql/18/bin/pg_ctl -D "$PG_ROOT/data" stop -m fast
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=default.target
EOF
chmod 600 "$PG_UNIT_FILE"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Meu Financeiro (aplicação local)
Requires=meu-financeiro-postgres.service
After=meu-financeiro-postgres.service

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart="$PROJECT_DIR/scripts/run-api.sh"
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=default.target
EOF
chmod 600 "$UNIT_FILE"
systemctl --user daemon-reload
if ! systemctl --user is-active --quiet meu-financeiro-postgres.service; then
  if /usr/lib/postgresql/18/bin/pg_isready -q -h "$PG_ROOT/socket" -p 55432; then
    /usr/lib/postgresql/18/bin/pg_ctl -D "$PG_ROOT/data" stop -m fast
  fi
  systemctl --user start meu-financeiro-postgres.service
fi
if systemctl --user is-active --quiet meu-financeiro.service; then
  systemctl --user restart meu-financeiro.service
fi
echo "$UNIT_FILE"
