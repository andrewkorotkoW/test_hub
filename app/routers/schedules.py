"""REST API для расписаний ночных/регулярных прогонов (app/core/schedule.py).

Весь CRUD и run-now ограничены ролью qa (см. задачу — расписания настраивает
только QA); run-now использует тот же runner.submit_run, что и обычный
POST /runs, но от имени того, кто нажал кнопку (сервисная учётка бота
используется только автопланировщиком, см. app.core.schedule.scheduler_loop)."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core import schedule as schedule_core
from ..deps import get_db, require_roles
from ..schemas import Schedule, ScheduleCreate, ScheduleRunNowResult, ScheduleUpdate

router = APIRouter(prefix="/api/projects", tags=["schedules"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _get_schedule_or_404(conn: sqlite3.Connection, project: str, schedule_id: int) -> sqlite3.Row:
    row = schedule_core.get_schedule(conn, project, schedule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return row


def _check_stand(conn: sqlite3.Connection, project: str, stand: str | None) -> None:
    if stand is None:
        return
    row = conn.execute("SELECT 1 FROM stands WHERE project = ? AND name = ?", (project, stand)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")


def _schedule_payload(row: sqlite3.Row) -> Schedule:
    return Schedule(**schedule_core.row_to_dict(row))


@router.get("/{name}/schedules")
def list_schedules(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> list[Schedule]:
    _get_project_or_404(conn, name)
    rows = schedule_core.list_schedules(conn, name)
    return [_schedule_payload(r) for r in rows]


@router.post("/{name}/schedules", status_code=status.HTTP_201_CREATED)
def create_schedule(
    name: str,
    body: ScheduleCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> Schedule:
    _get_project_or_404(conn, name)
    _check_stand(conn, name, body.stand)
    try:
        row = schedule_core.create_schedule(
            conn, name, body.stand, body.target, body.marker, body.cron, body.enabled, body.notify_chat_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _schedule_payload(row)


@router.put("/{name}/schedules/{schedule_id}")
def update_schedule(
    name: str,
    schedule_id: int,
    body: ScheduleUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> Schedule:
    _get_project_or_404(conn, name)
    row = _get_schedule_or_404(conn, name, schedule_id)
    stand = body.stand if body.stand is not None else row["stand"]
    _check_stand(conn, name, stand)
    target = body.target if body.target is not None else row["target"]
    marker = body.marker if body.marker is not None else row["marker"]
    cron = body.cron if body.cron is not None else row["cron"]
    enabled = body.enabled if body.enabled is not None else bool(row["enabled"])
    notify_chat_ids = (
        body.notify_chat_ids if body.notify_chat_ids is not None else schedule_core.row_to_dict(row)["notify_chat_ids"]
    )
    try:
        updated = schedule_core.update_schedule(conn, row, stand, target, marker, cron, enabled, notify_chat_ids)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _schedule_payload(updated)


@router.delete("/{name}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    name: str,
    schedule_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> None:
    _get_project_or_404(conn, name)
    _get_schedule_or_404(conn, name, schedule_id)
    schedule_core.delete_schedule(conn, schedule_id)


@router.post("/{name}/schedules/{schedule_id}/run-now", status_code=status.HTTP_201_CREATED)
async def run_now(
    name: str,
    schedule_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa")),
) -> ScheduleRunNowResult:
    _get_project_or_404(conn, name)
    row = _get_schedule_or_404(conn, name, schedule_id)
    run_id = await schedule_core.run_now(conn, row, user["login"])
    return ScheduleRunNowResult(run_id=run_id)
