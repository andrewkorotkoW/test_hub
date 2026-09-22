"""REST API поверх app/core/coverage.py (app/routers/coverage.py).

coverage.py — чистый ast.parse, без исполнения pytest, поэтому фикстурному
проекту достаточно быть синтаксически валидным: реальных импортов между
api/endpoints/*.py, conftest.py и tests/*.py не требуется (в отличие от
runner-тестов в conftest.py, где pytest реально исполняется).

app.core.coverage.COVERAGE_DIR вычисляется один раз при импорте модуля
(settings.WORKSPACE_DIR / "coverage"), поэтому изолировать recalc()/
load_cached() от реального workspace/coverage/ репозитория можно только
монки-патчем самого атрибута модуля, а не settings.WORKSPACE_DIR.

qa_client/manager_client/customer_client (tests/conftest.py) все логинятся на
ОДНОМ общем httpx.AsyncClient ("client" fixture) — второй login() в рамках
того же теста перезатирает cookie первого. Поэтому тесты, которым нужно
сравнить доступ нескольких ролей в одном тесте, поднимают отдельные
AsyncClient через role_client(role), как это делает conftest.py для
superadmin_client.
"""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app as fastapi_app

from .conftest import login, register_project
from app.config import settings
from app.core import coverage
from app.db import get_connection

API_ENDPOINT_SRC = '''\
class FooEndpoint:
    PATH = "/foo"

    def __init__(self, client):
        self.client = client

    def list_foo(self):
        return self.client.get(self.PATH)

    def get_foo(self, foo_id):
        return self.client.get(f"{self.PATH}/{foo_id}")
'''

CONFTEST_SRC = '''\
import pytest


@pytest.fixture()
def foo_endpoint():
    return FooEndpoint(None)
'''

TESTS_SRC = '''\
import pytest


def test_list_foo(foo_endpoint):
    foo_endpoint.list_foo()


def test_get_foo(foo_endpoint):
    foo_endpoint.get_foo(1)


@pytest.mark.env("develop")
def test_get_foo_develop_only(foo_endpoint):
    foo_endpoint.get_foo(2)
'''

ROUTES_TSV = (
    "foo.index\tGET\t/api/v1/foo\n"
    "foo.show\tGET\t/api/v1/foo/{foo}\n"
    "foo.create\tPOST\t/api/v1/foo\n"
    "bar.destroy\tDELETE\t/api/v1/bar/{bar}\n"
)

PAGE_OBJECT_SRC = '''\
class FooPage:
    LIST_PATH = "/admin/foo"

    def __init__(self, page):
        self.page = page

    def open_list(self):
        self.page.goto(self.LIST_PATH)
'''

PAGE_TESTS_SRC = '''\
from ui.pages.foo_page import FooPage


def test_open_foo_list(page):
    FooPage(page).open_list()
'''

# страница /admin/foo уже открывается тестом выше; /admin/reports нет ни в одном
# UI-тесте — должна попасть в инвентарь непокрытой через routes.tsv
ROUTES_TSV_WITH_FRONTEND = ROUTES_TSV + (
    "frontend.foo.list\tGET\t/admin/foo\n"
    "frontend.reports\tGET\t/admin/reports\n"
)

ROLE_CREDENTIALS = {"qa": ("qa", "qa"), "manager": ("manager", "manager"), "customer": ("customer", "customer")}


@pytest.fixture()
def isolated_coverage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "COVERAGE_DIR", tmp_path / "coverage")


@pytest.fixture()
def coverage_project_dir(tmp_path):
    proj = tmp_path / "cov_proj"
    (proj / "api" / "endpoints").mkdir(parents=True)
    (proj / "api" / "endpoints" / "foo_endpoint.py").write_text(API_ENDPOINT_SRC)
    (proj / "conftest.py").write_text(CONFTEST_SRC)
    (proj / "tests").mkdir()
    (proj / "tests" / "test_foo.py").write_text(TESTS_SRC)
    return proj


@pytest.fixture()
def coverage_project_dir_with_pages(coverage_project_dir):
    proj = coverage_project_dir
    (proj / "ui" / "pages").mkdir(parents=True)
    (proj / "ui" / "pages" / "foo_page.py").write_text(PAGE_OBJECT_SRC)
    (proj / "tests" / "test_foo_page.py").write_text(PAGE_TESTS_SRC)
    return proj


