"""Юнит-тесты app/core/coverage.py: извлечение маршрутов из AST, нормализация путей,
сопоставление с инвентарём routes.tsv, граф тест -> маршрут/страница, маркер env.

coverage.py работает чисто статически (ast.parse по текстовым файлам), ничего не
исполняет — поэтому фикстурному мини-проекту не нужен ни .venv, ни рабочий pytest
(в отличие от tests/conftest.py::runnable_project_dir для раннера, см. заметку
testhub-runner-tests): достаточно разложить .py-файлы по tmp_path в ожидаемой
структуре (api/endpoints, ui/pages, tests/conftest.py + tests/test_*.py)."""

import json

import pytest

from app.config import settings
from app.core import coverage
from app.db import get_connection


# ------------------------------------------------------------------ _normalize_path

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("/api/v1/programs", "/api/v1/programs"),
        ("/api/v1/programs/{program_id}", "/api/v1/programs/{}"),
        ("/api/v1/programs/{id}", "/api/v1/programs/{}"),
        ("/api/v1/programs?active=1", "/api/v1/programs"),
        ("/api/v1/programs/{a}/streams/{b}", "/api/v1/programs/{}/streams/{}"),
        ("/api/v1/programs/{program_id}?x=1", "/api/v1/programs/{}"),
    ],
)
def test_normalize_path(raw, expected):
    assert coverage._normalize_path(raw) == expected


# ------------------------------------------------------------------ parse_routes_tsv

_ROUTES_TSV = """\
programs.index\tGET\t/api/v1/programs
programs.store\tPOST\t/api/v1/programs/{program}
programs.show\tGET\t/api/v1/programs/{id}
programs.update\tPUT\t/api/v1/programs/{id}
programs.destroy\tDELETE\t/api/v1/programs/{id}
programs.archive\tGET\t/api/v1/programs/{id}/archive
programs.multi\tGET,POST\t/api/v1/programs/{id}/multi
l5-swagger.default.api\tGET\t/api/documentation
passport.token\tPOST\t/api/v1/oauth/token
sanctum.csrf-cookie\tGET\t/sanctum/csrf-cookie

malformed line without tabs
onlytwo\tGET
"""


@pytest.fixture()
def routes_tsv_file(tmp_path):
    path = tmp_path / "routes.tsv"
    path.write_text(_ROUTES_TSV, encoding="utf-8")
    return path


def test_parse_routes_tsv_skips_malformed_and_blank_lines(routes_tsv_file):
    routes = coverage.parse_routes_tsv(routes_tsv_file)
    assert len(routes) == 10
    assert all(r.name for r in routes)


def test_parse_routes_tsv_missing_file(tmp_path):
    assert coverage.parse_routes_tsv(tmp_path / "missing.tsv") == []


def test_parse_routes_tsv_multi_method(routes_tsv_file):
    routes = {r.name: r for r in coverage.parse_routes_tsv(routes_tsv_file)}
    assert routes["programs.multi"].methods == ("GET", "POST")


def test_parse_routes_tsv_normalizes_param_names(routes_tsv_file):
    routes = {r.name: r for r in coverage.parse_routes_tsv(routes_tsv_file)}
    # {program} в инвентаре и {program_id}/f-строка в коде должны схлопнуться в одно "{}"
    assert routes["programs.store"].normalized == "/api/v1/programs/{}"
    assert routes["programs.show"].normalized == "/api/v1/programs/{}"


def test_parse_routes_tsv_keeps_foreign_prefixes(routes_tsv_file):
    routes = {r.name: r for r in coverage.parse_routes_tsv(routes_tsv_file)}
    assert routes["l5-swagger.default.api"].normalized == "/api/documentation"
    assert routes["passport.token"].normalized == "/api/v1/oauth/token"
    assert routes["sanctum.csrf-cookie"].normalized == "/sanctum/csrf-cookie"


