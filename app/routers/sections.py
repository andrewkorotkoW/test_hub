"""REST API поверх app/core/sections.py — дерево разделов проекта (api/ui/e2e
-> области -> файлы) для формы запуска и формы расписаний (ui/project.html/js),
а также для команды бота /run <проект> <раздел> (app/tg_bot.py).

Статус «последнего прогона раздела» рядом с каждой областью берётся из уже
посчитанной статистики (app.core.stats, часть 2 миссии) — этот роутер её сам
не пересчитывает (recalc стоит только на живом просмотре страницы статистики),
если кэша ещё нет, статус просто отсутствует (null)."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core import sections as sections_core
from ..core import stats
from ..deps import get_db, require_roles
from ..schemas import SectionArea, SectionKind, SectionsTree, StatsSection

router = APIRouter(prefix="/api/projects", tags=["sections"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _ensure_cached(project: sqlite3.Row) -> dict:
    """load_cached, либо пересчёт, если дерево tests/ на диске изменилось со
    времени последнего пересчёта (см. app.core.sections::mtime_signature) —
    по аналогии с app.routers.coverage._ensure_cached."""
    cached = sections_core.load_cached(project["name"])
    signature = sections_core.mtime_signature(project["path"])
    if cached is None or cached.get("mtime_signature") != signature:
        cached = sections_core.recalc(project["name"], project["path"])
    return cached


def _attach_status(cached: dict, conn: sqlite3.Connection, project_name: str, stand: str | None) -> SectionsTree:
    resolved_stand = stand if stand is not None else stats.default_stand(conn, project_name)
    stats_cached = stats.load_cached(project_name, resolved_stand)
    status_by_section = {s["section"]: s for s in (stats_cached["sections"] if stats_cached else [])}

    kinds = []
    for kind_node in cached["kinds"]:
        areas = []
        for area in kind_node["areas"]:
            area_status = status_by_section.get(area["section"])
            areas.append(SectionArea(
                area=area["area"],
                section=area["section"],
                target=area["target"],
                tests_count=area["tests_count"],
                files=area["files"],
                status=StatsSection(**area_status) if area_status else None,
            ))
        kinds.append(SectionKind(kind=kind_node["kind"], target=kind_node["target"], areas=areas))

    return SectionsTree(project=cached["project"], generated_at=cached["generated_at"], kinds=kinds)


@router.get("/{name}/sections")
def get_sections(
    name: str,
    stand: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> SectionsTree:
    project = _get_project_or_404(conn, name)
    cached = _ensure_cached(project)
    return _attach_status(cached, conn, name, stand)