@pytest_asyncio.fixture()
async def role_client(db_path):
    """Фабрика независимых AsyncClient (каждый на своей cookie-сессии), в
    отличие от qa_client/manager_client/customer_client, разделяющих один
    и тот же httpx.AsyncClient."""
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


def _write_routes_tsv(name: str, content: str = ROUTES_TSV) -> None:
    path = coverage.routes_tsv_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _register_with_stands(qa_client, name, project_dir):
    await register_project(qa_client, name, project_dir)
    for stand in ("develop", "stage"):
        resp = await qa_client.post(f"/api/projects/{name}/stands", json={"name": stand, "url": ""})
        assert resp.status_code == 201, resp.text


async def test_get_coverage_lazily_recalculates_and_builds_summary(
    qa_client, isolated_coverage_dir, coverage_project_dir
):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    resp = await qa_client.get("/api/projects/cov_proj/coverage")
    assert resp.status_code == 200
    body = resp.json()

    assert body["project"] == "cov_proj"
    assert body["routes_total"] == 4
    assert body["routes_covered"] == 2
    assert body["zero_coverage_areas"] == ["bar"]

    stands = {s["stand"]: s for s in body["stands"]}
    assert set(stands) == {"develop", "stage"}
    for stand in stands.values():
        assert stand["routes_total"] == 4
        assert stand["routes_covered"] == 2
        assert stand["percent"] == 50.0

    areas = {a["area"]: a for a in body["map"]}
    assert set(areas) == {"foo", "bar"}
    # path один и тот же ("/api/v1/foo") у foo.index (GET) и foo.create (POST) —
    # различаются только методом, поэтому ключ должен быть (methods, path).
    foo_routes = {(tuple(r["methods"]), r["path"]): r for r in areas["foo"]["routes"]}
    assert foo_routes[(("GET",), "/api/v1/foo")]["tests_count"] == 1  # foo.index: только test_list_foo
    assert foo_routes[(("GET",), "/api/v1/foo")]["shared"] is False
    assert foo_routes[(("POST",), "/api/v1/foo")]["tests_count"] == 0  # foo.create: не покрыт
    assert foo_routes[(("GET",), "/api/v1/foo/{foo}")]["tests_count"] == 2  # foo.show: 2 теста -> пересечение
    assert foo_routes[(("GET",), "/api/v1/foo/{foo}")]["shared"] is True
    assert areas["bar"]["routes"][0]["tests_count"] == 0


