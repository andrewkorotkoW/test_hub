"""Логин/логаут/сессии."""

import pytest

from app.config import settings
from tests.conftest import login


@pytest.mark.parametrize(
    "login_, password, role, onboarded",
    [
        ("qa", "qa", "qa", True),
        ("manager", "manager", "manager", False),
        ("customer", "customer", "customer", True),
    ],
)
async def test_login_success_sets_cookie_and_returns_role(client, login_, password, role, onboarded):
    resp = await login(client, login_, password)
    assert resp.status_code == 200
    assert resp.json() == {"login": login_, "role": role, "onboarded": onboarded}
    assert settings.SESSION_COOKIE in resp.cookies


@pytest.mark.parametrize("login_, password, role", [("qa", "qa", "qa"), ("manager", "manager", "manager"), ("customer", "customer", "customer")])
async def test_me_returns_correct_identity_after_login(client, login_, password, role):
    await login(client, login_, password)
    resp = await client.get("/api/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["login"] == login_
    assert body["role"] == role


async def test_login_wrong_password_is_401(client):
    resp = await login(client, "qa", "wrong-password")
    # Проверено по факту реализации: app/routers/auth.py возвращает 401 Unauthorized
    # (не 403) при неверном пароле или неизвестном логине.
    assert resp.status_code == 401
    assert settings.SESSION_COOKIE not in resp.cookies


async def test_login_unknown_user_is_401(client):
    resp = await login(client, "no-such-user", "whatever")
    assert resp.status_code == 401


async def test_me_without_cookie_is_401(client):
    resp = await client.get("/api/me")
    assert resp.status_code == 401


async def test_protected_endpoint_without_cookie_is_401(client):
    resp = await client.get("/api/projects")
    assert resp.status_code == 401


async def test_me_with_garbage_cookie_is_401(client):
    client.cookies.set(settings.SESSION_COOKIE, "not-a-valid-token")
    resp = await client.get("/api/me")
    assert resp.status_code == 401


async def test_logout_clears_cookie_and_invalidates_session(client):
    await login(client, "qa", "qa")
    resp = await client.get("/api/me")
    assert resp.status_code == 200

    logout_resp = await client.post("/api/logout")
    assert logout_resp.status_code == 200

    resp = await client.get("/api/me")
    assert resp.status_code == 401
