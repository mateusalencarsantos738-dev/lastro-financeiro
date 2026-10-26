#!/usr/bin/env bash
set -euo pipefail
if ! curl --silent --fail --max-time 1 http://127.0.0.1:8765/api/overview >/dev/null 2>&1; then
  if ! systemctl --user start meu-financeiro.service; then
    zenity --error --title='Meu Financeiro' --text='Não foi possível iniciar o serviço. Consulte: journalctl --user -u meu-financeiro.service' 2>/dev/null || true
    exit 1
  fi
  for i in {1..60}; do
    if curl --silent --fail --max-time 1 http://127.0.0.1:8765/api/overview >/dev/null 2>&1; then break; fi
    sleep 0.25
  done
fi
if ! curl --silent --fail --max-time 2 http://127.0.0.1:8765/api/overview >/dev/null 2>&1; then
  zenity --error --title='Meu Financeiro' --text='A API não ficou disponível. Consulte: journalctl --user -u meu-financeiro.service' 2>/dev/null || true
  exit 1
fi
xdg-open http://127.0.0.1:8765 >/dev/null 2>&1
