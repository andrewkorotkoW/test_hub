"""REST API поверх app/core/coverage.py для страницы «Покрытие».

Область (area) маршрута — первый сегмент его dotted-имени из routes.tsv
(например "knowledge_base" для "knowledge_base.home.bundles.index"): в
auto_tests_vshgu_cloude (Laravel-именование роутов) это естественная и уже
готовая группировка, без необходимости парсить path.
"""
import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from ..core import coverage, runner
from ..deps import get_db, require_roles
from ..schemas import (
    CoverageGraph,
    CoverageGraphEdge,
    CoverageGraphNode,
    CoverageMapArea,
    CoverageMapRoute,
    CoveragePageDetail,
    CoverageRouteDetail,
    CoverageRouteStandStatus,
    CoverageRoutesUploadResult,
    CoverageRouteTestStatus,
    CoverageStandSummary,
    CoverageSummary,
    CoverageTestDetail,
    CoverageTestPage,
    CoverageTestRoute,
    CoverageTree,
)

router = APIRouter(prefix="/api/projects", tags=["coverage"])

_VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
PAGES_AREA_NAME = "UI: страницы"
MAX_GRAPH_NODES = 150


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _ensure_cached(project_name: str) -> dict:
    """load_cached, либо ленивый пересчёт — рядовому пользователю (manager/customer),
    зашедшему на страницу «Покрытие» первым, не нужно знать про существование
    отдельной ручки /recalc."""
    cached = coverage.load_cached(project_name)
    if cached is None or not _cache_is_current(cached):
        cached = coverage.recalc(project_name)
    return cached


def _cache_is_current(cached: dict) -> bool:
    """coverage.json старого формата (до слоя страниц/статусов) — пересчитать, а не падать с KeyError."""
    if "pages" not in cached or "routes" not in cached:
        return False
    items = list(cached.get("pages") or []) + list(cached.get("routes") or [])
    return all(isinstance(i, dict) and "status" in i and "tests" in i for i in items)


def _area_of(route_name: str) -> str:
    return route_name.split(".", 1)[0] if route_name else "other"


def _build_summary(cached: dict) -> CoverageSummary:
    stands = cached["stands"]
    routes = cached["routes"]

    stand_summaries = []
    for stand in stands:
        total = len(routes)
        covered = sum(
            1 for r in routes if r["status"][stand]["state"] not in ("not_covered", "no_tests_for_stand")
        )
        percent = round(covered / total * 100, 1) if total else 0.0
        stand_summaries.append(
            CoverageStandSummary(stand=stand, routes_total=total, routes_covered=covered, percent=percent)
        )

    areas: dict[str, list[CoverageMapRoute]] = {}
    area_has_covered: dict[str, bool] = {}
    for route in routes:
        area = _area_of(route["name"])
        areas.setdefault(area, []).append(
            CoverageMapRoute(
                name=route["name"],
                methods=route["methods"],
                path=route["path"],
                area=area,
                tests_count=len(route["tests"]),
                shared=len(route["tests"]) > 1,
                status={
                    stand: CoverageRouteStandStatus(
                        state=route["status"][stand]["state"], run_id=route["status"][stand]["run_id"]
                    )
                    for stand in stands
                },
            )
        )
        area_has_covered[area] = area_has_covered.get(area, False) or route["covered"]

    pages = cached["pages"]
    if pages:
        page_cells = [
            CoverageMapRoute(
                name=page["path"],
                methods=["PAGE"],
                path=page["path"],
                area=PAGES_AREA_NAME,
                tests_count=len(page["tests"]),
                shared=len(page["tests"]) > 1,
                kind="page",
                status={
                    stand: CoverageRouteStandStatus(
                        state=page["status"][stand]["state"], run_id=page["status"][stand]["run_id"]
                    )
                    for stand in stands
                },
            )
            for page in pages
        ]
        areas[PAGES_AREA_NAME] = sorted(page_cells, key=lambda r: r.path)
        area_has_covered[PAGES_AREA_NAME] = any(page["covered"] for page in pages)

    map_areas = [
        CoverageMapArea(area=area, routes=area_routes if area == PAGES_AREA_NAME else sorted(area_routes, key=lambda r: r.path))
        for area, area_routes in sorted(areas.items(), key=lambda kv: (kv[0] == PAGES_AREA_NAME, kv[0]))
    ]
    zero_coverage_areas = sorted(area for area, has_covered in area_has_covered.items() if not has_covered)

    return CoverageSummary(
        project=cached["project"],
        generated_at=cached["generated_at"],
        stands=stand_summaries,
        routes_total=cached["routes_total"],
        routes_covered=cached["routes_covered"],
        pages_total=cached["pages_total"],
        pages_covered=cached["pages_covered"],
        zero_coverage_areas=zero_coverage_areas,
        map=map_areas,
        test_status=cached["test_status"],
    )


