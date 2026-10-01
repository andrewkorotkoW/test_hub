import json
import logging
import secrets
import sqlite3
from pathlib import Path

from .config import settings
from .security import hash_password

logger = logging.getLogger(__name__)

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
    use_env_flag INTEGER NOT NULL DEFAULT 0,
    color TEXT
);

CREATE TABLE IF NOT EXISTS stands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL REFERENCES projects(name) ON DELETE CASCADE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    login TEXT,
    manual_only INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project, name)
);

CREATE TABLE IF NOT EXISTS stand_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL REFERENCES projects(name) ON DELETE CASCADE,
    stand TEXT NOT NULL,
    name TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT 'all',
    marker TEXT,
    FOREIGN KEY (project, stand) REFERENCES stands(project, name) ON DELETE CASCADE
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
    repeat INTEGER NOT NULL DEFAULT 1,
    label TEXT,
    live INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    line TEXT NOT NULL,
    nodeid TEXT,
    kind TEXT NOT NULL DEFAULT 'line'
);

CREATE TABLE IF NOT EXISTS run_test_videos (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    nodeid TEXT NOT NULL,
    path TEXT NOT NULL,
    duration_ms INTEGER,
    size INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, nodeid)
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

CREATE TABLE IF NOT EXISTS test_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL REFERENCES projects(name) ON DELETE CASCADE,
    section TEXT NOT NULL,
    title TEXT NOT NULL,
    steps TEXT NOT NULL DEFAULT '[]',
    precondition TEXT,
    priority TEXT NOT NULL DEFAULT 'medium',
    nodeid TEXT,
    case_key TEXT,
    requirement TEXT,
    source TEXT NOT NULL DEFAULT 'generated' CHECK (source IN ('generated', 'manual')),
    updated_at TEXT,
    updated_by TEXT,
    UNIQUE (project, nodeid)
);

