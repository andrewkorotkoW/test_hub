"""runs.mobile — флаг «Мобильный (Pixel 7)» для прогона (docs/missions/
2026-10-06_mobile_frame.md, п.1): миграция колонки app/db.py, поле RunCreate.mobile,
env MOBILE=1 только когда run.mobile (app/core/runner.py::_execute), поле mobile
в ответах POST/GET /api/projects/{name}/runs и GET /api/runs/{id}/report, дефолтный
label «Мобильный (Pixel 7)», если label не передан и mobile=true.

Написано по образцу tests/test_runs_live_flag.py. В отличие от live, у mobile нет
серверного лимита числа тестов (миссия не требует) и нет отдельного поля в
GET /api/config — здесь это не проверяется.

Задача 7d61f59 (бэкенд: флаг runs.mobile + MOBILE=1 в раннере) — t1, здесь только тесты.
"""
import json
import sqlite3
import sys

from app.config import settings
from app.db import init_db

from .conftest import poll_until, register_project


# ------------------------------------------------------------------ миграция колонки

def test_migration_adds_mobile_column_to_old_runs_table_without_it(tmp_path, monkeypatch):
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
        "label TEXT,"
        "live INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "INSERT INTO runs (id, project, status, counts) VALUES (1, 'legacy_proj', 'passed', '{}')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()  # не должно падать на старой БД без runs.mobile (и без runs.live тоже мигрирует)

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "mobile" in cols

        old_row = conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()
        assert old_row["mobile"] == 0  # ALTER TABLE ... DEFAULT 0 -> существующие строки получают 0, не NULL

        conn.execute(
            "INSERT INTO runs (project, status, counts, mobile) VALUES ('legacy_proj', 'passed', '{}', 1)"
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM runs WHERE mobile = 1").fetchone()
        assert new_row is not None
    finally:
        conn.close()

    init_db()  # повторный запуск (рестарт сервиса) на уже мигрированной БД идемпотентен


def test_fresh_db_runs_table_already_has_mobile_column(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "mobile" in cols
    finally:
        conn.close()


# ------------------------------------------------------------------ поле mobile в ответах

async def test_create_run_with_mobile_saves_and_returns_it(qa_client, isolated_allure_dir, runnable_project_dir):
    await register_project(qa_client, "mobile_flag_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/mobile_flag_proj/runs",
        json={"target": "tests/test_sample.py::test_pass", "mobile": True},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mobile"] is True
    run_id = body["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/mobile_flag_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None
    assert final["mobile"] is True  # GET .../runs тоже отдаёт mobile

    report = await qa_client.get(f"/api/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["mobile"] is True  # GET .../report тоже отдаёт mobile


async def test_create_run_without_mobile_defaults_to_false_no_regression(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    await register_project(qa_client, "no_mobile_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/no_mobile_proj/runs", json={"target": "tests/test_sample.py::test_pass"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mobile"] is False
    assert body["status"] == "running"  # не затронуто новым полем


# ------------------------------------------------------------------ дефолтный label «Мобильный (Pixel 7)»

async def test_create_run_mobile_without_label_defaults_to_pixel7_label(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    """app/core/runner.py::submit_run: `if label is None and mobile: label = "Мобильный (Pixel 7)"`."""
    await register_project(qa_client, "mobile_label_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/mobile_label_proj/runs",
        json={"target": "tests/test_sample.py::test_pass", "mobile": True},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["label"] == "Мобильный (Pixel 7)"


async def test_create_run_mobile_with_explicit_label_keeps_it(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    """Явно переданный label не перезаписывается дефолтом даже при mobile=true."""
    await register_project(qa_client, "mobile_explicit_label_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/mobile_explicit_label_proj/runs",
        json={
            "target": "tests/test_sample.py::test_pass",
            "mobile": True,
            "label": "Моя сборка",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["label"] == "Моя сборка"


async def test_create_run_without_mobile_does_not_set_pixel7_label(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    await register_project(qa_client, "mobile_off_label_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/mobile_off_label_proj/runs",
        json={"target": "tests/test_sample.py::test_pass"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["label"] is None


# ----------------------------------------------- mobile=true без live=true не ломает сервер

async def test_create_run_mobile_true_without_live_does_not_require_live(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    """Включение «Мобильный» без «Эфир» — бэкенд не обязан сам включать live
    (это фронтовая логика t2), сервер должен принять запрос без ошибок."""
    await register_project(qa_client, "mobile_no_live_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/mobile_no_live_proj/runs",
        json={"target": "tests/test_sample.py::test_pass", "mobile": True},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mobile"] is True
    assert body["live"] is False  # live не включился сам по себе


# ------------------------------------------------------------------ env MOBILE только при mobile=true

_PROBE_CONFTEST = '''\
import json
import os
from pathlib import Path


def pytest_configure(config):
    probe = {"mobile": os.environ.get("MOBILE")}
    Path(__file__).parent.joinpath("probe.json").write_text(json.dumps(probe))
'''

_PLAIN_TEST = '''\
def test_probe():
    assert True
'''


def _probe_project_dir(tmp_path):
    proj = tmp_path / "mobile_probe_proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(_PLAIN_TEST)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe(project_dir):
    return json.loads((project_dir / "probe.json").read_text())


async def test_mobile_true_passes_mobile_env_to_pytest(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path)
    await register_project(qa_client, "mobile_env_proj", proj_dir)
    resp = await qa_client.post(
        "/api/projects/mobile_env_proj/runs", json={"target": "tests/test_probe.py", "mobile": True}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/mobile_env_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None and final["status"] == "passed", final
    assert _read_probe(proj_dir)["mobile"] == "1"


async def test_mobile_false_does_not_pass_mobile_env(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path)
    await register_project(qa_client, "no_mobile_env_proj", proj_dir)
    resp = await qa_client.post(
        "/api/projects/no_mobile_env_proj/runs", json={"target": "tests/test_probe.py"}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/no_mobile_env_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None and final["status"] == "passed", final
    assert _read_probe(proj_dir)["mobile"] is None