# ------------------------------------------------------------------ фикстурный мини-проект
#
# ProgramsEndpoint покрывает все HTTP_VERBS, self.PATH-константу внутри f-строки и
# путь без плейсхолдера. raw_ping() дёргает self.client напрямую с уже готовым
# /api/ префиксом — маршрут, которого нет в инвентаре ни одного теста ниже.
_PROGRAMS_ENDPOINT = '''\
class ProgramsEndpoint:
    PATH = "/programs"

    def __init__(self, client):
        self.client = client

    def list_programs(self):
        return self.client.get(self.PATH)

    def create(self, program_id):
        return self.client.post(f"{self.PATH}/{program_id}")

    def get(self, program_id):
        return self.client.get(f"{self.PATH}/{program_id}")

    def update(self, program_id):
        return self.client.put(f"{self.PATH}/{program_id}")

    def patch_program(self, program_id):
        return self.client.patch(f"{self.PATH}/{program_id}")

    def delete(self, program_id):
        return self.client.delete(f"{self.PATH}/{program_id}")

    def raw_ping(self):
        return self.client.get("/api/v1/ping")
'''

_ADMIN_PROGRAMS_PAGE = '''\
class AdminProgramsPage:
    LIST_PATH = "/admin/programs"

    def __init__(self, page):
        self.page = page

    def open_list(self):
        self.page.goto(self.LIST_PATH)

    def open_program(self, program_id):
        self.page.goto(f"{self.LIST_PATH}/{program_id}")
'''

# open() оборачивает self.page.goto(path) с параметром (не резолвится статически),
# а open_login() дёргает self.open("/login") с литералом — так проверяется ветка
# is_self_open в discover_page_routes отдельно от self.page.goto.
_LOGIN_PAGE = '''\
class LoginPage:
    def __init__(self, page):
        self.page = page

    def open(self, path):
        self.page.goto(path)

    def open_login(self):
        self.open("/login")
'''

_CONFTEST = '''\
import pytest

from api.endpoints.programs import ProgramsEndpoint
from ui.pages.admin_programs import AdminProgramsPage


@pytest.fixture
def api_client():
    return object()


@pytest.fixture
def page():
    return object()


@pytest.fixture
def programs_endpoint(api_client):
    return ProgramsEndpoint(api_client)


@pytest.fixture
def created_program(programs_endpoint):
    return programs_endpoint.create("42")


@pytest.fixture
def created_stream_program(created_program):
    return created_program


@pytest.fixture
def programs_page(page):
    page_obj = AdminProgramsPage(page)
    page_obj.open_program("42")
    return page_obj


@pytest.fixture
def visited_programs_page(programs_page):
    return programs_page
'''

_TEST_API_GRAPH = '''\
from api.endpoints.programs import ProgramsEndpoint


def test_list_programs_direct(api_client):
    ProgramsEndpoint(api_client).list_programs()


def test_get_program_direct(api_client):
    endpoint = ProgramsEndpoint(api_client)
    endpoint.get("42")


def test_create_via_fixture(created_program):
    assert created_program is not None


def test_create_via_transitive_fixture(created_stream_program):
    assert created_stream_program is not None


def test_raw_client_direct(api_client):
    api_client.get("/api/v1/programs")
'''

_TEST_PAGE_GRAPH = '''\
from ui.pages.admin_programs import AdminProgramsPage
from ui.pages.login import LoginPage


def test_open_list_direct(page):
    AdminProgramsPage(page).open_list()


def test_open_program_via_fixture(programs_page):
    assert programs_page is not None


def test_open_program_via_transitive_fixture(visited_programs_page):
    assert visited_programs_page is not None


def test_login_direct(page):
    LoginPage(page).open_login()
'''

_TEST_ENV_MARKER = '''\
import pytest


def test_no_marker():
    assert True


@pytest.mark.env("stage")
def test_only_stage():
    assert True


class TestGroupMarker:
    def test_class_no_marker(self):
        assert True


@pytest.mark.env("stage")
class TestGroupStage:
    def test_in_marked_class(self):
        assert True
'''

# Модульный pytestmark действует на тесты без собственного маркера; маркер на самом
# тесте должен его переопределять (см. приоритет в _handle: decorator or class_env or
# module_env).
_TEST_ENV_MODULE_MARKER = '''\
import pytest

pytestmark = pytest.mark.env("stage")


def test_module_level_stage():
    assert True


@pytest.mark.env("develop")
def test_overrides_module_marker():
    assert True
'''


