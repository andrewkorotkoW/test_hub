import json
import sqlite3

from .config import settings
from .security import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    login TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('qa', 'manager', 'customer', 'superadmin')),
    onboarded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    venv TEXT NOT NULL,
    stands TEXT NOT NULL DEFAULT '[]',
    use_env_flag INTEGER NOT NULL DEFAULT 0
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
    counts TEXT NOT NULL DEFAULT '{}',
    marker TEXT,
    repeat INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    line TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS share_links (
    token TEXT PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS flaky_stats (
    project TEXT NOT NULL,
    stand TEXT NOT NULL,
    test TEXT NOT NULL,
    runs INTEGER NOT NULL DEFAULT 0,
    fails INTEGER NOT NULL DEFAULT 0,
    flips INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    last_statuses TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT,
    PRIMARY KEY (project, stand, test)
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL REFERENCES projects(name) ON DELETE CASCADE,
    stand TEXT,
    target TEXT NOT NULL DEFAULT 'all',
    marker TEXT,
    cron TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    notify_chat_ids TEXT NOT NULL DEFAULT '[]',
    last_run_id INTEGER,
    next_run_at TEXT
);

CREATE TABLE IF NOT EXISTS xfail_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    stand TEXT NOT NULL,
    test TEXT NOT NULL,
    reason TEXT,
    first_seen TEXT NOT NULL,
    last_run_id INTEGER,
    state TEXT NOT NULL CHECK (state IN ('xfail', 'xpass')),
    issue_url TEXT,
    note TEXT,
    UNIQUE (project, stand, test)
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

SUPERADMIN_LOGIN = "admin"
SUPERADMIN_PASSWORD = "admin"

VSHGU_PROJECT_NAME = "auto_tests_vshgu_cloude"
VSHGU_PROJECT_PATH = "/Users/andreykorotkow/PycharmProjects/auto_tests_vshgu_cloude"
VSHGU_PROJECT_VENV = ".venv"
VSHGU_STANDS = ("develop", "stage")


def get_connection() -> sqlite3.Connection:
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: async route handlers run on the event loop thread while
    # sync Depends(get_db) is resolved in a threadpool worker thread, so the connection
    # can cross threads within a single request (never used concurrently from two).
    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
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


def _users_role_check_outdated(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    return row is not None and "superadmin" not in (row["sql"] or "")


def _migrate_users_role_check(conn: sqlite3.Connection) -> None:
    """Существующая БД (workspace/test_hub.db) уже содержит таблицу users с CHECK,
    не знающим про 'superadmin' — CREATE TABLE IF NOT EXISTS в SCHEMA её не трогает.
    SQLite не умеет ALTER TABLE ... DROP/ADD CONSTRAINT, поэтому пересоздаём таблицу
    с новым CHECK и переносим данные, не теряя существующих пользователей."""
    conn.execute("ALTER TABLE users RENAME TO users_old")
    conn.execute(
        "CREATE TABLE users ("
        "login TEXT PRIMARY KEY,"
        "password_hash TEXT NOT NULL,"
        "role TEXT NOT NULL CHECK (role IN ('qa', 'manager', 'customer', 'superadmin')),"
        "onboarded INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "INSERT INTO users (login, password_hash, role, onboarded) "
        "SELECT login, password_hash, role, onboarded FROM users_old"
    )
    conn.execute("DROP TABLE users_old")
    conn.commit()


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """PRAGMA table_info + ALTER TABLE ... ADD COLUMN для колонок, добавленных к уже
    существующей таблице (CREATE TABLE IF NOT EXISTS в SCHEMA их не тронет)."""
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        conn.commit()


def _seed_vshgu_project(conn: sqlite3.Connection) -> None:
    """Гарантирует наличие проекта auto_tests_vshgu_cloude и его стендов develop/stage.
    Идемпотентно и вызывается на каждом старте (не только _seed_if_empty — боевая БД
    непустая): вставляет только отсутствующие записи, не трогая поля, изменённые
    пользователем вручную (например, use_env_flag, выключенный через API)."""
    exists = conn.execute(
        "SELECT 1 FROM projects WHERE name = ?", (VSHGU_PROJECT_NAME,)
    ).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands, use_env_flag) VALUES (?, ?, ?, '[]', 1)",
            (VSHGU_PROJECT_NAME, VSHGU_PROJECT_PATH, VSHGU_PROJECT_VENV),
        )
    for stand_name in VSHGU_STANDS:
        stand_exists = conn.execute(
            "SELECT 1 FROM stands WHERE project = ? AND name = ?", (VSHGU_PROJECT_NAME, stand_name)
        ).fetchone()
        if not stand_exists:
            conn.execute(
                "INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)",
                (VSHGU_PROJECT_NAME, stand_name),
            )
    conn.commit()


