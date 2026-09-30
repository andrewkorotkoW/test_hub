"""runs.label — «сборка тестов» (этап 2 миссии 2026-10-01_coverage_k_and_test_sets.md):
миграция колонки app/db.py, сохранение/фильтр в app/routers/runs.py, форматирование
в app/tg_bot.py::format_report. Реализация уже в main (коммит b61af30) — здесь только
тесты, покрывающие то, что ни сиблинг-задача (t1, test_coverage_traffic_*), ни более
ранние тесты runs (test_run_queue.py, test_run_target_list.py и т.п.) не проверяли.

Демо-сиды (пункт 7 миссии, `app/db.py::_seed_demo_project`) прогонов вообще не создают
(ни с label, ни без) — история прогонов Demo появляется только от реального прогона,
не из статических сидов. Условие задачи («если demo-сиды получили label — тест») здесь
не сработало, тест на это не пишем (см. отчёт)."""
import sqlite3

from app.db import init_db
from app.tg_bot import format_report

from .conftest import poll_until, register_project


# ------------------------------------------------------------------ миграция колонки

def test_migration_adds_label_column_to_old_runs_table_without_it(tmp_path, monkeypatch):
    from app.config import settings

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
        "repeat INTEGER NOT NULL DEFAULT 1"
        ")"
    )
    conn.execute(
        "INSERT INTO runs (id, project, status, counts) VALUES (1, 'legacy_proj', 'passed', '{}')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()  # не должно падать на старой БД без runs.label

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "label" in cols

        old_row = conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()
        assert old_row["project"] == "legacy_proj"
        assert old_row["label"] is None  # ALTER TABLE ADD COLUMN без DEFAULT -> NULL у существующих строк

        conn.execute(
            "INSERT INTO runs (project, status, counts, label) VALUES ('legacy_proj', 'passed', '{}', 'smoke')"
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM runs WHERE label = 'smoke'").fetchone()
        assert new_row is not None
    finally:
        conn.close()

    init_db()  # повторный запуск (рестарт сервиса) на уже мигрированной БД идемпотентен


def test_fresh_db_runs_table_already_has_label_column(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "label" in cols
    finally:
        conn.close()


# ------------------------------------------------------------------ сохранение label при создании прогона

async def test_create_run_with_label_saves_and_returns_it(qa_client, isolated_allure_dir, runnable_project_dir):
    await register_project(qa_client, "label_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/label_proj/runs",
        json={"target": "tests/test_sample.py", "label": "notifications"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["label"] == "notifications"
    run_id = body["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/label_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None
    assert final["label"] == "notifications"  # label доживает до финального статуса

    report = await qa_client.get(f"/api/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["label"] == "notifications"  # GET .../report тоже отдаёт label


async def test_create_run_without_label_is_null_no_regression(qa_client, isolated_allure_dir, runnable_project_dir):
    """Регрессия: запуск без поля label (как до этапа 2) должен работать ровно как раньше —
    201, статус running/started, все прежние поля на месте, label просто None."""
    await register_project(qa_client, "no_label_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/no_label_proj/runs", json={"target": "tests/test_sample.py"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["label"] is None
    assert body["status"] == "running"
    assert body["target"] == "tests/test_sample.py"
    assert body["started"] is not None


# ------------------------------------------------------------------ фильтр ?label=

async def test_list_runs_filter_by_label_returns_only_matching_and_all_without_param(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    await register_project(qa_client, "filter_proj", runnable_project_dir)

    async def run_with_label(label):
        resp = await qa_client.post(
            "/api/projects/filter_proj/runs",
            json={"target": "tests/test_sample.py", **({"label": label} if label else {})},
        )
        assert resp.status_code == 201, resp.text
        run_id = resp.json()["id"]

        async def finished():
            rows = (await qa_client.get("/api/projects/filter_proj/runs")).json()
            row = next(r for r in rows if r["id"] == run_id)
            return row if row["status"] in {"passed", "failed"} else None

        assert await poll_until(finished, timeout=15) is not None
        return run_id

    id_a = await run_with_label("area-a")
    id_b = await run_with_label("area-b")
    id_none = await run_with_label(None)

    only_a = (await qa_client.get("/api/projects/filter_proj/runs?label=area-a")).json()
    assert [r["id"] for r in only_a] == [id_a]

    only_b = (await qa_client.get("/api/projects/filter_proj/runs?label=area-b")).json()
    assert [r["id"] for r in only_b] == [id_b]

    unknown_label = (await qa_client.get("/api/projects/filter_proj/runs?label=does-not-exist")).json()
    assert unknown_label == []

    everything = (await qa_client.get("/api/projects/filter_proj/runs")).json()
    assert {r["id"] for r in everything} == {id_a, id_b, id_none}
    assert next(r for r in everything if r["id"] == id_none)["label"] is None


# ------------------------------------------------------------------ format_report «сборка <label>»

def test_format_report_includes_sborka_label_in_title():
    report = {
        "id": 42,
        "project": "bike_fit",
        "status": "passed",
        "duration": 3.0,
        "label": "notifications",
        "counts": {"passed": 2, "failed": 0, "broken": 0, "skipped": 0},
        "tests": [],
    }
    text = format_report(report)
    first_line = text.splitlines()[0]
    assert first_line == "Прогон #42 (bike_fit, сборка notifications) — пройден"


def test_format_report_without_label_has_no_sborka_suffix():
    report = {
        "id": 43,
        "project": "bike_fit",
        "status": "passed",
        "duration": 3.0,
        "counts": {"passed": 2, "failed": 0, "broken": 0, "skipped": 0},
        "tests": [],
    }
    text = format_report(report)
    first_line = text.splitlines()[0]
    assert first_line == "Прогон #43 (bike_fit) — пройден"
    assert "сборка" not in text
