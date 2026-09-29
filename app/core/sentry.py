"""Клиент Sentry Web API — блок ошибок продукта для QA (см. миссию
docs/missions/2026-09-29_sentry.md). Только чтение: GET issues/ и GET
events/latest/. Настройки — app.config.settings (TH_SENTRY_URL/TOKEN/ORG),
привязка стенда к Sentry-проекту/environment — stands.sentry_project/
sentry_environment (см. app/routers/projects.py).

Синхронный клиент (httpx.get), как и остальные core-модули (allure_report,
flaky, xfail_registry) — вызывающая сторона сама уносит вызов в поток через
asyncio.to_thread (см. app/core/runner.py::_finalize для образца), явного
async тут не требуется.

TH_SENTRY_TOKEN никогда не должен попасть в лог или в текст исключения: он
передаётся только в заголовке Authorization конкретного запроса и нигде
больше не форматируется в строку."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 5.0
CACHE_TTL = 60.0


class SentryError(Exception):
    """Базовое исключение клиента."""


class SentryUnauthorized(SentryError):
    """401/403 — неверный/просроченный токен или нет доступа к проекту."""


class SentryRateLimited(SentryError):
    """429 — превышен лимит запросов к Sentry."""


class SentryUnavailable(SentryError):
    """Sentry не настроен, сеть недоступна, таймаут или иная ошибка запроса."""


@dataclass
class SentryIssue:
    id: str
    title: str
    culprit: str | None
    level: str
    count: int
    user_count: int
    first_seen: str | None
    last_seen: str | None
    permalink: str | None


# Кэш ответов list_issues на CACHE_TTL секунд в памяти процесса — ключ учитывает
# org/project/environment/query целиком, чтобы разные фильтры не смешивались.
_cache: dict[tuple[str, str, str, str], tuple[float, list[SentryIssue]]] = {}


def is_configured() -> bool:
    return bool(settings.TH_SENTRY_URL and settings.TH_SENTRY_TOKEN and settings.TH_SENTRY_ORG)


def clear_cache() -> None:
    """Сбрасывает кэш list_issues — используется тестами; в остальном кэш живёт
    CACHE_TTL секунд и обходится параметром use_cache=False."""
    _cache.clear()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.TH_SENTRY_TOKEN}"}


def _raise_for_status(resp: httpx.Response, action: str) -> None:
    if resp.status_code in (401, 403):
        logger.warning("sentry: %s: доступ запрещён (HTTP %s)", action, resp.status_code)
        raise SentryUnauthorized("Sentry: неверный или просроченный токен либо нет доступа к проекту")
    if resp.status_code == 429:
        logger.warning("sentry: %s: превышен лимит запросов (429)", action)
        raise SentryRateLimited("Sentry: превышен лимит запросов, попробуйте позже")
    if resp.status_code >= 400:
        logger.warning("sentry: %s: HTTP %s", action, resp.status_code)
        raise SentryUnavailable(f"Sentry: ошибка запроса (HTTP {resp.status_code})")


def _issue_from_raw(raw: dict[str, Any]) -> SentryIssue:
    metadata = raw.get("metadata") or {}
    return SentryIssue(
        id=str(raw.get("id", "")),
        title=raw.get("title") or metadata.get("value") or "",
        culprit=raw.get("culprit"),
        level=raw.get("level") or "error",
        count=int(raw.get("count") or 0),
        user_count=int(raw.get("userCount") or 0),
        first_seen=raw.get("firstSeen"),
        last_seen=raw.get("lastSeen"),
        permalink=raw.get("permalink"),
    )


def list_issues(
    project: str,
    environment: str,
    since: str | None = None,
    *,
    use_cache: bool = True,
) -> list[SentryIssue]:
    """issues Sentry-проекта `project` для окружения `environment`. `since`,
    если задан, добавляется в query как `firstSeen:>{since}` (ISO-строка или
    относительное значение вроде "-24h" — как принимает сам Sentry).

    Поднимает SentryUnauthorized/SentryRateLimited/SentryUnavailable вместо
    возврата пустого списка — так роутер может превратить ошибку в понятную
    подпись для UI, а не молча показать "ошибок нет"."""
    if not is_configured():
        raise SentryUnavailable("Sentry не настроен")

    query = f"environment:{environment}"
    if since:
        query += f" firstSeen:>{since}"

    cache_key = (settings.TH_SENTRY_ORG, project, environment, query)
    now = time.monotonic()
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]

    url = f"{settings.TH_SENTRY_URL.rstrip('/')}/api/0/projects/{settings.TH_SENTRY_ORG}/{project}/issues/"
    try:
        resp = httpx.get(url, headers=_headers(), params={"query": query}, timeout=TIMEOUT)
    except httpx.TimeoutException:
        logger.warning("sentry: list_issues(%s/%s): таймаут запроса", project, environment)
        raise SentryUnavailable("Sentry не отвечает (таймаут)") from None
    except httpx.HTTPError as exc:
        logger.warning("sentry: list_issues(%s/%s): сеть недоступна (%s)", project, environment, type(exc).__name__)
        raise SentryUnavailable("Sentry недоступен") from None

    _raise_for_status(resp, f"list_issues({project}/{environment})")

    issues = [_issue_from_raw(raw) for raw in resp.json()]
    _cache[cache_key] = (now + CACHE_TTL, issues)
    return issues


def latest_event(issue_id: str) -> dict[str, Any]:
    """Последнее событие issue (стектрейс и подобные детали) — для карточки с
    подробностями, если понадобится в UI. Без кэша: вызывается точечно, по
    клику на конкретный issue, а не в списках."""
    if not is_configured():
        raise SentryUnavailable("Sentry не настроен")

    url = f"{settings.TH_SENTRY_URL.rstrip('/')}/api/0/issues/{issue_id}/events/latest/"
    try:
        resp = httpx.get(url, headers=_headers(), timeout=TIMEOUT)
    except httpx.TimeoutException:
        logger.warning("sentry: latest_event(%s): таймаут запроса", issue_id)
        raise SentryUnavailable("Sentry не отвечает (таймаут)") from None
    except httpx.HTTPError as exc:
        logger.warning("sentry: latest_event(%s): сеть недоступна (%s)", issue_id, type(exc).__name__)
        raise SentryUnavailable("Sentry недоступен") from None

    _raise_for_status(resp, f"latest_event({issue_id})")
    return resp.json()
