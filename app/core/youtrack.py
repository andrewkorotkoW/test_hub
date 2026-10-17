"""Клиент YouTrack REST API — отправка подтверждённых вручную багов комментарием
в один тикет-накопитель (TH_YOUTRACK_ISSUE, см. миссию «Новые дефекты»).

Пишущий клиент (в отличие от app/core/sentry.py, который только читает) —
единственная операция сейчас: POST .../issues/{issue}/comments. Настройки —
app.config.settings (TH_YOUTRACK_URL/TOKEN/ISSUE); без них is_configured()
возвращает False и вкладка «Новые дефекты» показывает заглушку «YouTrack не
подключён», ничего не ломая (тот же приём, что у Sentry).

TH_YOUTRACK_TOKEN никогда не должен попасть в лог или в текст исключения: он
передаётся только в заголовке Authorization конкретного запроса и нигде
больше не форматируется в строку.

Синхронный клиент (httpx.post), как и остальные core-модули (allure_report,
flaky, xfail_registry, sentry) — вызывающая сторона сама уносит вызов в поток
через asyncio.to_thread."""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 10.0


class YouTrackError(Exception):
    """Базовое исключение клиента."""


class YouTrackUnauthorized(YouTrackError):
    """401/403 — неверный/просроченный токен или нет доступа к тикету."""


class YouTrackUnavailable(YouTrackError):
    """YouTrack не настроен, сеть недоступна, таймаут или иная ошибка запроса."""


def is_configured() -> bool:
    return bool(settings.TH_YOUTRACK_URL and settings.TH_YOUTRACK_TOKEN and settings.TH_YOUTRACK_ISSUE)


def issue_url() -> str:
    """Ссылка на тикет-накопитель для UI (кнопка «Открыть в YouTrack»)."""
    return f"{settings.TH_YOUTRACK_URL}/issue/{settings.TH_YOUTRACK_ISSUE}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.TH_YOUTRACK_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _raise_for_status(resp: httpx.Response, action: str) -> None:
    if resp.status_code in (401, 403):
        logger.warning("youtrack: %s: доступ запрещён (HTTP %s)", action, resp.status_code)
        raise YouTrackUnauthorized("YouTrack: неверный или просроченный токен либо нет доступа к тикету")
    if resp.status_code >= 400:
        logger.warning("youtrack: %s: HTTP %s", action, resp.status_code)
        raise YouTrackUnavailable(f"YouTrack: ошибка запроса (HTTP {resp.status_code})")


def post_comment(text: str) -> dict:
    """Добавляет комментарий в TH_YOUTRACK_ISSUE, возвращает {id, url} — url
    собран вручную (YouTrack REST не отдаёт прямую ссылку на комментарий),
    ведёт на сам тикет (якорь на конкретный комментарий открывается оттуда)."""
    if not is_configured():
        raise YouTrackUnavailable("YouTrack не настроен (TH_YOUTRACK_URL/TOKEN/ISSUE)")
    try:
        resp = httpx.post(
            f"{settings.TH_YOUTRACK_URL}/api/issues/{settings.TH_YOUTRACK_ISSUE}/comments",
            params={"fields": "id"},
            headers=_headers(),
            json={"text": text},
            timeout=TIMEOUT,
        )
    except httpx.RequestError as exc:
        logger.warning("youtrack: post_comment: сетевая ошибка: %s", exc)
        raise YouTrackUnavailable(f"YouTrack: сетевая ошибка ({exc})") from exc

    _raise_for_status(resp, "post_comment")
    data = resp.json()
    comment_id = data.get("id", "")
    return {"id": comment_id, "url": issue_url()}
