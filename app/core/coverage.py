"""Статический анализ покрытия API-маршрутов и UI-страниц тестами проекта.

Ничего не исполняет — весь граф "маршрут инвентаря routes.tsv -> тест -> (опционально)
фикстуры, транзитивно" строится через ast.parse тестового проекта (api/endpoints/*.py,
ui/pages/*.py, tests/**/test_*.py и все conftest.py). Единственное, что реально
исполняется — чтение уже готовых allure-results прошлых прогонов (через
app.core.allure_report) для определения статуса последнего прогона на каждом стенде.

Рассчитан в первую очередь на auto_tests_vshgu_cloude (см. workspace/coverage/
auto_tests_vshgu_cloude/routes.tsv), но не завязан на конкретный проект: recalc()
берёт path/venv/стенды зарегистрированного проекта из app.db, а вся AST-эвристика
работает с произвольным project_path, у которого есть api/endpoints, ui/pages и tests
в том же виде, что и у auto_tests_vshgu_cloude.
"""
from __future__ import annotations

import ast
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import allure_report

COVERAGE_DIR = settings.WORKSPACE_DIR / "coverage"

HTTP_VERBS = {"get", "post", "put", "patch", "delete"}
# Имена параметров/переменных, через которые тесты и фикстуры дёргают API напрямую,
# без промежуточного объекта *Endpoint (см. api_client/api_client_global/... в
# corretest.py auto_tests_vshgu_cloude).
RAW_CLIENT_NAMES = {"api_client", "api_client_global", "stage_api_client", "external_system_client"}

_PARAM_RE = re.compile(r"\{[^{}]*\}")
_STATUS_PRIORITY = {"failed": 5, "broken": 4, "skipped": 3, "xfail": 2, "passed": 1, "unknown": 0}


# ------------------------------------------------------------------ routes.tsv

@dataclass(frozen=True)
class TsvRoute:
    name: str
    methods: tuple[str, ...]
    path: str
    normalized: str


def routes_tsv_path(project_name: str) -> Path:
    return COVERAGE_DIR / project_name / "routes.tsv"


def cache_path(project_name: str) -> Path:
    return COVERAGE_DIR / project_name / "coverage.json"


def _normalize_path(path: str) -> str:
    """Отбрасывает query-строку и схлопывает любые {var} в единый плейсхолдер "{}",
    чтобы /programs/{program} (routes.tsv) и /programs/{program_id} (код) сравнивались
    позиционно, а не по имени переменной."""
    return _PARAM_RE.sub("{}", path.split("?", 1)[0].strip())


def parse_routes_tsv(path: Path) -> list[TsvRoute]:
    """Разбор name<TAB>METHOD[,METHOD...]<TAB>path. Строки не из 3 полей — как и
    служебные маршруты вне /api/v1 (l5-swagger, passport, sanctum, /auth/...) —
    парсятся точно так же и просто не найдут пары среди вызовов self.client.*."""
    if not path.is_file():
        return []
    routes: list[TsvRoute] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        if len(parts) != 3:
            continue
        name, methods_raw, route_path = parts
        methods = tuple(m.strip().upper() for m in methods_raw.split(",") if m.strip())
        route_path = route_path.strip()
        if not methods or not route_path:
            continue
        routes.append(TsvRoute(name.strip(), methods, route_path, _normalize_path(route_path)))
    return routes


def load_routes(project_name: str) -> list[TsvRoute]:
    return parse_routes_tsv(routes_tsv_path(project_name))


def _is_api_path(path: str) -> bool:
    return path.startswith("/api/")


def _frontend_routes(tsv_routes: list[TsvRoute]) -> list[TsvRoute]:
    """Маршруты routes.tsv без /api/ префикса — это страницы фронтенда, а не API-эндпоинты;
    они идут в инвентарь страниц (см. _page_inventory), а не в инвентарь API-маршрутов."""
    return [r for r in tsv_routes if not _is_api_path(r.path)]


