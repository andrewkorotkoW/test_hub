"""Форматы длительностей и дат, общие для серверных текстов (Telegram-бот, PNG-отчёт,
уведомления по расписанию) — те же правила, что у ui/common.js::fmtDuration и
ui/run-report-logic.js::fmtRunDuration, чтобы бот и веб показывали одно и то же
(замечание владельца 22.10.2026: в боте «1381.6с», в вебе «23 мин 2 с»)."""
from __future__ import annotations

from datetime import datetime


def fmt_run_duration(seconds) -> str:
    """Длительность прогона: «3 ч 02 мин», «23 мин 2 с», «45 с», «—»."""
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
        return "—"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} ч {m:02d} мин"
    if m:
        return f"{m} мин {sec} с"
    return f"{sec} с"


def fmt_test_duration(seconds) -> str:
    """Длительность одного теста: «840 мс», «53.5 с», «4:37», «1:00:12», «—»."""
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
        return "—"
    if seconds < 1:
        return f"{round(seconds * 1000)} мс"
    if seconds < 60:
        return f"{seconds:.1f} с"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_dt(value) -> str:
    """«19.10 22:01» из ISO-строки; пустое/кривое значение — «—»."""
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return dt.strftime("%d.%m %H:%M")


def short_test_name(name: str) -> str:
    """Короткое имя теста для подписей: из allure fullName «tests.api.test_x#test_y» —
    «test_x::test_y», из nodeid «tests/api/test_x.py::Cls::test_y» — «test_x::test_y»,
    параметры [..] сохраняются. Как label в дереве/сплите окна прогона."""
    if not name:
        return "—"
    params = ""
    base = name
    if "[" in name and name.endswith("]"):
        base, _, rest = name.partition("[")
        params = "[" + rest
    if "#" in base:
        module, _, test = base.rpartition("#")
        # «tests.mobile.test_card.TestMobileProgramCard#test_x» — класс в конце пути
        # пропускаем, подпись по файлу: test_card::test_x
        segments = [s for s in module.split(".") if s]
        while len(segments) > 1 and segments[-1][:1].isupper():
            segments.pop()
        return f"{segments[-1] if segments else module}::{test}{params}"
    if "::" in base:
        parts = base.split("::")
        file_part = parts[0].rsplit("/", 1)[-1]
        if file_part.endswith(".py"):
            file_part = file_part[:-3]
        return f"{file_part}::{parts[-1]}{params}"
    return base + params


def pass_rate(counts: dict | None) -> int | None:
    """Доля passed среди passed+failed+broken (skipped не в счёт), как
    RunReportLogic.passRate; None, если считать не из чего."""
    c = counts or {}
    denom = sum(int(c.get(k, 0) or 0) for k in ("passed", "failed", "broken"))
    if denom <= 0:
        return None
    return round(100 * int(c.get("passed", 0) or 0) / denom)
