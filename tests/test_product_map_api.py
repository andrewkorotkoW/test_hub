"""REST API поверх app/core/product_map.py (app/routers/product_map.py):
GET /api/projects/{name}/product-map?stand= — форма ответа, права ролей (те же,
что у соседних ручек app.routers.coverage: qa/manager/customer читают), кэш по
(project, run_id) — повторный вызов без нового прогона не пересчитывает.

По образцу tests/test_coverage_api.py: role_client — независимые AsyncClient на
своей cookie-сессии (в отличие от qa_client/manager_client/customer_client,
которые делят один и тот же httpx.AsyncClient и затирают друг другу cookie при
логине в одном тесте)."""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app as fastapi_app

from .conftest import login, register_project
from app.config import settings
from app.core import product_map
from app.db import get_connection

ROLE_CREDENTIALS = {"qa": ("qa", "qa"), "manager": ("manager", "manager"), "customer": ("customer", "customer")}

_ORDERS_SRC = '''\
def test_list_orders():
    assert True


def test_delete_order():
    assert True
'''

_MAP_YML = """\
zones:
  - {id: main, label: "Основное", x: 0, y: 0, w: 400, h: 200}
nodes:
  - {id: orders, label: "Заказы", zone: main, x: 10, y: 10, w: 120, h: 40, tests: ["tests/api/orders"]}
  - {id: empty_screen, label: "Без тестов", zone: main, x: 10, y: 60, w: 120, h: 40}
edges: []
"""


@pytest.fixture()
def isolated_product_map_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(product_map, "PRODUCT_MAP_DIR", tmp_path / "product_map")


@pytest.fixture()
def pm_project_dir(tmp_path):
    proj = tmp_path / "pm_api_proj"
    (proj / "tests" / "api" / "orders").mkdir(parents=True)
    (proj / "tests" / "api" / "orders" / "test_orders.py").write_text(_ORDERS_SRC)
    (proj / "tests" / "product_map.yml").write_text(_MAP_YML, encoding="utf-8")
    return proj


@pytest_asyncio.fixture()
async def role_client(db_path):
    clients: list[AsyncClient] = []

    async def make(role: str) -> AsyncClient:
        transport = ASGITransport(app=fastapi_app)
        ac = AsyncClient(transport=transport, base_url="http://testserver")
        resp = await login(ac, *ROLE_CREDENTIALS[role])
        assert resp.status_code == 200, resp.text
        clients.append(ac)
        return ac

    yield make

    for ac in clients:
        await ac.aclose()


async def _register_with_stands(qa_client, name, project_dir, stands=("develop", "stage")):
    await register_project(qa_client, name, project_dir)
    for stand in stands:
        resp = await qa_client.post(f"/api/projects/{name}/stands", json={"name": stand, "url": ""})
        assert resp.status_code == 201, resp.text


def _write_allure_result(results_dir, filename, full_name, status, message=None):
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fullName": full_name, "status": status}
    if message:
        payload["statusDetails"] = {"message": message}
    (results_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


# ------------------------------------------------------------------ форма ответа

async def test_get_product_map_response_shape(
    qa_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir
):
    await _register_with_stands(qa_client, "pm_api_proj", pm_project_dir)

    resp = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["project"] == "pm_api_proj"
    assert body["stand"] == "stage"
    assert body["source"] == "file"
    assert body["run_id"] is None  # прогонов ещё не было
    assert set(body["canvas"]) == {"width", "height"}

    zone_ids = {z["id"] for z in body["zones"]}
    assert zone_ids == {"main"}

    nodes_by_id = {n["id"]: n for n in body["nodes"]}
    assert set(nodes_by_id) == {"orders", "empty_screen"}
    orders = nodes_by_id["orders"]
    assert orders["state"] == "grey"  # тесты есть, но прогонов на стенде ещё не было
    assert set(orders["tests_count"]) == {"api", "ui", "other", "total"}
    assert orders["tests_count"]["total"] == 2
    assert orders["sample_tests"] and set(orders["sample_tests"][0]) == {"nodeid", "name"}
    empty_screen = nodes_by_id["empty_screen"]
    assert empty_screen["state"] == "grey"
    assert empty_screen["tests_count"]["total"] == 0

    assert body["edges"] == []
    summary = body["summary"]
    assert set(summary) == {"total", "covered", "no_tests", "failing"}
    assert summary["total"] == 2
    # summary.no_tests считает все узлы в состоянии grey — и без тестов вовсе (empty_screen),
    # и с тестами, ещё не засветившимися ни в одном прогоне стенда (orders)
    assert summary["no_tests"] == 2


async def test_get_product_map_reflects_run_results(
    qa_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir
):
    await _register_with_stands(qa_client, "pm_api_proj", pm_project_dir, stands=("stage",))

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, counts) VALUES ('pm_api_proj', 'stage', 'all', 'failed', '{}')"
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    _write_allure_result(results_dir, "00-result.json", "tests.api.orders.test_orders#test_list_orders", "passed")
    _write_allure_result(results_dir, "01-result.json", "tests.api.orders.test_orders#test_delete_order", "failed")

    resp = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    orders = next(n for n in body["nodes"] if n["id"] == "orders")
    assert orders["state"] == "red"
    assert body["summary"]["failing"] == 1
    assert body["summary"]["covered"] == 0