# ------------------------------------------------------------------ общие AST-хелперы

def _parse_module(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _fstring_template(node: ast.AST, class_constants: dict[str, str]) -> str | None:
    """Строковый литерал или f-строка -> шаблон, где каждая {переменная} заменена на
    "{}" — кроме self.<CONST>, если CONST — известная строковая константа класса
    (например self.PATH), её значение подставляется буквально."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                inner = value.value
                if (
                    isinstance(inner, ast.Attribute)
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == "self"
                    and inner.attr in class_constants
                ):
                    parts.append(class_constants[inner.attr])
                else:
                    parts.append("{}")
            else:
                return None
        return "".join(parts)
    return None


def _resolve_path_arg(arg: ast.AST, class_constants: dict[str, str]) -> str | None:
    template = _fstring_template(arg, class_constants)
    if template is not None:
        return template
    if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "self":
        return class_constants.get(arg.attr)
    return None


def _class_string_constants(class_node: ast.ClassDef) -> dict[str, str]:
    constants: dict[str, str] = {}
    for stmt in class_node.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            constants[stmt.targets[0].id] = stmt.value.value
    return constants


@dataclass(frozen=True)
class RouteCall:
    method: str
    path: str        # с базовым префиксом (/api/v1/... для backend), без схлопывания {}
    normalized: str  # то же, но с {} вместо любых {var} — используется для сопоставления
    file: str
    line: int


def _with_base_prefix(path: str, prefix: str = "/api/v1") -> str:
    """Базовый префикс добавляется только к относительным путям без своего префикса —
    self.client.*/api_client.* в auto_tests_vshgu_cloude всегда шлют запрос через
    base_url, который уже заканчивается на /api/v1 (см. config/environments.py), но
    если путь уже начинается с /api/ (другой префикс, например /api/v1-public),
    менять его не нужно."""
    if not path.startswith("/") or path.startswith("/api/"):
        return path
    return prefix + path


# ------------------------------------------------------------------ backend: api/endpoints/*.py

def discover_backend_routes(project_path: str) -> tuple[dict[tuple[str, str], list[RouteCall]], set[str]]:
    """(класс, метод) -> вызовы self.client.<verb>("путь") внутри тела метода, плюс
    множество всех имён классов, найденных в api/endpoints/*.py (для распознавания
    ручного инстанцирования вроде ExternalCasEndpoint(client) в conftest.py)."""
    root = Path(project_path) / "api" / "endpoints"
    index: dict[tuple[str, str], list[RouteCall]] = {}
    known_classes: set[str] = set()
    if not root.is_dir():
        return index, known_classes

    for file_path in sorted(root.glob("*.py")):
        tree = _parse_module(file_path)
        if tree is None:
            continue
        rel = file_path.relative_to(project_path).as_posix()
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            known_classes.add(class_node.name)
            constants = _class_string_constants(class_node)
            for func_node in class_node.body:
                if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls: list[RouteCall] = []
                for call in ast.walk(func_node):
                    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                        continue
                    attr = call.func
                    if attr.attr not in HTTP_VERBS:
                        continue
                    owner = attr.value
                    if not (
                        isinstance(owner, ast.Attribute)
                        and isinstance(owner.value, ast.Name)
                        and owner.value.id == "self"
                        and owner.attr == "client"
                    ):
                        continue
                    if not call.args:
                        continue
                    raw = _resolve_path_arg(call.args[0], constants)
                    if raw is None:
                        continue
                    full = _with_base_prefix(raw)
                    calls.append(RouteCall(attr.attr.upper(), full, _normalize_path(full), rel, call.lineno))
                if calls:
                    index.setdefault((class_node.name, func_node.name), []).extend(calls)
    return index, known_classes


# ------------------------------------------------------------------ UI: ui/pages/*.py

def discover_page_routes(project_path: str) -> tuple[dict[tuple[str, str], list[RouteCall]], set[str]]:
    """(класс, метод) -> вызовы self.page.goto("путь")/self.open("путь") — отдельный
    граф от API-маршрутов, ни с чем не сопоставляется, только тест -> страница."""
    root = Path(project_path) / "ui" / "pages"
    index: dict[tuple[str, str], list[RouteCall]] = {}
    known_classes: set[str] = set()
    if not root.is_dir():
        return index, known_classes

    for file_path in sorted(root.glob("*.py")):
        tree = _parse_module(file_path)
        if tree is None:
            continue
        rel = file_path.relative_to(project_path).as_posix()
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            known_classes.add(class_node.name)
            constants = _class_string_constants(class_node)
            for func_node in class_node.body:
                if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls: list[RouteCall] = []
                for call in ast.walk(func_node):
                    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                        continue
                    attr = call.func
                    owner = attr.value
                    is_page_goto = (
                        attr.attr == "goto"
                        and isinstance(owner, ast.Attribute)
                        and isinstance(owner.value, ast.Name)
                        and owner.value.id == "self"
                        and owner.attr == "page"
                    )
                    is_self_open = (
                        attr.attr == "open" and isinstance(owner, ast.Name) and owner.id == "self"
                    )
                    if not (is_page_goto or is_self_open) or not call.args:
                        continue
                    raw = _resolve_path_arg(call.args[0], constants)
                    if raw is None:
                        continue
                    calls.append(RouteCall("GET", raw, _normalize_path(raw), rel, call.lineno))
                if calls:
                    index.setdefault((class_node.name, func_node.name), []).extend(calls)
    return index, known_classes


# ------------------------------------------------------------------ conftest.py / фикстуры

@dataclass(frozen=True)
class FixtureDef:
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    dir: Path


def _is_fixture_decorator(dec: ast.AST) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Attribute):
        return target.attr == "fixture"
    if isinstance(target, ast.Name):
        return target.id == "fixture"
    return False


def _collect_fixtures(project_path: str) -> dict[str, list[FixtureDef]]:
    registry: dict[str, list[FixtureDef]] = {}
    for conftest in sorted(Path(project_path).glob("**/conftest.py")):
        tree = _parse_module(conftest)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(_is_fixture_decorator(d) for d in node.decorator_list):
                continue
            registry.setdefault(node.name, []).append(FixtureDef(node.name, node, conftest.parent))
    return registry


def _select_fixture(registry: dict[str, list[FixtureDef]], name: str, test_dir: Path) -> FixtureDef | None:
    """Ближайший (по каталогу) conftest.py, как при разрешении фикстур в pytest:
    среди файлов, чей каталог — предок test_dir, берём самый глубокий; если такого
    нет (не должно случаться при обычной раскладке conftest.py), берём любой."""
    candidates = registry.get(name)
    if not candidates:
        return None

    def _is_ancestor(directory: Path) -> bool:
        try:
            test_dir.relative_to(directory)
            return True
        except ValueError:
            return False

    applicable = [c for c in candidates if _is_ancestor(c.dir)]
    pool = applicable or candidates
    return max(pool, key=lambda c: len(c.dir.parts))


def _fixture_return_class(func_node: ast.AST, known_classes: set[str]) -> str | None:
    """Класс, который фикстура в итоге return/yield-ит: либо напрямую
    `return XxxEndpoint(...)`, либо через локальную переменную
    (`endpoint = XxxEndpoint(...); ...; yield endpoint`)."""
    local_vars: dict[str, str] = {}
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in known_classes
        ):
            local_vars[node.targets[0].id] = node.value.func.id

    result: str | None = None
    for node in ast.walk(func_node):
        if not isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in known_classes:
            result = value.func.id
        elif isinstance(value, ast.Name) and value.id in local_vars:
            result = local_vars[value.id]
    return result