def _validate_routes_tsv(text: str) -> None:
    """Строже, чем coverage.parse_routes_tsv (который молча пропускает
    неподходящие строки) — здесь любая проблемная строка в загружаемом файле
    возвращает 422 с номером строки, чтобы её было легко найти и исправить."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="routes.tsv пуст")
    for i, line in enumerate(lines, start=1):
        parts = line.split("\t")
        if len(parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"строка {i}: ожидается 3 поля name<TAB>METHOD[,METHOD...]<TAB>path, получено {len(parts)}",
            )
        _, methods_raw, route_path = parts
        methods = [m.strip().upper() for m in methods_raw.split(",") if m.strip()]
        if not methods or any(m not in _VALID_METHODS for m in methods):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"строка {i}: некорректный список HTTP-методов {methods_raw!r}",
            )
        if not route_path.strip().startswith("/"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"строка {i}: путь должен начинаться с / ({route_path!r})",
            )


@router.get("/{name}/coverage")
def get_coverage(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> CoverageSummary:
    _get_project_or_404(conn, name)
    return _build_summary(_ensure_cached(name))


@router.get("/{name}/coverage/tree")
async def get_coverage_tree(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> CoverageTree:
    """Дерево тестов проекта (файл -> класс -> [тест], `runner.discover`, то же, что
    видит `project.html`) вместе со статусом каждого теста на каждом стенде из
    последнего завершённого прогона — источник дерева-диаграммы на странице «Покрытие»."""
    project = _get_project_or_404(conn, name)
    discovered = await runner.discover(project["path"], project["venv"])
    tree: dict[str, dict[str, list[str]]] = discovered.get("tree", {})
    nodeids = [
        f"{file}::{cls}::{test}" if cls else f"{file}::{test}"
        for file, classes in tree.items()
        for cls, tests in classes.items()
        for test in tests
    ]
    stands = [
        row["name"] for row in conn.execute("SELECT name FROM stands WHERE project = ? ORDER BY name", (name,))
    ]
    run_ids: dict[str, int | None] = {}
    statuses: dict[str, dict[str, str]] = {}
    for stand in stands:
        run_id, status_map = coverage.nodeid_status_map(conn, name, stand, nodeids)
        run_ids[stand] = run_id
        statuses[stand] = status_map
    return CoverageTree(tree=tree, error=discovered.get("error"), stands=stands, run_ids=run_ids, statuses=statuses)


@router.post("/{name}/coverage/recalc")
def recalc_coverage(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> CoverageSummary:
    _get_project_or_404(conn, name)
    try:
        cached = coverage.recalc(name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _build_summary(cached)


@router.post("/{name}/coverage/routes")
async def upload_routes(
    name: str,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> CoverageRoutesUploadResult:
    _get_project_or_404(conn, name)
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="routes.tsv должен быть в кодировке UTF-8"
        ) from exc

    _validate_routes_tsv(text)

    path = coverage.routes_tsv_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

    routes_parsed = len(coverage.load_routes(name))
    cached = coverage.recalc(name)
    return CoverageRoutesUploadResult(routes_parsed=routes_parsed, coverage=_build_summary(cached))


def _tests_with_stand_status(item: dict, stands: list[str]) -> list[CoverageRouteTestStatus]:
    status_by_stand = {
        stand: {t["nodeid"]: t["status"] for t in item["status"][stand]["tests"]} for stand in stands
    }
    return [
        CoverageRouteTestStatus(
            nodeid=t["nodeid"],
            env=t["env"],
            status={stand: status_by_stand[stand].get(t["nodeid"]) for stand in stands},
        )
        for t in item["tests"]
    ]


@router.get("/{name}/coverage/route")
def get_route_coverage(
    name: str,
    method: str,
    path: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> CoverageRouteDetail:
    _get_project_or_404(conn, name)
    cached = _ensure_cached(name)

    method_upper = method.strip().upper()
    normalized = coverage._normalize_path(path)
    route = next(
        (r for r in cached["routes"] if method_upper in r["methods"] and r["normalized"] == normalized),
        None,
    )
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

    tests = _tests_with_stand_status(route, cached["stands"])
    return CoverageRouteDetail(name=route["name"], methods=route["methods"], path=route["path"], tests=tests)


@router.get("/{name}/coverage/page")
def get_page_coverage(
    name: str,
    path: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> CoveragePageDetail:
    _get_project_or_404(conn, name)
    cached = _ensure_cached(name)

    normalized = coverage._normalize_path(path)
    page = next((p for p in cached["pages"] if p["normalized"] == normalized), None)
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    tests = _tests_with_stand_status(page, cached["stands"])
    return CoveragePageDetail(path=page["path"], tests=tests)


@router.get("/{name}/coverage/test")
def get_test_coverage(
    name: str,
    id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> CoverageTestDetail:
    _get_project_or_404(conn, name)
    cached = _ensure_cached(name)

    routes = [
        CoverageTestRoute(name=r["name"], methods=r["methods"], path=r["path"])
        for r in cached["routes"]
        if any(t["nodeid"] == id for t in r["tests"])
    ]
    pages = [
        CoverageTestPage(path=p["path"])
        for p in cached["pages"]
        if any(t["nodeid"] == id for t in p["tests"])
    ]
    if not routes and not pages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found in coverage data")
    return CoverageTestDetail(nodeid=id, routes=routes, pages=pages)


def _area_items(cached: dict, area: str) -> list[dict]:
    if area == PAGES_AREA_NAME:
        return cached["pages"]
    return [r for r in cached["routes"] if _area_of(r["name"]) == area]


def _area_graph(area: str, items: list[dict]) -> CoverageGraph:
    is_pages = area == PAGES_AREA_NAME
    nodes: dict[str, CoverageGraphNode] = {}
    edges: list[CoverageGraphEdge] = []
    for item in items:
        ref = item["path"] if is_pages else item["name"]
        item_id = f"page:{ref}" if is_pages else f"route:{ref}"
        label = item["path"] if is_pages else f"{'/'.join(item['methods'])} {item['path']}"
        nodes[item_id] = CoverageGraphNode(
            id=item_id,
            kind="page" if is_pages else "route",
            label=label,
            ref=ref,
            path=item["path"],
            methods=[] if is_pages else item["methods"],
            tests_count=len(item["tests"]),
        )
        for t in item["tests"]:
            test_id = f"test:{t['nodeid']}"
            nodes.setdefault(test_id, CoverageGraphNode(id=test_id, kind="test", label=t["nodeid"], ref=t["nodeid"]))
            edges.append(CoverageGraphEdge(source=test_id, target=item_id))

    node_count = len(nodes)
    if node_count > MAX_GRAPH_NODES:
        return CoverageGraph(scope=f"area:{area}", nodes=[], edges=[], truncated=True, node_count=node_count)
    return CoverageGraph(scope=f"area:{area}", nodes=list(nodes.values()), edges=edges, truncated=False, node_count=node_count)


def _test_graph(cached: dict, nodeid: str) -> CoverageGraph:
    test_id = f"test:{nodeid}"
    nodes: dict[str, CoverageGraphNode] = {test_id: CoverageGraphNode(id=test_id, kind="test", label=nodeid, ref=nodeid)}
    edges: list[CoverageGraphEdge] = []
    for r in cached["routes"]:
        if not any(t["nodeid"] == nodeid for t in r["tests"]):
            continue
        route_id = f"route:{r['name']}"
        nodes[route_id] = CoverageGraphNode(
            id=route_id, kind="route", label=f"{'/'.join(r['methods'])} {r['path']}",
            ref=r["name"], path=r["path"], methods=r["methods"], tests_count=len(r["tests"]),
        )
        edges.append(CoverageGraphEdge(source=test_id, target=route_id))
    for p in cached["pages"]:
        if not any(t["nodeid"] == nodeid for t in p["tests"]):
            continue
        page_id = f"page:{p['path']}"
        nodes[page_id] = CoverageGraphNode(
            id=page_id, kind="page", label=p["path"], ref=p["path"], path=p["path"], tests_count=len(p["tests"]),
        )
        edges.append(CoverageGraphEdge(source=test_id, target=page_id))

    if len(nodes) < 2:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found in coverage data")
    return CoverageGraph(scope=f"test:{nodeid}", nodes=list(nodes.values()), edges=edges, truncated=False, node_count=len(nodes))


@router.get("/{name}/coverage/graph")
def get_coverage_graph(
    name: str,
    area: str | None = None,
    test: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> CoverageGraph:
    _get_project_or_404(conn, name)
    cached = _ensure_cached(name)

    if test:
        return _test_graph(cached, test)
    if not area:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Укажите area или test")

    items = _area_items(cached, area)
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Область не найдена")
    return _area_graph(area, items)
