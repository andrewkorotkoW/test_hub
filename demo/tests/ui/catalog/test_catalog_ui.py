import allure
import pytest

from ui.pages.catalog_item_page import CatalogItemPage
from ui.pages.catalog_page import CatalogPage

pytestmark = [pytest.mark.ui]


@allure.title("Страница каталога показывает все товары")
def test_catalog_page_lists_items(page):
    catalog_page = CatalogPage(page)
    titles = catalog_page.open().item_titles()
    assert "Кружка Demo" in titles
    assert "Футболка Demo" in titles


@allure.title("Карточка товара показывает цену")
def test_catalog_item_page_shows_price(page):
    item_page = CatalogItemPage(page)
    price = item_page.open(item_id=1).price_text()
    assert "500" in price


@allure.title("Кнопка «Купить» оформляет заказ и переводит на страницу заказа")
def test_catalog_item_page_buy_button_creates_order(page):
    item_page = CatalogItemPage(page)
    with allure.step("Открыть карточку товара без скидки (id=1) и нажать «Купить»"):
        item_page.open(item_id=1).buy()
    page.wait_for_url("**/orders/*")
    assert "/orders/" in page.url
