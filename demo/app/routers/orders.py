from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import store

router = APIRouter(prefix="/api/orders", tags=["orders"])


class OrderCreate(BaseModel):
    item_id: int
    qty: int = 1


def _order_out(order: store.Order) -> dict:
    return dict(order)


@router.post("")
def create_order(body: OrderCreate) -> dict:
    item = store.CATALOG.get(body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="товар не найден")
    if body.qty < 1:
        raise HTTPException(status_code=400, detail="qty должен быть больше 0")
    if body.qty > item["stock"]:
        raise HTTPException(status_code=400, detail="нет в наличии")

    # БАГ (намеренный, для демо-тестов, см. demo/tests/api/orders): total считается
    # как unit_price * qty без учёта item["discount"] — должно быть
    # unit_price * qty * (100 - discount) / 100. Из-за этого для любого товара со
    # скидкой (например "Футболка Demo", discount=20) сумма заказа завышена.
    # Именно на этом падают demo/tests/api/orders/test_orders.py::test_create_order_applies_discount,
    # ::test_create_order_total_reflects_discount_in_list и e2e-тест покупки товара со скидкой.
    total = item["price"] * body.qty

    order: store.Order = {
        "id": store.next_order_id(),
        "item_id": item["id"],
        "qty": body.qty,
        "unit_price": item["price"],
        "discount": item["discount"],
        "total": total,
        "user_id": None,
    }
    store.ORDERS[order["id"]] = order
    return _order_out(order)


@router.get("/{order_id}")
def get_order(order_id: int) -> dict:
    order = store.ORDERS.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="заказ не найден")
    return _order_out(order)


@router.get("")
def list_orders() -> list[dict]:
    return [_order_out(o) for o in store.ORDERS.values()]
