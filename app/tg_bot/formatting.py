"""Форматирование ответов бота (отчёты, флаки, xfail, статистика, расписания) —
чистые функции без объектов aiogram, юнит-тестируются напрямую."""
from __future__ import annotations

from ..config import settings
from ..core import allure_report, failure_causes
from ..core.fmt import fmt_dt, fmt_run_duration, fmt_test_duration, pass_rate, short_test_name

MAX_FAILED_LISTED = 15


# В подписи к фото на телефоне длинный текст ошибки занимал полэкрана (22.10.2026) —
# в боте причина короче, чем в GET /runs/{id}/causes (failure_causes.MAX_REASON_LEN)
MAX_REASON_LEN = 80


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
    line = (
        f"passed: {counts.get('passed', 0)}, failed: {counts.get('failed', 0)}, "
        f"broken: {counts.get('broken', 0)}, skipped: {counts.get('skipped', 0)}"
    )
    rate = pass_rate(counts)
    if rate is not None:
        line += f" · pass rate {rate} %"
    return line


def _run_title(report: dict) -> str:
    """«Прогон #96 (vshgu, develop, сборка X) — провален»: стенд в скобках, как в
    окне прогона; прогон сборки называем по имени сборки (см. этап 2 миссии
    2026-10-01_coverage_k_and_test_sets.md), а не по списку целей."""
    status_ru = STATUS_RU.get(report["status"], report["status"])
    parts = [str(report.get("project"))]
    if report.get("stand"):
        parts.append(str(report["stand"]))
    if report.get("label"):
        parts.append(f"сборка {report['label']}")
    return f"Прогон #{report['id']} ({', '.join(parts)}) — {status_ru}"


def run_url(report: dict) -> str:
    """Ссылка на окно прогона по TH_PUBLIC_URL (адрес, видимый снаружи), а не по
    127.0.0.1:TH_PORT — с телефона такой адрес не открывался (22.10.2026)."""
    return f"{settings.TH_PUBLIC_URL}/project.html?name={report.get('project')}&run={report['id']}"