CREATE TABLE IF NOT EXISTS test_case_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    step_n INTEGER NOT NULL,
    path TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('allure', 'manual')),
    created_at TEXT NOT NULL
);
"""

SEED_USERS = [
    ("qa", "qa", "qa", 1),
    ("manager", "manager", "manager", 0),
    ("customer", "customer", "customer", 1),
]

SEED_PROJECTS = [
    ("bike_fit", str(settings.TH_PROJECTS_ROOT / "bike_fit"), ".venv"),
    ("Velo_bot", str(settings.TH_PROJECTS_ROOT / "Velo_bot"), ".venv"),
]

SUPERADMIN_LOGIN = "admin"
SUPERADMIN_PASSWORD = "admin"

VSHGU_PROJECT_NAME = "VSHGU"
VSHGU_PROJECT_PATH = str(settings.TH_VSHGU_PATH)
VSHGU_PROJECT_VENV = ".venv"
VSHGU_STANDS = ("develop", "stage")
VSHGU_MANUAL_ONLY_STAND = "stage"

# Демо-проект: единственный seed-проект, чей путь гарантированно существует у
# любого, кто склонировал test_hub (в отличие от SEED_PROJECTS/VSHGU_PROJECT_PATH
# выше — это личные абсолютные пути владельца на его машине). Путь вычисляется
# от расположения этого файла, а не хардкодится строкой, чтобы работать после
# клонирования в произвольную директорию.
DEMO_PROJECT_NAME = "Demo"
DEMO_PROJECT_PATH = str(Path(__file__).resolve().parent.parent / "demo")
# Пустая строка — раннер (app/core/runner.py::_venv_python) резолвит её в
# интерпретатор самого test_hub, у демо-проекта нет собственного venv.
DEMO_PROJECT_VENV = ""
DEMO_STAND_NAME = "local"
DEMO_PROJECT_COLOR = "#22c55e"  # зелёный из PROJECT_COLOR_PALETTE, не занят SEED_PROJECTS/VSHGU
DEMO_SCHEDULE_CRON = "0 4 * * 1-5"

# Пресеты запуска для стенда stage: сидируются один раз, сразу при первом создании
# этого стенда (см. _seed_vshgu_project) — target='all' там, где в задаче указан
# только marker, чтобы поле оставалось NOT NULL и совместимым с submit_run/RunCreate.
VSHGU_STAGE_PRESETS = (
    ("Smoke", "all", "smoke"),
    ("БУК", "tests/api/buk\ntests/ui/buk", None),
    (
        "LPD",
        "tests/api/create_activity/lpd\ntests/ui/test_user_lpd_flow.py\n"
        "tests/ui/test_user_lpd_stream_flow.py\ntests/e2e",
        None,
    ),
    ("API", "all", "api"),
    ("UI", "all", "ui"),
    ("Всё", "all", None),
)


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


def _log_generated_passwords(passwords: dict[str, str]) -> None:
    """TH_ENV=prod: единственное место, где случайный seed-пароль виден в открытом
    виде (дальше в БД попадает только его scrypt-хэш, см. hash_password) — вместо
    принудительной смены пароля при первом входе (потребовала бы новой колонки и
    экрана в UI) выводим его в лог один раз при первом создании учётки."""
    lines = "\n".join(f"  {login}: {password}" for login, password in sorted(passwords.items()))
    logger.warning(
        "TH_ENV=prod: сгенерированы случайные пароли seed-пользователей — "
        "сохраните их сейчас, повторно нигде не выводятся:\n%s",
        lines,
    )


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count:
        return
    generated: dict[str, str] = {}
    for login, password, role, onboarded in SEED_USERS:
        if settings.TH_ENV == "prod":
            password = secrets.token_urlsafe(12)
            generated[login] = password
        conn.execute(
            "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, ?, ?)",
            (login, hash_password(password), role, onboarded),
        )
    if generated:
        _log_generated_passwords(generated)
    for name, path, venv in SEED_PROJECTS:
        # На чужой машине эти абсолютные пути (личные проекты владельца) не
        # существуют — сидировать нечего, и раннер всё равно не найдёт venv/bin/python.
        if not Path(path).exists():
            continue
        conn.execute(
            "INSERT OR IGNORE INTO projects (name, path, venv, stands) VALUES (?, ?, ?, '[]')",
            (name, path, venv),
        )
    _seed_demo_project(conn)
    conn.commit()


def _seed_demo_project(conn: sqlite3.Connection) -> None:
    """Проект Demo (см. DEMO_PROJECT_* выше) — единственный seed-проект без
    зависимости от машины владельца: путь внутри репозитория, venv — сам
    test_hub. Вызывается только из _seed_if_empty (только на пустой БД), как и
    остальные seed-пользователи/проекты — в отличие от VSHGU он не переcидируется
    на каждом старте (см. _seed_vshgu_project)."""
    conn.execute(
        "INSERT OR IGNORE INTO projects (name, path, venv, stands, color) VALUES (?, ?, ?, '[]', ?)",
        (DEMO_PROJECT_NAME, DEMO_PROJECT_PATH, DEMO_PROJECT_VENV, DEMO_PROJECT_COLOR),
    )
    conn.execute(
        "INSERT OR IGNORE INTO stands (project, name, url) VALUES (?, ?, ?)",
        (DEMO_PROJECT_NAME, DEMO_STAND_NAME, f"http://127.0.0.1:{settings.TH_DEMO_PORT}"),
    )
    # Расписание выключено (enabled=0) — как и у VSHGU (_seed_vshgu_schedules),
    # просто пример настройки, а не боевой ночной прогон.
    conn.execute(
        "INSERT INTO schedules (project, stand, target, marker, cron, enabled, notify_chat_ids, next_run_at) "
        "VALUES (?, ?, 'all', NULL, ?, 0, '[]', NULL)",
        (DEMO_PROJECT_NAME, DEMO_STAND_NAME, DEMO_SCHEDULE_CRON),
    )


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
    """Гарантирует наличие проекта VSHGU и его стендов develop/stage.
    Идемпотентно и вызывается на каждом старте (не только _seed_if_empty — боевая БД
    непустая): вставляет только отсутствующие записи, не трогая поля, изменённые
    пользователем вручную (например, use_env_flag, выключенный через API).

    На чужой машине VSHGU_PROJECT_PATH (личный путь владельца) не существует —
    сидировать нечего, раннер всё равно не найдёт venv/bin/python по этому пути."""
    if not Path(VSHGU_PROJECT_PATH).exists():
        return
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
            manual_only = 1 if stand_name == VSHGU_MANUAL_ONLY_STAND else 0
            conn.execute(
                "INSERT INTO stands (project, name, url, login, manual_only) VALUES (?, ?, '', NULL, ?)",
                (VSHGU_PROJECT_NAME, stand_name, manual_only),
            )
            if stand_name == VSHGU_MANUAL_ONLY_STAND:
                _seed_vshgu_stage_presets(conn)
    conn.commit()


def _seed_vshgu_stage_presets(conn: sqlite3.Connection) -> None:
    """Вызывается ровно один раз — сразу после INSERT стенда stage внутри
    _seed_vshgu_project (не идемпотентна сама по себе, не проверяет наличие
    пресетов по имени): если вызывать её на каждом старте независимо, она бы
    восстанавливала пресеты, которые qa сознательно удалил/переименовал вручную
    на уже существующем стенде — 'только при первом создании', как и manual_only
    у самого стенда."""
    for preset_name, target, marker in VSHGU_STAGE_PRESETS:
        conn.execute(
            "INSERT INTO stand_presets (project, stand, name, target, marker) VALUES (?, ?, ?, ?, ?)",
            (VSHGU_PROJECT_NAME, VSHGU_MANUAL_ONLY_STAND, preset_name, target, marker),
        )


def _seed_vshgu_schedules(conn: sqlite3.Connection) -> None:
    """Выключенное расписание ночного прогона для VSHGU: develop,
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
    зависимостей на app.core.*, см. остальной модуль).

    На чужой машине _seed_vshgu_project вообще не создаёт проект VSHGU (путь не
    существует) — тогда INSERT ниже упал бы на внешнем ключе schedules.project,
    поэтому сначала проверяем, что проект реально есть."""
    if not conn.execute("SELECT 1 FROM projects WHERE name = ?", (VSHGU_PROJECT_NAME,)).fetchone():
        return
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
    password = SUPERADMIN_PASSWORD
    if settings.TH_ENV == "prod":
        password = secrets.token_urlsafe(12)
        _log_generated_passwords({SUPERADMIN_LOGIN: password})
    conn.execute(
        "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, ?, ?)",
        (SUPERADMIN_LOGIN, hash_password(password), "superadmin", 1),
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
        _migrate_add_column(conn, "stands", "manual_only", "manual_only INTEGER NOT NULL DEFAULT 0")
        _migrate_add_column(conn, "projects", "color", "color TEXT")
        _migrate_add_column(conn, "run_events", "nodeid", "nodeid TEXT")
        _migrate_add_column(conn, "run_events", "kind", "kind TEXT NOT NULL DEFAULT 'line'")
        _migrate_add_column(conn, "stands", "sentry_project", "sentry_project TEXT")
        _migrate_add_column(conn, "stands", "sentry_environment", "sentry_environment TEXT")
        _migrate_add_column(conn, "test_cases", "case_key", "case_key TEXT")
        _migrate_add_column(conn, "test_cases", "requirement", "requirement TEXT")
        _migrate_add_column(conn, "runs", "label", "label TEXT")
        _migrate_add_column(conn, "runs", "live", "live INTEGER NOT NULL DEFAULT 0")
        # На старых БД case_key ещё не заполнен для уже импортированных кейсов с
        # автотестом (у них case_key всегда равен nodeid, см. app/core/test_cases.py)
        # — без бэкфилла первый же повторный импорт не нашёл бы их по case_key и
        # попытался вставить дубликат, упав в UNIQUE(project, nodeid).
        conn.execute("UPDATE test_cases SET case_key = nodeid WHERE case_key IS NULL AND nodeid IS NOT NULL")
        conn.commit()
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_test_cases_project_case_key "
            "ON test_cases (project, case_key) WHERE case_key IS NOT NULL"
        )
        conn.commit()
        # flaky_stats, xfail_registry, schedules и stand_presets сами по себе — новые
        # таблицы (не существующие с другой схемой в старых БД), поэтому их создание
        # уже покрыто CREATE TABLE IF NOT EXISTS в SCHEMA выше и отдельной ALTER-
        # миграции, как для колонок, не требует.
        _seed_if_empty(conn)
        _seed_superadmin(conn)
        _seed_vshgu_project(conn)
        _seed_vshgu_schedules(conn)
        _seed_tg_bot_user(conn)
    finally:
        conn.close()
