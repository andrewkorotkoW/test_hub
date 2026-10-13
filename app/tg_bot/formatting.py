"""Форматирование ответов бота (отчёты, флаки, xfail, статистика, расписания) —
чистые функции без объектов aiogram, юнит-тестируются напрямую."""
from __future__ import annotations

from ..config import settings
from ..core import failure_causes

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


def _cause_by_full_name(causes: dict | None) -> dict[str, str | None]:
    if not causes:
        return {}
    return {t["full_name"]: t.get("cause") for t in causes.get("tests") or []}


def _bad_tests(report: dict, causes: dict | None = None) -> list[dict]:
    """Упавшие/сломанные тесты прогона. Если известны причины падения (causes —
    ответ GET /runs/{id}/causes, см. docs/missions/2026-10-13_run_compare_and_causes.md),
    список ограничивается code-падениями — стендовые (throttling/session/stand)
    и так видны в сводной строке _causes_line, перечислять их здесь избыточно.
    Без causes (старые вызовы, недоступность API) — прежнее поведение: все failed/broken."""
    bad = [t for t in report.get("tests", []) if t.get("status") in ("failed", "broken")]
    cause_by_name = _cause_by_full_name(causes)
    if not cause_by_name:
        return bad
    return [t for t in bad if cause_by_name.get(t.get("name")) not in failure_causes.INFRA_CAUSES]


def _short_reason(test: dict) -> str:
    """Обёртка над app.core.failure_causes.short_reason — общей логикой для бота
    и GET /runs/{id}/causes (см. docs/missions/2026-10-13_run_compare_and_causes.md)."""
    return failure_causes.short_reason(test.get("message"))


def _short_test_label(name: str) -> str:
    """allure fullName — "{dotted.module.path}{.Class}?#{test}" (см. allure_pytest.utils.
    allure_full_name) — короткое имя это часть после "#", как label теста в дереве
    (build_flat_tree), а не полный путь модуля."""
    short = (name or "").rsplit("#", 1)[-1] or "?"
    if len(short) > MAX_FAILED_LABEL_LEN:
        short = short[: MAX_FAILED_LABEL_LEN - 1] + "…"
    return short


CAUSE_LABELS = {
    "throttling": "троттлинг 429",
    "session": "потеря сессии",
    "stand": "таймаут/не ответил",
}


MAX_CODE_NAMES = 3


_WAVE_COUNT_WORDS = {
    2: "две", 3: "три", 4: "четыре", 5: "пять", 6: "шесть", 7: "семь", 8: "восемь",
    9: "девять", 10: "десять",
}


def _wave_label(count: int) -> str:
    """Русское согласование числительного с «волна» — 2-4/5+ (не считая 11-14,
    волн столько в одном прогоне в принципе не бывает, но правило общее)."""
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "волны"
    return "волн"


def _waves_text(waves: list[dict]) -> str:
    """«две волны, 09:43–09:50 и 10:44–10:47» — пример из миссии; при одной волне
    просто «волна HH:MM–HH:MM» без числительного."""
    spans = [f"{w['start_ts'][11:16]}–{w['end_ts'][11:16]}" for w in waves]
    if len(waves) == 1:
        return f"волна {spans[0]}"
    count_word = _WAVE_COUNT_WORDS.get(len(waves), str(len(waves)))
    return f"{count_word} {_wave_label(len(waves))}, " + " и ".join(spans)


def _causes_line(causes: dict | None) -> str | None:
    """Строка причин падений после _counts_line — только если среди падений есть
    инфраструктурные (throttling/session/stand), см. п.5 миссии
    2026-10-13_run_compare_and_causes.md. causes — ответ GET /runs/{id}/causes."""
    if not causes:
        return None
    summary = causes.get("summary") or {}
    infra_total = sum(summary.get(c, 0) for c in failure_causes.INFRA_CAUSES)
    if not infra_total:
        return None
    total = summary.get("total", 0)

    waves_by_cause: dict[str, list[dict]] = {}
    for wave in causes.get("waves") or []:
        waves_by_cause.setdefault(wave["cause"], []).append(wave)

    parts = []
    for cause in failure_causes.INFRA_CAUSES:
        count = summary.get(cause, 0)
        if not count:
            continue
        waves = waves_by_cause.get(cause)
        suffix = f" ({_waves_text(waves)})" if waves else ""
        parts.append(f"{count} × {CAUSE_LABELS[cause]}{suffix}")

    line = f"Из {total} падений {infra_total} — стенд: {', '.join(parts)}."

    code_count = summary.get("code", 0)
    if code_count:
        code_tests = [
            t for t in causes.get("tests") or []
            if t.get("cause") == "code" and t.get("status") in ("failed", "broken")
        ]
        names = [_short_test_label(t.get("full_name") or "") for t in code_tests]
        shown = ", ".join(names[:MAX_CODE_NAMES])
        remaining = len(names) - MAX_CODE_NAMES
        if remaining > 0:
            shown += f" и ещё {remaining}"
        suffix = f": {shown}" if shown else ""
        line += f" Тест или продукт — {code_count}{suffix}"
    return line


def _compare_line(compare: dict | None) -> str | None:
    """Строка «Сравнение с #N» — п.3 задачи, по ответу GET /runs/{id}/compare."""
    if not compare:
        return None
    base_id = (compare.get("base") or {}).get("id")
    if base_id is None:
        return None
    passed = (compare.get("kpis") or {}).get("passed") or {}
    delta_passed = (passed.get("now") or 0) - (passed.get("was") or 0)
    new_failures = len((compare.get("groups") or {}).get("new_failures") or [])
    return f"Сравнение с #{base_id}: passed {delta_passed:+d}, новых падений {new_failures}"


def _error_text(test: dict) -> str:
    parts = [p for p in (test.get("message"), test.get("trace")) if p]
    text = "\n\n".join(parts).strip()
    if not text:
        return "Текст ошибки недоступен."
    if len(text) > MAX_ERROR_TEXT_LEN:
        text = text[:MAX_ERROR_TEXT_LEN].rstrip() + "…"
    return text


def format_report(report: dict, causes: dict | None = None, compare: dict | None = None) -> str:
    """causes/compare — ответы GET /runs/{id}/causes и GET /runs/{id}/compare
    (см. app/tg_bot/client.py), подтягиваются вызывающей стороной только для
    завершённых прогонов (app/tg_bot/handlers.py); без них — прежнее поведение
    (строка причин и сравнения не добавляются, список упавших — все failed/broken)."""
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
    causes_line = _causes_line(causes)
    if causes_line:
        lines.append(causes_line)
    compare_line = _compare_line(compare)
    if compare_line:
        lines.append(compare_line)
    bad_tests = _bad_tests(report, causes)
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
