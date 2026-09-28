"""REST API поверх app/core/stats.py — статистика по разделам проекта и её
динамика за 30 дней (страница ui/stats.html, команда бота /stats)."""
import csv
import io
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from ..core import stats
from ..deps import get_db, require_roles
from ..schemas import (
    StatsDynamicsPoint,
    StatsSection,
    StatsSummary,
    StatsTopFlakyTest,
    StatsTopSlowTest,
)

router = APIRouter(prefix="/api/projects", tags=["stats"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _resolve_stand(conn: sqlite3.Connection, name: str, stand: str | None) -> str | None:
    return stand if stand is not None else stats.default_stand(conn, name)


def _ensure_cached(conn: sqlite3.Connection, name: str, stand: str | None) -> dict:
    """load_cached, либо пересчёт, если появился новый завершённый прогон —
    по аналогии с app.routers.coverage._ensure_cached."""
    cached = stats.load_cached(name, stand)
    current_run_id = stats.latest_finished_run_id(conn, name, stand)
    if cached is None or cached.get("cache_key_run_id") != current_run_id:
        cached = stats.recalc(name, stand)
    return cached


def _summary_from_cache(cached: dict) -> StatsSummary:
    return StatsSummary(
        project=cached["project"],
        stand=cached["stand"],
        generated_at=cached["generated_at"],
        run_id=cached["run_id"],
        sections=[StatsSection(**s) for s in cached["sections"]],
        empty_sections=cached["empty_sections"],
        dynamics_project=[StatsDynamicsPoint(**p) for p in cached["dynamics_project"]],
        dynamics_by_section={
            section: [StatsDynamicsPoint(**p) for p in points]
            for section, points in cached["dynamics_by_section"].items()
        },
        top_slowest=[StatsTopSlowTest(**t) for t in cached["top_slowest"]],
        top_flaky=[StatsTopFlakyTest(**t) for t in cached["top_flaky"]],
    )


@router.get("/{name}/stats")
def get_stats(
    name: str,
    stand: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> StatsSummary:
    _get_project_or_404(conn, name)
    stand = _resolve_stand(conn, name, stand)
    cached = _ensure_cached(conn, name, stand)
    return _summary_from_cache(cached)


@router.get("/{name}/stats/sections.csv")
def export_sections_csv(
    name: str,
    stand: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> Response:
    _get_project_or_404(conn, name)
    stand = _resolve_stand(conn, name, stand)
    cached = _ensure_cached(conn, name, stand)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "раздел", "тестов", "passed", "failed", "xfail", "skipped",
        "доля passed, %", "средняя длительность, с", "флаки", "активных xfail", "покрытие маршрутов, %",
    ])
    for s in cached["sections"]:
        writer.writerow([
            s["section"], s["tests_total"], s["passed"], s["failed"], s["xfail"], s["skipped"],
            s["passed_percent"] if s["passed_percent"] is not None else "",
            s["avg_duration"] if s["avg_duration"] is not None else "",
            s["flaky_count"], s["xfail_count"],
            s["routes_percent"] if s["routes_percent"] is not None else "",
        ])

    filename = f"{name}_stats_sections.csv"
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
