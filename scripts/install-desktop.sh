#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$TARGET_DIR"
DESKTOP_FILE="$TARGET_DIR/meu-financeiro.desktop"
if [[ -e "$DESKTOP_FILE" ]]; then
  if grep -Fxq "Exec=$PROJECT_DIR/scripts/open-app.sh" "$DESKTOP_FILE"; then
    desktop-file-validate "$DESKTOP_FILE"
    echo "$DESKTOP_FILE"
    exit 0
  fi
  echo "Já existe outro lançador em $DESKTOP_FILE; não foi substituído." >&2
  exit 1
fi
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Meu Financeiro
Comment=Gestão financeira pessoal local
Exec=$PROJECT_DIR/scripts/open-app.sh
Icon=$PROJECT_DIR/assets/icons/meu-financeiro.svg
Terminal=false
Categories=Office;Finance;
StartupNotify=true
EOF
chmod 644 "$DESKTOP_FILE"
desktop-file-validate "$DESKTOP_FILE"
echo "$DESKTOP_FILE"
