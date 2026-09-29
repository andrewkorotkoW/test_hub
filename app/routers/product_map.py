"""REST API поверх app/core/product_map.py для страницы «Покрытие» как схемы
продукта: зоны -> узлы со светофором -> связи + итог по стенду.

Права доступа — те же, что у соседних ручек app.routers.coverage/sections
(qa/manager/customer читают, ручного recalc для этой карты нет — она пересчитывается
лениво, см. _ensure_cached)."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core import product_map, stats
from ..deps import get_db, require_roles
from ..schemas import (
    ProductMap,
    ProductMapCanvas,
    ProductMapEdge,
    ProductMapNode,
    ProductMapSampleTest,
    ProductMapSummary,
    ProductMapZone,
)

router = APIRouter(prefix="/api/projects", tags=["product-map"])

_EMPTY_NODE_STATUS = {"state": "grey", "run_id": None, "tests_count": {"api": 0, "ui": 0, "other": 0, "total": 0}, "sample_tests": []}


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _cache_is_current(cached: dict, project: sqlite3.Row, conn: sqlite3.Connection) -> bool:
    """Раскладка не изменилась (файл карты/дерево тестов) и ни на одном стенде не
    появился новый завершённый прогон — иначе пересчёт (см. app.core.product_map.recalc,
    по аналогии с app.routers.coverage._cache_is_current/sections._ensure_cached)."""
    if "stands" not in cached or "zones" not in cached:
        return False
    if cached.get("map_signature") != product_map.map_signature(project["path"]):
        return False
    stands = [
        row["name"]
        for row in conn.execute("SELECT name FROM stands WHERE project = ? ORDER BY name", (project["name"],)).fetchall()
    ]
    if set(cached["stands"].keys()) != set(stands):
        return False
    return all(
        cached["stands"][stand].get("run_id") == product_map.latest_run_id(conn, project["name"], stand)
        for stand in stands
    )


def _ensure_cached(project: sqlite3.Row, conn: sqlite3.Connection) -> dict:
    cached = product_map.load_cached(project["name"])
    if cached is None or not _cache_is_current(cached, project, conn):
        cached = product_map.recalc(project["name"], conn)
    return cached


@router.get("/{name}/product-map")
def get_product_map(
    name: str,
    stand: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> ProductMap:
    project = _get_project_or_404(conn, name)
    cached = _ensure_cached(project, conn)

    resolved_stand = stand or stats.default_stand(conn, name)
    if resolved_stand is None or resolved_stand not in cached["stands"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")

    stand_data = cached["stands"][resolved_stand]
    nodes_status: dict[str, dict] = stand_data["nodes"]

    nodes_out = []
    covered = no_tests = failing = 0
    for node in cached["nodes"]:
        node_status = nodes_status.get(node["id"], _EMPTY_NODE_STATUS)
        state = node_status["state"]
        if state == "green":
            covered += 1
        elif state == "grey":
            no_tests += 1
        elif state == "red":
            failing += 1
        nodes_out.append(ProductMapNode(
            id=node["id"], label=node["label"], zone=node["zone"],
            x=node["x"], y=node["y"], w=node["w"], h=node["h"],
            target=node.get("target"),
            state=state,
            tests_count=node_status["tests_count"],
            sample_tests=[ProductMapSampleTest(**t) for t in node_status["sample_tests"]],
        ))

    return ProductMap(
        project=name,
        stand=resolved_stand,
        generated_at=cached["generated_at"],
        source=cached["source"],
        message=cached["message"],
        run_id=stand_data["run_id"],
        canvas=ProductMapCanvas(**cached["canvas"]),
        zones=[ProductMapZone(**z) for z in cached["zones"]],
        nodes=nodes_out,
        edges=[ProductMapEdge(source=e["from"], target=e["to"]) for e in cached["edges"]],
        summary=ProductMapSummary(total=len(cached["nodes"]), covered=covered, no_tests=no_tests, failing=failing),
    )
