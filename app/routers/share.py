"""Публичная ссылка на отчёт прогона: без логина, только чтение.

Два роутера в одном файле:
- `router` (/api/runs/{id}/share) — создание/отзыв/список ссылок, требует сессию
  qa/manager (как остальной test_hub, через Depends(require_roles)).
- `public_router` (/share/{token}) — ровно противоположное: без Depends(get_current_user)
  вообще, доступ только по действующему токену (не отозван, не истёк). Отдаёт статику
  ui/share.html и JSON/PNG/allure-отчёт только для одного конкретного прогона —
  ссылка на прогон #5 не должна давать доступ к данным прогона #6.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response

from ..config import settings
from ..core import allure_report, charts, runner
from ..deps import get_db, require_roles
from ..schemas import ShareLink, ShareLinkCreate

router = APIRouter(prefix="/api/runs", tags=["share"])
public_router = APIRouter(prefix="/share", tags=["share-public"])

UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"

_EXPIRES_DELTA = {"7d": timedelta(days=7), "30d": timedelta(days=30), "never": None}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_run_or_404(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return row


def _share_payload(row: sqlite3.Row) -> dict:
    return {
        "token": row["token"],
        "url": f"{settings.TH_PUBLIC_URL}/share/{row['token']}",
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "revoked": bool(row["revoked"]),
    }


# ------------------------------------------------------------------ API: создание/список/отзыв (qa/manager)
@router.post("/{run_id}/share", status_code=status.HTTP_201_CREATED, response_model=ShareLink)
def create_share_link(
    run_id: int,
    body: ShareLinkCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa", "manager")),
) -> dict:
    _get_run_or_404(conn, run_id)
    token = secrets.token_urlsafe(24)
    delta = _EXPIRES_DELTA[body.expires]
    expires_at = (datetime.now() + delta).isoformat(timespec="seconds") if delta else None
    conn.execute(
        "INSERT INTO share_links (token, run_id, created_by, created_at, expires_at, revoked) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (token, run_id, user["login"], _now_iso(), expires_at),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
    return _share_payload(row)


@router.get("/{run_id}/share", response_model=list[ShareLink])
def list_share_links(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager")),
) -> list[dict]:
    _get_run_or_404(conn, run_id)
    rows = conn.execute(
        "SELECT * FROM share_links WHERE run_id = ? ORDER BY created_at DESC", (run_id,)
    ).fetchall()
    return [_share_payload(r) for r in rows]


@router.delete("/{run_id}/share/{token}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share_link(
    run_id: int,
    token: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager")),
) -> None:
    row = conn.execute(
        "SELECT 1 FROM share_links WHERE token = ? AND run_id = ?", (token, run_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found")
    conn.execute("UPDATE share_links SET revoked = 1 WHERE token = ?", (token,))
    conn.commit()


# ------------------------------------------------------------------ публичные маршруты: без Depends(get_current_user)
def _get_active_share_or_404(conn: sqlite3.Connection, token: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
    if not row or row["revoked"] or (row["expires_at"] and row["expires_at"] < _now_iso()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return row


def _public_run_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "project": row["project"],
        "stand": row["stand"],
        "marker": row["marker"],
        "status": row["status"],
        "started": row["started"],
        "finished": row["finished"],
        "duration": row["duration"],
    }


def _safe_report_path(report_dir: Path, rel_path: str) -> Path | None:
    """Не выпускает FileResponse за пределы report_dir (запрос вида "../../.env")."""
    candidate = (report_dir / rel_path).resolve()
    try:
        candidate.relative_to(report_dir.resolve())
    except ValueError:
        return None
    return candidate


def _allure_asset_response(conn: sqlite3.Connection, token: str, rel_path: str) -> FileResponse:
    share = _get_active_share_or_404(conn, token)
    run = _get_run_or_404(conn, share["run_id"])
    report_dir = settings.ALLURE_REPORTS_DIR / str(run["id"])
    if not allure_report.ensure_static_report(runner.allure_dir(run["id"]), report_dir):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allure report is not available")
    target = _safe_report_path(report_dir, rel_path or "index.html")
    if target is None or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(target)


@public_router.get("/{token}")
def public_share_page(token: str, conn: sqlite3.Connection = Depends(get_db)) -> FileResponse:
    _get_active_share_or_404(conn, token)
    return FileResponse(UI_DIR / "share.html")


@public_router.get("/{token}/data.json")
def public_share_data(token: str, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    share = _get_active_share_or_404(conn, token)
    run = _get_run_or_404(conn, share["run_id"])
    tests = allure_report.parse_results(runner.allure_dir(run["id"]))
    counts = (
        json.loads(run["counts"]) if run["counts"] and run["counts"] != "{}" else allure_report.counts_from_tests(tests)
    )
    public_tests = [
        {
            "name": t["name"],
            "status": t["status"],
            "duration": t["duration"],
            "message": (t["message"][:1500] if t["message"] else None),
        }
        for t in tests
    ]
    report_dir = settings.ALLURE_REPORTS_DIR / str(run["id"])
    allure_ready = allure_report.ensure_static_report(runner.allure_dir(run["id"]), report_dir)
    return {
        "run": _public_run_payload(run),
        "counts": counts,
        "tests": public_tests,
        "allure_available": allure_ready,
        "report_png_url": f"/share/{token}/report.png",
        "allure_url": f"/share/{token}/allure/index.html" if allure_ready else None,
    }


@public_router.get("/{token}/report.png")
def public_share_report_png(token: str, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    share = _get_active_share_or_404(conn, token)
    run = _get_run_or_404(conn, share["run_id"])
    run_payload = _public_run_payload(run)
    results = allure_report.parse_results(runner.allure_dir(run["id"]))
    # counts нужны кольцевой диаграмме — без них build_report_png рисует «нет данных»
    run_payload["counts"] = (
        json.loads(run["counts"]) if run["counts"] and run["counts"] != "{}"
        else allure_report.counts_from_tests(results)
    )
    # history пустая: публичный отчёт — снимок одного прогона, без данных других
    # прогонов того же проекта/стенда (см. заголовок файла).
    png = charts.build_report_png(run_payload, [], results)
    return Response(content=png, media_type="image/png")


@public_router.get("/{token}/allure")
def public_share_allure_index(token: str, conn: sqlite3.Connection = Depends(get_db)) -> FileResponse:
    return _allure_asset_response(conn, token, "index.html")


@public_router.get("/{token}/allure/{path:path}")
def public_share_allure_asset(token: str, path: str, conn: sqlite3.Connection = Depends(get_db)) -> FileResponse:
    return _allure_asset_response(conn, token, path)
