"""Ролевые проверки CRUD: только qa может изменять проекты/стенды/пользователей.

Согласно README (## Роли): qa — «всё», manager — «запускать прогоны, видеть
все данные», customer — «только запуск и просмотр отчётов». Ни manager, ни
customer не входят в require_roles("qa") ни на одном write-эндпоинте
(app/routers/projects.py, app/routers/users.py), поэтому оба должны получать
403 на POST/PUT/DELETE.
"""

import pytest

WRITE_REQUESTS = [
    ("post", "/api/projects", {"name": "tmp_proj", "path": "/tmp/tmp_proj", "venv": ".venv"}),
    ("put", "/api/projects/bike_fit", {"path": "/tmp/new-path"}),
    ("delete", "/api/projects/bike_fit", None),
    ("post", "/api/projects/bike_fit/stands", {"name": "stg", "url": "http://stg"}),
    # put/delete stand используют несуществующий id — это ок: проверка роли (403)
    # срабатывает раньше проверки существования ресурса (require_roles идёт первым
    # в сигнатуре зависимостей), поэтому 404 не должен маскировать 403.
    ("put", "/api/projects/bike_fit/stands/1", {"url": "http://x"}),
    ("delete", "/api/projects/bike_fit/stands/1", None),
    ("post", "/api/users", {"login": "tmp_user", "password": "x", "role": "customer"}),
    ("put", "/api/users/customer", {"onboarded": True}),
    ("delete", "/api/users/customer", None),
    # Пресеты запуска на manual_only-стенде stage у auto_tests_vshgu_cloude (сидируется
    # в init_db() на любой пустой БД, см. app/db.py::_seed_vshgu_project) — put/delete
    # используют несуществующий id пресета по той же причине, что и put/delete stand
    # выше: 403 из require_roles("qa") должен срабатывать раньше 404 "Preset not found".
    (
        "post",
        "/api/projects/auto_tests_vshgu_cloude/stands/stage/presets",
        {"name": "tmp_preset", "target": "all", "marker": None},
    ),
    ("put", "/api/projects/auto_tests_vshgu_cloude/stands/stage/presets/99999", {"name": "x"}),
    ("delete", "/api/projects/auto_tests_vshgu_cloude/stands/stage/presets/99999", None),
]


@pytest.mark.parametrize("method, url, payload", WRITE_REQUESTS)
async def test_customer_forbidden_on_write_endpoints(customer_client, method, url, payload):
    resp = await customer_client.request(method, url, json=payload)
    assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}, ожидался 403"


@pytest.mark.parametrize("method, url, payload", WRITE_REQUESTS)
async def test_manager_forbidden_on_write_endpoints(manager_client, method, url, payload):
    resp = await manager_client.request(method, url, json=payload)
    assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}, ожидался 403"


async def test_manager_can_read_projects_and_stands(manager_client):
    # README: manager «видит все данные» — read-эндпоинты доступны любому
    # аутентифицированному пользователю (get_current_user, а не require_roles("qa")).
    resp = await manager_client.get("/api/projects")
    assert resp.status_code == 200
    resp = await manager_client.get("/api/projects/bike_fit/stands")
    assert resp.status_code == 200


async def test_customer_can_read_projects_and_stands(customer_client):
    resp = await customer_client.get("/api/projects")
    assert resp.status_code == 200
    resp = await customer_client.get("/api/projects/bike_fit/stands")
    assert resp.status_code == 200


async def test_manager_forbidden_on_list_users(manager_client):
    # Найдено при чтении кода: GET /api/users тоже защищён require_roles("qa")
    # (app/routers/users.py:list_users), а не только get_current_user — то есть
    # список пользователей недоступен даже manager'у на чтение, только qa.
    resp = await manager_client.get("/api/users")
    assert resp.status_code == 403


async def test_customer_forbidden_on_list_users(customer_client):
    resp = await customer_client.get("/api/users")
    assert resp.status_code == 403
