"""Seed-данные при первом старте (init_db на чистой БД)."""

import sqlite3

from app.db import SEED_PROJECTS, SEED_USERS, init_db


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_seed_users_have_expected_roles(db_path):
    conn = _connect(db_path)
    try:
        rows = {r["login"]: r for r in conn.execute("SELECT * FROM users").fetchall()}
    finally:
        conn.close()

    assert set(rows.keys()) == {"qa", "manager", "customer"}
    assert rows["qa"]["role"] == "qa"
    assert rows["manager"]["role"] == "manager"
    assert rows["customer"]["role"] == "customer"
    # sanity: пароли захешированы, не хранятся в открытом виде
    for login_, row in rows.items():
        assert row["password_hash"] != login_
        assert row["password_hash"].startswith("scrypt$")


def test_seed_onboarded_flags_match_seed_table(db_path):
    conn = _connect(db_path)
    try:
        rows = {r["login"]: r["onboarded"] for r in conn.execute("SELECT * FROM users").fetchall()}
    finally:
        conn.close()

    expected = {login_: onboarded for login_, _password, _role, onboarded in SEED_USERS}
    assert rows == expected


def test_seed_projects_present(db_path):
    conn = _connect(db_path)
    try:
        names = {r["name"] for r in conn.execute("SELECT name FROM projects").fetchall()}
    finally:
        conn.close()

    expected_names = {name for name, _path, _venv in SEED_PROJECTS}
    assert expected_names == {"bike_fit", "Velo_bot"}
    assert expected_names <= names


def test_seed_is_idempotent(db_path):
    conn = _connect(db_path)
    try:
        before_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        before_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    finally:
        conn.close()

    # Повторная инициализация на уже заполненной БД не должна дублировать seed-данные.
    init_db()

    conn = _connect(db_path)
    try:
        after_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        after_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    finally:
        conn.close()

    assert after_users == before_users == 3
    assert after_projects == before_projects == 2


async def test_seed_projects_visible_via_api(qa_client):
    resp = await qa_client.get("/api/projects")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert {"bike_fit", "Velo_bot"} <= names