def _seed_vshgu_schedules(conn: sqlite3.Connection) -> None:
    """Выключенное расписание ночного прогона для auto_tests_vshgu_cloude: develop,
    все тесты, 03:00 по будням (пн-пт). Идемпотентно и вызывается на каждом старте,
    как и _seed_vshgu_project — вставляет запись, только если расписания с такими
    project/stand/cron ещё нет, не трогая изменённые вручную через API.

    Правило владельца (см. задачу): stage не сидируем вообще — второе расписание
    для stage сознательно не создаётся. next_run_at оставляем NULL: расписание
    выключено (enabled=0), scheduler_loop (app.core.schedule) не подхватит его,
    пока next_run_at не появится — это происходит автоматически при включении
    через PUT /api/projects/{name}/schedules/{id} (schedule.update_schedule
    пересчитывает next_run_at при переходе enabled 0 -> 1), так что здесь не нужно
    импортировать app.core.schedule и считать cron самим (db.py и так не тянет
    зависимостей на app.core.*, см. остальной модуль)."""
    cron = "0 3 * * 1-5"
    exists = conn.execute(
        "SELECT 1 FROM schedules WHERE project = ? AND stand = ? AND cron = ?",
        (VSHGU_PROJECT_NAME, "develop", cron),
    ).fetchone()
    if exists:
        return
    chat_ids = sorted(settings.TH_TG_ALLOWED_IDS)[:1]
    conn.execute(
        "INSERT INTO schedules (project, stand, target, marker, cron, enabled, notify_chat_ids, next_run_at) "
        "VALUES (?, 'develop', 'all', NULL, ?, 0, ?, NULL)",
        (VSHGU_PROJECT_NAME, cron, json.dumps(chat_ids)),
    )
    conn.commit()


def _seed_superadmin(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM users WHERE login = ?", (SUPERADMIN_LOGIN,)
    ).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, ?, ?)",
        (SUPERADMIN_LOGIN, hash_password(SUPERADMIN_PASSWORD), "superadmin", 1),
    )
    conn.commit()


def _seed_tg_bot_user(conn: sqlite3.Connection) -> None:
    """Сервисная учётка Telegram-бота (app/tg_bot.py): роль 'customer' — ровно те
    права, что нужны боту (смотреть проекты/стенды/дерево, запускать прогоны,
    смотреть отчёты, без CRUD и без отмены). Идемпотентно, как _seed_superadmin:
    если логин уже есть (в т.ч. с паролем, изменённым вручную), не трогаем."""
    exists = conn.execute(
        "SELECT 1 FROM users WHERE login = ?", (settings.TH_TG_SERVICE_LOGIN,)
    ).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, ?, ?)",
        (
            settings.TH_TG_SERVICE_LOGIN,
            hash_password(settings.TH_TG_SERVICE_PASSWORD),
            "customer",
            1,
        ),
    )
    conn.commit()


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        if _users_role_check_outdated(conn):
            _migrate_users_role_check(conn)
        _migrate_add_column(conn, "projects", "use_env_flag", "use_env_flag INTEGER NOT NULL DEFAULT 0")
        _migrate_add_column(conn, "runs", "marker", "marker TEXT")
        _migrate_add_column(conn, "runs", "repeat", "repeat INTEGER NOT NULL DEFAULT 1")
        # flaky_stats, xfail_registry и schedules сами по себе — новые таблицы (не
        # существующие с другой схемой в старых БД), поэтому их создание уже покрыто
        # CREATE TABLE IF NOT EXISTS в SCHEMA выше и отдельной ALTER-миграции, как
        # для колонок, не требует.
        _seed_if_empty(conn)
        _seed_superadmin(conn)
        _seed_vshgu_project(conn)
        _seed_vshgu_schedules(conn)
        _seed_tg_bot_user(conn)
    finally:
        conn.close()
