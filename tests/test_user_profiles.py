"""Миссия docs/missions/2026-10-10_user_profiles.md: регистрация с одобрением,
профиль (`PUT /api/me`), аватар (`POST/GET /api/me/avatar`, `GET
/api/users/{login}/avatar`) — app/routers/auth.py, app/routers/users.py.

app.routers.auth.AVATARS_DIR вычисляется один раз при импорте модуля
(settings.WORKSPACE_DIR / "avatars"), как и test_cases.TESTCASES_DIR в
tests/test_testcases_attachments.py — monkeypatch.setattr(settings,
"WORKSPACE_DIR", ...) его не подменит, нужен monkeypatch.setattr(auth_router,
"AVATARS_DIR", ...) напрямую.
"""
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import SCHEMA, init_db
from app.main import app
from app.routers import auth as auth_router

from .conftest import login

PROJECT = "bike_fit"  # сидируется SEED_PROJECTS на пустой БД (tests/test_seed.py)

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-but-good-enough-for-extension-only-check"
_JPG_BYTES = b"\xff\xd8\xff\xe0" + b"fake-but-good-enough-for-extension-only-check"


@pytest.fixture()
def isolated_avatars_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_router, "AVATARS_DIR", tmp_path / "avatars")
    return tmp_path / "avatars"


async def register(client, login_, password="pwd12345", full_name="Иван Иванов", position="QA", project=None):
    body = {"login": login_, "password": password, "full_name": full_name, "position": position}
    if project is not None:
        body["project"] = project
    return await client.post("/api/auth/register", json=body)


# ------------------------------------------------------------------ регистрация

async def test_register_creates_pending_customer_without_cookie(client):
    resp = await register(client, "newbie")
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"status": "pending"}
    assert settings.SESSION_COOKIE not in resp.cookies

    login_resp = await login(client, "newbie", "pwd12345")
    assert login_resp.status_code == 403  # пока не одобрено, войти нельзя


async def test_register_sets_pending_status_and_customer_role(client, db_path):
    await register(client, "newbie2")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM users WHERE login = 'newbie2'").fetchone()
    finally:
        conn.close()
    assert row["status"] == "pending"
    assert row["role"] == "customer"
    assert row["full_name"] == "Иван Иванов"
    assert row["position"] == "QA"
    assert row["onboarded"] == 0


async def test_register_duplicate_login_is_409(client):
    resp1 = await register(client, "dupe")
    assert resp1.status_code == 201
    resp2 = await register(client, "dupe")
    assert resp2.status_code == 409


async def test_register_duplicate_of_seeded_user_is_409(client):
    # "qa" уже сидирован init_db() на пустой БД (tests/test_seed.py) — регистрация
    # с тем же login должна считаться конфликтом, а не создавать второго pending.
    resp = await register(client, "qa")
    assert resp.status_code == 409


async def test_register_with_known_project_succeeds(client, db_path):
    resp = await register(client, "newbie3", project=PROJECT)
    assert resp.status_code == 201
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT project FROM users WHERE login = 'newbie3'").fetchone()
    finally:
        conn.close()
    assert row["project"] == PROJECT


async def test_register_with_unknown_project_is_404(client):
    resp = await register(client, "newbie4", project="no-such-project")
    assert resp.status_code == 404


async def test_register_missing_required_fields_is_422(client):
    resp = await client.post("/api/auth/register", json={"login": "incomplete", "password": "x"})
    assert resp.status_code == 422  # full_name/position обязательны по контракту миссии


# ------------------------------------------------------------------ логин pending/rejected

async def test_login_pending_user_is_403_not_401(client):
    await register(client, "pending_user")
    resp = await login(client, "pending_user", "pwd12345")
    assert resp.status_code == 403, resp.text
    assert "одобрен" in resp.json()["detail"].lower()
    assert settings.SESSION_COOKIE not in resp.cookies


