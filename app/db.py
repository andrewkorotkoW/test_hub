import sqlite3

from .config import settings
from .security import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    login TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('qa', 'manager', 'customer')),
    onboarded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    venv TEXT NOT NULL,
    stands TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS stands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL REFERENCES projects(name) ON DELETE CASCADE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    login TEXT,
    UNIQUE (project, name)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    stand TEXT,
    target TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'passed', 'failed', 'cancelled')),
    started TEXT,
    finished TEXT,
    duration REAL,
    requested_by TEXT,
    counts TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    line TEXT NOT NULL
);
"""

SEED_USERS = [
    ("qa", "qa", "qa", 1),
    ("manager", "manager", "manager", 0),
    ("customer", "customer", "customer", 1),
]

SEED_PROJECTS = [
    ("bike_fit", "/Users/andreykorotkow/PycharmProjects/bike_fit", ".venv"),
    ("Velo_bot", "/Users/andreykorotkow/PycharmProjects/Velo_bot", ".venv"),
]


def get_connection() -> sqlite3.Connection:
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count:
        return
    for login, password, role, onboarded in SEED_USERS:
        conn.execute(
            "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, ?, ?)",
            (login, hash_password(password), role, onboarded),
        )
    for name, path, venv in SEED_PROJECTS:
        conn.execute(
            "INSERT OR IGNORE INTO projects (name, path, venv, stands) VALUES (?, ?, ?, '[]')",
            (name, path, venv),
        )
    conn.commit()


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _seed_if_empty(conn)
    finally:
        conn.close()
