"""Ночные/регулярные прогоны по расписанию (таблица schedules, app.db.SCHEMA).

Свой парсер cron-строки формата "мин час * * дни" (без croniter — задача явно
просит обойтись без внешней зависимости, если можно, а формат ограничен ровно
двумя переменными полями + днями недели, так что можно). Планировщик
(scheduler_loop) — asyncio-задача, запускаемая/отменяемая в app/main.py::lifespan;
раз в минуту проверяет schedules с enabled=1 и next_run_at <= now, вызывает
runner.submit_run от сервисной учётки (settings.TH_TG_SERVICE_LOGIN) и
пересчитывает next_run_at.

Уведомление по завершении прогона идёт через runner.register_finalize_hook
(on_run_finished ниже) — раннер не импортирует этот модуль (см. комментарий в
app/core/runner.py), хук подписывается снаружи, в app/main.py::lifespan, где
видны обе стороны. Фото-отчёт переиспользует app.tg_bot._send_report_png и
app.core.charts, как и обычный просмотр отчёта в боте/UI."""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import settings
from ..db import get_connection
from . import allure_report, charts, runner

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60.0
CRON_FIELDS = 5


# ------------------------------------------------------------------ cron-парсер
def _parse_field(spec: str, lo: int, hi: int) -> set[int] | None:
    """"*" -> None (любое значение); "5", "1,3,5" или "1-5" (и их комбинации через
    запятую) -> множество разрешённых целых в пределах [lo, hi]."""
    if spec == "*":
        return None
    values: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(part)
        if start > end or start < lo or end > hi:
            raise ValueError(f"некорректное поле cron {spec!r}: значение вне диапазона {lo}-{hi}")
        values.update(range(start, end + 1))
    return values


def parse_cron(cron: str) -> tuple[set[int] | None, set[int] | None, set[int] | None]:
    """"мин час * * дни" -> (минуты, часы, дни-недели). День месяца и месяц (3-е и
    4-е поля) в этом простом планировщике поддерживаются только как "*" — ровно
    формат, который просит задача ('0 3 * * 1-5'). Дни недели — как в POSIX cron:
    0 или 7 = воскресенье, 1 = понедельник, ..., 6 = суббота."""
    parts = cron.split()
    if len(parts) != CRON_FIELDS:
        raise ValueError(f"cron должен состоять из {CRON_FIELDS} полей 'мин час * * дни', получено: {cron!r}")
    minute_f, hour_f, dom_f, month_f, dow_f = parts
    if dom_f != "*" or month_f != "*":
        raise ValueError("день месяца и месяц должны быть '*' — поддерживаются только минуты/часы/дни недели")
    minutes = _parse_field(minute_f, 0, 59)
    hours = _parse_field(hour_f, 0, 23)
    dows = _parse_field(dow_f, 0, 7)
    if dows is not None:
        dows = {d % 7 for d in dows}  # 7 (воскресенье) -> 0, тот же токен
    return minutes, hours, dows


def next_run_at(cron: str, after: datetime) -> datetime:
    """Ближайший момент времени строго после `after`, удовлетворяющий cron-строке.
    Перебор по минутам (без внешних зависимостей) в пределах года — для реального
    cron вида 'мин час * * дни' совпадение находится за секунды или доли секунды."""
    minutes, hours, dows = parse_cron(cron)
    candidate = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    horizon = candidate + timedelta(days=366)
    while candidate < horizon:
        if (minutes is None or candidate.minute in minutes) and (hours is None or candidate.hour in hours):
            cron_dow = (candidate.weekday() + 1) % 7  # Python: пн=0..вс=6 -> cron: вс=0..сб=6
            if dows is None or cron_dow in dows:
                return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(f"не удалось найти следующее время запуска для cron {cron!r} в пределах года")


# ------------------------------------------------------------------ CRUD (используется app/routers/schedules.py)
def row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "project": row["project"],
        "stand": row["stand"],
        "target": row["target"],
        "marker": row["marker"],
        "cron": row["cron"],
        "enabled": bool(row["enabled"]),
        "notify_chat_ids": json.loads(row["notify_chat_ids"] or "[]"),
        "last_run_id": row["last_run_id"],
        "next_run_at": row["next_run_at"],
    }


