import allure
import pytest

pytestmark = [pytest.mark.api]


@allure.title("Успешный логин возвращает токен и данные пользователя")
def test_login_success(auth_api):
    with allure.step("POST /api/auth/login с верными логином/паролем"):
        resp = auth_api.login("alice", "alice123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["user"]["login"] == "alice"
    assert body["user"]["role"] == "customer"
    assert "password" not in body["user"]


@allure.title("Неверный пароль — 401")
def test_login_wrong_password(auth_api):
    resp = auth_api.login("alice", "wrong-password")
    assert resp.status_code == 401


@allure.title("Неизвестный логин — 401")
def test_login_unknown_user(auth_api):
    resp = auth_api.login("nobody", "whatever")
    assert resp.status_code == 401


@allure.title("GET /api/auth/me с валидным токеном возвращает пользователя")
def test_me_with_valid_token(auth_api):
    token = auth_api.login("bob", "bob123").json()["token"]
    with allure.step("GET /api/auth/me с Bearer-токеном"):
        resp = auth_api.me(token)
    assert resp.status_code == 200
    assert resp.json()["login"] == "bob"


@allure.title("GET /api/auth/me без токена — 401")
def test_me_without_token(auth_api):
    resp = auth_api.me()
    assert resp.status_code == 401
