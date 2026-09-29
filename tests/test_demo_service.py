"""Встроенный демо-сервис (demo/app/) — самостоятельное FastAPI-приложение,
которое test_hub поднимает отдельным процессом при settings.TH_DEMO=1 (см.
app/main.py::lifespan). lifespan не выполняется в тестах на ASGITransport (см.
docstring tests/test_schedule.py) — здесь поэтому два независимых уровня проверки:

1. demo/app/ проверяется напрямую через ASGITransport, без реального порта и без
   лишнего subprocess — быстрый способ убедиться, что JSON-эндпоинты и HTML-страницы
   вообще работают.
2. Сам факт старта/остановки процесса проверяется тем же способом, каким это делает
   lifespan (тот же subprocess-запуск `sys.executable -m uvicorn demo.app.main:app`),
   но напрямую в тесте — в стиле tests/test_schedule.py, тестирующего планировщик
   отдельно от lifespan."""
import asyncio
import socket
import sys

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import BASE_DIR, settings
from demo.app import store
from demo.app.main import app as demo_app


@pytest.fixture(autouse=True)
def _reset_demo_store():
    # store.ORDERS/TOKENS копятся, пока живёт процесс демо-сервиса (см. docstring
    # demo/app/store.py) — между тестами этого файла (общий импортированный модуль)
    # сбрасываем их вручную, иначе заказы одного теста были бы видны в другом.
    store.reset()
    yield
    store.reset()


@pytest_asyncio.fixture()
async def demo_client():
    transport = ASGITransport(app=demo_app)
    async with AsyncClient(transport=transport, base_url="http://demo-testserver") as ac:
        yield ac


# ------------------------------------------------------------------ настройки TH_DEMO/TH_DEMO_PORT


def test_th_demo_enabled_by_default():
    # По умолчанию демо-сервис включён (см. комментарий в app/config.py) — рабочий
    # пример из коробки сразу после клонирования, без реальных стендов.
    assert settings.TH_DEMO is True
    assert settings.TH_DEMO_PORT == 8710


# ------------------------------------------------------------------ JSON-эндпоинты демо-сервиса


async def test_catalog_list_returns_seed_items(demo_client):
    resp = await demo_client.get("/api/catalog")
    assert resp.status_code == 200
    titles = {item["title"] for item in resp.json()}
    assert {"Кружка Demo", "Футболка Demo"} <= titles


async def test_catalog_item_not_found_returns_404(demo_client):
    resp = await demo_client.get("/api/catalog/9999")
    assert resp.status_code == 404


async def test_auth_login_success_returns_token(demo_client):
    resp = await demo_client.post("/api/auth/login", json={"login": "alice", "password": "alice123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["login"] == "alice"
    assert body["token"]

    me_resp = await demo_client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["login"] == "alice"


async def test_auth_login_wrong_password_returns_401(demo_client):
    resp = await demo_client.post("/api/auth/login", json={"login": "alice", "password": "wrong"})
    assert resp.status_code == 401


async def test_auth_me_without_token_returns_401(demo_client):
    resp = await demo_client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_orders_create_success_and_get_by_id(demo_client):
    create_resp = await demo_client.post("/api/orders", json={"item_id": 1, "qty": 2})
    assert create_resp.status_code == 200
    order = create_resp.json()
    assert order["total"] == 1000  # 500 * 2, товар без скидки

    get_resp = await demo_client.get(f"/api/orders/{order['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json() == order


async def test_orders_create_known_bug_ignores_discount(demo_client):
    # Намеренный баг демо-сервиса (см. demo/app/routers/orders.py::create_order) —
    # total не учитывает скидку. Тест фиксирует текущее (ошибочное) поведение, а не
    # чинит его: правки за пределами app/main.py::lifespan/этого файла вне scope задачи.
    resp = await demo_client.post("/api/orders", json={"item_id": 2, "qty": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1200  # должно быть 960 (1200 * 0.8), баг завышает сумму


async def test_orders_create_out_of_stock_returns_400(demo_client):
    resp = await demo_client.post("/api/orders", json={"item_id": 3, "qty": 1})
    assert resp.status_code == 400


async def test_orders_get_unknown_returns_404(demo_client):
    resp = await demo_client.get("/api/orders/999999")
    assert resp.status_code == 404


async def test_users_list_and_get_by_id(demo_client):
    list_resp = await demo_client.get("/api/users")
    assert list_resp.status_code == 200
    logins = {u["login"] for u in list_resp.json()}
    assert {"alice", "bob"} <= logins

    get_resp = await demo_client.get("/api/users/1")
    assert get_resp.status_code == 200
    assert get_resp.json()["login"] == "alice"
    assert "password" not in get_resp.json()


async def test_users_get_unknown_returns_404(demo_client):
    resp = await demo_client.get("/api/users/9999")
    assert resp.status_code == 404


# ------------------------------------------------------------------ HTML-страницы демо-сервиса


async def test_login_page_renders_form(demo_client):
    resp = await demo_client.get("/login")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert 'id="login"' in resp.text
    assert 'id="password"' in resp.text
    assert 'id="submit"' in resp.text


async def test_catalog_page_renders_shell(demo_client):
    resp = await demo_client.get("/catalog")
    assert resp.status_code == 200
    assert 'id="items"' in resp.text


async def test_catalog_item_page_renders_shell(demo_client):
    resp = await demo_client.get("/catalog/1")
    assert resp.status_code == 200
    assert 'data-item-id="1"' in resp.text


async def test_order_page_renders_shell(demo_client):
    resp = await demo_client.get("/orders/1")
    assert resp.status_code == 200
    assert 'data-order-id="1"' in resp.text


# ------------------------------------------------------------------ факт старта/остановки процесса (см. app/main.py::lifespan)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_demo_service_subprocess_starts_and_serves_and_stops():
    # Тот же способ запуска, что app/main.py::lifespan использует для demo_proc
    # (sys.executable -m uvicorn demo.app.main:app, cwd=BASE_DIR) — но на отдельном
    # свободном порту и напрямую в тесте, минуя полный lifespan приложения (тот не
    # выполняется под ASGITransport, см. docstring этого файла).
    port = _free_port()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "demo.app.main:app",
        "--host", "127.0.0.1", "--port", str(port),
        "--log-level", "warning",
        cwd=str(BASE_DIR),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        started = False
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                if proc.returncode is not None:
                    break
                try:
                    resp = await client.get(f"{base_url}/api/catalog", timeout=1)
                    if resp.status_code == 200:
                        started = True
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)

        assert started, "демо-сервис (subprocess uvicorn demo.app.main:app) не поднялся вовремя"
        assert proc.returncode is None  # процесс всё ещё жив, пока сервис отвечает

        async with httpx.AsyncClient() as client:
            login_resp = await client.get(f"{base_url}/login", timeout=2)
            assert login_resp.status_code == 200
    finally:
        # Та же остановка, что делает lifespan при выходе (terminate -> wait с
        # таймаутом -> kill, если не успел).
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    assert proc.returncode is not None, "процесс демо-сервиса не завершился после terminate()"