def list_schedules(conn: sqlite3.Connection, project: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM schedules WHERE project = ? ORDER BY id", (project,)).fetchall()


def get_schedule(conn: sqlite3.Connection, project: str, schedule_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM schedules WHERE project = ? AND id = ?", (project, schedule_id)
    ).fetchone()


def create_schedule(
    conn: sqlite3.Connection,
    project: str,
    stand: str | None,
    target: str,
    marker: str | None,
    cron: str,
    enabled: bool,
    notify_chat_ids: list[int],
) -> sqlite3.Row:
    next_at = next_run_at(cron, datetime.now()).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO schedules (project, stand, target, marker, cron, enabled, notify_chat_ids, next_run_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project, stand, target, marker, cron, int(enabled), json.dumps(notify_chat_ids), next_at),
    )
    conn.commit()
    return get_schedule(conn, project, cur.lastrowid)


def update_schedule(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    stand: str | None,
    target: str,
    marker: str | None,
    cron: str,
    enabled: bool,
    notify_chat_ids: list[int],
) -> sqlite3.Row:
    """Полная замена изменяемых полей (вызывающий код в app/routers/schedules.py уже
    смёржил PUT-тело с текущей строкой — `None` в теле запроса значит "не менять",
    как и для ProjectUpdate/StandUpdate). next_run_at пересчитывается только если
    cron изменился или расписание только что включили (enabled 0 -> 1) — иначе
    уже посчитанное значение не трогаем, чтобы не сдвигать ближайший запуск."""
    recompute = cron != row["cron"] or (enabled and not row["enabled"])
    next_at = next_run_at(cron, datetime.now()).isoformat(timespec="seconds") if recompute else row["next_run_at"]
    conn.execute(
        "UPDATE schedules SET stand = ?, target = ?, marker = ?, cron = ?, enabled = ?, "
        "notify_chat_ids = ?, next_run_at = ? WHERE id = ?",
        (stand, target, marker, cron, int(enabled), json.dumps(notify_chat_ids), next_at, row["id"]),
    )
    conn.commit()
    return get_schedule(conn, row["project"], row["id"])


def delete_schedule(conn: sqlite3.Connection, schedule_id: int) -> None:
    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    conn.commit()


# ------------------------------------------------------------------ запуск прогонов (планировщик и «запустить сейчас»)
# run_id -> (schedule_id, run_id предыдущего прогона этого расписания, для compare_runs).
_pending_runs: dict[int, tuple[int, int | None]] = {}


async def _trigger(conn: sqlite3.Connection, row: sqlite3.Row, requested_by: str, *, advance: bool) -> int:
    run_id = await runner.submit_run(row["project"], row["stand"], row["target"] or "all", requested_by, row["marker"])
    _pending_runs[run_id] = (row["id"], row["last_run_id"])
    if advance:
        next_at = next_run_at(row["cron"], datetime.now()).isoformat(timespec="seconds")
        conn.execute("UPDATE schedules SET last_run_id = ?, next_run_at = ? WHERE id = ?", (run_id, next_at, row["id"]))
    else:
        conn.execute("UPDATE schedules SET last_run_id = ? WHERE id = ?", (run_id, row["id"]))
    conn.commit()
    return run_id


async def run_now(conn: sqlite3.Connection, row: sqlite3.Row, requested_by: str) -> int:
    return await _trigger(conn, row, requested_by, advance=False)


async def _tick() -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        due = conn.execute(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (now,),
        ).fetchall()
        for row in due:
            try:
                await _trigger(conn, row, settings.TH_TG_SERVICE_LOGIN, advance=True)
            except Exception:
                logger.exception("schedule: не удалось запустить прогон по расписанию #%s", row["id"])
    finally:
        conn.close()


async def scheduler_loop(poll_interval: float = POLL_INTERVAL_SECONDS) -> None:
    """Запускается/отменяется в app/main.py::lifespan (по аналогии с polling-задачей
    tg-бота)."""
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("schedule: ошибка в цикле планировщика")
        await asyncio.sleep(poll_interval)


# ------------------------------------------------------------------ сравнение двух прогонов
def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


_FAIL_STATUSES = {"failed", "broken"}


def compare_runs(prev_run_id: int | None, cur_run_id: int) -> dict:
    """Сравнивает статусы тестов (allure fullName) между двумя прогонами одного
    расписания: какие тесты стали падать (newly_failed) и какие починились
    (newly_fixed). `flaky` — TODO: пока не смотрит на историю нескольких прогонов
    (app.core.flaky.flaky_stats), только на два конкретных прогона, поэтому
    отдельно не отличает флаки от настоящей регрессии/починки; отдаётся пустым
    списком, это не блокер задачи."""
    cur_status = {t["name"]: t["status"] for t in allure_report.parse_results(_allure_dir(cur_run_id))}
    prev_status = (
        {t["name"]: t["status"] for t in allure_report.parse_results(_allure_dir(prev_run_id))}
        if prev_run_id is not None
        else {}
    )

    newly_failed = sorted(
        name
        for name, status in cur_status.items()
        if status in _FAIL_STATUSES and prev_status.get(name) not in _FAIL_STATUSES
    )
    newly_fixed = sorted(
        name
        for name, status in prev_status.items()
        if status in _FAIL_STATUSES and name in cur_status and cur_status[name] not in _FAIL_STATUSES
    )
    return {"newly_failed": newly_failed, "newly_fixed": newly_fixed, "flaky": []}


