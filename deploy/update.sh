#!/usr/bin/env bash
# Обновление уже развёрнутого test_hub: git pull + переустановка зависимостей (если
# requirements.txt изменился) + перезапуск systemd-юнита.
#
#   sudo deploy/update.sh
#
# Требует, чтобы test_hub уже был установлен через deploy/install.sh (venv, systemd-юнит).

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Запускайте от root (sudo deploy/update.sh) — нужен systemctl restart." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
SERVICE_USER="$(systemctl show -p User --value test_hub 2>/dev/null || true)"
SERVICE_USER="${SERVICE_USER:-test_hub}"

echo "==> git pull в ${APP_DIR}"
sudo -u "$SERVICE_USER" git -C "$APP_DIR" pull --ff-only

echo "==> зависимости"
sudo -u "$SERVICE_USER" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q

echo "==> перезапуск test_hub"
systemctl restart test_hub
systemctl status test_hub --no-pager -l | head -n 10
