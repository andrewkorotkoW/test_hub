import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response

from ..config import settings
from ..core import allure_report, charts, runner
from ..core.ws import hub
from ..db import get_connection
from ..deps import get_current_user, get_db, require_roles
from ..schemas import RunCreate

router = APIRouter(prefix="/api", tags=["runs"])
ws_router = APIRouter(tags=["runs-ws"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _get_run_or_404(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return row


def _run_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "project": row["project"],
        "stand": row["stand"],
        "target": row["target"],
        "marker": row["marker"],
        "status": row["status"],
        "started": row["started"],
        "finished": row["finished"],
        "duration": row["duration"],
        "requested_by": row["requested_by"],
        "counts": json.loads(row["counts"]) if row["counts"] else {},
    }


@router.get("/projects/{name}/tests")
async def list_tests(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> dict:
    project = _get_project_or_404(conn, name)
    return await runner.discover(project["path"], project["venv"])


@router.post("/projects/{name}/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    name: str,
    body: RunCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> dict:
    project = _get_project_or_404(conn, name)
    if body.stand is not None:
        stand = conn.execute(
            "SELECT 1 FROM stands WHERE project = ? AND name = ?", (project["name"], body.stand)
        ).fetchone()
        if not stand:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")
    run_id = await runner.submit_run(project["name"], body.stand, body.target, user["login"], body.marker)
    row = _get_run_or_404(conn, run_id)
    return _run_payload(row)


@router.get("/projects/{name}/runs")
def list_runs(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> list[dict]:
    _get_project_or_404(conn, name)
    rows = conn.execute(
        "SELECT * FROM runs WHERE project = ? ORDER BY id DESC", (name,)
    ).fetchall()
    return [_run_payload(r) for r in rows]


@router.get("/runs/{run_id}/report")
def get_report(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    row = _get_run_or_404(conn, run_id)
    tests = allure_report.parse_results(runner.allure_dir(run_id))
    counts = json.loads(row["counts"]) if row["counts"] and row["counts"] != "{}" else allure_report.counts_from_tests(tests)
    payload = _run_payload(row)
    payload["counts"] = counts
    payload["tests"] = tests
    return payload


def _run_history(conn: sqlite3.Connection, row: sqlite3.Row, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE project = ? AND stand IS ? ORDER BY id DESC LIMIT ?",
        (row["project"], row["stand"], limit),
    ).fetchall()
    return [_run_payload(r) for r in rows]


@router.get("/runs/{run_id}/report.png")
def get_report_png(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> Response:
    row = _get_run_or_404(conn, run_id)
    run = _run_payload(row)
    history = _run_history(conn, row, 10)
    results = allure_report.parse_results(runner.allure_dir(run_id))
    png = charts.build_report_png(run, history, results)
    return Response(content=png, media_type="image/png")


@router.get("/runs/{run_id}/trend.png")
def get_trend_png(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> Response:
    row = _get_run_or_404(conn, run_id)
    history = _run_history(conn, row, 30)
    png = charts.build_trend_png(history)
    return Response(content=png, media_type="image/png")


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager")),
) -> dict:
    _get_run_or_404(conn, run_id)
    outcome = await runner.cancel_run(run_id)
    if outcome == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if outcome == "not_cancellable":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run is not running or queued")
    row = _get_run_or_404(conn, run_id)
    return _run_payload(row)


def _ws_user(websocket: WebSocket) -> sqlite3.Row | None:
    from ..security import verify_session_token

    token = websocket.cookies.get(settings.SESSION_COOKIE)
    login = verify_session_token(token, settings.TH_SECRET, settings.SESSION_MAX_AGE) if token else None
    if not login:
        return None
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
    finally:
        conn.close()


@ws_router.websocket("/ws/runs/{run_id}")
async def run_events_ws(websocket: WebSocket, run_id: int) -> None:
    """Один сокет на прогон: клиент, кому интересен только один run_id, не получает
    чужой трафик (альтернатива — общий /ws с фильтрацией на клиенте, но тут выбран
    путь на прогон, см. app/core/ws.py)."""
    user = _ws_user(websocket)
    if user is None:
        await websocket.close(code=4401)
        return

    conn = get_connection()
    try:
        run = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            await websocket.close(code=4404)
            return
        history = conn.execute(
            "SELECT line FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    finally:
        conn.close()

    await websocket.accept()
    for row in history:
        await websocket.send_json({"type": "line", "run_id": run_id, "line": row["line"]})
    hub.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(run_id, websocket)
