"""Миграция таблиц test_cases/test_case_attachments (app/db.py SCHEMA): должны
появляться и на пустой БД, и на БД со старой схемой (сидированной до этапа 2
вкладки «Тест-кейсы», без этих таблиц), без падений init_db() и без потери
уже существующих данных в других таблицах."""
import sqlite3

import pytest

from app.config import settings
from app.db import SCHEMA, init_db


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def test_init_db_creates_testcases_tables_on_empty_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        names = _table_names(conn)
        assert "test_cases" in names
        assert "test_case_attachments" in names
    finally:
        conn.close()


def test_testcases_table_columns(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(test_cases)").fetchall()}
        assert cols == {
            "id", "project", "section", "title", "steps", "precondition",
            "priority", "nodeid", "case_key", "requirement", "source", "updated_at", "updated_by",
        }
        att_cols = {row["name"] for row in conn.execute("PRAGMA table_info(test_case_attachments)").fetchall()}
        assert att_cols == {"id", "case_id", "step_n", "path", "source", "created_at"}
    finally:
        conn.close()


def _old_schema_without_testcases() -> str:
    """SCHEMA этапа до вкладки «Тест-кейсы»: все таблицы, кроме test_cases/
    test_case_attachments — имитация реальной БД, сидированной старой версией
    test_hub (workspace/test_hub.db на машине владельца)."""
    statements = [
        stmt.strip() + ";"
        for stmt in SCHEMA.split(";")
        if stmt.strip() and "test_cases" not in stmt and "test_case_attachments" not in stmt
    ]
    return "\n".join(statements)


@pytest.fixture()
def old_schema_db_path(tmp_path, monkeypatch):
    path = tmp_path / "old_test_hub.db"
    monkeypatch.setattr(settings, "DB_PATH", path)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_old_schema_without_testcases())
        conn.execute(
            "INSERT INTO users (login, password_hash, role, onboarded) VALUES ('qa', 'x', 'qa', 1)"
        )
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES ('legacy_proj', '/tmp/legacy', '.venv', '[]')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_init_db_adds_testcases_tables_to_old_schema_without_data_loss(old_schema_db_path):
    conn = sqlite3.connect(old_schema_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert "test_cases" not in _table_names(conn)
        assert "test_case_attachments" not in _table_names(conn)
    finally:
        conn.close()

    init_db()  # не должно падать на БД без test_cases/test_case_attachments

    conn = sqlite3.connect(old_schema_db_path)
    conn.row_factory = sqlite3.Row
    try:
        names = _table_names(conn)
        assert "test_cases" in names
        assert "test_case_attachments" in names
        # существующие данные не тронуты
        assert conn.execute("SELECT login FROM users WHERE login = 'qa'").fetchone() is not None
        assert conn.execute("SELECT name FROM projects WHERE name = 'legacy_proj'").fetchone() is not None
    finally:
        conn.close()


def test_init_db_is_idempotent_on_testcases_tables(db_path):
    init_db()
    init_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        names = _table_names(conn)
        assert "test_cases" in names
        assert "test_case_attachments" in names
    finally:
        conn.close()


@pytest.fixture()
def old_testcases_schema_db_path(tmp_path, monkeypatch):
    """test_cases существует, но без case_key/requirement (до этой миссии) —
    уже содержит кейс с nodeid, как на боевой БД до апгрейда."""
    path = tmp_path / "old_testcases_test_hub.db"
    monkeypatch.setattr(settings, "DB_PATH", path)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_old_schema_without_testcases())
        conn.execute(
            "CREATE TABLE test_cases ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL, section TEXT NOT NULL, "
            "title TEXT NOT NULL, steps TEXT NOT NULL DEFAULT '[]', precondition TEXT, "
            "priority TEXT NOT NULL DEFAULT 'medium', nodeid TEXT, "
            "source TEXT NOT NULL DEFAULT 'generated', updated_at TEXT, updated_by TEXT, "
            "UNIQUE (project, nodeid))"
        )
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES ('legacy_proj', '/tmp/legacy', '.venv', '[]')"
        )
        conn.execute(
            "INSERT INTO test_cases (project, section, title, nodeid, source, updated_at) "
            "VALUES ('legacy_proj', 'api/buk', 'Старый кейс', 'tests/api/buk/test_x.py::test_y', 'generated', '2024-01-01')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_init_db_adds_case_key_and_backfills_it_from_nodeid(old_testcases_schema_db_path):
    init_db()  # не должно падать: case_key/requirement добавляются ALTER TABLE
    conn = sqlite3.connect(old_testcases_schema_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(test_cases)").fetchall()}
        assert {"case_key", "requirement"} <= cols
        row = conn.execute(
            "SELECT * FROM test_cases WHERE project = 'legacy_proj' AND nodeid = 'tests/api/buk/test_x.py::test_y'"
        ).fetchone()
        assert row["case_key"] == "tests/api/buk/test_x.py::test_y"  # бэкфилл из nodeid, повторный импорт найдёт кейс

        # уникальный индекс (project, case_key) реально создан и работает
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO test_cases (project, section, title, steps, priority, case_key, source, updated_at) "
                "VALUES ('legacy_proj', 'x', 'dup', '[]', 'medium', 'tests/api/buk/test_x.py::test_y', 'generated', '2024-01-01')"
            )
    finally:
        conn.close()