async def test_get_coverage_visible_to_manager_and_customer(
    role_client, isolated_coverage_dir, coverage_project_dir
):
    qa = await role_client("qa")
    await _register_with_stands(qa, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    for role in ("manager", "customer"):
        client = await role_client(role)
        resp = await client.get("/api/projects/cov_proj/coverage")
        assert resp.status_code == 200
        assert resp.json()["routes_total"] == 4


async def test_recalc_requires_qa_role(role_client, isolated_coverage_dir, coverage_project_dir):
    qa = await role_client("qa")
    await _register_with_stands(qa, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    for role in ("manager", "customer"):
        forbidden_client = await role_client(role)
        forbidden = await forbidden_client.post("/api/projects/cov_proj/coverage/recalc")
        assert forbidden.status_code == 403

    ok = await qa.post("/api/projects/cov_proj/coverage/recalc")
    assert ok.status_code == 200
    assert ok.json()["routes_total"] == 4


async def test_upload_routes_replaces_tsv_and_triggers_recalc(
    role_client, isolated_coverage_dir, coverage_project_dir
):
    qa = await role_client("qa")
    await _register_with_stands(qa, "cov_proj", coverage_project_dir)

    files = {"file": ("routes.tsv", ROUTES_TSV, "text/tab-separated-values")}

    for role in ("manager", "customer"):
        forbidden_client = await role_client(role)
        forbidden = await forbidden_client.post(
            "/api/projects/cov_proj/coverage/routes",
            files={"file": ("routes.tsv", ROUTES_TSV, "text/tab-separated-values")},
        )
        assert forbidden.status_code == 403

    resp = await qa.post("/api/projects/cov_proj/coverage/routes", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["routes_parsed"] == 4
    assert body["coverage"]["routes_total"] == 4
    assert coverage.routes_tsv_path("cov_proj").read_text(encoding="utf-8") == ROUTES_TSV


async def test_upload_routes_rejects_malformed_tsv(qa_client, isolated_coverage_dir, coverage_project_dir):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)

    bad = {"file": ("routes.tsv", "foo.index\tGET\n", "text/tab-separated-values")}
    resp = await qa_client.post("/api/projects/cov_proj/coverage/routes", files=bad)
    assert resp.status_code == 422

    bad_method = {"file": ("routes.tsv", "foo.index\tWRONG\t/api/v1/foo\n", "text/tab-separated-values")}
    resp = await qa_client.post("/api/projects/cov_proj/coverage/routes", files=bad_method)
    assert resp.status_code == 422

    empty = {"file": ("routes.tsv", "   \n\n", "text/tab-separated-values")}
    resp = await qa_client.post("/api/projects/cov_proj/coverage/routes", files=empty)
    assert resp.status_code == 422

    no_leading_slash = {"file": ("routes.tsv", "foo.index\tGET\tapi/v1/foo\n", "text/tab-separated-values")}
    resp = await qa_client.post("/api/projects/cov_proj/coverage/routes", files=no_leading_slash)
    assert resp.status_code == 422

    # routes.tsv не в UTF-8 (например, экспортирован в latin-1) — должен быть отклонён
    # как 422, а не 500 на UnicodeDecodeError внутри file.read()/decode().
    non_utf8 = {"file": ("routes.tsv", "café.index\tGET\t/api/v1/foo\n".encode("latin-1"))}
    resp = await qa_client.post("/api/projects/cov_proj/coverage/routes", files=non_utf8)
    assert resp.status_code == 422


async def test_get_route_coverage_lists_tests_with_env(
    role_client, isolated_coverage_dir, coverage_project_dir
):
    qa = await role_client("qa")
    await _register_with_stands(qa, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")
    await qa.post("/api/projects/cov_proj/coverage/recalc")

    for role in ("qa", "manager", "customer"):
        client = await role_client(role)
        resp = await client.get(
            "/api/projects/cov_proj/coverage/route", params={"method": "get", "path": "/api/v1/foo/{foo}"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "foo.show"
        nodeids = {t["nodeid"]: t for t in body["tests"]}
        assert set(nodeids) == {"tests/test_foo.py::test_get_foo", "tests/test_foo.py::test_get_foo_develop_only"}
        assert nodeids["tests/test_foo.py::test_get_foo"]["env"] is None
        assert nodeids["tests/test_foo.py::test_get_foo_develop_only"]["env"] == "develop"
        # без прогонов на стендах статус теста по каждому стенду ещё не известен
        for stand_status in nodeids["tests/test_foo.py::test_get_foo"]["status"].values():
            assert stand_status is None


async def test_get_route_coverage_404_for_unknown_route(qa_client, isolated_coverage_dir, coverage_project_dir):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    resp = await qa_client.get(
        "/api/projects/cov_proj/coverage/route", params={"method": "GET", "path": "/api/v1/does-not-exist"}
    )
    assert resp.status_code == 404


async def test_get_route_coverage_404_for_nonsense_method(qa_client, isolated_coverage_dir, coverage_project_dir):
    """method — произвольная строка (не выбор из ограниченного списка): FastAPI её
    примет как обычный str-параметр, а не 422, поэтому несуществующий метод должен
    просто не найти маршрут (404), а не 500."""
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    resp = await qa_client.get(
        "/api/projects/cov_proj/coverage/route", params={"method": "TRACE", "path": "/api/v1/foo/{foo}"}
    )
    assert resp.status_code == 404


async def test_coverage_endpoints_404_for_unknown_project(qa_client, isolated_coverage_dir):
    for method, url, kwargs in (
        ("get", "/api/projects/no_such_proj/coverage", {}),
        ("get", "/api/projects/no_such_proj/coverage/tree", {}),
        ("get", "/api/projects/no_such_proj/coverage/route", {"params": {"method": "GET", "path": "/x"}}),
        ("get", "/api/projects/no_such_proj/coverage/test", {"params": {"id": "tests/test_x.py::test_x"}}),
        ("post", "/api/projects/no_such_proj/coverage/recalc", {}),
        (
            "post",
            "/api/projects/no_such_proj/coverage/routes",
            {"files": {"file": ("routes.tsv", ROUTES_TSV, "text/tab-separated-values")}},
        ),
    ):
        resp = await getattr(qa_client, method)(url, **kwargs)
        assert resp.status_code == 404, f"{method.upper()} {url} -> {resp.status_code}"


async def test_get_test_coverage_lists_routes(role_client, isolated_coverage_dir, coverage_project_dir):
    qa = await role_client("qa")
    await _register_with_stands(qa, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")
    await qa.post("/api/projects/cov_proj/coverage/recalc")

    for role in ("qa", "manager", "customer"):
        client = await role_client(role)
        resp = await client.get(
            "/api/projects/cov_proj/coverage/test", params={"id": "tests/test_foo.py::test_get_foo"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["nodeid"] == "tests/test_foo.py::test_get_foo"
        paths = {r["path"] for r in body["routes"]}
        assert paths == {"/api/v1/foo/{foo}"}
        assert body["pages"] == []


async def test_get_test_coverage_404_for_unknown_test(qa_client, isolated_coverage_dir, coverage_project_dir):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    resp = await qa_client.get(
        "/api/projects/cov_proj/coverage/test", params={"id": "tests/test_foo.py::test_does_not_exist"}
    )
    assert resp.status_code == 404


# ------------------------------------------------------------------ слой UI-страниц

async def test_coverage_summary_includes_pages_area_and_totals(
    qa_client, isolated_coverage_dir, coverage_project_dir_with_pages
):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir_with_pages)
    _write_routes_tsv("cov_proj", ROUTES_TSV_WITH_FRONTEND)

    resp = await qa_client.get("/api/projects/cov_proj/coverage")
    assert resp.status_code == 200
    body = resp.json()

    # /admin/foo и /admin/reports из routes.tsv не должны попасть в routes_total
    # (это не /api/ маршруты) — только foo.*/bar.* из ROUTES_TSV
    assert body["routes_total"] == 4
    assert body["pages_total"] == 2
    assert body["pages_covered"] == 1

    areas = {a["area"]: a for a in body["map"]}
    assert "UI: страницы" in areas
    pages_by_path = {r["path"]: r for r in areas["UI: страницы"]["routes"]}
    assert set(pages_by_path) == {"/admin/foo", "/admin/reports"}
    assert pages_by_path["/admin/foo"]["tests_count"] == 1
    assert pages_by_path["/admin/foo"]["kind"] == "page"
    assert pages_by_path["/admin/reports"]["tests_count"] == 0
    # области без покрытия учитывают и слой страниц
    assert "UI: страницы" not in body["zero_coverage_areas"]


async def test_get_page_coverage_lists_tests(qa_client, isolated_coverage_dir, coverage_project_dir_with_pages):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir_with_pages)
    _write_routes_tsv("cov_proj", ROUTES_TSV_WITH_FRONTEND)
    await qa_client.post("/api/projects/cov_proj/coverage/recalc")

    resp = await qa_client.get("/api/projects/cov_proj/coverage/page", params={"path": "/admin/foo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "/admin/foo"
    assert {t["nodeid"] for t in body["tests"]} == {"tests/test_foo_page.py::test_open_foo_list"}


async def test_get_page_coverage_404_for_unknown_page(qa_client, isolated_coverage_dir, coverage_project_dir_with_pages):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir_with_pages)
    _write_routes_tsv("cov_proj", ROUTES_TSV_WITH_FRONTEND)

    resp = await qa_client.get("/api/projects/cov_proj/coverage/page", params={"path": "/does-not-exist"})
    assert resp.status_code == 404


async def test_get_test_coverage_includes_pages(qa_client, isolated_coverage_dir, coverage_project_dir_with_pages):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir_with_pages)
    _write_routes_tsv("cov_proj", ROUTES_TSV_WITH_FRONTEND)
    await qa_client.post("/api/projects/cov_proj/coverage/recalc")

    resp = await qa_client.get(
        "/api/projects/cov_proj/coverage/test",
        params={"id": "tests/test_foo_page.py::test_open_foo_list"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["routes"] == []
    assert {p["path"] for p in body["pages"]} == {"/admin/foo"}


# ------------------------------------------------------------------ /coverage/graph

async def test_get_coverage_graph_by_area(qa_client, isolated_coverage_dir, coverage_project_dir):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")
    await qa_client.post("/api/projects/cov_proj/coverage/recalc")

    resp = await qa_client.get("/api/projects/cov_proj/coverage/graph", params={"area": "foo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is False
    node_kinds = {n["kind"] for n in body["nodes"]}
    assert node_kinds == {"route", "test"}
    route_ids = {n["id"] for n in body["nodes"] if n["kind"] == "route"}
    test_ids = {n["id"] for n in body["nodes"] if n["kind"] == "test"}
    assert route_ids == {"route:foo.index", "route:foo.show", "route:foo.create"}
    assert test_ids == {
        "test:tests/test_foo.py::test_list_foo",
        "test:tests/test_foo.py::test_get_foo",
        "test:tests/test_foo.py::test_get_foo_develop_only",
    }
    for edge in body["edges"]:
        assert edge["source"] in test_ids
        assert edge["target"] in route_ids


async def test_get_coverage_graph_by_test(qa_client, isolated_coverage_dir, coverage_project_dir_with_pages):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir_with_pages)
    _write_routes_tsv("cov_proj", ROUTES_TSV_WITH_FRONTEND)
    await qa_client.post("/api/projects/cov_proj/coverage/recalc")

    resp = await qa_client.get(
        "/api/projects/cov_proj/coverage/graph",
        params={"test": "tests/test_foo_page.py::test_open_foo_list"},
    )
    assert resp.status_code == 200
    body = resp.json()
    kinds = {n["kind"] for n in body["nodes"]}
    assert kinds == {"test", "page"}


async def test_get_coverage_graph_requires_area_or_test(qa_client, isolated_coverage_dir, coverage_project_dir):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    resp = await qa_client.get("/api/projects/cov_proj/coverage/graph")
    assert resp.status_code == 422


async def test_get_coverage_graph_unknown_area_404(qa_client, isolated_coverage_dir, coverage_project_dir):
    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)
    _write_routes_tsv("cov_proj")

    resp = await qa_client.get("/api/projects/cov_proj/coverage/graph", params={"area": "does-not-exist"})
    assert resp.status_code == 404


# ---------------------------------------------------------------- дерево проекта (coverage/tree)
#
# coverage_project_dir не содержит .venv, поэтому runner.discover сам по себе
# вернёт {"error": ..., "tree": {}} (см. app/core/runner.py) — валидный ответ для
# проверки формы ответа и ролей, но без реальных данных. Чтобы проверить дерево
# и статусы тестов, discover монкипатчится напрямую в app.routers.coverage.

async def test_get_coverage_tree_without_venv_returns_error_and_empty_tree(
    role_client, isolated_coverage_dir, coverage_project_dir
):
    qa = await role_client("qa")
    await _register_with_stands(qa, "cov_proj", coverage_project_dir)

    for role in ("qa", "manager", "customer"):
        client = await role_client(role)
        resp = await client.get("/api/projects/cov_proj/coverage/tree")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tree"] == {}
        assert body["error"]
        assert set(body["stands"]) == {"develop", "stage"}
        assert body["statuses"] == {"develop": {}, "stage": {}}


async def test_get_coverage_tree_matches_discover_nodeids_with_run_status(
    qa_client, isolated_coverage_dir, isolated_allure_dir, coverage_project_dir, monkeypatch
):
    from app.routers import coverage as coverage_router

    await _register_with_stands(qa_client, "cov_proj", coverage_project_dir)

    async def fake_discover(path, venv):
        return {"tree": {"tests/test_foo.py": {"": ["test_list_foo"], "TestBar": ["test_x"]}}}

    monkeypatch.setattr(coverage_router.runner, "discover", fake_discover)

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, counts) VALUES ('cov_proj', 'develop', 'all', 'passed', '{}')"
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "a-result.json").write_text(
        json.dumps({"fullName": "tests.test_foo#test_list_foo", "status": "passed"}), encoding="utf-8"
    )
    (results_dir / "b-result.json").write_text(
        json.dumps({"fullName": "tests.test_foo.TestBar#test_x", "status": "failed"}), encoding="utf-8"
    )

    resp = await qa_client.get("/api/projects/cov_proj/coverage/tree")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tree"] == {"tests/test_foo.py": {"": ["test_list_foo"], "TestBar": ["test_x"]}}
    assert body["run_ids"]["develop"] == run_id
    assert body["run_ids"]["stage"] is None
    assert body["statuses"]["develop"] == {
        "tests/test_foo.py::test_list_foo": "passed",
        "tests/test_foo.py::TestBar::test_x": "failed",
    }
    assert body["statuses"]["stage"] == {}