def _endpoint_fixture_classes(registry: dict[str, list[FixtureDef]], endpoint_classes: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, defs in registry.items():
        for fd in defs:
            cls = _fixture_return_class(fd.node, endpoint_classes)
            if cls:
                result[name] = cls
                break
    return result


# ------------------------------------------------------------------ разбор тел тестов/фикстур

@dataclass(frozen=True)
class CallContext:
    backend_routes: dict[tuple[str, str], list[RouteCall]]
    endpoint_classes: set[str]
    page_routes: dict[tuple[str, str], list[RouteCall]]
    page_classes: set[str]
    fixture_registry: dict[str, list[FixtureDef]]
    endpoint_fixture_classes: dict[str, str]


def _local_class_vars(func_node: ast.AST, ctx: CallContext) -> dict[str, str]:
    """var -> класс для `var = ProgramsEndpoint(...)` / `page_obj = AdminProgramsPage(page)`,
    встреченных где угодно в теле функции (в т.ч. во вложенных with/try)."""
    result: dict[str, str] = {}
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            cls = node.value.func.id
            if cls in ctx.endpoint_classes or cls in ctx.page_classes:
                result[node.targets[0].id] = cls
    return result


def _extract_direct_calls(func_node: ast.AST, ctx: CallContext) -> tuple[list[RouteCall], list[RouteCall]]:
    """Маршруты/страницы, до которых можно дотянуться прямо из тела этой функции (без
    учёта параметров-фикстур — см. _resolve_calls)."""
    local_vars = _local_class_vars(func_node, ctx)
    api_calls: list[RouteCall] = []
    page_calls: list[RouteCall] = []

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func
        method_name = attr.attr
        target = attr.value

        if isinstance(target, ast.Name) and method_name in HTTP_VERBS and target.id in RAW_CLIENT_NAMES:
            if node.args:
                raw = _resolve_path_arg(node.args[0], {})
                if raw is not None:
                    full = _with_base_prefix(raw)
                    api_calls.append(RouteCall(method_name.upper(), full, _normalize_path(full), "", node.lineno))
            continue

        cls_name: str | None = None
        if isinstance(target, ast.Name):
            cls_name = local_vars.get(target.id) or ctx.endpoint_fixture_classes.get(target.id)
        elif isinstance(target, ast.Call) and isinstance(target.func, ast.Name):
            # ClassName(page_arg).method(...) одной цепочкой, без промежуточной переменной
            candidate = target.func.id
            if candidate in ctx.endpoint_classes or candidate in ctx.page_classes:
                cls_name = candidate

        if cls_name in ctx.endpoint_classes:
            api_calls.extend(ctx.backend_routes.get((cls_name, method_name), []))
        elif cls_name in ctx.page_classes:
            page_calls.extend(ctx.page_routes.get((cls_name, method_name), []))

    return api_calls, page_calls


def _resolve_calls(
    func_node: ast.AST,
    test_dir: Path,
    ctx: CallContext,
    memo: dict[int, tuple[list[RouteCall], list[RouteCall]]],
    visiting: set[int],
) -> tuple[list[RouteCall], list[RouteCall]]:
    """Маршруты/страницы функции (теста или фикстуры) + транзитивно через параметры,
    которые сами являются фикстурами (created_stream -> created_program -> ...)."""
    key = id(func_node)
    if key in memo:
        return memo[key]
    if key in visiting:
        return [], []  # цикл фикстур — защита, в нормальном коде не встречается

    visiting.add(key)
    api_calls, page_calls = _extract_direct_calls(func_node, ctx)

    args = func_node.args
    params = [a.arg for a in args.args + args.kwonlyargs if a.arg not in ("self", "cls")]
    for param in params:
        fixture = _select_fixture(ctx.fixture_registry, param, test_dir)
        if fixture is None:
            continue
        sub_api, sub_page = _resolve_calls(fixture.node, test_dir, ctx, memo, visiting)
        api_calls = api_calls + sub_api
        page_calls = page_calls + sub_page

    visiting.discard(key)
    memo[key] = (api_calls, page_calls)
    return api_calls, page_calls


# ------------------------------------------------------------------ tests/**/test_*.py

@dataclass(frozen=True)
class TestInfo:
    nodeid: str
    file: str
    cls: str | None
    name: str
    env: str | None  # None значит "оба стенда" (маркер pytest.mark.env отсутствует)
    api_routes: list[RouteCall]
    page_routes: list[RouteCall]


def _env_arg(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _marker_env_from_decorators(decorators: list[ast.expr]) -> str | None:
    for dec in decorators:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "env":
            env = _env_arg(dec)
            if env is not None:
                return env
    return None


def _marker_env_from_pytestmark(body: list[ast.stmt]) -> str | None:
    for stmt in body:
        if not (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "pytestmark"
        ):
            continue
        values = stmt.value.elts if isinstance(stmt.value, (ast.List, ast.Tuple)) else [stmt.value]
        for value in values:
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "env":
                env = _env_arg(value)
                if env is not None:
                    return env
    return None


def discover_tests(project_path: str, ctx: CallContext) -> list[TestInfo]:
    root = Path(project_path) / "tests"
    tests: list[TestInfo] = []
    if not root.is_dir():
        return tests

    memo: dict[int, tuple[list[RouteCall], list[RouteCall]]] = {}
    project = Path(project_path)
    # id(func_node) как ключ memo валиден только пока сам func_node жив — иначе Python
    # может переиспользовать тот же id() для другой функции из следующего файла и
    # memo вернёт результат для чужого узла. keep_alive держит все разобранные деревья
    # до конца discover_tests(), гарантируя уникальность id() на всё время анализа.
    keep_alive: list[ast.Module] = []

    for file_path in sorted(root.glob("**/test_*.py")):
        tree = _parse_module(file_path)
        if tree is None:
            continue
        keep_alive.append(tree)
        module_env = _marker_env_from_pytestmark(tree.body)
        rel = file_path.relative_to(project).as_posix()
        test_dir = file_path.parent

        def _handle(func_node: ast.FunctionDef | ast.AsyncFunctionDef, cls_name: str | None, class_env: str | None) -> None:
            if not func_node.name.startswith("test_"):
                return
            env = _marker_env_from_decorators(func_node.decorator_list) or class_env or module_env
            api_calls, page_calls = _resolve_calls(func_node, test_dir, ctx, memo, set())
            nodeid = f"{rel}::" + (f"{cls_name}::" if cls_name else "") + func_node.name
            tests.append(TestInfo(nodeid, rel, cls_name, func_node.name, env, api_calls, page_calls))

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _handle(node, None, None)
            elif isinstance(node, ast.ClassDef):
                class_env = _marker_env_from_decorators(node.decorator_list) or _marker_env_from_pytestmark(node.body)
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _handle(sub, node.name, class_env)

    return tests


# ------------------------------------------------------------------ сборка графа проекта

def build_call_context(project_path: str) -> CallContext:
    backend_routes, endpoint_classes = discover_backend_routes(project_path)
    page_routes, page_classes = discover_page_routes(project_path)
    fixture_registry = _collect_fixtures(project_path)
    endpoint_fixture_classes = _endpoint_fixture_classes(fixture_registry, endpoint_classes)
    return CallContext(
        backend_routes=backend_routes,
        endpoint_classes=endpoint_classes,
        page_routes=page_routes,
        page_classes=page_classes,
        fixture_registry=fixture_registry,
        endpoint_fixture_classes=endpoint_fixture_classes,
    )


def analyze_project(project_path: str) -> list[TestInfo]:
    """Чистый статический анализ (без БД/allure) — по пути проекта отдаёт список тестов
    с их API- и UI-маршрутами. Основа для recalc(), но полезна и сама по себе."""
    ctx = build_call_context(project_path)
    return discover_tests(project_path, ctx)


def _match_route_tests(tsv_routes: list[TsvRoute], tests: list[TestInfo]) -> dict[int, list[TestInfo]]:
    by_key: dict[tuple[str, str], list[int]] = {}
    for idx, route in enumerate(tsv_routes):
        for method in route.methods:
            by_key.setdefault((method, route.normalized), []).append(idx)

    result: dict[int, list[TestInfo]] = {idx: [] for idx in range(len(tsv_routes))}
    for test in tests:
        matched_idx: set[int] = set()
        for call in test.api_routes:
            matched_idx.update(by_key.get((call.method, call.normalized), []))
        for idx in matched_idx:
            result[idx].append(test)
    return result


# ------------------------------------------------------------------ статус последнего прогона

def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid (tests/foo/test_bar.py::TestClass::test_x) -> allure fullName
    ({dotted.module.path}{.Class}?#{test}, см. allure_pytest.utils.allure_full_name) —
    так статически найденный тест сопоставляется с записью в allure-results."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def _classify_allure_status(entry: dict) -> str:
    if entry["status"] == "skipped" and entry.get("message") and "xfail" in entry["message"].lower():
        return "xfail"
    return entry["status"]


def _latest_finished_run(conn: sqlite3.Connection, project: str, stand: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM runs WHERE project = ? AND stand = ? AND status IN ('passed', 'failed', 'cancelled') "
        "ORDER BY id DESC LIMIT 1",
        (project, stand),
    ).fetchone()


def _stand_results(conn: sqlite3.Connection, project: str, stand: str) -> tuple[sqlite3.Row | None, dict[str, str]]:
    run = _latest_finished_run(conn, project, stand)
    if run is None:
        return None, {}
    entries = allure_report.parse_results(_allure_dir(run["id"]))
    return run, {entry["name"]: _classify_allure_status(entry) for entry in entries}


def _coverage_stand_status(
    item_tests: list[TestInfo], stand: str, run: sqlite3.Row | None, by_full_name: dict[str, str]
) -> dict:
    """Статус покрытия одного элемента инвентаря (маршрута или страницы) на одном
    стенде — общая логика, используется и для routes_out, и для pages_out."""
    if not item_tests:
        return {"state": "not_covered", "run_id": None, "tests": []}

    applicable = [t for t in item_tests if t.env is None or t.env == stand]
    if not applicable:
        return {"state": "no_tests_for_stand", "run_id": run["id"] if run else None, "tests": []}
    if run is None:
        return {"state": "no_run", "run_id": None, "tests": []}

    matched = [
        (t.nodeid, by_full_name[full_name])
        for t in applicable
        for full_name in [_nodeid_to_full_name(t.nodeid)]
        if full_name in by_full_name
    ]
    if not matched:
        return {"state": "not_executed", "run_id": run["id"], "tests": []}

    worst_status = max(matched, key=lambda pair: _STATUS_PRIORITY.get(pair[1], 0))[1]
    return {
        "state": worst_status,
        "run_id": run["id"],
        "tests": [{"nodeid": nodeid, "status": status} for nodeid, status in matched],
    }


@dataclass(frozen=True)
class PageEntry:
    path: str
    normalized: str


def _page_inventory(tests: list[TestInfo], frontend_routes: list[TsvRoute]) -> list[PageEntry]:
    """Инвентарь UI-страниц: то, что реально открывают UI-тесты (page.goto/self.open),
    плюс маршруты фронтенда из routes.tsv без /api/ префикса, даже если их пока не
    открывает ни один тест (тогда страница просто окажется непокрытой)."""
    by_normalized: dict[str, str] = {}
    for test in tests:
        for call in test.page_routes:
            by_normalized.setdefault(call.normalized, call.path)
    for route in frontend_routes:
        by_normalized.setdefault(route.normalized, route.path)
    return [PageEntry(path=path, normalized=normalized) for normalized, path in sorted(by_normalized.items())]


def _match_page_tests(pages: list[PageEntry], tests: list[TestInfo]) -> dict[int, list[TestInfo]]:
    by_normalized = {page.normalized: idx for idx, page in enumerate(pages)}
    result: dict[int, list[TestInfo]] = {idx: [] for idx in range(len(pages))}
    for test in tests:
        matched_idx = {by_normalized[call.normalized] for call in test.page_routes if call.normalized in by_normalized}
        for idx in matched_idx:
            result[idx].append(test)
    return result


def _test_status_counts(items: list[dict], stands: list[str]) -> dict[str, dict[str, int]]:
    """Число покрывающих тестов по статусу на каждом стенде (для диаграммы статусов),
    дедуплицированное по nodeid — один и тот же тест может покрывать несколько
    маршрутов/страниц, но должен считаться в диаграмме один раз."""
    result: dict[str, dict[str, int]] = {}
    for stand in stands:
        by_nodeid: dict[str, str] = {}
        for item in items:
            for t in item["status"][stand]["tests"]:
                by_nodeid[t["nodeid"]] = t["status"]
        counts: dict[str, int] = {}
        for status_value in by_nodeid.values():
            counts[status_value] = counts.get(status_value, 0) + 1
        result[stand] = counts
    return result


# ------------------------------------------------------------------ публичный API: recalc/load_cached

def recalc(project_name: str) -> dict:
    """Пересчитывает покрытие для зарегистрированного проекта (путь/стенды берутся из
    app.db) и кладёт результат в workspace/coverage/<project>/coverage.json."""
    conn = get_connection()
    try:
        project = conn.execute("SELECT * FROM projects WHERE name = ?", (project_name,)).fetchone()
        if project is None:
            raise ValueError(f"проект {project_name} не найден")
        stands = [
            row["name"]
            for row in conn.execute("SELECT name FROM stands WHERE project = ? ORDER BY name", (project_name,)).fetchall()
        ]

        tsv_routes = load_routes(project_name)
        api_tsv_routes = [r for r in tsv_routes if _is_api_path(r.path)]
        frontend_tsv_routes = _frontend_routes(tsv_routes)

        tests = analyze_project(project["path"])
        route_tests_by_idx = _match_route_tests(api_tsv_routes, tests)
        stand_data = {stand: _stand_results(conn, project_name, stand) for stand in stands}

        routes_out = []
        for idx, route in enumerate(api_tsv_routes):
            route_tests = route_tests_by_idx.get(idx, [])
            routes_out.append({
                "name": route.name,
                "methods": list(route.methods),
                "path": route.path,
                "normalized": route.normalized,
                "covered": bool(route_tests),
                "tests": [{"nodeid": t.nodeid, "env": t.env} for t in route_tests],
                "status": {
                    stand: _coverage_stand_status(route_tests, stand, *stand_data[stand])
                    for stand in stands
                },
            })

        pages_inventory = _page_inventory(tests, frontend_tsv_routes)
        page_tests_by_idx = _match_page_tests(pages_inventory, tests)
        pages_out = []
        for idx, page in enumerate(pages_inventory):
            page_tests = page_tests_by_idx.get(idx, [])
            pages_out.append({
                "path": page.path,
                "normalized": page.normalized,
                "covered": bool(page_tests),
                "tests": [{"nodeid": t.nodeid, "env": t.env} for t in page_tests],
                "status": {
                    stand: _coverage_stand_status(page_tests, stand, *stand_data[stand])
                    for stand in stands
                },
            })

        result = {
            "project": project_name,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "stands": stands,
            "routes_total": len(routes_out),
            "routes_covered": sum(1 for r in routes_out if r["covered"]),
            "routes": routes_out,
            "pages_total": len(pages_out),
            "pages_covered": sum(1 for p in pages_out if p["covered"]),
            "pages": pages_out,
            "test_status": _test_status_counts([*routes_out, *pages_out], stands),
        }
    finally:
        conn.close()

    out_path = cache_path(project_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_cached(project_name: str) -> dict | None:
    """Читает workspace/coverage/<project>/coverage.json без пересчёта; None, если
    recalc() для этого проекта ещё не запускался."""
    path = cache_path(project_name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
