"""deploy/migrate_workspace.sh на фикстуре: локально нет ни реального сервера, ни
systemd, ни ssh-доступа куда-либо, поэтому ssh/sudo/systemctl подменяются на
локальные заглушки (PATH перед системными путями), а rsync и sqlite3 — настоящие
(они уже есть в PATH сборочной машины), чтобы честно проверить и копирование
файлов workspace/, и PRAGMA integrity_check. Ни при одном сценарии не трогаем
реальный workspace/ владельца — только tmp_path.
"""
import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "migrate_workspace.sh"


def _system_rsync_supports_info_progress2() -> bool:
    result = subprocess.run(
        ["rsync", "--info=progress2", "--version"], capture_output=True, text=True
    )
    return result.returncode == 0

# Заглушка ssh: без реального сервера просто выполняет "удалённую" команду локально
# (host = $1 игнорируется). И сам migrate_workspace.sh (ssh host "команда одной
# строкой"), и системный rsync (ssh host rsync --server ...) вызывают её как единый
# транспорт, поэтому подмена делает весь скрипт локальным, без сети/systemd.
FAKE_SSH = """#!/usr/bin/env bash
shift
if [[ $# -eq 1 ]]; then
  exec bash -c "$1"
else
  exec "$@"
fi
"""

FAKE_SUDO = """#!/usr/bin/env bash
exec "$@"
"""

# Заглушка rsync: фильтрует --info=progress2 и передаёт всё остальное настоящему
# системному rsync. Нужна только тестам, не проверяющим сам rsync-флаг напрямую -
# см. test_migrate_workspace_progress2_flag_unsupported_by_stock_macos_rsync ниже,
# где используется настоящий /usr/bin/rsync без этой подмены.
FAKE_RSYNC = """#!/usr/bin/env bash
args=()
for a in "$@"; do
  if [[ "$a" == "--info=progress2" ]]; then
    continue
  fi
  args+=("$a")
done
exec /usr/bin/rsync "${args[@]}"
"""