async def test_login_rejected_user_is_403_with_different_message(qa_client, client):
    await register(client, "rejected_user")
    resp = await qa_client.put("/api/users/rejected_user/reject")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"

    login_resp = await login(client, "rejected_user", "pwd12345")
    assert login_resp.status_code == 403
    assert "отклон" in login_resp.json()["detail"].lower()

    pending_resp = await login(client, "rejected_user" + "_does_not_exist", "x")
    assert pending_resp.status_code == 401  # sanity: неизвестный логин остаётся 401, не 403


# ------------------------------------------------------------------ approve/reject

async def test_approve_activates_user_and_login_succeeds(qa_client, client):
    await register(client, "approve_me")
    resp = await qa_client.put("/api/users/approve_me/approve")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["role"] == "customer"  # role не передана -> осталась customer

    login_resp = await login(client, "approve_me", "pwd12345")
    assert login_resp.status_code == 200
    assert settings.SESSION_COOKIE in login_resp.cookies


async def test_approve_with_role_changes_role(qa_client, client):
    await register(client, "approve_as_manager")
    resp = await qa_client.put("/api/users/approve_as_manager/approve", json={"role": "manager"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "manager"
    assert resp.json()["status"] == "active"


async def test_approve_without_role_keeps_customer(qa_client, client):
    await register(client, "approve_keep_customer")
    resp = await qa_client.put("/api/users/approve_keep_customer/approve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "customer"


async def test_approve_forbidden_for_customer(customer_client, client):
    await register(client, "approve_target_1")
    resp = await customer_client.put("/api/users/approve_target_1/approve")
    assert resp.status_code == 403


async def test_approve_forbidden_for_manager(manager_client, client):
    await register(client, "approve_target_2")
    resp = await manager_client.put("/api/users/approve_target_2/approve")
    assert resp.status_code == 403


async def test_reject_sets_rejected_status_without_deleting_row(qa_client, client, db_path):
    await register(client, "reject_me")
    resp = await qa_client.put("/api/users/reject_me/reject")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM users WHERE login = 'reject_me'").fetchone()
    finally:
        conn.close()
    assert row is not None  # soft-delete, не DELETE
    assert row["status"] == "rejected"


async def test_reject_forbidden_for_customer_and_manager(customer_client, manager_client, client):
    await register(client, "reject_target_1")
    resp_c = await customer_client.put("/api/users/reject_target_1/reject")
    assert resp_c.status_code == 403
    resp_m = await manager_client.put("/api/users/reject_target_1/reject")
    assert resp_m.status_code == 403


# ------------------------------------------------------------------ PUT /api/me

async def test_update_me_changes_allowed_fields(customer_client):
    resp = await customer_client.put(
        "/api/me", json={"full_name": "Новое Имя", "position": "Senior QA", "project": PROJECT}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Новое Имя"
    assert body["position"] == "Senior QA"
    assert body["project"] == PROJECT

    me_resp = await customer_client.get("/api/me")
    assert me_resp.json()["full_name"] == "Новое Имя"


async def test_update_me_ignores_role_login_status_in_body(customer_client):
    resp = await customer_client.put(
        "/api/me",
        json={"full_name": "Имя", "role": "superadmin", "login": "someone-else", "status": "rejected"},
    )
    assert resp.status_code == 200, resp.text  # лишние поля игнорируются, не 422
    body = resp.json()
    assert body["login"] == "customer"  # не переименован
    assert body["role"] == "customer"  # роль не самообслуживание
    assert body["status"] == "active"  # статус не тронут


async def test_update_me_unknown_project_is_404(customer_client):
    resp = await customer_client.put("/api/me", json={"project": "no-such-project"})
    assert resp.status_code == 404


async def test_update_me_partial_update_keeps_other_fields(customer_client):
    await customer_client.put("/api/me", json={"full_name": "ФИО 1", "position": "Должность 1"})
    resp = await customer_client.put("/api/me", json={"position": "Должность 2"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "ФИО 1"  # не передан в этом запросе -> не затёрт
    assert body["position"] == "Должность 2"


# ------------------------------------------------------------------ GET /api/me, GET /api/users payload

async def test_me_payload_includes_profile_fields(customer_client):
    resp = await customer_client.get("/api/me")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("full_name", "position", "project", "status", "avatar_url"):
        assert field in body
    assert body["status"] == "active"
    assert body["avatar_url"] is None


async def test_list_users_includes_profile_fields(qa_client):
    resp = await qa_client.get("/api/users")
    assert resp.status_code == 200
    by_login = {u["login"]: u for u in resp.json()}
    for field in ("full_name", "position", "project", "status", "avatar_url"):
        assert field in by_login["qa"]
    assert by_login["qa"]["status"] == "active"


# ------------------------------------------------------------------ аватар

async def test_avatar_upload_png_success_then_fetch(customer_client, isolated_avatars_dir):
    resp = await customer_client.post(
        "/api/me/avatar", files={"file": ("photo.png", _PNG_BYTES, "image/png")}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"] == "/api/me/avatar"

    fetch_resp = await customer_client.get("/api/me/avatar")
    assert fetch_resp.status_code == 200
    assert fetch_resp.headers["content-type"] == "image/png"
    assert fetch_resp.content == _PNG_BYTES


async def test_avatar_upload_jpg_success_then_fetch(customer_client, isolated_avatars_dir):
    resp = await customer_client.post(
        "/api/me/avatar", files={"file": ("photo.jpg", _JPG_BYTES, "image/jpeg")}
    )
    assert resp.status_code == 200, resp.text

    fetch_resp = await customer_client.get("/api/me/avatar")
    assert fetch_resp.status_code == 200
    assert fetch_resp.headers["content-type"] == "image/jpeg"
    assert fetch_resp.content == _JPG_BYTES


async def test_avatar_upload_rejects_unsupported_type(customer_client, isolated_avatars_dir):
    resp = await customer_client.post(
        "/api/me/avatar", files={"file": ("notes.txt", b"just text", "text/plain")}
    )
    assert resp.status_code == 422, resp.text

    me_resp = await customer_client.get("/api/me")
    assert me_resp.json()["avatar_url"] is None


async def test_avatar_upload_rejects_gif(customer_client, isolated_avatars_dir):
    resp = await customer_client.post(
        "/api/me/avatar", files={"file": ("animated.gif", b"GIF89a-fake", "image/gif")}
    )
    assert resp.status_code == 422, resp.text


async def test_avatar_upload_rejects_oversized_file(customer_client, isolated_avatars_dir, monkeypatch):
    monkeypatch.setattr(settings, "TH_TESTCASE_ATTACHMENT_MAX_BYTES", 10)
    resp = await customer_client.post(
        "/api/me/avatar", files={"file": ("photo.png", _PNG_BYTES, "image/png")}
    )
    assert resp.status_code == 413, resp.text

    me_resp = await customer_client.get("/api/me")
    assert me_resp.json()["avatar_url"] is None


async def test_avatar_replaces_previous_file_not_accumulates(customer_client, isolated_avatars_dir):
    first = await customer_client.post(
        "/api/me/avatar", files={"file": ("first.png", _PNG_BYTES, "image/png")}
    )
    assert first.status_code == 200

    second = await customer_client.post(
        "/api/me/avatar", files={"file": ("second.jpg", _JPG_BYTES, "image/jpeg")}
    )
    assert second.status_code == 200

    stored_files = list(isolated_avatars_dir.iterdir())
    assert len(stored_files) == 1  # старый .png удалён, не накоплен рядом с новым .jpg

    fetch_resp = await customer_client.get("/api/me/avatar")
    assert fetch_resp.content == _JPG_BYTES


async def test_get_my_avatar_without_upload_is_404(customer_client, isolated_avatars_dir):
    resp = await customer_client.get("/api/me/avatar")
    assert resp.status_code == 404


async def test_get_user_avatar_by_login_visible_to_other_authenticated_user(
    customer_client, isolated_avatars_dir
):
    # customer_client и qa_client используют общую фикстуру `client` — второй login()
    # в одном тесте затирал бы cookie первого (см. tests/test_testcases_attachments.py),
    # поэтому для qa здесь собственный AsyncClient, как superadmin_client в conftest.
    upload_resp = await customer_client.post(
        "/api/me/avatar", files={"file": ("photo.png", _PNG_BYTES, "image/png")}
    )
    assert upload_resp.status_code == 200

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as qa_only_client:
        login_resp = await login(qa_only_client, "qa", "qa")
        assert login_resp.status_code == 200
        resp = await qa_only_client.get("/api/users/customer/avatar")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == _PNG_BYTES


async def test_get_user_avatar_requires_auth(client, isolated_avatars_dir):
    resp = await client.get("/api/users/customer/avatar")
    assert resp.status_code == 401


async def test_get_user_avatar_unknown_login_is_404(qa_client, isolated_avatars_dir):
    resp = await qa_client.get("/api/users/no-such-login/avatar")
    assert resp.status_code == 404


# ------------------------------------------------------------------ сидированные пользователи после миграции

async def test_seeded_users_remain_active_and_login_unchanged(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["login"]: r for r in conn.execute("SELECT * FROM users").fetchall()}
    finally:
        conn.close()
    for login_ in ("qa", "manager", "customer", "admin", "tg_bot"):
        assert rows[login_]["status"] == "active"
        assert rows[login_]["full_name"] is None
        assert rows[login_]["avatar_filename"] is None


@pytest.mark.parametrize(
    "login_, password",
    [("qa", "qa"), ("manager", "manager"), ("customer", "customer"), ("admin", "admin")],
)
async def test_seeded_users_still_login_successfully(client, login_, password):
    resp = await login(client, login_, password)
    assert resp.status_code == 200
    assert settings.SESSION_COOKIE in resp.cookies


def _old_schema_without_new_users_columns() -> str:
    statements = []
    for stmt in SCHEMA.split(";"):
        text = stmt.strip()
        if not text:
            continue
        if text.startswith("CREATE TABLE IF NOT EXISTS users"):
            text = (
                "CREATE TABLE IF NOT EXISTS users (\n"
                "    login TEXT PRIMARY KEY,\n"
                "    password_hash TEXT NOT NULL,\n"
                "    role TEXT NOT NULL CHECK (role IN ('qa', 'manager', 'customer', 'superadmin')),\n"
                "    onboarded INTEGER NOT NULL DEFAULT 0\n"
                ")"
            )
        statements.append(text + ";")
    return "\n".join(statements)


@pytest.fixture()
def old_schema_db_path(tmp_path, monkeypatch):
    path = tmp_path / "old_test_hub.db"
    monkeypatch.setattr(settings, "DB_PATH", path)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_old_schema_without_new_users_columns())
        conn.execute(
            "INSERT INTO users (login, password_hash, role, onboarded) VALUES ('qa', ?, 'qa', 1)",
            ("scrypt$fake-hash-not-checked-by-this-test",),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_migration_adds_profile_columns_to_old_users_table_without_data_loss(old_schema_db_path):
    conn = sqlite3.connect(old_schema_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols_before = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    finally:
        conn.close()
    assert "status" not in cols_before
    assert "full_name" not in cols_before

    init_db()  # не должно падать на старой таблице users без новых колонок

    conn = sqlite3.connect(old_schema_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols_after = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert {"full_name", "position", "project", "avatar_filename", "status"} <= cols_after

        old_row = conn.execute("SELECT * FROM users WHERE login = 'qa'").fetchone()
        assert old_row["role"] == "qa"
        assert old_row["onboarded"] == 1
        # ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT 'active' проставляет значение
        # по умолчанию существующим строкам, а не NULL (в отличие от колонок без
        # DEFAULT, см. tests/test_runs_label.py с тем же приёмом для runs.label).
        assert old_row["status"] == "active"
        assert old_row["full_name"] is None
    finally:
        conn.close()

    init_db()  # повторный запуск (рестарт сервиса) на уже мигрированной БД идемпотентен
