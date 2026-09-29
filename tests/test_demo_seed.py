"""Сид демо-проекта Demo (app/db.py::_seed_demo_project) и условный сид
bike_fit/Velo_bot/VSHGU (см. app/db.py::_seed_if_empty/_seed_vshgu_project) —
по образцу tests/test_seed.py и tests/test_vshgu_seed.py."""

import sqlite3

import pytest

from app import db
from app.config import settings
from app.db import (
    DEMO_PROJECT_COLOR,
    DEMO_PROJECT_NAME,
    DEMO_PROJECT_PATH,
    DEMO_PROJECT_VENV,
    DEMO_SCHEDULE_CRON,
    DEMO_STAND_NAME,
    VSHGU_PROJECT_NAME,
    VSHGU_PROJECT_PATH,
    init_db,
)


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------------ Demo сидируется на пустой БД


def test_demo_project_seeded_on_empty_db(db_path):
    conn = _connect(db_path)
    try:
        project = conn.execute(
            "SELECT * FROM projects WHERE name = ?", (DEMO_PROJECT_NAME,)
        ).fetchone()
        assert project is not None, f"{DEMO_PROJECT_NAME} не создан на пустой БД"
        assert project["path"] == DEMO_PROJECT_PATH
        assert project["venv"] == DEMO_PROJECT_VENV
        assert project["color"] == DEMO_PROJECT_COLOR
        assert project["use_env_flag"] == 0

        stands = conn.execute(
            "SELECT * FROM stands WHERE project = ?", (DEMO_PROJECT_NAME,)
        ).fetchall()
        schedules = conn.execute(
            "SELECT * FROM schedules WHERE project = ?", (DEMO_PROJECT_NAME,)
        ).fetchall()
    finally:
        conn.close()

    assert len(stands) == 1
    assert stands[0]["name"] == DEMO_STAND_NAME
    assert stands[0]["url"] == f"http://127.0.0.1:{settings.TH_DEMO_PORT}"
    assert stands[0]["manual_only"] == 0

    assert len(schedules) == 1
    assert schedules[0]["stand"] == DEMO_STAND_NAME
    assert schedules[0]["target"] == "all"
    assert schedules[0]["marker"] is None
    assert schedules[0]["cron"] == DEMO_SCHEDULE_CRON
    assert schedules[0]["enabled"] == 0


def test_demo_project_path_points_inside_repo(db_path):
    # DEMO_PROJECT_PATH вычисляется от расположения app/db.py, а не хардкодится
    # абсолютным путём владельца (см. комментарий в db.py) — путь должен реально
    # существовать на любой машине, склонировавшей репозиторий, и указывать на demo/.
    from pathlib import Path

    path = Path(DEMO_PROJECT_PATH)
    assert path.is_dir()
    assert path.name == "demo"
    assert (path / "tests").is_dir()
    assert (path / "app" / "main.py").is_file()