async def test_get_product_map_default_stand_when_omitted(
    qa_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir
):
    await _register_with_stands(qa_client, "pm_api_proj", pm_project_dir, stands=("develop", "stage"))
    resp = await qa_client.get("/api/projects/pm_api_proj/product-map")
    assert resp.status_code == 200, resp.text
    # stats.default_stand: первый по алфавиту -> "develop"
    assert resp.json()["stand"] == "develop"


async def test_get_product_map_unknown_stand_404(
    qa_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir
):
    await _register_with_stands(qa_client, "pm_api_proj", pm_project_dir, stands=("stage",))
    resp = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "no_such_stand"})
    assert resp.status_code == 404


async def test_get_product_map_unknown_project_404(qa_client, isolated_product_map_dir):
    resp = await qa_client.get("/api/projects/no_such_proj/product-map")
    assert resp.status_code == 404


async def test_get_product_map_no_stands_registered_404(qa_client, isolated_product_map_dir, pm_project_dir):
    await register_project(qa_client, "pm_api_proj", pm_project_dir)
    resp = await qa_client.get("/api/projects/pm_api_proj/product-map")
    assert resp.status_code == 404


# ------------------------------------------------------------------ fallback (без файла карты) через API

async def test_get_product_map_fallback_when_no_map_file(qa_client, isolated_product_map_dir, tmp_path):
    proj = tmp_path / "no_map_proj"
    (proj / "tests" / "api" / "orders").mkdir(parents=True)
    (proj / "tests" / "api" / "orders" / "test_orders.py").write_text(_ORDERS_SRC)
    await _register_with_stands(qa_client, "no_map_proj", proj, stands=("stage",))

    resp = await qa_client.get("/api/projects/no_map_proj/product-map", params={"stand": "stage"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "fallback"
    assert body["message"]
    zone_ids = {z["id"] for z in body["zones"]}
    assert zone_ids == {"api"}


# ------------------------------------------------------------------ права ролей

async def test_get_product_map_visible_to_manager_and_customer(
    role_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir
):
    qa = await role_client("qa")
    await _register_with_stands(qa, "pm_api_proj", pm_project_dir, stands=("stage",))

    for role in ("manager", "customer"):
        client = await role_client(role)
        resp = await client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["project"] == "pm_api_proj"


async def test_get_product_map_requires_authentication(client, isolated_product_map_dir, pm_project_dir):
    resp = await client.get("/api/projects/pm_api_proj/product-map")
    assert resp.status_code == 401


# ------------------------------------------------------------------ кэш по (project, run_id)

async def test_product_map_cache_not_recalculated_without_new_run(
    qa_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir, monkeypatch
):
    await _register_with_stands(qa_client, "pm_api_proj", pm_project_dir, stands=("stage",))

    resp1 = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp1.status_code == 200
    first_generated_at = resp1.json()["generated_at"]

    calls = []
    real_recalc = product_map.recalc

    def spy_recalc(*args, **kwargs):
        calls.append(1)
        return real_recalc(*args, **kwargs)

    monkeypatch.setattr(product_map, "recalc", spy_recalc)

    resp2 = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp2.status_code == 200
    assert resp2.json()["generated_at"] == first_generated_at
    assert calls == [], "без нового прогона и без изменения карты кэш не должен пересчитываться"


async def test_product_map_cache_invalidated_by_new_run(
    qa_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir, monkeypatch
):
    await _register_with_stands(qa_client, "pm_api_proj", pm_project_dir, stands=("stage",))
    resp1 = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp1.status_code == 200
    assert resp1.json()["run_id"] is None

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, counts) VALUES ('pm_api_proj', 'stage', 'all', 'passed', '{}')"
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    calls = []
    real_recalc = product_map.recalc

    def spy_recalc(*args, **kwargs):
        calls.append(1)
        return real_recalc(*args, **kwargs)

    monkeypatch.setattr(product_map, "recalc", spy_recalc)

    resp2 = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp2.status_code == 200
    assert resp2.json()["run_id"] == run_id
    assert calls == [1], "новый завершённый прогон на стенде должен вызвать пересчёт"


async def test_product_map_cache_invalidated_by_map_file_change(
    qa_client, isolated_product_map_dir, isolated_allure_dir, pm_project_dir, monkeypatch
):
    await _register_with_stands(qa_client, "pm_api_proj", pm_project_dir, stands=("stage",))
    resp1 = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp1.status_code == 200
    assert {n["id"] for n in resp1.json()["nodes"]} == {"orders", "empty_screen"}

    (pm_project_dir / "tests" / "product_map.yml").write_text(
        _MAP_YML + "\n# изменена разметка карты\n", encoding="utf-8"
    )

    calls = []
    real_recalc = product_map.recalc

    def spy_recalc(*args, **kwargs):
        calls.append(1)
        return real_recalc(*args, **kwargs)

    monkeypatch.setattr(product_map, "recalc", spy_recalc)

    resp2 = await qa_client.get("/api/projects/pm_api_proj/product-map", params={"stand": "stage"})
    assert resp2.status_code == 200
    assert calls == [1], "изменение файла карты должно инвалидировать кэш"
