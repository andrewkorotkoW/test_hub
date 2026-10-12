"""Форматирование ответов бота (отчёты, флаки, xfail, статистика, расписания) —
чистые функции без объектов aiogram, юнит-тестируются напрямую."""
from __future__ import annotations

from ..config import settings

MAX_FAILED_LISTED = 15


MAX_REASON_LEN = 120


MAX_FAILED_LABEL_LEN = 40


MAX_ERROR_TEXT_LEN = 1500


STATUS_RU = {
    "queued": "в очереди",
    "running": "выполняется",
    "passed": "пройден",
    "failed": "провален",
    "cancelled": "отменён",
}


MARKER_BUTTONS = [("Smoke", "smoke"), ("API", "api"), ("UI", "ui"), ("Все", None)]


MARKER_LABELS = dict(MARKER_BUTTONS)


FLAKY_TOP_N = 10


XFAIL_TOP_N = 10


def _stand_label(stand: str | None) -> str:
    return stand if stand is not None else "без стенда"


def _marker_label(marker: str | None) -> str:
    return MARKER_LABELS.get(marker, marker) if marker is not None else "Все"


def format_projects(projects: list[dict]) -> str:
    if not projects:
        return "Проектов пока нет."
    lines = ["Проекты:"]
    for project in projects:
        stands = ", ".join(s["name"] for s in project.get("stands", [])) or "—"
        lines.append(f"• {project['name']} (стенды: {stands})")
    return "\n".join(lines)


def _counts_line(counts: dict) -> str:
    return (
        f"passed: {counts.get('passed', 0)}, failed: {counts.get('failed', 0)}, "
        f"broken: {counts.get('broken', 0)}, skipped: {counts.get('skipped', 0)}"
    )


def format_status(report: dict) -> str:
    status_ru = STATUS_RU.get(report["status"], report["status"])
    lines = [
        f"Прогон #{report['id']} ({report.get('project')}) — {status_ru}",
        _counts_line(report.get("counts") or {}),
    ]
    return "\n".join(lines)


def _bad_tests(report: dict) -> list[dict]:
    return [t for t in report.get("tests", []) if t.get("status") in ("failed", "broken")]


def _short_reason(test: dict) -> str:
    message = (test.get("message") or "").strip()
    if not message:
        return ""
    return message.splitlines()[0][:MAX_REASON_LEN]


def _short_test_label(name: str) -> str:
    """allure fullName — "{dotted.module.path}{.Class}?#{test}" (см. allure_pytest.utils.
    allure_full_name) — короткое имя это часть после "#", как label теста в дереве
    (build_flat_tree), а не полный путь модуля."""
    short = (name or "").rsplit("#", 1)[-1] or "?"
    if len(short) > MAX_FAILED_LABEL_LEN:
        short = short[: MAX_FAILED_LABEL_LEN - 1] + "…"
    return short


def _error_text(test: dict) -> str:
    parts = [p for p in (test.get("message"), test.get("trace")) if p]
    text = "\n\n".join(parts).strip()
    if not text:
        return "Текст ошибки недоступен."
    if len(text) > MAX_ERROR_TEXT_LEN:
        text = text[:MAX_ERROR_TEXT_LEN].rstrip() + "…"
    return text


def format_report(report: dict) -> str:
    status_ru = STATUS_RU.get(report["status"], report["status"])
    duration = report.get("duration")
    duration_str = f"{duration:.1f}с" if isinstance(duration, (int, float)) else "—"
    label = report.get("label")
    # Прогон сборки (см. этап 2 миссии 2026-10-01_coverage_k_and_test_sets.md)
    # называем по имени сборки, а не по (обычно длинному) списку целей.
    title_suffix = f", сборка {label}" if label else ""
    lines = [
        f"Прогон #{report['id']} ({report.get('project')}{title_suffix}) — {status_ru}",
        _counts_line(report.get("counts") or {}),
        f"Длительность: {duration_str}",
    ]
    bad_tests = _bad_tests(report)
    if bad_tests:
        lines.append("Упавшие тесты:")
        shown = bad_tests[:MAX_FAILED_LISTED]
        for t in shown:
            reason = _short_reason(t)
            suffix = f": {reason}" if reason else ""
            lines.append(f"  - {t.get('name')}{suffix}")
        remaining = len(bad_tests) - len(shown)
        if remaining > 0:
            lines.append(f"  …и ещё {remaining}")
    lines.append(f"http://127.0.0.1:{settings.TH_PORT}/project.html?name={report.get('project')}&run={report['id']}")
    return "\n".join(lines)


