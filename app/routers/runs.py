import base64
import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect,
    status,
)
from fastapi.responses import Response

from ..config import settings
from ..core import allure_report, charts, live, runner
from ..core.ws import hub
from ..db import get_connection
from ..deps import get_current_user, get_db, require_roles
from ..schemas import RunCreate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["runs"])
ws_router = APIRouter(tags=["runs-ws"])

_FRAME_HASH_RE = re.compile(r"^[0-9a-f]{16}$")


def _nodeid_hash(nodeid: str) -> str:
    return hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:16]


def _frame_step_and_url(run_id: int, rel_path: str) -> tuple[int, str]:
    """rel_path — "<hash>/<step>.png", как его пишет upload_frame в run_events.line."""
    step = int(rel_path.rsplit("/", 1)[-1].removesuffix(".png"))
    return step, f"/api/runs/{run_id}/frames/{rel_path}"


def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid -> allure fullName. Та же логика, что и в app.core.coverage/flaky/
    xfail_registry/tg_bot (allure_pytest.utils.allure_full_name) — своя копия по тому
    же соглашению модулей: не тянуть межмодульную зависимость ради одной функции."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def _full_name_index(tree: dict) -> dict[str, str]:
    """allure fullName -> pytest nodeid по дереву тестов (runner.discover()) — тем же
    приёмом, что и app/core/flaky.py::full_name_index и app/core/xfail_registry.py::
    full_name_index, здесь нужен для GET /runs/{id}/tests после завершения прогона:
    allure_report.parse_results отдаёт только fullName (см. allure_report._parse_result),
    а единым ключом теста в ответе должен быть pytest nodeid (кадры/лог пишутся под ним)."""
    index: dict[str, str] = {}
    for file_path, classes in tree.items():
        for cls_name, tests in classes.items():
            for test_name in tests:
                nodeid = f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}"
                index.setdefault(_nodeid_to_full_name(nodeid), nodeid)
    return index


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
        "repeat": row["repeat"],
        "status": row["status"],
        "started": row["started"],
        "finished": row["finished"],
        "duration": row["duration"],
        "requested_by": row["requested_by"],
        "counts": json.loads(row["counts"]) if row["counts"] else {},
        "label": row["label"],
        "live": bool(row["live"]),
        "mobile": bool(row["mobile"]),
    }


@router.get("/config")
def get_config(_user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """Фронт формы запуска/страницы сборки сверяет число выбранных тестов с этим
    лимитом до отправки (галочка «Эфир» недоступна при превышении) — сервер
    дублирует ту же проверку в create_run, см. settings.TH_LIVE_MAX_TESTS."""
    return {"live_max_tests": settings.TH_LIVE_MAX_TESTS}


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
    if body.live:
        tree_data = await runner.discover(project["path"], project["venv"])
        selected = runner.count_target_tests(tree_data.get("tree", {}), body.target)
        if selected > settings.TH_LIVE_MAX_TESTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Эфир доступен для прогонов до {settings.TH_LIVE_MAX_TESTS} тестов, выбрано {selected}",
            )
    try:
        run_id = await runner.submit_run(
            project["name"], body.stand, body.target, user["login"], body.marker, body.repeat,
            confirm_manual=body.confirm_manual, label=body.label, live=body.live, mobile=body.mobile,
        )
    except runner.ManualRunNotConfirmed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    row = _get_run_or_404(conn, run_id)
    return _run_payload(row)


