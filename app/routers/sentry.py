"""REST API поверх app/core/sentry.py — ошибки продукта (Sentry) для QA (см.
миссию docs/missions/2026-09-29_sentry.md). Доступ только роли qa: остальным
Depends(require_roles) сам вернёт 403.

Если Sentry не настроен глобально (app/config.settings) или у стенда не
заполнены sentry_project/sentry_environment, а также при ошибке клиента
(401/403/429/недоступность) — ответ 200 с connected=false и причиной в поле
reason для UI-заглушки, а не 500: отсутствие Sentry не должно ронять страницу
проекта/прогона."""
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import settings
from ..core import sentry as sentry_client
from ..deps import get_db, require_roles
from ..schemas import SentryIssueOut, SentryIssuesResponse

router = APIRouter(prefix="/api", tags=["sentry"])

WINDOW_TAIL = timedelta(minutes=5)


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _get_stand_or_404(conn: sqlite3.Connection, project: str, stand: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM stands WHERE project = ? AND name = ?", (project, stand)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")
    return row


def _get_run_or_404(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return row


def _stand_reason(stand_row: sqlite3.Row) -> str | None:
    """None, если у стенда есть привязка к Sentry-проекту/environment, иначе
    причина для connected=false."""
    if not settings.TH_SENTRY_URL or not settings.TH_SENTRY_TOKEN or not settings.TH_SENTRY_ORG:
        return "Sentry не настроен"
    if not stand_row["sentry_project"] or not stand_row["sentry_environment"]:
        return "У стенда не заполнены Sentry-проект и окружение"
    return None


def _issue_out(issue: sentry_client.SentryIssue, *, is_new: bool | None = None) -> SentryIssueOut:
    return SentryIssueOut(
        id=issue.id,
        title=issue.title,
        culprit=issue.culprit,
        level=issue.level,
        count=issue.count,
        user_count=issue.user_count,
        first_seen=issue.first_seen,
        last_seen=issue.last_seen,
        permalink=issue.permalink,
        is_new=is_new,
    )


def _parse_dt(value: str | None) -> datetime | None:
    """Разбирает ISO-дату (в т.ч. Sentry-формат с суффиксом Z) в naive datetime
    в UTC — чтобы сравнивать с started/finished прогона (naive, см.
    app/core/runner.py::_finalize, datetime.now().isoformat())."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.get("/projects/{name}/stands/{stand}/sentry/issues")
def get_stand_sentry_issues(
    name: str,
    stand: str,
    since: str | None = None,
    until: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> SentryIssuesResponse:
    _get_project_or_404(conn, name)
    stand_row = _get_stand_or_404(conn, name, stand)

    reason = _stand_reason(stand_row)
    if reason:
        return SentryIssuesResponse(connected=False, reason=reason)

    try:
        issues = sentry_client.list_issues(
            stand_row["sentry_project"], stand_row["sentry_environment"], since=since
        )
    except sentry_client.SentryError as exc:
        return SentryIssuesResponse(connected=False, reason=str(exc))

    until_dt = _parse_dt(until)
    if until_dt is not None:
        issues = [i for i in issues if (_parse_dt(i.first_seen) or until_dt) <= until_dt]

    return SentryIssuesResponse(connected=True, issues=[_issue_out(i) for i in issues])


@router.get("/runs/{run_id}/sentry")
def get_run_sentry_issues(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> SentryIssuesResponse:
    run = _get_run_or_404(conn, run_id)

    if not run["stand"]:
        return SentryIssuesResponse(connected=False, reason="У прогона не указан стенд")

    window_start = _parse_dt(run["started"])
    if window_start is None:
        return SentryIssuesResponse(connected=False, reason="Прогон ещё не запущен")

    window_end_base = _parse_dt(run["finished"]) or datetime.now()
    window_end = window_end_base + WINDOW_TAIL

    stand_row = conn.execute(
        "SELECT * FROM stands WHERE project = ? AND name = ?", (run["project"], run["stand"])
    ).fetchone()
    if stand_row is None:
        return SentryIssuesResponse(connected=False, reason="Стенд прогона не найден")

    reason = _stand_reason(stand_row)
    if reason:
        return SentryIssuesResponse(connected=False, reason=reason)

    try:
        issues = sentry_client.list_issues(stand_row["sentry_project"], stand_row["sentry_environment"])
    except sentry_client.SentryError as exc:
        return SentryIssuesResponse(connected=False, reason=str(exc))

    windowed = []
    for issue in issues:
        first_seen = _parse_dt(issue.first_seen)
        last_seen = _parse_dt(issue.last_seen)
        if last_seen is not None and last_seen < window_start:
            continue
        if first_seen is not None and first_seen > window_end:
            continue
        is_new = first_seen is not None and window_start <= first_seen <= window_end
        windowed.append(_issue_out(issue, is_new=is_new))

    return SentryIssuesResponse(connected=True, issues=windowed)