def test_demo_seed_is_idempotent(db_path):
    conn = _connect(db_path)
    try:
        before_projects = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE name = ?", (DEMO_PROJECT_NAME,)
        ).fetchone()[0]
        before_schedules = conn.execute(
            "SELECT COUNT(*) FROM schedules WHERE project = ?", (DEMO_PROJECT_NAME,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert before_projects == 1
    assert before_schedules == 1

    # Повторный init_db() (например перезапуск сервера) не должен ни падать, ни
    # дублировать проект/стенд/расписание Demo — в отличие от VSHGU, Demo сидируется
    # только внутри _seed_if_empty (на пустой БД), но init_db() всё равно вызывает
    # его на каждом старте, поэтому важно, чтобы повторный вызов ничего не менял.
    init_db()
    init_db()

    conn = _connect(db_path)
    try:
        after_projects = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE name = ?", (DEMO_PROJECT_NAME,)
        ).fetchone()[0]
        after_stands = conn.execute(
            "SELECT COUNT(*) FROM stands WHERE project = ?", (DEMO_PROJECT_NAME,)
        ).fetchone()[0]
        after_schedules = conn.execute(
            "SELECT COUNT(*) FROM schedules WHERE project = ?", (DEMO_PROJECT_NAME,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert after_projects == 1
    assert after_stands == 1
    assert after_schedules == 1


async def test_demo_project_visible_via_api(qa_client):
    resp = await qa_client.get("/api/projects")
    assert resp.status_code == 200
    project = next(p for p in resp.json() if p["name"] == DEMO_PROJECT_NAME)
    assert project["path"] == DEMO_PROJECT_PATH
    assert project["venv"] == DEMO_PROJECT_VENV
    assert project["color"] == DEMO_PROJECT_COLOR

    stands_resp = await qa_client.get(f"/api/projects/{DEMO_PROJECT_NAME}/stands")
    assert stands_resp.status_code == 200
    stand_names = {s["name"] for s in stands_resp.json()}
    assert stand_names == {DEMO_STAND_NAME}

    schedules_resp = await qa_client.get(f"/api/projects/{DEMO_PROJECT_NAME}/schedules")
    assert schedules_resp.status_code == 200
    schedules = schedules_resp.json()
    assert len(schedules) == 1
    assert schedules[0]["enabled"] is False


# ------------------------------------------------------------------ bike_fit/Velo_bot/VSHGU сидируются только при наличии пути


@pytest.fixture()
def missing_owner_paths(tmp_path, monkeypatch):
    """Подменяет пути bike_fit/Velo_bot (SEED_PROJECTS) и VSHGU_PROJECT_PATH на
    заведомо несуществующие директории — имитирует машину, на которую склонировали
    test_hub без личных проектов владельца (см. задачу: эти три проекта не должны
    сидироваться, если их пути не существуют на диске)."""
    fake_bike_fit = tmp_path / "no_such_bike_fit"
    fake_velo_bot = tmp_path / "no_such_velo_bot"
    fake_vshgu = tmp_path / "no_such_vshgu"
    monkeypatch.setattr(
        db,
        "SEED_PROJECTS",
        [
            ("bike_fit", str(fake_bike_fit), ".venv"),
            ("Velo_bot", str(fake_velo_bot), ".venv"),
        ],
    )
    monkeypatch.setattr(db, "VSHGU_PROJECT_PATH", str(fake_vshgu))
    return tmp_path


@pytest.fixture()
def isolated_db_path(tmp_path, monkeypatch):
    path = tmp_path / "test_hub.db"
    monkeypatch.setattr(settings, "DB_PATH", path)
    return path


def test_owner_projects_not_seeded_when_paths_missing(missing_owner_paths, isolated_db_path):
    db.init_db()

    conn = _connect(isolated_db_path)
    try:
        names = {r["name"] for r in conn.execute("SELECT name FROM projects").fetchall()}
    finally:
        conn.close()

    assert "bike_fit" not in names
    assert "Velo_bot" not in names
    assert VSHGU_PROJECT_NAME not in names
    # Demo (путь внутри репозитория) сидируется независимо от путей владельца
    assert DEMO_PROJECT_NAME in names


def test_vshgu_still_not_seeded_on_repeated_init_db_when_path_missing(missing_owner_paths, isolated_db_path):
    # _seed_vshgu_project вызывается на КАЖДОМ старте (не только на пустой БД,
    # см. init_db) — важно, что повторные вызовы тоже не создают VSHGU, если путь
    # по-прежнему не существует (а не только "не досидировали один раз").
    db.init_db()
    db.init_db()
    db.init_db()

    conn = _connect(isolated_db_path)
    try:
        project = conn.execute(
            "SELECT 1 FROM projects WHERE name = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()
        schedule = conn.execute(
            "SELECT 1 FROM schedules WHERE project = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()
    finally:
        conn.close()

    assert project is None
    assert schedule is None


def test_owner_projects_seeded_as_before_when_paths_exist(db_path):
    # Без monkeypatch (db_path фикстура использует реальные SEED_PROJECTS/
    # VSHGU_PROJECT_PATH) поведение владельца не должно измениться: если пути
    # реально существуют на диске (как на его машине), проекты сидируются, как и
    # до появления условного сида (см. tests/test_seed.py, tests/test_vshgu_seed.py).
    from pathlib import Path

    from app.db import SEED_PROJECTS, VSHGU_PROJECT_PATH as REAL_VSHGU_PATH

    owner_paths_present = all(Path(path).exists() for _name, path, _venv in SEED_PROJECTS) and Path(
        REAL_VSHGU_PATH
    ).exists()
    if not owner_paths_present:
        pytest.skip("на этой машине нет путей владельца bike_fit/Velo_bot/VSHGU — нечего проверять")

    conn = _connect(db_path)
    try:
        names = {r["name"] for r in conn.execute("SELECT name FROM projects").fetchall()}
    finally:
        conn.close()

    assert {"bike_fit", "Velo_bot", VSHGU_PROJECT_NAME} <= names
