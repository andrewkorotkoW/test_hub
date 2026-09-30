#!/usr/bin/env bash
# Перенос workspace/ (БД, allure-results, frames, testcases, coverage-кэш) с машины
# владельца на сервер по rsync + проверка целостности БД после переноса.
#
# Запускать с мака владельца (там, где сейчас живут данные):
#
#   deploy/migrate_workspace.sh user@server:/opt/test_hub
#   # или явно указать источник, если он не рядом со скриптом:
#   TH_MIGRATE_SRC=/Users/andreykorotkow/.../test_hub/workspace \
#     deploy/migrate_workspace.sh user@server:/opt/test_hub
#
# Первый аргумент — ssh-адрес и путь до каталога установки test_hub на сервере
# (тот же APP_DIR, что в deploy/install.sh); workspace/ будет создан/обновлён внутри него.
# На время копирования сервис на сервере останавливается (чтобы БД не менялась под rsync)
# и запускается обратно после проверки целостности.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Использование: $0 user@host:/opt/test_hub [SRC_WORKSPACE_DIR]" >&2
  exit 1
fi

DST_TARGET="$1"
REMOTE_HOST="${DST_TARGET%%:*}"
REMOTE_APP_DIR="${DST_TARGET#*:}"
if [[ "$REMOTE_HOST" == "$DST_TARGET" || -z "$REMOTE_APP_DIR" ]]; then
  echo "Ожидался формат user@host:/path, получено: $DST_TARGET" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
SRC="${2:-${TH_MIGRATE_SRC:-${SCRIPT_DIR}/../workspace}}"
SRC="$(cd -- "$SRC" >/dev/null 2>&1 && pwd)"
REMOTE_WORKSPACE="${REMOTE_APP_DIR}/workspace"
REMOTE_DB="${REMOTE_WORKSPACE}/test_hub.db"

echo "==> Источник: $SRC"
echo "==> Назначение: ${REMOTE_HOST}:${REMOTE_WORKSPACE}"

echo "==> Останавливаю test_hub на сервере (чтобы БД не менялась во время копирования)"
ssh "$REMOTE_HOST" "sudo systemctl stop test_hub" || echo "    не удалось остановить (сервис ещё не установлен?), продолжаю"

echo "==> rsync"
ssh "$REMOTE_HOST" "mkdir -p '${REMOTE_WORKSPACE}'"
rsync -az --delete --human-readable --info=progress2 \
  "${SRC}/" "${REMOTE_HOST}:${REMOTE_WORKSPACE}/"

echo "==> Проверка целостности БД на сервере"
INTEGRITY_RESULT="$(ssh "$REMOTE_HOST" "sqlite3 '${REMOTE_DB}' 'PRAGMA integrity_check;'")"
echo "    PRAGMA integrity_check: ${INTEGRITY_RESULT}"

echo "==> Запускаю test_hub на сервере обратно"
ssh "$REMOTE_HOST" "sudo systemctl start test_hub"

if [[ "$INTEGRITY_RESULT" != "ok" ]]; then
  echo "!! Целостность БД под вопросом (ожидалось 'ok') — проверьте вручную перед тем, как доверять данным." >&2
  exit 1
fi

echo "==> Готово, БД целостна."
