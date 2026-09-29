"""Разметка run_events по nodeid/kind (этап 2 окна прогона) — гэпы, не покрытые
сиблинг-задачей (см. tests/test_run_events_nodeid.py, tests/test_run_frames.py,
tests/test_run_tests_api.py, tests/test_admin.py — там уже разбор "[TH] ..."-строк
через реальный subprocess, TH_RUN_TOKEN/TH_URL/TH_RUN_ID, POST/GET frames с лимитами
и токеном, GET tests/log/frames + WS-реплей на синтетических run_events, чистка
frames_dir при удалении прогона):

1. Миграция самой колонки nodeid/kind на старой БД без них (пункт 1 задания) —
   сиблинг-задача мигрировала другие колонки (users.role, projects.color) по этому
   же _migrate_add_column, но не саму run_events.nodeid/kind.
2. Совместимость: проект БЕЗ плагина (обычные print/собственный вывод pytest, без
   "[TH] ..."-строк) — весь run_events должен остаться kind='line'/nodeid=NULL,
   как и до этой задачи. Реальный subprocess pytest, не синтетические INSERT.
3. Старый (домиграционный по сути) завершённый прогон — без единого run_events и
   без каталога allure-results вовсе — GET tests/log/frames не должны падать 500,
   а отдавать пустой/деградированный ответ.
"""
import sqlite3
from datetime import datetime

from app.db import init_db

from .conftest import poll_until, register_project


def test_migration_adds_nodeid_and_kind_columns_and_defaults_existing_rows_to_line(tmp_path, monkeypatch):
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
        "counts TEXT NOT NULL DEFAULT '{}'"
        ")"
    )
    conn.execute(
        "CREATE TABLE run_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,"
        "ts TEXT NOT NULL,"
        "line TEXT NOT NULL"
        ")"
    )
    conn.execute("INSERT INTO runs (id, project, status) VALUES (1, 'legacy_proj', 'passed')")
    conn.execute(
        "INSERT INTO run_events (run_id, ts, line) VALUES (1, ?, 'старая строка лога без разметки')",
        (datetime.now().isoformat(timespec="seconds"),),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()  # не должно падать на старой БД без nodeid/kind

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(run_events)").fetchall()}
        assert {"nodeid", "kind"} <= cols

        old_row = conn.execute("SELECT * FROM run_events WHERE run_id = 1").fetchone()
        assert old_row["line"] == "старая строка лога без разметки"
        assert old_row["nodeid"] is None
        assert old_row["kind"] == "line"

        # DEFAULT 'line' у самой колонки покрывает и вставки без явного kind
        # (например, если какой-то код ещё не знает про новую колонку).
        conn.execute(
            "INSERT INTO run_events (run_id, ts, line) VALUES (1, ?, 'ещё одна старая строка')",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
        new_row = conn.execute(
            "SELECT * FROM run_events WHERE line = 'ещё одна старая строка'"
        ).fetchone()
        assert new_row["kind"] == "line"
        assert new_row["nodeid"] is None
    finally:
        conn.close()

    # повторный init_db (обычный рестарт сервиса на уже мигрированной БД) идемпотентен
    init_db()


async def test_execute_without_plugin_all_events_stay_kind_line_no_nodeid(
    qa_client, isolated_allure_dir, runnable_project_dir, db_path
):
    """Проект без test_hub_plugin (никаких "[TH] ..."-строк в выводе pytest) должен
    продолжать работать ровно как до этой задачи: все run_events этого прогона —
    kind='line', nodeid=NULL. runnable_project_dir (tests/conftest.py) — обычный
    фикстурный проект с проходящими/падающими тестами и без какой-либо TH-разметки."""
    await register_project(qa_client, "no_plugin_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/no_plugin_proj/runs", json={"target": "tests/test_sample.py"}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/no_plugin_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    assert await poll_until(finished, timeout=15) is not None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT kind, nodeid FROM run_events WHERE run_id = ?", (run_id,)
        ).fetchall()
    finally:
        conn.close()
    assert rows, "прогон должен был хоть что-то залогировать"
    assert all(r["kind"] == "line" for r in rows)
    assert all(r["nodeid"] is None for r in rows)

    # GET .../tests для такого прогона (уже завершён, allure-результаты есть, но
    # без TH-разметки) не падает и просто перечисляет тесты из allure, без кадров.
    tests_resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert tests_resp.status_code == 200
    items = tests_resp.json()
    assert items, "allure-результаты должны были дать хотя бы один тест"
    assert all(item["has_frames"] is False for item in items)


async def test_tests_log_frames_endpoints_degrade_gracefully_for_run_without_any_events(
    qa_client, isolated_allure_dir, db_path
):
    """Прогон, у которого нет вообще ни одной строки run_events и нет каталога
    allure-results (искусственно смоделированный "древний" прогон, ещё до всякой
    разметки) — GET tests/log/frames должны деградировать до пустого ответа,
    а не падать 500."""
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now().isoformat(timespec="seconds")
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, finished, requested_by, counts) "
            "VALUES ('ancient_proj', NULL, 'all', 'passed', ?, ?, 'qa', '{}')",
            (now, now),
        )
        conn.commit()
        run_id = cur.lastrowid
    finally:
        conn.close()

    tests_resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert tests_resp.status_code == 200
    assert tests_resp.json() == []

    log_resp = await qa_client.get(f"/api/runs/{run_id}/tests/tests%2Fx.py%3A%3Atest_a/log")
    assert log_resp.status_code == 200
    assert log_resp.json() == []

    frames_resp = await qa_client.get(f"/api/runs/{run_id}/tests/tests%2Fx.py%3A%3Atest_a/frames")
    assert frames_resp.status_code == 200
    assert frames_resp.json() == []