# Логирует каждый вызов (аргументы), чтобы тест мог проверить порядок stop/start
# относительно копирования, и всегда успешен (на маке нет systemctl вообще).
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
echo "$@" >> "${FAKE_SYSTEMCTL_LOG}"
exit 0
"""


def _make_fakebin(tmp_path, with_rsync_shim=True):
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    scripts = [("ssh", FAKE_SSH), ("sudo", FAKE_SUDO), ("systemctl", FAKE_SYSTEMCTL)]
    if with_rsync_shim:
        scripts.append(("rsync", FAKE_RSYNC))
    for name, content in scripts:
        path = fakebin / name
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fakebin


def _make_src_workspace(tmp_path):
    src = tmp_path / "src_workspace"
    src.mkdir()
    conn = sqlite3.connect(src / "test_hub.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('x')")
    conn.commit()
    conn.close()
    (src / "allure-results").mkdir()
    (src / "allure-results" / "sample.json").write_text('{"ok": true}')
    (src / "frames").mkdir()
    (src / "frames" / "frame1.png").write_bytes(b"\x89PNG\r\n fake bytes")
    return src


def _run_migrate(tmp_path, args, fakebin, systemctl_log=None):
    env = dict(os.environ)
    env["PATH"] = f"{fakebin}:{env['PATH']}"
    env.pop("TH_MIGRATE_SRC", None)
    env["FAKE_SYSTEMCTL_LOG"] = str(systemctl_log or (tmp_path / "systemctl.log"))
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30, env=env,
    )


def test_migrate_workspace_copies_files_and_passes_integrity_check(tmp_path):
    src = _make_src_workspace(tmp_path)
    dst = tmp_path / "dst_app"
    fakebin = _make_fakebin(tmp_path)
    systemctl_log = tmp_path / "systemctl.log"

    result = _run_migrate(tmp_path, [f"faketesthost:{dst}", str(src)], fakebin, systemctl_log)

    assert result.returncode == 0, result.stdout + result.stderr
    dst_workspace = dst / "workspace"
    assert (dst_workspace / "test_hub.db").exists()
    assert (dst_workspace / "allure-results" / "sample.json").read_text() == '{"ok": true}'
    assert (dst_workspace / "frames" / "frame1.png").exists()
    assert "integrity_check: ok" in result.stdout
    assert "Готово, БД целостна." in result.stdout

    # stop должен произойти до копирования, start — после проверки целостности.
    log_lines = systemctl_log.read_text().splitlines()
    assert log_lines == ["stop test_hub", "start test_hub"], log_lines


def test_migrate_workspace_rejects_bad_target_format(tmp_path):
    fakebin = _make_fakebin(tmp_path)

    result = _run_migrate(tmp_path, ["not-a-valid-target"], fakebin)

    assert result.returncode != 0
    assert "Ожидался формат" in result.stderr


def test_migrate_workspace_no_args_prints_usage(tmp_path):
    fakebin = _make_fakebin(tmp_path)

    result = _run_migrate(tmp_path, [], fakebin)

    assert result.returncode != 0
    assert "Использование" in result.stderr


def test_migrate_workspace_invalid_db_file_aborts_before_restart(tmp_path):
    """ДЕФЕКТ (не правлю, только фиксирую тестом): если workspace/test_hub.db в SRC —
    не валидный файл SQLite (например, оборванный при предыдущем сбойном переносе),
    sqlite3 CLI завершается с ненулевым кодом (26, "file is not a database"), а не
    печатает что-то отличное от "ok" при коде 0, как для структурно валидной, но
    повреждённой БД. Строка `INTEGRITY_RESULT="$(ssh ... sqlite3 ...)"` в
    migrate_workspace.sh выполняется под `set -euo pipefail`, и такой сбой
    команды-подстановки обрывает скрипт СРАЗУ, до шага "Запускаю test_hub на
    сервере обратно" — systemd-сервис на сервере остаётся остановленным, а
    пользователь вместо понятного предупреждения "Целостность БД под вопросом"
    видит только сырое stderr sqlite3.
    """
    src = _make_src_workspace(tmp_path)
    (src / "test_hub.db").write_bytes(b"not a valid sqlite database file at all, just padding bytes")
    dst = tmp_path / "dst_app"
    fakebin = _make_fakebin(tmp_path)
    systemctl_log = tmp_path / "systemctl.log"

    result = _run_migrate(tmp_path, [f"faketesthost:{dst}", str(src)], fakebin, systemctl_log)

    assert result.returncode != 0
    # rsync успел отработать до integrity-check - файл на месте.
    assert (dst / "workspace" / "test_hub.db").exists()
    assert "file is not a database" in result.stderr
    assert "Запускаю test_hub на сервере обратно" not in result.stdout
    # sudo systemctl start ни разу не выполнился - сервис остался остановленным.
    log_lines = systemctl_log.read_text().splitlines()
    assert log_lines == ["stop test_hub"], log_lines


@pytest.mark.skipif(
    _system_rsync_supports_info_progress2(),
    reason="системный rsync здесь достаточно новый и понимает --info=progress2 - "
    "дефект воспроизводится только со штатным rsync 2.6.9 из macOS",
)
def test_migrate_workspace_progress2_flag_unsupported_by_stock_macos_rsync(tmp_path):
    """ДЕФЕКТ (не правлю, только фиксирую тестом): скрипт вызывает `rsync -az --delete
    --human-readable --info=progress2 ...` и его собственный заголовок явно предписывает
    "Запускать с мака владельца" - но штатный rsync, поставляемый Apple с macOS (в этом
    окружении: 2.6.9, протокол 29 - старый форк без GPLv3, `--info=progress2` появился
    только в rsync 3.1), не понимает `--info=progress2` и падает с "unknown option" ДО
    какого-либо копирования. К этому моменту "stop test_hub" на сервере уже выполнен
    (это первый шаг скрипта), а "start" - нет: сервис остаётся остановленным, если у
    оператора не установлен более новый rsync (например, через Homebrew) впереди
    системного в PATH.
    """
    src = _make_src_workspace(tmp_path)
    dst = tmp_path / "dst_app"
    # Без --with_rsync_shim: сознательно используем настоящий системный rsync, а не
    # шим из других тестов, чтобы проверить реальное поведение "из коробки" на macOS.
    fakebin = _make_fakebin(tmp_path, with_rsync_shim=False)
    systemctl_log = tmp_path / "systemctl.log"

    result = _run_migrate(tmp_path, [f"faketesthost:{dst}", str(src)], fakebin, systemctl_log)

    assert result.returncode != 0
    assert "unknown option" in result.stderr
    assert not (dst / "workspace" / "test_hub.db").exists()
    log_lines = systemctl_log.read_text().splitlines()
    assert log_lines == ["stop test_hub"], log_lines
