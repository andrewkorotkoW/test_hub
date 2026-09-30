#!/usr/bin/env bash
# Бэкап workspace/test_hub.db в timestamp-именованный файл (используется онлайн-бэкап
# sqlite3 .backup — безопасен, пока БД открыта другим процессом, без остановки сервиса).
#
# Запуск вручную:
#   deploy/backup.sh
#
# Пример строки в crontab (ежедневно в 03:15, от имени сервисного пользователя test_hub):
#   15 3 * * * cd /opt/test_hub && deploy/backup.sh >> /opt/test_hub/workspace/backups/backup.log 2>&1
#
# Переменные окружения (необязательные):
#   TH_BACKUP_KEEP  сколько последних бэкапов хранить, старше — удаляются (по умолчанию 14, 0 = не чистить)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
DB_PATH="${APP_DIR}/workspace/test_hub.db"
BACKUP_DIR="${APP_DIR}/workspace/backups"
KEEP="${TH_BACKUP_KEEP:-14}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "Не найдена БД: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_PATH="${BACKUP_DIR}/test_hub_${TIMESTAMP}.db"

echo "==> Бэкап ${DB_PATH} -> ${BACKUP_PATH}"
sqlite3 "$DB_PATH" ".backup '${BACKUP_PATH}'"

echo "==> Проверка целостности бэкапа"
INTEGRITY_RESULT="$(sqlite3 "$BACKUP_PATH" 'PRAGMA integrity_check;')"
echo "    PRAGMA integrity_check: ${INTEGRITY_RESULT}"
if [[ "$INTEGRITY_RESULT" != "ok" ]]; then
  echo "!! Бэкап повреждён (ожидалось 'ok')" >&2
  exit 1
fi

if [[ "$KEEP" != "0" ]]; then
  echo "==> Чистка старых бэкапов (оставляю последние ${KEEP})"
  # shellcheck disable=SC2012
  ls -1t "${BACKUP_DIR}"/test_hub_*.db 2>/dev/null | tail -n "+$((KEEP + 1))" | xargs -r rm -f
fi

echo "==> Готово: ${BACKUP_PATH}"
