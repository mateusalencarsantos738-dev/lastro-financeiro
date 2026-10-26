#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
npm --prefix frontend install
npm --prefix frontend run build
"$PROJECT_DIR/scripts/setup-local-postgres.sh"
CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/meu-financeiro/.env"
set -a
source "$CONFIG_FILE"
set +a
"$PROJECT_DIR/.venv/bin/alembic" upgrade head
"$PROJECT_DIR/scripts/install-service.sh"
"$PROJECT_DIR/scripts/install-desktop.sh"
printf 'Meu Financeiro instalado. Abra pelo menu de aplicativos.\n'