def _xpass_count(project: str, stand: str | None) -> int:
    if not stand:
        return 0
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM xfail_registry WHERE project = ? AND stand = ? AND state = 'xpass'",
            (project, stand),
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()


# ------------------------------------------------------------------ уведомление в Telegram по завершении прогона
_bot: "Bot | None" = None


def set_bot(bot: "Bot | None") -> None:
    """Вызывается из app/main.py::lifespan с уже собранным ботом (или None, если
    TH_TG_BOT_TOKEN не задан — тогда уведомления просто не отправляются, сами
    прогоны по расписанию продолжают выполняться)."""
    global _bot
    _bot = bot


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
        "counts": json.loads(row["counts"]) if row["counts"] else {},
    }


def _run_history(conn: sqlite3.Connection, project: str, stand: str | None, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE project = ? AND stand IS ? ORDER BY id DESC LIMIT ?",
        (project, stand, limit),
    ).fetchall()
    return [_run_payload(r) for r in rows]


def _short_name(full_name: str) -> str:
    return (full_name or "").rsplit("#", 1)[-1]


def _notification_caption(run_row: sqlite3.Row, comparison: dict, xpass_count: int) -> str:
    from .. import tg_bot  # ленивый импорт: aiogram нужен только когда реально шлём сообщение

    report = dict(_run_payload(run_row))
    report["tests"] = allure_report.parse_results(_allure_dir(run_row["id"]))
    lines = [tg_bot.format_report(report)]

    newly_failed = comparison["newly_failed"]
    if newly_failed:
        shown = ", ".join(_short_name(n) for n in newly_failed[:10])
        suffix = f" (и ещё {len(newly_failed) - 10})" if len(newly_failed) > 10 else ""
        lines.append(f"Новые падения: {shown}{suffix}")
    newly_fixed = comparison["newly_fixed"]
    if newly_fixed:
        shown = ", ".join(_short_name(n) for n in newly_fixed[:10])
        suffix = f" (и ещё {len(newly_fixed) - 10})" if len(newly_fixed) > 10 else ""
        lines.append(f"Починились: {shown}{suffix}")
    if xpass_count:
        lines.append(f"Можно снять xfail (xpass): {xpass_count}")
    return "\n".join(lines)


async def on_run_finished(run_id: int) -> None:
    """Хук app.core.runner._finalize (см. register_finalize_hook в app/main.py) —
    если run_id был запущен этим модулем (планировщиком или кнопкой «Запустить
    сейчас»), шлёт фото-отчёт + сравнение с предыдущим прогоном этого расписания
    в notify_chat_ids. Для остальных run_id (обычные ручные прогоны из UI/бота) —
    no-op."""
    pending = _pending_runs.pop(run_id, None)
    if pending is None:
        return
    schedule_id, prev_run_id = pending

    conn = get_connection()
    try:
        schedule_row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if schedule_row is None or run_row is None:
            return
        chat_ids = json.loads(schedule_row["notify_chat_ids"] or "[]")
        if not chat_ids or _bot is None:
            return
        history = _run_history(conn, schedule_row["project"], schedule_row["stand"], 10)
    finally:
        conn.close()

    comparison = compare_runs(prev_run_id, run_id)
    xpass_count = _xpass_count(schedule_row["project"], schedule_row["stand"])
    caption = _notification_caption(run_row, comparison, xpass_count)
    results = allure_report.parse_results(_allure_dir(run_id))
    png = charts.build_report_png(_run_payload(run_row), history, results)

    from .. import tg_bot  # тот же ленивый импорт, что и в _notification_caption

    for chat_id in chat_ids:
        try:
            await tg_bot._send_report_png(
                functools.partial(_bot.send_photo, chat_id),
                functools.partial(_bot.send_message, chat_id),
                run_id,
                png,
                caption,
            )
        except Exception:
            logger.exception("schedule: не удалось отправить уведомление о прогоне #%s в чат %s", run_id, chat_id)
