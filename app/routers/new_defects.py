"""REST API поверх app/core/new_defects.py — вкладка «Новые дефекты»: падения с
причиной «код» из конкретного прогона, которых ещё нет ни в «Известные дефекты»
(xfail_registry), ни среди уже решённых руками QA (confirmed_defects).

Если YouTrack не настроен (app.config.settings.TH_YOUTRACK_*) — GET отдаёт
connected=false с кандидатами всё равно (список не зависит от YouTrack), но
«Подтвердить» (status=confirmed) ответит 503: без тикета-накопителя подтверждать
некуда. «Пропустить» (status=dismissed) работает всегда — это чисто локальное
решение, в YouTrack ничего не уходит."""
import asyncio
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core import new_defects, youtrack
from ..deps import get_db, require_roles
from ..schemas import NewDefectDecided, NewDefectDecision, NewDefectsResponse

router = APIRouter(prefix="/api/projects", tags=["new-defects"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


@router.get("/{name}/new-defects")
async def list_new_defects(
    name: str,
    stand: str,
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> NewDefectsResponse:
    _get_project_or_404(conn, name)
    items = new_defects.list_candidates(conn, name, stand, run_id)
    connected = youtrack.is_configured()
    return NewDefectsResponse(
        connected=connected,
        reason=None if connected else "YouTrack не подключён (TH_YOUTRACK_URL/TOKEN/ISSUE)",
        items=items,
    )


@router.post("/{name}/new-defects/decide", status_code=status.HTTP_201_CREATED)
async def decide_new_defect(
    name: str,
    stand: str,
    body: NewDefectDecision,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa", "manager")),
) -> NewDefectDecided:
    _get_project_or_404(conn, name)

    issue_url = None
    if body.status == "confirmed":
        if not youtrack.is_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="YouTrack не настроен — подтверждать некуда (TH_YOUTRACK_URL/TOKEN/ISSUE)",
            )
        comment = _build_comment(body)
        try:
            result = await asyncio.to_thread(youtrack.post_comment, comment)
        except youtrack.YouTrackError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        issue_url = result["url"]

    new_defects.decide(
        conn, name, stand, body.full_name, body.status, user["login"],
        issue_url=issue_url, priority=body.priority,
        expected_result=body.expected_result, precondition=body.precondition,
        run_id=body.run_id,
    )
    row = conn.execute(
        "SELECT * FROM confirmed_defects WHERE project = ? AND stand = ? AND test = ?",
        (name, stand, body.full_name),
    ).fetchone()
    return NewDefectDecided(**dict(row))


def _build_comment(body: NewDefectDecision) -> str:
    lines = [f"**{body.full_name}**", ""]
    if body.priority:
        lines.append(f"Приоритет: {body.priority}")
    if body.precondition:
        lines.append(f"\nПред_условие:\n{body.precondition}")
    if body.expected_result:
        lines.append(f"\nОР: {body.expected_result}")
    lines.append(f"\n---\nИсточник: test_hub, прогон #{body.run_id}")
    return "\n".join(lines)