def format_flaky(project: str, stand: str | None, items: list[dict]) -> str:
    header = f"Нестабильные тесты «{project}»" + (f" / {stand}" if stand else "") + ":"
    top = items[:FLAKY_TOP_N]
    if not top:
        return f"{header}\nПока нет данных (мало прогонов) или все тесты стабильны."
    lines = [header]
    for item in top:
        percent = round(item["score"] * 100)
        short = (item.get("test") or "").rsplit("#", 1)[-1]
        stand_suffix = "" if stand else f", стенд {item.get('stand')}"
        lines.append(f"• {short}: {percent}% ({item.get('fails', 0)}/{item.get('runs', 0)} упал{stand_suffix})")
    return "\n".join(lines)


def format_xfail(project: str, items: list[dict]) -> str:
    header = f"Известные дефекты «{project}»:"
    if not items:
        return f"{header}\nДефектов не найдено."
    top = items[:XFAIL_TOP_N]
    lines = [header]
    for item in top:
        short = (item.get("test") or "").rsplit("#", 1)[-1]
        mark = "можно снять xfail (xpass)" if item.get("state") == "xpass" else "xfail"
        lines.append(f"• {short} [{item.get('stand')}]: {mark}")
    remaining = len(items) - len(top)
    if remaining > 0:
        lines.append(f"…и ещё {remaining}")
    return "\n".join(lines)


STATS_SECTIONS_LIMIT = 15


def format_stats(project: str, stand: str | None, data: dict) -> str:
    """Краткая сводка по разделам для /stats — та же таблица, что и на
    ui/stats.html, но текстом: раздел, тестов, доля passed, средняя длительность,
    флаки, активные xfail (по последнему полному прогону выбранного стенда)."""
    header = f"Статистика «{project}»" + (f" / {stand}" if stand else "") + ":"
    sections = [s for s in data.get("sections", []) if s.get("tests_total")]
    if not sections:
        return f"{header}\nПока нет данных — ни один раздел не прогонялся полностью."
    lines = [header]
    for s in sections[:STATS_SECTIONS_LIMIT]:
        percent = s["passed_percent"]
        percent_text = f"{percent}%" if percent is not None else "—"
        duration_text = f"{s['avg_duration']:.1f}с" if s.get("avg_duration") is not None else "—"
        extra = []
        if s.get("flaky_count"):
            extra.append(f"флаки {s['flaky_count']}")
        if s.get("xfail_count"):
            extra.append(f"xfail {s['xfail_count']}")
        extra_text = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"• {s['section']}: {s['tests_total']} тестов, {percent_text} passed, {duration_text}{extra_text}")
    remaining = len(sections) - STATS_SECTIONS_LIMIT
    if remaining > 0:
        lines.append(f"…и ещё {remaining}")
    empty = data.get("empty_sections") or []
    if empty:
        lines.append(f"Без единого теста: {', '.join(empty)}")
    return "\n".join(lines)


def format_schedules(project: str, items: list[dict]) -> str:
    header = f"Расписания «{project}»:"
    if not items:
        return f"{header}\nРасписаний нет."
    lines = [header]
    for item in items:
        state = "включено" if item.get("enabled") else "выключено"
        stand = _stand_label(item.get("stand"))
        target = "все тесты" if (item.get("target") or "all") == "all" else "выборочно"
        marker = _marker_label(item.get("marker"))
        last_run_id = item.get("last_run_id")
        suffix = f", последний прогон #{last_run_id}" if last_run_id else ""
        lines.append(f"• #{item['id']} {stand} / {marker} / {target} — {item['cron']} ({state}){suffix}")
    return "\n".join(lines)


def _confirm_text(project: str, stand: str | None, marker: str | None, args: list[str]) -> str:
    lines = [f"Запустить {project} / {_stand_label(stand)} / {_marker_label(marker)}?"]
    if args:
        lines.append(f"Аргументы pytest: {' '.join(args)}")
    return "\n".join(lines)


def _manual_confirm_text(stand: str | None, label: str) -> str:
    """Подтверждение запуска на manual_only-стенде (boевой stage) — отдельный
    текст от _confirm_text, т.к. submit_run на таком стенде требует
    confirm_manual=True (см. app/core/runner.py::ManualRunNotConfirmed)."""
    return f"⚠️ Запуск на {_stand_label(stand)}: {label}. Подтвердить?"
