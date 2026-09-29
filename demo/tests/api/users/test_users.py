import allure
import pytest

pytestmark = [pytest.mark.api]


@allure.title("Список пользователей не содержит паролей")
def test_list_users(users_api):
    resp = users_api.list()
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 2
    for user in users:
        assert "password" not in user


@allure.title("Среди пользователей есть alice и bob")
def test_list_users_contains_seed_logins(users_api):
    resp = users_api.list()
    logins = {u["login"] for u in resp.json()}
    assert {"alice", "bob"} <= logins
