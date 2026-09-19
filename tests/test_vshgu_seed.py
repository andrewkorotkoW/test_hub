"""init_db() всегда обеспечивает наличие проекта auto_tests_vshgu_cloude
(app/db.py::_seed_vshgu_project) — идемпотентно и без сброса значений, изменённых
вручную через API между повторными вызовами init_db()."""

import sqlite3

from app.db import (
    VSHGU_PROJECT_NAME,
    VSHGU_PROJECT_PATH,
    VSHGU_PROJECT_VENV,
    VSHGU_STANDS,
    init_db,
)


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_init_db_seeds_vshgu_project_on_empty_db(db_path):
    conn = _connect(db_path)
    try:
        project = conn.execute(
            "SELECT * FROM projects WHERE name = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()
        assert project is not None, f"{VSHGU_PROJECT_NAME} не создан на пустой БД"
        assert project["path"] == VSHGU_PROJECT_PATH
        assert project["venv"] == VSHGU_PROJECT_VENV
        assert project["use_env_flag"] == 1

        stands = conn.execute(
            "SELECT name, url, login FROM stands WHERE project = ? ORDER BY name", (VSHGU_PROJECT_NAME,)
        ).fetchall()
    finally:
        conn.close()

    assert {s["name"] for s in stands} == set(VSHGU_STANDS)
    for s in stands:
        assert s["url"] == ""
        assert s["login"] is None


def test_init_db_is_idempotent_for_vshgu_project(db_path):
    conn = _connect(db_path)
    try:
        before_projects = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE name = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()[0]
        before_stands = conn.execute(
            "SELECT COUNT(*) FROM stands WHERE project = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert before_projects == 1
    assert before_stands == 2

    # Повторный init_db() (например перезапуск сервера) не должен ни падать, ни
    # дублировать проект/стенды.
    init_db()
    init_db()

    conn = _connect(db_path)
    try:
        after_projects = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE name = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()[0]
        after_stands = conn.execute(
            "SELECT COUNT(*) FROM stands WHERE project = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert after_projects == 1
    assert after_stands == 2


async def test_init_db_does_not_reset_use_env_flag_disabled_via_api(qa_client, db_path):
    # Сид гарантирует use_env_flag=1 при создании, но пользователь мог выключить его
    # руками через API между перезапусками сервера — повторный init_db() не должен
    # молча включать его обратно.
    off_resp = await qa_client.put(
        f"/api/projects/{VSHGU_PROJECT_NAME}", json={"use_env_flag": False}
    )
    assert off_resp.status_code == 200
    assert off_resp.json()["use_env_flag"] is False

    init_db()

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT use_env_flag FROM projects WHERE name = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()
    finally:
        conn.close()

    assert row["use_env_flag"] == 0, (
        "init_db() сбросил use_env_flag обратно в 1 после того, как он был явно "
        "выключен через API — это дефект: повторный старт сервера должен уважать "
        "ручное отключение флага пользователем, а не молча его включать"
    )


async def test_vshgu_project_visible_via_api_with_env_flag_and_stands(qa_client):
    # На свежей БД (фикстура db_path -> qa_client вызывает init_db() один раз) сид-проект
    # должен быть виден через тот же HTTP API, которым пользуется UI/раннер, а не только
    # напрямую в БД (это уже проверяют test_init_db_seeds_vshgu_project_on_empty_db выше).
    list_resp = await qa_client.get("/api/projects")
    assert list_resp.status_code == 200
    project = next(p for p in list_resp.json() if p["name"] == VSHGU_PROJECT_NAME)
    assert project["use_env_flag"] is True
    assert project["path"] == VSHGU_PROJECT_PATH
    assert project["venv"] == VSHGU_PROJECT_VENV

    stands_resp = await qa_client.get(f"/api/projects/{VSHGU_PROJECT_NAME}/stands")
    assert stands_resp.status_code == 200
    stand_names = {s["name"] for s in stands_resp.json()}
    assert stand_names == set(VSHGU_STANDS)
