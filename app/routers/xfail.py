"""REST API поверх app/core/xfail_registry.py — известные дефекты (xfail/xpass).

Идентификатор теста в БД (xfail_registry.test) — allure fullName (как и
flaky_stats.test, см. app/routers/flaky.py), GET обогащает каждую запись
best-effort полем nodeid по дереву тестов (runner.discover()), чтобы кнопка
«Проверить» могла передать submit_run реальные nodeid'ы."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core import runner, xfail_registry
from ..deps import get_db, require_roles
from ..schemas import XfailCheckRequest, XfailCheckResult, XfailEntry, XfailList, XfailUpdate

router = APIRouter(prefix="/api/projects", tags=["xfail"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _entry_payload(row: sqlite3.Row, nodeid_by_full_name: dict[str, str]) -> XfailEntry:
    return XfailEntry(
        id=row["id"],
        project=row["project"],
        stand=row["stand"],
        test=row["test"],
        nodeid=nodeid_by_full_name.get(row["test"]),
        reason=row["reason"],
        first_seen=row["first_seen"],
        last_run_id=row["last_run_id"],
        state=row["state"],
        issue_url=row["issue_url"],
        note=row["note"],
    )


@router.get("/{name}/xfail")
async def list_xfail(
    name: str,
    stand: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> XfailList:
    project = _get_project_or_404(conn, name)
    rows = xfail_registry.list_entries(conn, name, stand)

    discovered = await runner.discover(project["path"], project["venv"])
    nodeid_by_full_name = xfail_registry.full_name_index(discovered.get("tree") or {})

    return XfailList(items=[_entry_payload(r, nodeid_by_full_name) for r in rows])


@router.post("/{name}/xfail/check", status_code=status.HTTP_201_CREATED)
async def check_xfail(
    name: str,
    stand: str,
    body: XfailCheckRequest = XfailCheckRequest(),
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa")),
) -> XfailCheckResult:
    """Перезапускает известные дефекты этого стенда (все, либо только `body.ids`)
    одним прогоном — target собирается из их nodeid'ов, join'ом через \\n (как и
    остальной код, см. app/core/runner.py::_execute)."""
    project = _get_project_or_404(conn, name)
    rows = xfail_registry.list_entries(conn, name, stand)
    if body.ids:
        wanted = set(body.ids)
        rows = [r for r in rows if r["id"] in wanted]
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No known xfail tests for this stand")

    discovered = await runner.discover(project["path"], project["venv"])
    nodeid_by_full_name = xfail_registry.full_name_index(discovered.get("tree") or {})
    nodeids = [nodeid_by_full_name[r["test"]] for r in rows if r["test"] in nodeid_by_full_name]
    if not nodeids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Known xfail tests not found in current test tree"
        )

    run_id = await runner.submit_run(name, stand, "\n".join(nodeids), user["login"])
    return XfailCheckResult(run_id=run_id, count=len(nodeids))


@router.put("/{name}/xfail/{entry_id}")
async def update_xfail(
    name: str,
    entry_id: int,
    body: XfailUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> XfailEntry:
    project = _get_project_or_404(conn, name)
    row = xfail_registry.get_entry(conn, name, entry_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    xfail_registry.update_entry(conn, entry_id, body.issue_url, body.note)
    row = xfail_registry.get_entry(conn, name, entry_id)

    discovered = await runner.discover(project["path"], project["venv"])
    nodeid_by_full_name = xfail_registry.full_name_index(discovered.get("tree") or {})
    return _entry_payload(row, nodeid_by_full_name)
