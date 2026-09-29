import allure
import pytest

from ui.pages.login_page import LoginPage

pytestmark = [pytest.mark.ui]


@allure.title("Успешный логин через форму переводит на каталог")
def test_login_page_redirects_to_catalog(page):
    login_page = LoginPage(page)
    with allure.step("Открыть /login и войти под alice/alice123"):
        login_page.open().login("alice", "alice123")
    page.wait_for_url("**/catalog")
    assert "/catalog" in page.url


@allure.title("Неверный пароль показывает ошибку и не уводит со страницы логина")
def test_login_page_shows_error_on_wrong_password(page):
    login_page = LoginPage(page)
    login_page.open().login("alice", "wrong-password")
    assert "Неверный логин или пароль" in login_page.error_text()
    assert "/login" in page.url
