import allure
import pytest

pytestmark = [pytest.mark.api]


@allure.title("Заказ товара без скидки — сумма верна")
def test_create_order_success(orders_api):
    with allure.step("POST /api/orders на товар без скидки (id=1, Кружка Demo)"):
        resp = orders_api.create(item_id=1, qty=2)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1000  # 500 * 2, discount=0


@allure.title("Заказ товара со скидкой — сумма должна учитывать скидку")
def test_create_order_applies_discount(orders_api):
    # Item id=2 "Футболка Demo": price=1200, discount=20% -> ожидаемая сумма 960.
    # Падает из-за намеренного бага в demo/app/routers/orders.py::create_order —
    # см. docstring рядом с полем total.
    with allure.step("POST /api/orders на товар со скидкой 20% (id=2, Футболка Demo)"):
        resp = orders_api.create(item_id=2, qty=1)
    assert resp.status_code == 200
    body = resp.json()
    expected_total = body["unit_price"] * 1 * (100 - body["discount"]) // 100
    assert body["total"] == expected_total


@allure.title("Заказ нескольких единиц товара со скидкой — сумма должна учитывать скидку")
def test_create_order_multiple_qty_applies_discount(orders_api):
    with allure.step("POST /api/orders на 3 единицы товара со скидкой 20% (id=2)"):
        resp = orders_api.create(item_id=2, qty=3)
    assert resp.status_code == 200
    body = resp.json()
    expected_total = body["unit_price"] * 3 * (100 - body["discount"]) // 100
    assert body["total"] == expected_total


@allure.title("Заказ товара, которого нет в наличии — 400")
def test_create_order_out_of_stock_returns_400(orders_api):
    # Item id=3 "Стикерпак Demo": stock=0.
    resp = orders_api.create(item_id=3, qty=1)
    assert resp.status_code == 400


@allure.title("Заказ несуществующего товара — 404")
def test_create_order_unknown_item_returns_404(orders_api):
    resp = orders_api.create(item_id=9999, qty=1)
    assert resp.status_code == 404


@allure.title("Заказ с qty=0 — 400")
def test_create_order_invalid_qty_returns_400(orders_api):
    resp = orders_api.create(item_id=1, qty=0)
    assert resp.status_code == 400


@allure.title("Заказ по id возвращает те же поля, что и при создании")
def test_get_order_by_id(orders_api):
    created = orders_api.create(item_id=4, qty=1).json()
    resp = orders_api.get(created["id"])
    assert resp.status_code == 200
    assert resp.json() == created


@allure.title("Несуществующий заказ — 404")
def test_get_order_not_found(orders_api):
    resp = orders_api.get(999999)
    assert resp.status_code == 404
