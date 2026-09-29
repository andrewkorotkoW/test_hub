"""In-memory данные демо-магазина: пользователи, каталог, заказы.

Не база данных — обычные словари уровня модуля. Демо-сервис живёт ровно
столько, сколько запущен test_hub (см. lifespan в app/main.py), сброс
состояния при рестарте — ожидаемое поведение для демо."""
from __future__ import annotations

import itertools
from typing import Optional, TypedDict


class User(TypedDict):
    id: int
    login: str
    password: str
    name: str
    role: str


class CatalogItem(TypedDict):
    id: int
    title: str
    price: int
    discount: int  # проценты, 0..100
    stock: int


class Order(TypedDict):
    id: int
    item_id: int
    qty: int
    unit_price: int
    discount: int
    total: int
    user_id: Optional[int]


USERS: dict[int, User] = {
    1: {"id": 1, "login": "alice", "password": "alice123", "name": "Алиса", "role": "customer"},
    2: {"id": 2, "login": "bob", "password": "bob123", "name": "Боб", "role": "customer"},
}

CATALOG: dict[int, CatalogItem] = {
    1: {"id": 1, "title": "Кружка Demo", "price": 500, "discount": 0, "stock": 10},
    2: {"id": 2, "title": "Футболка Demo", "price": 1200, "discount": 20, "stock": 5},
    3: {"id": 3, "title": "Стикерпак Demo", "price": 300, "discount": 10, "stock": 0},
    4: {"id": 4, "title": "Кепка Demo", "price": 900, "discount": 0, "stock": 3},
}

ORDERS: dict[int, Order] = {}
TOKENS: dict[str, int] = {}  # token -> user_id

_order_id_seq = itertools.count(1)


def reset() -> None:
    """Используется только вручную (нет эндпоинта/фикстуры, дергающей это на
    каждый тест) — заказы копятся, пока живёт процесс демо-сервиса, как и
    задумано для демо-данных."""
    ORDERS.clear()
    TOKENS.clear()
    global _order_id_seq
    _order_id_seq = itertools.count(1)


def next_order_id() -> int:
    return next(_order_id_seq)


def find_user_by_login(login: str) -> Optional[User]:
    return next((u for u in USERS.values() if u["login"] == login), None)
