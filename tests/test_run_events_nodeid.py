"""Разметка run_events по nodeid/kind (этап 2 окна прогона, app/core/runner.py).

Проверяет две вещи по образцу test_run_env_and_marker.py (probe-conftest для
переменных окружения) и test_run_repeat.py (реальный прогон + опрос статуса):

- `_parse_th_line` — чистый разбор строк плагина "[TH] start/end/step ..." без БД;
- раннер реально пишет nodeid/kind в run_events для строк реального subprocess
  pytest и передаёт TH_RUN_TOKEN/TH_URL/TH_RUN_ID в его env (плагина в этом
  фикстурном проекте нет — тест сам печатает "[TH] ..."-строки вместо него).
"""
import json
import sqlite3
import sys

from app.core import runner

from .conftest import poll_until, register_project


def test_parse_th_line_tracks_current_nodeid_across_calls():
    run_id = 12345
    runner._current_nodeid.pop(run_id, None)
    try:
        # до первого "start" — обычная строка без nodeid
        assert runner._parse_th_line(run_id, "pytest session starts") == ("line", None)

        assert runner._parse_th_line(run_id, "[TH] start tests/ui/test_x.py::test_foo[a b]") == (
            "test_start",
            "tests/ui/test_x.py::test_foo[a b]",
        )
        # внутри блока обычная строка получает текущий nodeid
        assert runner._parse_th_line(run_id, "some console output") == (
            "line",
            "tests/ui/test_x.py::test_foo[a b]",
        )
        assert runner._parse_th_line(
            run_id, "[TH] step tests/ui/test_x.py::test_foo[a b] 2 клик по кнопке"
        ) == ("step", "tests/ui/test_x.py::test_foo[a b]")
        assert runner._parse_th_line(run_id, "[TH] end tests/ui/test_x.py::test_foo[a b] passed") == (
            "test_end",
            "tests/ui/test_x.py::test_foo[a b]",
        )
        # после "end" — снова без nodeid
        assert runner._parse_th_line(run_id, "next test setup") == ("line", None)
    finally:
        runner._current_nodeid.pop(run_id, None)


def test_check_run_token_rejects_unknown_or_empty():
    run_id = 54321
    runner._run_tokens.pop(run_id, None)
    assert runner.check_run_token(run_id, "anything") is False
    assert runner.check_run_token(run_id, None) is False

    runner._run_tokens[run_id] = "secret-token"
    try:
        assert runner.check_run_token(run_id, "secret-token") is True
        assert runner.check_run_token(run_id, "wrong-token") is False
        assert runner.check_run_token(run_id, "") is False
    finally:
        runner._run_tokens.pop(run_id, None)


_TH_MARKED_TEST = '''\
def test_marked():
    print("[TH] start tests/test_sample.py::test_marked")
    print("[TH] step tests/test_sample.py::test_marked 1 открыли страницу")
    print("обычная строка внутри теста")
    assert True
    print("[TH] end tests/test_sample.py::test_marked passed")
'''

_PROBE_CONFTEST = '''\
import json
import os
from pathlib import Path


def pytest_configure(config):
    probe = {
        "th_run_token": os.environ.get("TH_RUN_TOKEN"),
        "th_url": os.environ.get("TH_URL"),
        "th_run_id": os.environ.get("TH_RUN_ID"),
    }
    Path(__file__).parent.joinpath("probe.json").write_text(json.dumps(probe))
'''


def _marked_project_dir(tmp_path):
    proj = tmp_path / "marked_proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_sample.py").write_text(_TH_MARKED_TEST)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    # pytest по умолчанию перехватывает stdout прошедшего теста и не льёт его в
    # реальный поток процесса (наш raw = raw.decode(...) читает именно его) — "-s"
    # имитирует то, как настоящий плагин (отдельная миссия) пишет "[TH] ..."-строки
    # мимо перехвата capsys, например через sys.__stdout__/логирование.
    # "-q" вдобавок к "-s": без него pytest пишет прогресс вида "tests/test_sample.py "
    # без перевода строки перед первым print()-ом теста, и наша "[TH] start ..."-строка
    # склеивается с этим префиксом в одну строку вывода.
    (proj / "pytest.ini").write_text("[pytest]\naddopts = -q -s\n")
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


async def test_execute_marks_run_events_and_passes_th_env(qa_client, isolated_allure_dir, tmp_path, db_path):
    project_dir = _marked_project_dir(tmp_path)
    await register_project(qa_client, "th_marked_proj", project_dir)

    resp = await qa_client.post(
        "/api/projects/th_marked_proj/runs", json={"target": "tests/test_sample.py::test_marked"}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/th_marked_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None, "прогон не завершился вовремя"
    assert final["status"] == "passed", final

    probe = json.loads((project_dir / "probe.json").read_text())
    assert probe["th_run_token"], "TH_RUN_TOKEN не передан pytest"
    assert probe["th_run_id"] == str(run_id)
    assert probe["th_url"].startswith("http://")

    # Токен прогона вычищается после завершения (_finalize) — плагину, отправившему
    # кадр уже после того, как раннер закрыл прогон, больше нечем авторизоваться.
    assert runner.check_run_token(run_id, probe["th_run_token"]) is False

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT line, nodeid, kind FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    finally:
        conn.close()

    nodeid = "tests/test_sample.py::test_marked"
    by_kind = {(r["kind"], r["nodeid"]): r["line"] for r in rows}
    assert ("test_start", nodeid) in by_kind
    assert ("test_end", nodeid) in by_kind
    assert ("step", nodeid) in by_kind
    assert any(k == "line" and n == nodeid for k, n in by_kind), "обычная строка внутри блока без nodeid"

    # строки вне start/end (заголовок pytest-сессии и т.п.) остаются kind='line' без nodeid
    assert any(r["kind"] == "line" and r["nodeid"] is None for r in rows)
