import re

import allure
import pytest

from ui.pages.catalog_item_page import CatalogItemPage
from ui.pages.login_page import LoginPage

pytestmark = [pytest.mark.smoke]


@allure.title("Полный путь покупки: логин -> каталог -> товар без скидки -> заказ с верной суммой")
def test_full_purchase_flow_without_discount_succeeds(page):
    login_page = LoginPage(page)
    item_page = CatalogItemPage(page)

    with allure.step("Войти под alice/alice123"):
        login_page.open().login("alice", "alice123")
        page.wait_for_url("**/catalog")

    with allure.step("Открыть карточку товара без скидки (Кружка Demo, id=1) и купить"):
        item_page.open(item_id=1).buy()
        page.wait_for_url("**/orders/*")

    total_text = page.locator("#total").inner_text()
    assert "500" in total_text


@allure.title("Полный путь покупки товара со скидкой — итог на странице заказа неверен")
def test_full_purchase_flow_with_discount_shows_wrong_total(page):
    # Товар id=2 "Футболка Demo": price=1200, discount=20% -> корректный итог 960 ₽.
    # Падает из-за того же бага, что и demo/tests/api/orders/test_orders.py
    # ::test_create_order_applies_discount (demo/app/routers/orders.py::create_order):
    # на странице заказа виден "чужой" итог 1200 ₽.
    login_page = LoginPage(page)
    item_page = CatalogItemPage(page)

    with allure.step("Войти под bob/bob123"):
        login_page.open().login("bob", "bob123")
        page.wait_for_url("**/catalog")

    with allure.step("Открыть карточку товара со скидкой 20% (Футболка Demo, id=2) и купить"):
        item_page.open(item_id=2).buy()
        page.wait_for_url("**/orders/*")

    total_text = page.locator("#total").inner_text()
    total = int(re.search(r"\d+", total_text).group())
    assert total == 960


@allure.title("Товар не в наличии — кнопка «Купить» недоступна")
def test_purchase_flow_blocked_for_out_of_stock_item(page):
    # Товар id=3 "Стикерпак Demo": stock=0.
    item_page = CatalogItemPage(page)
    item_page.open(item_id=3)
    page.wait_for_selector("#buy")
    assert page.is_disabled("#buy")
