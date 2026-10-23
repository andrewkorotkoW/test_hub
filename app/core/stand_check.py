"""Проверка доступности стенда по URL — кнопка «Проверить» в форме стенда
(ui/stands.html) и рядом с выбором стенда во вкладках «Запуск»/«Данные»
(ui/project.html), где прогон/генерация данных реально открывают соединение
со стендом (см. app/core/runner.py, app/core/datagen.py).

Это только проверка доступности URL (GET с коротким таймаутом), не логина:
test_hub не хранит пароль стенда (stands.login есть, stands.password нет,
см. app/db.py) — пароль живёт в .env/фикстурах тестируемого проекта.
ok=True для любого ответа 2xx/3xx; таймаут, сетевая ошибка и 4xx/5xx — ok=False
с причиной в error, без исключений наружу (вызывающая сторона не должна
ронять страницу из-за недоступного стенда)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 5.0


@dataclass
class StandCheckResult:
    ok: bool
    status_code: int | None
    elapsed_ms: int
    error: str | None = None


def check_url(url: str) -> StandCheckResult:
    if not url or not url.strip():
        # Пустой url у стенда — осознанный выбор (проект сам берёт адрес из своего
        # .env/конфига, см. StandCreate.url), а не ошибка; отдаём отдельную причину,
        # а не пытаемся сходить по пустой строке и получить непонятную сетевую ошибку.
        return StandCheckResult(ok=False, status_code=None, elapsed_ms=0, error="URL не задан")
    start = time.monotonic()
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info("stand_check: %s: таймаут запроса", url)
        return StandCheckResult(ok=False, status_code=None, elapsed_ms=elapsed_ms, error="Таймаут")
    except httpx.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info("stand_check: %s: сеть недоступна (%s)", url, type(exc).__name__)
        return StandCheckResult(ok=False, status_code=None, elapsed_ms=elapsed_ms, error="Сеть недоступна")

    elapsed_ms = int((time.monotonic() - start) * 1000)
    ok = resp.status_code < 400
    return StandCheckResult(
        ok=ok,
        status_code=resp.status_code,
        elapsed_ms=elapsed_ms,
        error=None if ok else f"HTTP {resp.status_code}",
    )
