"""Цвет проекта из палитры (app/db.py миграция, app/schemas.py, app/routers/projects.py).

GET /api/projects всегда отдаёт color — NULL в БД превращается в первый цвет палитры
(app/schemas.py::PROJECT_COLOR_PALETTE). PUT /api/projects/{name}/color меняет цвет
только на значение из палитры и доступен ролям qa/superadmin (manager/customer — 403,
как и другие ручки этого роутера).
"""

import sqlite3

import pytest

from app.db import init_db
from app.schemas import PROJECT_COLOR_PALETTE


def test_migration_adds_color_column_to_legacy_projects_table(tmp_path, monkeypatch):
    from app.config import settings

    old_db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(old_db_path)
    conn.execute(
        "CREATE TABLE projects ("
        "name TEXT PRIMARY KEY,"
        "path TEXT NOT NULL,"
        "venv TEXT NOT NULL,"
        "stands TEXT NOT NULL DEFAULT '[]',"
        "use_env_flag INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "INSERT INTO projects (name, path, venv) VALUES (?, ?, ?)",
        ("legacy_proj", "/tmp/legacy_proj", ".venv"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        assert "color" in cols
        row = conn.execute("SELECT * FROM projects WHERE name = 'legacy_proj'").fetchone()
        assert row["color"] is None
    finally:
        conn.close()


async def test_list_projects_defaults_missing_color_to_first_palette_entry(qa_client):
    resp = await qa_client.get("/api/projects")
    assert resp.status_code == 200
    row = next(p for p in resp.json() if p["name"] == "bike_fit")
    assert row["color"] == PROJECT_COLOR_PALETTE[0]


@pytest.mark.parametrize("color", [PROJECT_COLOR_PALETTE[3], PROJECT_COLOR_PALETTE[-1]])
async def test_qa_can_set_project_color_from_palette(qa_client, color):
    resp = await qa_client.put("/api/projects/bike_fit/color", json={"color": color})
    assert resp.status_code == 200
    assert resp.json()["color"] == color

    list_resp = await qa_client.get("/api/projects")
    row = next(p for p in list_resp.json() if p["name"] == "bike_fit")
    assert row["color"] == color


async def test_superadmin_can_set_project_color(superadmin_client):
    color = PROJECT_COLOR_PALETTE[4]
    resp = await superadmin_client.put("/api/projects/bike_fit/color", json={"color": color})
    assert resp.status_code == 200
    assert resp.json()["color"] == color


async def test_set_project_color_rejects_value_outside_palette(qa_client):
    resp = await qa_client.put("/api/projects/bike_fit/color", json={"color": "#123456"})
    assert resp.status_code == 422


async def test_manager_cannot_set_project_color(manager_client):
    resp = await manager_client.put(
        "/api/projects/bike_fit/color", json={"color": PROJECT_COLOR_PALETTE[1]}
    )
    assert resp.status_code == 403


async def test_customer_cannot_set_project_color(customer_client):
    resp = await customer_client.put(
        "/api/projects/bike_fit/color", json={"color": PROJECT_COLOR_PALETTE[1]}
    )
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "color",
    [
        "",  # пусто
        PROJECT_COLOR_PALETTE[0].upper(),  # тот же цвет, но не тем регистром — не строковое совпадение
        PROJECT_COLOR_PALETTE[0] + " ",  # с лишним пробелом
    ],
)
async def test_set_project_color_rejects_various_values_outside_palette(qa_client, color):
    resp = await qa_client.put("/api/projects/bike_fit/color", json={"color": color})
    assert resp.status_code == 422


async def test_set_project_color_unknown_project_returns_404(qa_client):
    resp = await qa_client.put(
        "/api/projects/does-not-exist/color", json={"color": PROJECT_COLOR_PALETTE[0]}
    )
    assert resp.status_code == 404


async def test_create_project_without_color_defaults_to_first_palette_entry(qa_client, tmp_path):
    project_dir = tmp_path / "no_color_proj"
    project_dir.mkdir()
    create_resp = await qa_client.post(
        "/api/projects", json={"name": "no_color_proj", "path": str(project_dir), "venv": ".venv"}
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["color"] == PROJECT_COLOR_PALETTE[0]

    list_resp = await qa_client.get("/api/projects")
    row = next(p for p in list_resp.json() if p["name"] == "no_color_proj")
    assert row["color"] == PROJECT_COLOR_PALETTE[0]
