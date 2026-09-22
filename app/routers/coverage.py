"""REST API поверх app/core/coverage.py для страницы «Покрытие».

Область (area) маршрута — первый сегмент его dotted-имени из routes.tsv
(например "knowledge_base" для "knowledge_base.home.bundles.index"): в
auto_tests_vshgu_cloude (Laravel-именование роутов) это естественная и уже
готовая группировка, без необходимости парсить path.
"""
import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from ..core import coverage
from ..deps import get_db, require_roles
from ..schemas import (
    CoverageMapArea,
    CoverageMapRoute,
    CoverageRouteDetail,
    CoverageRouteStandStatus,
    CoverageRoutesUploadResult,
    CoverageRouteTestStatus,
    CoverageStandSummary,
    CoverageSummary,
    CoverageTestDetail,
    CoverageTestPage,
    CoverageTestRoute,
)

router = APIRouter(prefix="/api/projects", tags=["coverage"])

_VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}


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
    if cached is None:
        cached = coverage.recalc(project_name)
    return cached


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

    map_areas = [
        CoverageMapArea(area=area, routes=sorted(area_routes, key=lambda r: r.path))
        for area, area_routes in sorted(areas.items())
    ]
    zero_coverage_areas = sorted(area for area, has_covered in area_has_covered.items() if not has_covered)

    return CoverageSummary(
        project=cached["project"],
        generated_at=cached["generated_at"],
        stands=stand_summaries,
        routes_total=cached["routes_total"],
        routes_covered=cached["routes_covered"],
        zero_coverage_areas=zero_coverage_areas,
        map=map_areas,
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

    stands = cached["stands"]
    status_by_stand = {
        stand: {t["nodeid"]: t["status"] for t in route["status"][stand]["tests"]} for stand in stands
    }
    tests = [
        CoverageRouteTestStatus(
            nodeid=t["nodeid"],
            env=t["env"],
            status={stand: status_by_stand[stand].get(t["nodeid"]) for stand in stands},
        )
        for t in route["tests"]
    ]
    return CoverageRouteDetail(name=route["name"], methods=route["methods"], path=route["path"], tests=tests)


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
