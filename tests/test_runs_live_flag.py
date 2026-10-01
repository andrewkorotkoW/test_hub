"""runs.live — флаг «Эфир» для прогона (докс/missions/2026-10-01_live_stream.md,
«Уточнение владельца 01.10»): миграция колонки app/db.py, поле RunCreate.live,
серверный лимит TH_LIVE_MAX_TESTS (app/config.py), env TH_LIVE=1 только когда
run.live (app/core/runner.py::_execute), поле live в ответах
GET /api/projects/{name}/runs и GET /api/runs/{id}/report, GET /api/config.

Задача 70165f07 (галочка «Эфир» в форме запуска/странице сборки) — отдельная,
здесь только бэкенд.
"""
import json
import sqlite3
import sys

from app.config import settings
from app.db import init_db

from .conftest import poll_until, register_project


# ------------------------------------------------------------------ миграция колонки

def test_migration_adds_live_column_to_old_runs_table_without_it(tmp_path, monkeypatch):
    old_db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(old_db_path)
    conn.execute(
        "CREATE TABLE runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "project TEXT NOT NULL,"
        "stand TEXT,"
        "target TEXT,"
        "status TEXT NOT NULL,"
        "started TEXT,"
        "finished TEXT,"
        "duration REAL,"
        "requested_by TEXT,"
        "counts TEXT NOT NULL DEFAULT '{}',"
        "marker TEXT,"
        "repeat INTEGER NOT NULL DEFAULT 1,"
        "label TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO runs (id, project, status, counts) VALUES (1, 'legacy_proj', 'passed', '{}')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()  # не должно падать на старой БД без runs.live

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "live" in cols

        old_row = conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()
        assert old_row["live"] == 0  # ALTER TABLE ... DEFAULT 0 -> существующие строки получают 0, не NULL

        conn.execute(
            "INSERT INTO runs (project, status, counts, live) VALUES ('legacy_proj', 'passed', '{}', 1)"
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM runs WHERE live = 1").fetchone()
        assert new_row is not None
    finally:
        conn.close()

    init_db()  # повторный запуск (рестарт сервиса) на уже мигрированной БД идемпотентен


def test_fresh_db_runs_table_already_has_live_column(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "live" in cols
    finally:
        conn.close()


# ------------------------------------------------------------------ поле live в ответах

async def test_create_run_with_live_saves_and_returns_it(qa_client, isolated_allure_dir, runnable_project_dir):
    await register_project(qa_client, "live_flag_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/live_flag_proj/runs",
        json={"target": "tests/test_sample.py::test_pass", "live": True},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["live"] is True
    run_id = body["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/live_flag_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None
    assert final["live"] is True  # GET .../runs тоже отдаёт live

    report = await qa_client.get(f"/api/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["live"] is True  # GET .../report тоже отдаёт live


async def test_create_run_without_live_defaults_to_false_no_regression(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    await register_project(qa_client, "no_live_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/no_live_proj/runs", json={"target": "tests/test_sample.py::test_pass"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["live"] is False
    assert body["status"] == "running"  # не затронуто новым полем


# ------------------------------------------------------------------ серверный лимит TH_LIVE_MAX_TESTS

async def test_create_run_live_over_limit_returns_422(
    qa_client, isolated_allure_dir, runnable_project_dir, monkeypatch
):
    """runnable_project_dir содержит 5 тестов (см. conftest._FIXTURE_TESTS) — лимит
    занижаем до 2, чтобы не плодить лишний фикстурный проект."""
    monkeypatch.setattr(settings, "TH_LIVE_MAX_TESTS", 2)
    await register_project(qa_client, "live_limit_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/live_limit_proj/runs", json={"target": "all", "live": True}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "Эфир доступен для прогонов до 2 тестов, выбрано 5"

    # прогон не должен был создаться
    rows = (await qa_client.get("/api/projects/live_limit_proj/runs")).json()
    assert rows == []


async def test_create_run_live_within_limit_passes(
    qa_client, isolated_allure_dir, runnable_project_dir, monkeypatch
):
    monkeypatch.setattr(settings, "TH_LIVE_MAX_TESTS", 5)
    await register_project(qa_client, "live_within_limit_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/live_within_limit_proj/runs", json={"target": "all", "live": True}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["live"] is True


async def test_create_run_without_live_ignores_limit(
    qa_client, isolated_allure_dir, runnable_project_dir, monkeypatch
):
    """Лимит эфира не должен мешать обычным (не-live) прогонам сколько угодно тестов."""
    monkeypatch.setattr(settings, "TH_LIVE_MAX_TESTS", 1)
    await register_project(qa_client, "no_live_limit_proj", runnable_project_dir)
    resp = await qa_client.post("/api/projects/no_live_limit_proj/runs", json={"target": "all"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["live"] is False


# ------------------------------------------------------------------ GET /api/config

async def test_get_config_returns_live_max_tests(qa_client, monkeypatch):
    monkeypatch.setattr(settings, "TH_LIVE_MAX_TESTS", 42)
    resp = await qa_client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json() == {"live_max_tests": 42}


# ------------------------------------------------------------------ env TH_LIVE только при live=true

_PROBE_CONFTEST = '''\
import json
import os
from pathlib import Path


def pytest_configure(config):
    probe = {"th_live": os.environ.get("TH_LIVE")}
    Path(__file__).parent.joinpath("probe.json").write_text(json.dumps(probe))
'''

_PLAIN_TEST = '''\
def test_probe():
    assert True
'''


def _probe_project_dir(tmp_path):
    proj = tmp_path / "live_probe_proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(_PLAIN_TEST)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe(project_dir):
    return json.loads((project_dir / "probe.json").read_text())


async def test_live_true_passes_th_live_env_to_pytest(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path)
    await register_project(qa_client, "live_env_proj", proj_dir)
    resp = await qa_client.post(
        "/api/projects/live_env_proj/runs", json={"target": "tests/test_probe.py", "live": True}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/live_env_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None and final["status"] == "passed", final
    assert _read_probe(proj_dir)["th_live"] == "1"


async def test_live_false_does_not_pass_th_live_env(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path)
    await register_project(qa_client, "no_live_env_proj", proj_dir)
    resp = await qa_client.post(
        "/api/projects/no_live_env_proj/runs", json={"target": "tests/test_probe.py"}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/no_live_env_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None and final["status"] == "passed", final
    assert _read_probe(proj_dir)["th_live"] is None


# ------------------------------------------------------------------ runner.count_target_tests

def test_count_target_tests():
    from app.core.runner import count_target_tests

    tree = {
        "tests/test_a.py": {"": ["test_one", "test_two"], "TestCls": ["test_three"]},
        "tests/test_b.py": {"": ["test_four"]},
    }
    assert count_target_tests(tree, "all") == 4
    assert count_target_tests(tree, "") == 4
    assert count_target_tests(tree, "tests/test_a.py::test_one") == 1
    assert count_target_tests(tree, "tests/test_a.py::TestCls::test_three") == 1
    assert count_target_tests(tree, "tests/test_a.py") == 3  # весь файл
    assert (
        count_target_tests(tree, "tests/test_a.py::test_one\ntests/test_b.py::test_four") == 2
    )