def format_status(report: dict) -> str:
    lines = [
        _run_title(report),
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
    # final_attempts: при реране (failed → passed) тест не упавший, а при двух
    # падениях — не два теста (22.10.2026, прогон #96: 7 строк на 5 тестов).
    bad = [
        t for t in allure_report.final_attempts(report.get("tests") or [], report.get("repeat") or 1)
        if t.get("status") in ("failed", "broken")
    ]
    cause_by_name = _cause_by_full_name(causes)
    if not cause_by_name:
        return bad
    return [t for t in bad if cause_by_name.get(t.get("name")) not in failure_causes.INFRA_CAUSES]


def _short_reason(test: dict) -> str:
    """Обёртка над app.core.failure_causes.short_reason — общей логикой для бота
    и GET /runs/{id}/causes (см. docs/missions/2026-10-13_run_compare_and_causes.md)."""
    reason = failure_causes.short_reason(test.get("message"))
    return reason if len(reason) <= MAX_REASON_LEN else reason[: MAX_REASON_LEN - 1].rstrip() + "…"


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
    lines = [
        _run_title(report),
        _counts_line(report.get("counts") or {}),
        f"Длительность: {fmt_run_duration(report.get('duration'))}",
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
            # nodeid есть в ответе GET /runs/{id}/report (окно прогона); у старых
            # вызовов и уведомлений — только allure fullName, short_test_name понимает оба
            lines.append(f"  - {short_test_name(t.get('nodeid') or t.get('name') or '')}{suffix}")
        remaining = len(bad_tests) - len(shown)
        if remaining > 0:
            lines.append(f"  …и ещё {remaining}")
    lines.append(run_url(report))
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
        duration_text = fmt_test_duration(s.get("avg_duration"))
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


# ------------------------------------------------------------------ карточка проекта и список прогонов (22.10.2026)
RUN_ICONS = {"passed": "✅", "failed": "❌", "cancelled": "⏹", "running": "▶️", "queued": "⏳"}
RUNS_IN_CARD = 3
RUNS_LIST_N = 8


def _run_counts_short(counts: dict | None) -> str:
    c = counts or {}
    return "/".join(str(c.get(k, 0) or 0) for k in ("passed", "failed", "broken", "skipped"))


def run_line(run: dict) -> str:
    """«#96 ❌ 19.10 22:01 · без стенда · Мобильный (Pixel 7) · 23 мин 2 с · 4/1/0/0»."""
    icon = RUN_ICONS.get(run.get("status"), "•")
    what = run.get("label") or _marker_label(run.get("marker"))
    parts = [f"#{run.get('id')} {icon} {fmt_dt(run.get('started'))}", _stand_label(run.get("stand")), str(what)]
    if run.get("status") in ("passed", "failed", "cancelled"):
        parts.append(fmt_run_duration(run.get("duration")))
        parts.append(_run_counts_short(run.get("counts")))
    else:
        parts.append(STATUS_RU.get(run.get("status"), str(run.get("status"))))
    return " · ".join(parts)


def format_project_card(project: str, stands: list[dict], runs: list[dict]) -> str:
    stand_names = [f"{s['name']} 🔒" if s.get("manual_only") else s["name"] for s in stands]
    lines = [f"Проект: {project}", f"Стенды: {', '.join(stand_names) or '—'}"]
    if runs:
        lines.append("Последние прогоны:")
        lines.extend(f"• {run_line(r)}" for r in runs[:RUNS_IN_CARD])
    else:
        lines.append("Прогонов ещё нет.")
    lines.append("Счётчики: passed/failed/broken/skipped.")
    return "\n".join(lines)


def format_runs_list(project: str, runs: list[dict]) -> str:
    if not runs:
        return f"У проекта «{project}» ещё нет прогонов."
    lines = [f"Прогоны «{project}» (последние {min(len(runs), RUNS_LIST_N)}):"]
    lines.extend(f"• {run_line(r)}" for r in runs[:RUNS_LIST_N])
    lines.append("Нажмите на прогон, чтобы открыть его.")
    return "\n".join(lines)


def run_button_label(run: dict) -> str:
    icon = RUN_ICONS.get(run.get("status"), "•")
    what = run.get("label") or _marker_label(run.get("marker"))
    return f"#{run.get('id')} {icon} {fmt_dt(run.get('started'))} · {_stand_label(run.get('stand'))} · {what}"[:60]


# ------------------------------------------------------------------ экран «Причины» и полное сравнение
CAUSE_TITLES = {
    "throttling": "троттлинг 429",
    "session": "потеря сессии",
    "stand": "стенд не ответил",
    "code": "тест или продукт",
}
CAUSES_TESTS_N = 10
COMPARE_GROUP_N = 8


def format_causes(run_id: int, causes: dict | None) -> str:
    """Экран «Причины» прогона — как вкладка окна прогона: сводка по причинам,
    волны инфраструктурных падений, code-падения со своей короткой причиной."""
    summary = (causes or {}).get("summary") or {}
    total = summary.get("total", 0)
    if not total:
        return f"Прогон #{run_id}: падений нет — причины классифицировать нечего."
    lines = [f"Причины падений прогона #{run_id} (всего {total}):"]
    for cause in ("throttling", "session", "stand", "code"):
        count = summary.get(cause, 0)
        if count:
            lines.append(f"• {CAUSE_TITLES[cause]}: {count}")
    waves = (causes or {}).get("waves") or []
    if waves:
        lines.append("Волны по стенду:")
        for wave in waves:
            lines.append(
                f"  {CAUSE_LABELS.get(wave.get('cause'), wave.get('cause'))}: "
                f"{str(wave.get('start_ts') or '')[11:16]}–{str(wave.get('end_ts') or '')[11:16]}, "
                f"{wave.get('count', '?')} падений"
            )
    code_tests = [
        t for t in (causes or {}).get("tests") or []
        if t.get("cause") == "code" and t.get("status") in ("failed", "broken")
    ]
    if code_tests:
        lines.append("Тест или продукт:")
        for t in code_tests[:CAUSES_TESTS_N]:
            reason = t.get("short_reason") or ""
            if len(reason) > MAX_REASON_LEN:
                reason = reason[: MAX_REASON_LEN - 1].rstrip() + "…"
            suffix = f": {reason}" if reason else ""
            lines.append(f"  - {short_test_name(t.get('nodeid') or t.get('full_name') or '')}{suffix}")
        remaining = len(code_tests) - CAUSES_TESTS_N
        if remaining > 0:
            lines.append(f"  …и ещё {remaining}")
    return "\n".join(lines)


def _delta(now, was) -> str:
    try:
        return f"{int(now or 0) - int(was or 0):+d}"
    except (TypeError, ValueError):
        return "—"


def format_compare(run_id: int, compare: dict | None) -> str:
    """Полное сравнение с базовым прогоном — вкладка «Сравнить с…» текстом:
    KPI (passed/failed/skipped/длительность) и группы новых падений, починившихся,
    всё ещё падающих, изменивших скорость."""
    base = (compare or {}).get("base") or {}
    if not base.get("id"):
        return f"Прогон #{run_id}: нет базового прогона для сравнения."
    kpis = (compare or {}).get("kpis") or {}
    groups = (compare or {}).get("groups") or {}
    lines = [f"Сравнение #{run_id} с #{base['id']} ({fmt_dt(base.get('started'))}):"]
    for key, title in (("passed", "passed"), ("failed", "failed"), ("skipped", "skipped")):
        k = kpis.get(key) or {}
        lines.append(f"• {title}: {k.get('now', 0)} (было {k.get('was', 0)}, {_delta(k.get('now'), k.get('was'))})")
    dur = kpis.get("duration") or {}
    lines.append(f"• длительность: {fmt_run_duration(dur.get('now'))} (было {fmt_run_duration(dur.get('was'))})")
    titles = (
        ("new_failures", "Новые падения"),
        ("fixed", "Починились"),
        ("still_failing", "Всё ещё падают"),
        ("speed", "Изменили скорость"),
    )
    for key, title in titles:
        items = groups.get(key) or []
        if not items:
            continue
        lines.append(f"{title} ({len(items)}):")
        for item in items[:COMPARE_GROUP_N]:
            name = short_test_name(item.get("nodeid") or item.get("full_name") or "")
            if key == "speed":
                extra = f" {fmt_test_duration(item.get('prev_duration'))} → {fmt_test_duration(item.get('duration'))}"
            elif key == "fixed" and item.get("was_xfail"):
                extra = " (был xfail)"
            else:
                reason = item.get("short_reason") or ""
                extra = f": {reason[:MAX_REASON_LEN]}" if reason and key != "fixed" else ""
            lines.append(f"  - {name}{extra}")
        if len(items) > COMPARE_GROUP_N:
            lines.append(f"  …и ещё {len(items) - COMPARE_GROUP_N}")
    if not any(groups.get(k) for k, _ in titles):
        lines.append("Изменений по тестам нет.")
    return "\n".join(lines)


# ------------------------------------------------------------------ «Данные» (вкладка «Данные» проекта в боте)
DATA_STATUS_RU = {
    "queued": "в очереди",
    "running": "создаётся",
    "done": "создано",
    "failed": "ошибка",
    "deleting": "удаляется",
    "deleted": "удалено",
    "delete_failed": "ошибка удаления",
}
DATA_ACTIVE_STATUSES = ("queued", "running", "deleting")
DATA_DELETABLE_STATUSES = ("done", "failed", "delete_failed")
DATA_BATCHES_N = 5
CLEANUP_SCENARIO = "cleanup_after_run"


def data_status_label(status: str | None) -> str:
    return DATA_STATUS_RU.get(status or "", status or "—")


def scenario_title(scenario: str, scenarios: list[dict] | None = None) -> str:
    if scenario == CLEANUP_SCENARIO:
        return "очистка после прогона"
    for s in scenarios or []:
        if s.get("name") == scenario:
            return s.get("title") or scenario
    return scenario


def batch_line(batch: dict, scenarios: list[dict] | None = None) -> str:
    """«#12 создано · Пользователи · develop · 19.10 22:01 · 3 сущностей»."""
    parts = [
        f"#{batch.get('id')} {data_status_label(batch.get('status'))}",
        scenario_title(batch.get("scenario") or "", scenarios),
        _stand_label(batch.get("stand")),
        fmt_dt(batch.get("created_at")),
    ]
    if batch.get("run_id"):
        parts.append(f"прогон #{batch['run_id']}")
    created = batch.get("created_total") or 0
    if created:
        parts.append(f"{created} сущностей")
    return " · ".join(parts)


def format_data_batches(project: str, supported: bool, batches: list[dict], scenarios: list[dict] | None = None) -> str:
    if not supported:
        return f"Данные «{project}»: в проекте нет генератора (test_data_generation/generate.py)."
    lines = [f"Данные «{project}»"]
    active = next((b for b in batches if b.get("status") in DATA_ACTIVE_STATUSES), None)
    if active:
        lines.append(f"⏳ Партия #{active['id']} ещё выполняется ({data_status_label(active.get('status'))}).")
    if batches:
        lines.append(f"Последние партии ({min(len(batches), DATA_BATCHES_N)}):")
        lines.extend(f"• {batch_line(b, scenarios)}" for b in batches[:DATA_BATCHES_N])
    else:
        lines.append("Партий данных ещё не создавалось.")
    lines.append("«Создать данные» — выбрать сценарий и стенд; нажмите на партию, чтобы открыть её.")
    return "\n".join(lines)


def format_data_batch(batch: dict, scenarios: list[dict] | None = None) -> str:
    lines = [f"Партия #{batch.get('id')} — {data_status_label(batch.get('status'))}"]
    lines.append(f"Сценарий: {scenario_title(batch.get('scenario') or '', scenarios)}")
    lines.append(f"Стенд: {_stand_label(batch.get('stand'))}")
    if batch.get("run_id"):
        lines.append(f"Прогон: #{batch['run_id']}")
    lines.append(f"Создана: {fmt_dt(batch.get('created_at'))}" + (f" ({batch['created_by']})" if batch.get("created_by") else ""))
    entities = batch.get("entities") or []
    if entities:
        lines.append("Создано: " + ", ".join(f"{e.get('entity')} × {e.get('count')}" for e in entities))
    elif batch.get("created_total"):
        lines.append(f"Создано сущностей: {batch['created_total']}")
    if batch.get("skipped_total"):
        lines.append(f"Пропущено: {batch['skipped_total']}")
    cleanup = batch.get("cleanup_summary") or {}
    if cleanup:
        lines.append(
            f"Удаление: удалено {cleanup.get('deleted', 0)}, ошибок {cleanup.get('failed', 0)}, "
            f"пропущено {cleanup.get('skipped', 0)}"
        )
    if batch.get("error"):
        lines.append(f"Ошибка: {str(batch['error'])[:MAX_ERROR_TEXT_LEN]}")
    return "\n".join(lines)


def format_data_confirm(project: str, scenario: dict | str, stand: str | None) -> str:
    title = scenario.get("title") or scenario.get("name") if isinstance(scenario, dict) else str(scenario)
    description = scenario.get("description") if isinstance(scenario, dict) else ""
    lines = [f"Создать данные «{title}» на {_stand_label(stand)} ({project})?"]
    if description:
        lines.append(str(description)[:300])
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