@router.get("/projects/{name}/runs")
def list_runs(
    name: str,
    label: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> list[dict]:
    _get_project_or_404(conn, name)
    if label is not None:
        rows = conn.execute(
            "SELECT * FROM runs WHERE project = ? AND label = ? ORDER BY id DESC", (name, label)
        ).fetchall()
    else:
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


@router.get("/runs/{run_id}/tests")
async def list_run_tests(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> list[dict]:
    """Тесты прогона со статусами: пока прогон running/queued — по живым
    test_start/test_end событиям run_events (статус теста в это время известен
    только из "[TH] end <nodeid> <status>"-строки, nodeid там уже pytest nodeid),
    после завершения — из allure_report.parse_results, как get_report.

    allure отдаёт только fullName (см. allure_report._parse_result), а единый ключ
    теста в ответе — pytest nodeid (кадры и лог пишутся под ним, не под fullName) —
    поэтому fullName после завершения прогона приводится к nodeid через статическое
    дерево тестов проекта (runner.discover() + _full_name_index), как это уже делают
    app/routers/flaky.py и app/routers/xfail.py. Оба поля (nodeid и full_name)
    отдаются всегда — UI использует nodeid, full_name — только для отображения/логов."""
    row = _get_run_or_404(conn, run_id)
    frame_nodeids = {
        r["nodeid"]
        for r in conn.execute(
            "SELECT DISTINCT nodeid FROM run_events WHERE run_id = ? AND kind = 'frame'", (run_id,)
        ).fetchall()
    }
    video_duration_by_nodeid = {
        r["nodeid"]: r["duration_ms"]
        for r in conn.execute(
            "SELECT nodeid, duration_ms FROM run_test_videos WHERE run_id = ?", (run_id,)
        ).fetchall()
    }
    video_nodeids = set(video_duration_by_nodeid)

    if row["status"] in ("running", "queued"):
        events = conn.execute(
            "SELECT nodeid, kind, line FROM run_events WHERE run_id = ? "
            "AND kind IN ('test_start', 'test_end') ORDER BY id",
            (run_id,),
        ).fetchall()
        statuses: dict[str, str] = {}
        for ev in events:
            nodeid = ev["nodeid"]
            if not nodeid:
                continue
            if ev["kind"] == "test_start":
                statuses.setdefault(nodeid, "running")
            else:
                statuses[nodeid] = runner.end_status_from_line(ev["line"]) or "unknown"
        return [
            {
                "nodeid": nodeid,
                "full_name": _nodeid_to_full_name(nodeid),
                "status": test_status,
                "has_frames": nodeid in frame_nodeids,
                "has_video": nodeid in video_nodeids,
                "video_duration_ms": video_duration_by_nodeid.get(nodeid),
            }
            for nodeid, test_status in statuses.items()
        ]

    project = conn.execute("SELECT path, venv FROM projects WHERE name = ?", (row["project"],)).fetchone()
    nodeid_by_full_name: dict[str, str] = {}
    if project is not None:
        discovered = await runner.discover(project["path"], project["venv"])
        nodeid_by_full_name = _full_name_index(discovered.get("tree") or {})

    results = allure_report.parse_results(runner.allure_dir(run_id))
    return [
        {
            "nodeid": nodeid_by_full_name.get(t["name"], t["name"]),
            "full_name": t["name"],
            "status": t["status"],
            "has_frames": nodeid_by_full_name.get(t["name"], t["name"]) in frame_nodeids,
            "has_video": nodeid_by_full_name.get(t["name"], t["name"]) in video_nodeids,
            "video_duration_ms": video_duration_by_nodeid.get(nodeid_by_full_name.get(t["name"], t["name"])),
        }
        for t in results
    ]


@router.get("/runs/{run_id}/tests/{nodeid:path}/log")
def get_run_test_log(
    run_id: int,
    nodeid: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> list[str]:
    _get_run_or_404(conn, run_id)
    rows = conn.execute(
        "SELECT line FROM run_events WHERE run_id = ? AND nodeid = ? AND kind IN ('line', 'step') "
        "ORDER BY id",
        (run_id, nodeid),
    ).fetchall()
    return [row["line"] for row in rows]


@router.get("/runs/{run_id}/tests/{nodeid:path}/frames")
def get_run_test_frames(
    run_id: int,
    nodeid: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> list[dict]:
    _get_run_or_404(conn, run_id)
    rows = conn.execute(
        "SELECT line FROM run_events WHERE run_id = ? AND nodeid = ? AND kind = 'frame' ORDER BY id",
        (run_id, nodeid),
    ).fetchall()
    frames = []
    for r in rows:
        step, url = _frame_step_and_url(run_id, r["line"])
        frames.append({"step": step, "url": url})
    return frames


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


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


@router.post("/runs/{run_id}/frames", status_code=status.HTTP_201_CREATED)
async def upload_frame(
    run_id: int,
    nodeid: str = Form(...),
    step: int = Form(...),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Приём кадра UI-теста от плагина проекта тестов (отдельная миссия в
    auto_tests_vshgu/demo) во время прогона. Авторизация — токеном прогона, а
    не пользовательской сессией: заголовок `Authorization: Bearer <TH_RUN_TOKEN>`
    с тем же токеном, что раннер передал pytest в env (см. app/core/runner.py::
    _execute, check_run_token). 401 — токен не совпал или прогон уже не running
    (токен раннер вычищает в _finalize, поэтому это одна и та же проверка)."""
    row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None or row["status"] != "running":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Run is not running")
    if not runner.check_run_token(run_id, _bearer_token(authorization)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid run token")

    raw = await file.read()
    if len(raw) > settings.TH_FRAME_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Frame exceeds TH_FRAME_MAX_BYTES ({settings.TH_FRAME_MAX_BYTES} bytes)",
        )

    frame_count = conn.execute(
        "SELECT COUNT(*) FROM run_events WHERE run_id = ? AND kind = 'frame'", (run_id,)
    ).fetchone()[0]
    if frame_count >= settings.TH_FRAME_MAX_PER_RUN:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Run already has TH_FRAME_MAX_PER_RUN frames ({settings.TH_FRAME_MAX_PER_RUN})",
        )

    nodeid_hash = _nodeid_hash(nodeid)
    rel_path = f"{nodeid_hash}/{step}.png"
    dest = runner.frames_dir(run_id) / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

    conn.execute(
        "INSERT INTO run_events (run_id, ts, line, nodeid, kind) VALUES (?, ?, ?, ?, 'frame')",
        (run_id, datetime.now().isoformat(timespec="seconds"), rel_path, nodeid),
    )
    conn.commit()

    url = f"/api/runs/{run_id}/frames/{rel_path}"
    await hub.broadcast(
        run_id, {"type": "frame", "run_id": run_id, "nodeid": nodeid, "step": step, "url": url}
    )
    return {"url": url}


@router.get("/runs/{run_id}/frames/{nodeid_hash}/{step}.png")
def get_frame_file(
    run_id: int,
    nodeid_hash: str,
    step: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> Response:
    """Сама картинка кадра — авторизация обычной пользовательской сессией (не
    токеном прогона, тот только для приёма от pytest в upload_frame выше)."""
    _get_run_or_404(conn, run_id)
    if not _FRAME_HASH_RE.match(nodeid_hash):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame not found")
    path = runner.frames_dir(run_id) / nodeid_hash / f"{step}.png"
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame not found")
    return Response(content=path.read_bytes(), media_type="image/png")


def _require_run_token(conn: sqlite3.Connection, run_id: int, authorization: str | None) -> None:
    """Общая проверка для /live и .../video (та же логика, что upload_frame выше):
    401, если прогон не running или Bearer-токен не совпал с runner.check_run_token."""
    row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None or row["status"] != "running":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Run is not running")
    if not runner.check_run_token(run_id, _bearer_token(authorization)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid run token")


@router.post("/runs/{run_id}/live", status_code=status.HTTP_204_NO_CONTENT)
async def upload_live_frame(
    run_id: int,
    nodeid: str = Form(...),
    ts: float = Form(...),
    step: str = Form(""),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Живой кадр от плагина (контракт п.1, docs/missions/2026-10-01_live_stream.md)
    — не пишется на диск, только в app/core/live.py (последний кадр на run_id) и
    рассылается подписчикам WS, если не сработал троттлинг 5 кадров/с."""
    _require_run_token(conn, run_id, authorization)
    raw = await file.read()
    if live.store_frame(run_id, nodeid, ts, step, raw):
        await hub.broadcast(
            run_id,
            {
                "type": "live",
                "run_id": run_id,
                "nodeid": nodeid,
                "ts": ts,
                "step": step,
                "jpeg_b64": base64.b64encode(raw).decode("ascii"),
            },
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/runs/{run_id}/live.jpg")
def get_live_frame(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> Response:
    """Последний живой кадр — авторизация обычной пользовательской сессией (как
    get_frame_file, не токеном прогона). 404, если кадров не было или последний
    протух (см. app/core/live.py::get_frame)."""
    _get_run_or_404(conn, run_id)
    frame = live.get_frame(run_id)
    if frame is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No live frame")
    return Response(content=frame["jpeg_bytes"], media_type="image/jpeg")


@router.post("/runs/{run_id}/tests/{nodeid:path}/video", status_code=status.HTTP_201_CREATED)
async def upload_test_video(
    run_id: int,
    nodeid: str,
    file: UploadFile = File(...),
    duration_ms: int = Form(...),
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Видео теста от плагина, после его завершения (контракт п.3) — токеном
    прогона, как /live: видео тоже шлёт плагин во время прогона, прогон ещё
    должен быть running. Повторная загрузка для того же (run_id, nodeid)
    заменяет запись (тот же приём, что у вложений тест-кейсов, см.
    app/routers/test_cases.py) — путь на диске детерминирован по _nodeid_hash,
    поэтому файл просто перезаписывается."""
    _require_run_token(conn, run_id, authorization)
    raw = await file.read()
    if len(raw) > settings.TH_VIDEO_MAX_MB * 1024 * 1024:
        logger.warning(
            "run %s: видео теста %s превышает TH_VIDEO_MAX_MB (%s МБ), отброшено",
            run_id, nodeid, settings.TH_VIDEO_MAX_MB,
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Video exceeds TH_VIDEO_MAX_MB ({settings.TH_VIDEO_MAX_MB} MB)",
        )

    dest = runner.video_dir(run_id) / f"{_nodeid_hash(nodeid)}.webm"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

    conn.execute("DELETE FROM run_test_videos WHERE run_id = ? AND nodeid = ?", (run_id, nodeid))
    conn.execute(
        "INSERT INTO run_test_videos (run_id, nodeid, path, duration_ms, size, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, nodeid, str(dest), duration_ms, len(raw), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return {"nodeid": nodeid, "duration_ms": duration_ms, "size": len(raw)}


@router.get("/runs/{run_id}/tests/{nodeid:path}/video")
def get_run_test_video(
    run_id: int,
    nodeid: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(get_current_user),
) -> Response:
    _get_run_or_404(conn, run_id)
    row = conn.execute(
        "SELECT path FROM run_test_videos WHERE run_id = ? AND nodeid = ?", (run_id, nodeid)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    path = Path(row["path"])
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return runner.serve_video_with_range(path, request)


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
            "SELECT line, nodeid, kind FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    finally:
        conn.close()

    await websocket.accept()
    for row in history:
        # Старые прогоны без разметки (kind=NULL до миграции — но DEFAULT 'line'
        # у самой колонки покрывает и их) шлются как раньше: type='line'.
        kind = row["kind"] or "line"
        if kind == "frame":
            step, url = _frame_step_and_url(run_id, row["line"])
            await websocket.send_json(
                {"type": "frame", "run_id": run_id, "nodeid": row["nodeid"], "step": step, "url": url}
            )
        else:
            await websocket.send_json(
                {"type": kind, "run_id": run_id, "line": row["line"], "nodeid": row["nodeid"]}
            )
    hub.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(run_id, websocket)
