"""Миграция таблицы run_test_videos (app/db.py SCHEMA, контракт п.3,
docs/missions/2026-10-01_live_stream.md): должна появляться и на пустой БД, и
на БД со старой схемой (сидированной до этой миссии, без таблицы), без падений
init_db() и без потери уже существующих данных в других таблицах.

Тот же приём, что и tests/test_testcases_migration.py::_old_schema_without_testcases
(вырезаем нужные CREATE TABLE из актуального SCHEMA — имитация реальной БД,
сидированной старой версией test_hub)."""
import sqlite3

import pytest

from app.config import settings
from app.db import SCHEMA, init_db


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def test_init_db_creates_run_test_videos_table_on_empty_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert "run_test_videos" in _table_names(conn)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(run_test_videos)").fetchall()}
        assert cols == {"run_id", "nodeid", "path", "duration_ms", "size", "created_at"}
    finally:
        conn.close()


def _old_schema_without_run_test_videos() -> str:
    statements = [
        stmt.strip() + ";"
        for stmt in SCHEMA.split(";")
        if stmt.strip() and "run_test_videos" not in stmt
    ]
    return "\n".join(statements)


@pytest.fixture()
def old_schema_db_path(tmp_path, monkeypatch):
    path = tmp_path / "old_test_hub.db"
    monkeypatch.setattr(settings, "DB_PATH", path)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_old_schema_without_run_test_videos())
        conn.execute(
            "INSERT INTO users (login, password_hash, role, onboarded) VALUES ('qa', 'x', 'qa', 1)"
        )
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES ('legacy_proj', '/tmp/legacy', '.venv', '[]')"
        )
        conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
            "VALUES ('legacy_proj', NULL, 'all', 'passed', '2024-01-01T00:00:00', 'qa', '{}')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_init_db_adds_run_test_videos_table_to_old_schema_without_data_loss(old_schema_db_path):
    conn = sqlite3.connect(old_schema_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert "run_test_videos" not in _table_names(conn)
    finally:
        conn.close()

    init_db()  # не должно падать на БД без run_test_videos

    conn = sqlite3.connect(old_schema_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert "run_test_videos" in _table_names(conn)
        # существующие данные не тронуты
        assert conn.execute("SELECT login FROM users WHERE login = 'qa'").fetchone() is not None
        assert conn.execute("SELECT name FROM projects WHERE name = 'legacy_proj'").fetchone() is not None
        assert conn.execute("SELECT id FROM runs WHERE project = 'legacy_proj'").fetchone() is not None

        # новая таблица реально рабочая: можно вставить и прочитать запись
        conn.execute(
            "INSERT INTO run_test_videos (run_id, nodeid, path, duration_ms, size, created_at) "
            "VALUES (1, 'tests/test_x.py::test_a', '/tmp/a.webm', 1000, 10, '2024-01-01T00:00:00')"
        )
        conn.commit()
        row = conn.execute(
            "SELECT nodeid FROM run_test_videos WHERE run_id = 1"
        ).fetchone()
        assert row["nodeid"] == "tests/test_x.py::test_a"
    finally:
        conn.close()


def test_init_db_is_idempotent_on_run_test_videos_table(db_path):
    init_db()
    init_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert "run_test_videos" in _table_names(conn)
    finally:
        conn.close()


def test_run_test_videos_primary_key_replaces_on_conflict(db_path):
    """PRIMARY KEY (run_id, nodeid) — таблица не накапливает дубликаты при повторной
    загрузке видео того же теста (сам router.py делает явный DELETE перед INSERT,
    см. app/routers/runs.py::upload_test_video, но и без него PK не даёт вставить
    вторую строку с тем же run_id/nodeid)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "INSERT INTO run_test_videos (run_id, nodeid, path, duration_ms, size, created_at) "
            "VALUES (1, 'tests/test_x.py::test_a', '/tmp/a.webm', 1000, 10, '2024-01-01T00:00:00')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO run_test_videos (run_id, nodeid, path, duration_ms, size, created_at) "
                "VALUES (1, 'tests/test_x.py::test_a', '/tmp/b.webm', 2000, 20, '2024-01-02T00:00:00')"
            )
    finally:
        conn.close()