@pytest.fixture()
def sample_project_dir(tmp_path):
    proj = tmp_path / "sample_proj"
    (proj / "api" / "endpoints").mkdir(parents=True)
    (proj / "ui" / "pages").mkdir(parents=True)
    (proj / "tests").mkdir(parents=True)

    (proj / "api" / "endpoints" / "programs.py").write_text(_PROGRAMS_ENDPOINT, encoding="utf-8")
    (proj / "ui" / "pages" / "admin_programs.py").write_text(_ADMIN_PROGRAMS_PAGE, encoding="utf-8")
    (proj / "ui" / "pages" / "login.py").write_text(_LOGIN_PAGE, encoding="utf-8")
    (proj / "tests" / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (proj / "tests" / "test_api_graph.py").write_text(_TEST_API_GRAPH, encoding="utf-8")
    (proj / "tests" / "test_page_graph.py").write_text(_TEST_PAGE_GRAPH, encoding="utf-8")
    (proj / "tests" / "test_env_marker.py").write_text(_TEST_ENV_MARKER, encoding="utf-8")
    (proj / "tests" / "test_env_module_marker.py").write_text(_TEST_ENV_MODULE_MARKER, encoding="utf-8")
    return proj


# ------------------------------------------------------------------ discover_backend_routes

def test_discover_backend_routes_extracts_all_verbs(sample_project_dir):
    routes, known_classes = coverage.discover_backend_routes(str(sample_project_dir))
    assert known_classes == {"ProgramsEndpoint"}

    def as_pairs(key):
        return [(c.method, c.normalized) for c in routes[key]]

    assert as_pairs(("ProgramsEndpoint", "list_programs")) == [("GET", "/api/v1/programs")]
    assert as_pairs(("ProgramsEndpoint", "create")) == [("POST", "/api/v1/programs/{}")]
    assert as_pairs(("ProgramsEndpoint", "get")) == [("GET", "/api/v1/programs/{}")]
    assert as_pairs(("ProgramsEndpoint", "update")) == [("PUT", "/api/v1/programs/{}")]
    assert as_pairs(("ProgramsEndpoint", "patch_program")) == [("PATCH", "/api/v1/programs/{}")]
    assert as_pairs(("ProgramsEndpoint", "delete")) == [("DELETE", "/api/v1/programs/{}")]
    assert as_pairs(("ProgramsEndpoint", "raw_ping")) == [("GET", "/api/v1/ping")]

    call = routes[("ProgramsEndpoint", "list_programs")][0]
    assert call.file == "api/endpoints/programs.py"
    assert call.line > 0


def test_discover_backend_routes_missing_dir(tmp_path):
    routes, known_classes = coverage.discover_backend_routes(str(tmp_path))
    assert routes == {}
    assert known_classes == set()


# ------------------------------------------------------------------ discover_page_routes

def test_discover_page_routes_extracts_goto_and_self_open(sample_project_dir):
    routes, known_classes = coverage.discover_page_routes(str(sample_project_dir))
    assert known_classes == {"AdminProgramsPage", "LoginPage"}

    def as_pairs(key):
        return [(c.method, c.normalized) for c in routes[key]]

    assert as_pairs(("AdminProgramsPage", "open_list")) == [("GET", "/admin/programs")]
    assert as_pairs(("AdminProgramsPage", "open_program")) == [("GET", "/admin/programs/{}")]
    assert as_pairs(("LoginPage", "open_login")) == [("GET", "/login")]
    # self.page.goto(path) с переменной-параметром — не резолвится статически
    assert ("LoginPage", "open") not in routes


# ------------------------------------------------------------------ граф тест -> маршрут (API)

def _tests_by_name(tests):
    return {t.name: t for t in tests}


def test_analyze_project_api_graph_direct_fixture_and_transitive(sample_project_dir):
    tests = _tests_by_name(coverage.analyze_project(str(sample_project_dir)))

    def normalized_pairs(test_name):
        return [(c.method, c.normalized) for c in tests[test_name].api_routes]

    assert normalized_pairs("test_list_programs_direct") == [("GET", "/api/v1/programs")]
    assert normalized_pairs("test_get_program_direct") == [("GET", "/api/v1/programs/{}")]
    assert normalized_pairs("test_create_via_fixture") == [("POST", "/api/v1/programs/{}")]
    assert normalized_pairs("test_create_via_transitive_fixture") == [("POST", "/api/v1/programs/{}")]
    assert normalized_pairs("test_raw_client_direct") == [("GET", "/api/v1/programs")]


# ------------------------------------------------------------------ граф тест -> страница (UI)

def test_analyze_project_page_graph(sample_project_dir):
    tests = _tests_by_name(coverage.analyze_project(str(sample_project_dir)))

    def normalized_pairs(test_name):
        return [(c.method, c.normalized) for c in tests[test_name].page_routes]

    assert normalized_pairs("test_open_list_direct") == [("GET", "/admin/programs")]
    assert normalized_pairs("test_open_program_via_fixture") == [("GET", "/admin/programs/{}")]
    assert normalized_pairs("test_open_program_via_transitive_fixture") == [("GET", "/admin/programs/{}")]
    assert normalized_pairs("test_login_direct") == [("GET", "/login")]


# ------------------------------------------------------------------ маркер pytest.mark.env

def test_analyze_project_env_marker(sample_project_dir):
    tests = _tests_by_name(coverage.analyze_project(str(sample_project_dir)))

    assert tests["test_no_marker"].env is None
    assert tests["test_only_stage"].env == "stage"
    assert tests["test_class_no_marker"].env is None
    assert tests["test_class_no_marker"].cls == "TestGroupMarker"
    assert tests["test_in_marked_class"].env == "stage"
    assert tests["test_in_marked_class"].cls == "TestGroupStage"
    assert tests["test_module_level_stage"].env == "stage"
    assert tests["test_overrides_module_marker"].env == "develop"


# ------------------------------------------------------------------ сопоставление инвентаря с тестами

def test_match_route_tests_true_and_false_positives(sample_project_dir, routes_tsv_file):
    tsv_routes = coverage.parse_routes_tsv(routes_tsv_file)
    tests = coverage.analyze_project(str(sample_project_dir))
    matches = coverage._match_route_tests(tsv_routes, tests)

    by_name = {r.name: idx for idx, r in enumerate(tsv_routes)}

    def matched_names(route_name):
        return {t.name for t in matches[by_name[route_name]]}

    # {program} в инвентаре против {program_id}/f-строки в коде — должны найти пару
    assert matched_names("programs.index") == {"test_list_programs_direct", "test_raw_client_direct"}
    assert matched_names("programs.store") == {"test_create_via_fixture", "test_create_via_transitive_fixture"}
    assert matched_names("programs.show") == {"test_get_program_direct"}

    # заведомо разные пути (лишний сегмент /archive, /multi) — ложных срабатываний нет
    assert matched_names("programs.archive") == set()
    assert matched_names("programs.multi") == set()
    assert matched_names("programs.update") == set()
    assert matched_names("programs.destroy") == set()

    # посторонние префиксы инвентаря (l5-swagger/passport/sanctum) ни с чем не матчатся
    assert matched_names("l5-swagger.default.api") == set()
    assert matched_names("passport.token") == set()
    assert matched_names("sanctum.csrf-cookie") == set()


# ------------------------------------------------------------------ инвентарь UI-страниц

_FRONTEND_ROUTES_TSV = """\
programs.index\tGET\t/api/v1/programs
frontend.programs.list\tGET\t/admin/programs
frontend.programs.show\tGET\t/admin/programs/{id}
frontend.reports\tGET\t/admin/reports
"""


@pytest.fixture()
def frontend_routes_tsv_file(tmp_path):
    path = tmp_path / "routes_frontend.tsv"
    path.write_text(_FRONTEND_ROUTES_TSV, encoding="utf-8")
    return path


def test_frontend_routes_keeps_only_non_api_paths(frontend_routes_tsv_file):
    tsv_routes = coverage.parse_routes_tsv(frontend_routes_tsv_file)
    frontend = coverage._frontend_routes(tsv_routes)
    assert {r.name for r in frontend} == {"frontend.programs.list", "frontend.programs.show", "frontend.reports"}


def test_page_inventory_merges_discovered_and_tsv_pages_and_dedupes(sample_project_dir, frontend_routes_tsv_file):
    tests = coverage.analyze_project(str(sample_project_dir))
    tsv_routes = coverage.parse_routes_tsv(frontend_routes_tsv_file)
    frontend_routes = coverage._frontend_routes(tsv_routes)

    pages = coverage._page_inventory(tests, frontend_routes)
    normalized = {p.normalized for p in pages}

    # /admin/programs и /admin/programs/{} уже открываются тестами (sample_project_dir) —
    # tsv-запись не создаёт дубликат, просто совпадает по нормализованному пути
    assert "/admin/programs" in normalized
    assert "/admin/programs/{}" in normalized
    # страница, которую не открывает ни один тест, но есть в routes.tsv — тоже попадает
    # в инвентарь (просто окажется непокрытой)
    assert "/admin/reports" in normalized
    # login-страница открывается только тестом, в routes.tsv её нет — тоже должна попасть
    assert "/login" in normalized


def test_page_inventory_uncovered_tsv_only_page_has_no_tests(sample_project_dir, frontend_routes_tsv_file):
    tests = coverage.analyze_project(str(sample_project_dir))
    tsv_routes = coverage.parse_routes_tsv(frontend_routes_tsv_file)
    frontend_routes = coverage._frontend_routes(tsv_routes)

    pages = coverage._page_inventory(tests, frontend_routes)
    matches = coverage._match_page_tests(pages, tests)

    by_normalized = {p.normalized: idx for idx, p in enumerate(pages)}
    reports_idx = by_normalized["/admin/reports"]
    assert matches[reports_idx] == []

    login_idx = by_normalized["/login"]
    assert {t.name for t in matches[login_idx]} == {"test_login_direct"}


def test_test_status_counts_dedupes_by_nodeid_across_items():
    stands = ["develop"]
    items = [
        {"status": {"develop": {"tests": [{"nodeid": "t::a", "status": "passed"}, {"nodeid": "t::b", "status": "failed"}]}}},
        {"status": {"develop": {"tests": [{"nodeid": "t::a", "status": "passed"}, {"nodeid": "t::c", "status": "xfail"}]}}},
    ]
    counts = coverage._test_status_counts(items, stands)
    assert counts == {"develop": {"passed": 1, "failed": 1, "xfail": 1}}


# ------------------------------------------------------------------ nodeid_status_map (дерево проекта)

def _write_allure_result(results_dir, full_name, status, message=None):
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fullName": full_name, "status": status}
    if message:
        payload["statusDetails"] = {"message": message}
    (results_dir / f"{full_name.replace('#', '_')}-result.json").write_text(json.dumps(payload), encoding="utf-8")


def test_nodeid_status_map_matches_by_full_name_and_skips_other_stands(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES ('p', '/x', '.venv', '[]')"
        )
        conn.execute("INSERT INTO stands (project, name, url) VALUES ('p', 'develop', '')")
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, counts) VALUES ('p', 'develop', 'all', 'passed', '{}')"
        )
        run_id = cur.lastrowid
        conn.commit()

        results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
        _write_allure_result(results_dir, "tests.test_foo#test_passing", "passed")
        _write_allure_result(results_dir, "tests.test_foo.TestBar#test_broken", "failed")
        _write_allure_result(results_dir, "tests.test_foo#test_expected_fail", "skipped", message="xfail: reason")

        nodeids = [
            "tests/test_foo.py::test_passing",
            "tests/test_foo.py::TestBar::test_broken",
            "tests/test_foo.py::test_expected_fail",
            "tests/test_foo.py::test_never_run",
        ]
        found_run_id, statuses = coverage.nodeid_status_map(conn, "p", "develop", nodeids)
        assert found_run_id == run_id
        assert statuses == {
            "tests/test_foo.py::test_passing": "passed",
            "tests/test_foo.py::TestBar::test_broken": "failed",
            "tests/test_foo.py::test_expected_fail": "xfail",
        }

        # незавершённых прогонов на другом стенде нет -> run_id None, статусов нет
        no_run_id, no_statuses = coverage.nodeid_status_map(conn, "p", "stage", nodeids)
        assert no_run_id is None
        assert no_statuses == {}
    finally:
        conn.close()
