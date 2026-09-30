#!/usr/bin/env bash
# Установка test_hub на чистый Ubuntu-сервер без Docker.
#
# Запускать из уже склонированного репозитория (тем путём, где он должен остаться жить —
# скрипт настраивает systemd на этот же каталог, "переезда" в /opt после клонирования нет):
#
#   git clone <repo> /opt/test_hub && cd /opt/test_hub
#   sudo TH_SERVICE_USER=test_hub deploy/install.sh
#
# Скрипт идемпотентен: повторный запуск не ломает уже настроенное окружение
# (venv/allure/systemd-юнит пересоздаются только если отсутствуют или отличаются).
#
# Переменные окружения (необязательные):
#   TH_SERVICE_USER   системный пользователь для systemd-юнита (по умолчанию test_hub)
#   TH_ALLURE_VERSION версия Allure CLI (по умолчанию 2.32.0)

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Запускайте от root (sudo deploy/install.sh) — нужны apt-get, useradd, systemctl." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
SERVICE_USER="${TH_SERVICE_USER:-test_hub}"
ALLURE_VERSION="${TH_ALLURE_VERSION:-2.32.0}"
ALLURE_INSTALL_DIR="/opt/allure-${ALLURE_VERSION}"
ALLURE_BIN_LINK="/usr/local/bin/allure"

echo "==> test_hub: $APP_DIR, сервисный пользователь: $SERVICE_USER"

echo "==> Системные пакеты (python3.11, JRE для allure, вспомогательные утилиты)"
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3.11 python3.11-venv python3-pip \
  default-jre-headless \
  curl ca-certificates rsync sqlite3

echo "==> Allure CLI ${ALLURE_VERSION}"
if [[ -x "${ALLURE_INSTALL_DIR}/bin/allure" ]]; then
  echo "    уже установлен в ${ALLURE_INSTALL_DIR}, пропускаю скачивание"
else
  TMP_TGZ="$(mktemp --suffix=.tgz)"
  trap 'rm -f "$TMP_TGZ"' EXIT
  curl -fsSL -o "$TMP_TGZ" \
    "https://github.com/allure-framework/allure2/releases/download/${ALLURE_VERSION}/allure-${ALLURE_VERSION}.tgz"
  rm -rf "$ALLURE_INSTALL_DIR"
  mkdir -p /opt
  tar -xzf "$TMP_TGZ" -C /opt
  mv "/opt/allure-${ALLURE_VERSION}" "$ALLURE_INSTALL_DIR"
  rm -f "$TMP_TGZ"
  trap - EXIT
fi
ln -sf "${ALLURE_INSTALL_DIR}/bin/allure" "$ALLURE_BIN_LINK"

echo "==> Сервисный пользователь"
if id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "    $SERVICE_USER уже существует"
else
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "$APP_DIR"

echo "==> Виртуальное окружение и зависимости"
if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  sudo -u "$SERVICE_USER" python3.11 -m venv "${APP_DIR}/.venv"
fi
sudo -u "$SERVICE_USER" "${APP_DIR}/.venv/bin/pip" install --upgrade pip -q
sudo -u "$SERVICE_USER" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q

echo "==> Playwright: системные зависимости для UI-тестов проектов"
# Библиотеки apt общие для всех .venv тестовых проектов на сервере, поэтому ставятся
# один раз через playwright test_hub, а не в каждом .venv проекта отдельно.
"${APP_DIR}/.venv/bin/playwright" install-deps

echo "==> .env"
if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  chown "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}/.env"
  echo "    создан из .env.example — обязательно заполните TH_SECRET и TH_PUBLIC_URL"
else
  echo "    уже существует, не трогаю"
fi

echo "==> systemd-юнит"
sed \
  -e "s#/opt/test_hub#${APP_DIR}#g" \
  -e "s/^User=test_hub/User=${SERVICE_USER}/" \
  -e "s/^Group=test_hub/Group=${SERVICE_USER}/" \
  "${SCRIPT_DIR}/test_hub.service" > /etc/systemd/system/test_hub.service
systemctl daemon-reload
systemctl enable test_hub
systemctl restart test_hub

echo
echo "==> Готово. Проверьте статус: systemctl status test_hub / journalctl -u test_hub -f"
echo
echo "Напоминания:"
echo "  - В ${APP_DIR}/.env задайте TH_SECRET (не change-me), TH_PUBLIC_URL (домен/https)."
echo "  - TH_ALLURE_BIN=${ALLURE_BIN_LINK} — под systemd PATH урезан, allure через shutil.which"
echo "    может не найтись, поэтому пропишите путь явно в .env (см. комментарий в .env.example)."
echo "  - Обновление кода на сервере:"
echo "      cd ${APP_DIR} && git pull && sudo systemctl restart test_hub"
echo "    либо: sudo deploy/update.sh"
