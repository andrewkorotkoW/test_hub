"""Статистика по разделам проекта и её динамика за 30 дней.

Раздел (область) — папка `tests/api/<area>`, `tests/ui/<area>` или весь `tests/e2e`
целиком (см. миссию). Раздел теста вычисляется прямо из allure fullName
("tests.api.notifications.test_x#test_y" -> "api/notifications") — того же
идентификатора, что использует app.core.coverage/flaky/xfail_registry — поэтому
recalc() не запускает runner.discover()/pytest: если тест ни разу не прогонялся,
его раздел просто не появится в срезе последнего прогона (для «разделов без
единого теста» это компенсирует discover_section_dirs — единственное место
здесь, которое смотрит в файловую систему проекта, а не в БД/allure-results).
Исключение — _discover_total_tests: запускается только когда на стенде нет ни
одного прогона с target='all' (fallback_run), чтобы подписать «N из M тестов».

recalc()/load_cached() — тот же приём, что и в app.core.coverage: результат
кладётся в workspace/stats/<project>/<stand>.json и пересчитывается по требованию
(см. app/routers/stats.py::_ensure_cached), а не на каждый GET."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import allure_report

logger = logging.getLogger(__name__)

STATS_DIR = settings.WORKSPACE_DIR / "stats"

FLAKY_THRESHOLD = 0.3
FLAKY_MIN_RUNS = 3
DYNAMICS_DAYS = 30
TOP_N = 10
FINISHED_STATUSES = ("passed", "failed", "cancelled")
# «Последний прогон» для KPI/раздела/кольца — только passed/failed (docs/missions/
# 2026-11-02_review_fixes.md, п.1): cancelled по определению неполный и часто падает
# по стенду, на него нельзя опираться как на состояние проекта. cancelled остаётся
# в FINISHED_STATUSES выше — для 30-дневной динамики и ленты он всё ещё нужен.
KPI_STATUSES = ("passed", "failed")
_NO_STAND_TOKEN = "_none_"


def cache_path(project_name: str, stand: str | None) -> Path:
    return STATS_DIR / project_name / f"{stand or _NO_STAND_TOKEN}.json"


def _section_of_full_name(full_name: str) -> str | None:
    """"tests.api.notifications.test_x#test_y" -> "api/notifications";
    "tests.e2e.test_x#test_y" -> "e2e" (весь e2e — один раздел, без разбивки на
    подпапки, см. миссию); тесты вне tests/api, tests/ui, tests/e2e -> None."""
    module = full_name.split("#", 1)[0]
    segments = module.split(".")
    if len(segments) < 2 or segments[0] != "tests":
        return None
    kind = segments[1]
    if kind == "e2e":
        return "e2e"
    if kind in ("api", "ui"):
        return f"{kind}/{segments[2]}" if len(segments) >= 3 else kind
    return None


def discover_section_dirs(project_path: str) -> list[str]:
    """Разделы по факту файловой системы — единственный способ узнать про раздел,
    для которого ещё нет ни одного теста в allure-results (иначе он просто не
    появится в разборе прогонов)."""
    root = Path(project_path) / "tests"
    sections: list[str] = []
    for kind in ("api", "ui"):
        kind_dir = root / kind
        if not kind_dir.is_dir():
            continue
        for sub in sorted(kind_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith(("__", ".")) and sub.name != "allure-results":
                sections.append(f"{kind}/{sub.name}")
    if (root / "e2e").is_dir():
        sections.append("e2e")
    return sections


def _route_area(route_name: str) -> str:
    """Копия app.core.coverage._area_of (первый сегмент dotted-имени маршрута) —
    своя копия по тому же соглашению модулей, что и _nodeid_to_full_name в
    app.core.flaky/xfail_registry: не тянуть межмодульную зависимость ради
    одной функции."""
    return route_name.split(".", 1)[0] if route_name else "other"


def _bucket_status(entry: dict) -> str:
    """passed/failed/xfail/skipped — broken схлопывается в failed (как и на
    дашборде проекта, см. ui/project.js::runMetrics), xfail — тот же признак,
    что и в app.core.coverage._classify_allure_status."""
    status = entry["status"]
    if status == "broken":
        return "failed"
    if status == "skipped" and entry.get("message") and "xfail" in entry["message"].lower():
        return "xfail"
    return status


def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def default_stand(conn: sqlite3.Connection, project_name: str) -> str | None:
    row = conn.execute(
        "SELECT name FROM stands WHERE project = ? ORDER BY name LIMIT 1", (project_name,)
    ).fetchone()
    return row["name"] if row else None


def _stand_filter(stand: str | None) -> tuple[str, tuple]:
    return ("stand IS NULL", ()) if stand is None else ("stand = ?", (stand,))


def _latest_full_run(conn: sqlite3.Connection, project: str, stand: str | None) -> sqlite3.Row | None:
    clause, params = _stand_filter(stand)
    return conn.execute(
        f"SELECT * FROM runs WHERE project = ? AND {clause} AND target = 'all' "
        f"AND status IN (?, ?) ORDER BY id DESC LIMIT 1",
        (project, *params, *KPI_STATUSES),
    ).fetchone()


def _latest_run_on_stand(conn: sqlite3.Connection, project: str, stand: str | None) -> sqlite3.Row | None:
    """Последний прогон на стенде ЛЮБОЙ цели (не только target='all') — источник
    fallback_run в recalc(), когда полного прогона (_latest_full_run) ещё не было."""
    clause, params = _stand_filter(stand)
    return conn.execute(
        f"SELECT * FROM runs WHERE project = ? AND {clause} "
        f"AND status IN (?, ?) ORDER BY id DESC LIMIT 1",
        (project, *params, *KPI_STATUSES),
    ).fetchone()


def _discover_total_tests(project_path: str, venv: str) -> int | None:
    """Сколько тестов всего в проекте (`pytest --collect-only`, app.core.runner.discover) —
    для подписи «N из M тестов» у fallback_run, когда на стенде ни разу не было прогона
    с target='all' и посчитать M по нему самому нельзя. Импорт runner — локальный (тот
    же приём, что app.core.failure_causes.ensure_run_results): на уровне модуля вышел бы
    цикл runner -> stats (не то что бы он сейчас есть, но заводить его незачем).
    Ошибка/нет .venv — None, UI покажет только N, без «из M»."""
    try:
        from . import runner

        discovered = asyncio.run(runner.discover(project_path, venv))
        if discovered.get("error"):
            return None
        return runner.count_target_tests(discovered.get("tree") or {}, "all")
    except Exception:
        logger.exception("stats._discover_total_tests упал для %s", project_path)
        return None


def latest_finished_run_id(conn: sqlite3.Connection, project: str, stand: str | None) -> int | None:
    """Курсор для кэша: любой завершённый прогон, не только полный — от него
    зависит и динамика (использует все прогоны за 30 дней), и разделы
    (используют только последний полный), поэтому кэш инвалидируется по самому
    свежему из них."""
    clause, params = _stand_filter(stand)
    row = conn.execute(
        f"SELECT id FROM runs WHERE project = ? AND {clause} "
        f"AND status IN ('passed', 'failed', 'cancelled') ORDER BY id DESC LIMIT 1",
        (project, *params),
    ).fetchone()
    return row["id"] if row else None


def _runs_since(conn: sqlite3.Connection, project: str, stand: str | None, since_iso: str) -> list[sqlite3.Row]:
    clause, params = _stand_filter(stand)
    return conn.execute(
        f"SELECT * FROM runs WHERE project = ? AND {clause} "
        f"AND status IN ('passed', 'failed', 'cancelled') AND started >= ? ORDER BY id",
        (project, *params, since_iso),
    ).fetchall()


def _project_dynamics_point(run: sqlite3.Row) -> dict:
    """passed_percent здесь не различает xfail (runs.counts, в отличие от
    посекционного среза ниже, не выделяет xfail отдельно от skipped — то же
    упрощение, что и в ui/project.js::runMetrics)."""
    counts = json.loads(run["counts"] or "{}")
    passed = int(counts.get("passed", 0) or 0)
    failed = int(counts.get("failed", 0) or 0) + int(counts.get("broken", 0) or 0)
    skipped = int(counts.get("skipped", 0) or 0)
    total = passed + failed + skipped
    percent = round(passed / total * 100, 1) if total else None
    return {
        "run_id": run["id"], "started": run["started"], "passed_percent": percent,
        "duration": run["duration"], "tests_total": total,
    }


def _empty_bucket() -> dict:
    return {"passed": 0, "failed": 0, "xfail": 0, "skipped": 0, "durations": []}


def _section_buckets_for_run(run_id: int) -> dict[str, dict]:
    """раздел -> {passed, failed, xfail, skipped, durations} для одного прогона
    (парсит allure-results прогона один раз, распределяя записи по разделам)."""
    buckets: dict[str, dict] = {}
    for entry in allure_report.parse_results(_allure_dir(run_id)):
        section = _section_of_full_name(entry["name"])
        if section is None:
            continue
        bucket = buckets.setdefault(section, _empty_bucket())
        bucket[_bucket_status(entry)] += 1
        if isinstance(entry.get("duration"), (int, float)):
            bucket["durations"].append(entry["duration"])
    return buckets


def _section_summary(bucket: dict) -> dict:
    total = bucket["passed"] + bucket["failed"] + bucket["xfail"] + bucket["skipped"]
    percent = round(bucket["passed"] / total * 100, 1) if total else None
    durations = bucket["durations"]
    avg_duration = round(sum(durations) / len(durations), 2) if durations else None
    return {
        "tests_total": total,
        "passed": bucket["passed"],
        "failed": bucket["failed"],
        "xfail": bucket["xfail"],
        "skipped": bucket["skipped"],
        "passed_percent": percent,
        "avg_duration": avg_duration,
    }


def _flaky_counts_by_section(conn: sqlite3.Connection, project: str, stand: str | None) -> dict[str, int]:
    if stand is None:  # flaky_stats.stand NOT NULL — без стенда данных нет
        return {}
    rows = conn.execute(
        "SELECT test FROM flaky_stats WHERE project = ? AND stand = ? AND runs >= ? AND score >= ?",
        (project, stand, FLAKY_MIN_RUNS, FLAKY_THRESHOLD),
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        section = _section_of_full_name(row["test"])
        if section:
            counts[section] = counts.get(section, 0) + 1
    return counts


def _xfail_counts_by_section(conn: sqlite3.Connection, project: str, stand: str | None) -> dict[str, int]:
    if stand is None:  # xfail_registry.stand NOT NULL — без стенда данных нет
        return {}
    rows = conn.execute(
        "SELECT test FROM xfail_registry WHERE project = ? AND stand = ? AND state = 'xfail'",
        (project, stand),
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        section = _section_of_full_name(row["test"])
        if section:
            counts[section] = counts.get(section, 0) + 1
    return counts


def _routes_coverage_by_area(project_name: str) -> dict[str, dict]:
    from . import coverage  # локальный импорт — избегаем цикла на уровне модуля

    cached = coverage.load_cached(project_name)
    if not cached:
        return {}
    by_area: dict[str, dict] = {}
    for route in cached.get("routes", []):
        area = _route_area(route["name"])
        bucket = by_area.setdefault(area, {"total": 0, "covered": 0})
        bucket["total"] += 1
        if route.get("covered"):
            bucket["covered"] += 1
    return by_area


def _section_entry(
    section: str, bucket: dict, flaky_by_section: dict[str, int], xfail_by_section: dict[str, int],
    routes_by_area: dict[str, dict],
) -> dict:
    summary = _section_summary(bucket)
    area_part = section.split("/", 1)[1] if "/" in section else None
    routes = routes_by_area.get(area_part) if area_part else None
    routes_total = routes["total"] if routes else None
    routes_covered = routes["covered"] if routes else None
    routes_percent = round(routes_covered / routes_total * 100, 1) if routes and routes_total else None
    return {
        "section": section,
        **summary,
        "flaky_count": flaky_by_section.get(section, 0),
        "xfail_count": xfail_by_section.get(section, 0),
        "routes_total": routes_total,
        "routes_covered": routes_covered,
        "routes_percent": routes_percent,
    }


def recalc(project_name: str, stand: str | None) -> dict:
    """Пересчитывает статистику по разделам и динамику за последние 30 дней для
    (project_name, stand) и кладёт результат в workspace/stats/<project>/<stand>.json."""
    conn = get_connection()
    try:
        project = conn.execute("SELECT * FROM projects WHERE name = ?", (project_name,)).fetchone()
        if project is None:
            raise ValueError(f"проект {project_name} не найден")

        full_run = _latest_full_run(conn, project_name, stand)
        # Нет прогона с target='all' на стенде — fallback_run ниже (docs/missions/
        # 2026-11-02_review_fixes.md, п.2): «Статистика» покажет состояние «частичный
        # прогон» вместо таблицы разделов в нулях.
        fallback_row = _latest_run_on_stand(conn, project_name, stand) if full_run is None else None
        section_buckets = _section_buckets_for_run(full_run["id"]) if full_run is not None else {}

        flaky_by_section = _flaky_counts_by_section(conn, project_name, stand)
        xfail_by_section = _xfail_counts_by_section(conn, project_name, stand)
        routes_by_area = _routes_coverage_by_area(project_name)

        if full_run is not None:
            section_names = set(section_buckets) | set(discover_section_dirs(project["path"]))
        elif fallback_row is None:
            # Стенда ни разу не касались — прежнее поведение: показать известные по
            # файловой системе разделы в нулях (а не прятать карточку статистики).
            section_names = set(discover_section_dirs(project["path"]))
        else:
            # Частичный прогон есть (fallback_run) — таблица разделов пустая, её
            # заменяет состояние «частичный прогон» на фронте; "Разделы без единого
            # теста" тоже не считаем — раздел, которого не было в цели частичного
            # прогона, не значит «без тестов».
            section_names = set()

        sections = []
        empty_sections = []
        for section in sorted(section_names):
            entry = _section_entry(section, section_buckets.get(section, _empty_bucket()),
                                    flaky_by_section, xfail_by_section, routes_by_area)
            if entry["tests_total"] == 0:
                empty_sections.append(section)
            sections.append(entry)

        fallback_run = None
        if fallback_row is not None:
            fallback_buckets = _section_buckets_for_run(fallback_row["id"])
            fallback_sections = [
                _section_entry(section, bucket, flaky_by_section, xfail_by_section, routes_by_area)
                for section, bucket in sorted(fallback_buckets.items())
            ]
            counts = json.loads(fallback_row["counts"] or "{}")
            tests_total = sum(int(counts.get(k) or 0) for k in ("passed", "failed", "broken", "skipped"))
            fallback_run = {
                "id": fallback_row["id"],
                "target": fallback_row["target"],
                "started": fallback_row["started"],
                "tests_total": tests_total,
                "expected_total": _discover_total_tests(project["path"], project["venv"]),
                "sections": fallback_sections,
            }

        since = (datetime.now() - timedelta(days=DYNAMICS_DAYS)).isoformat(timespec="seconds")
        runs = _runs_since(conn, project_name, stand, since)
        dynamics_project = [_project_dynamics_point(r) for r in runs]

        dynamics_by_section: dict[str, list[dict]] = {}
        for run in runs:
            for section, bucket in _section_buckets_for_run(run["id"]).items():
                summary = _section_summary(bucket)
                dynamics_by_section.setdefault(section, []).append({
                    "run_id": run["id"],
                    "started": run["started"],
                    "passed_percent": summary["passed_percent"],
                    "duration": summary["avg_duration"],
                    "tests_total": summary["tests_total"],
                })

        top_slowest = []
        if full_run is not None:
            timed = [
                e for e in allure_report.parse_results(_allure_dir(full_run["id"]))
                if isinstance(e.get("duration"), (int, float))
            ]
            timed.sort(key=lambda e: e["duration"], reverse=True)
            top_slowest = [
                {"name": e["name"], "section": _section_of_full_name(e["name"]), "duration": e["duration"]}
                for e in timed[:TOP_N]
            ]

        top_flaky = []
        if stand is not None:
            rows = conn.execute(
                "SELECT * FROM flaky_stats WHERE project = ? AND stand = ? AND runs >= ? "
                "ORDER BY score DESC, test LIMIT ?",
                (project_name, stand, FLAKY_MIN_RUNS, TOP_N),
            ).fetchall()
            top_flaky = [
                {
                    "test": r["test"],
                    "section": _section_of_full_name(r["test"]),
                    "score": r["score"],
                    "runs": r["runs"],
                    "fails": r["fails"],
                }
                for r in rows
            ]

        result = {
            "project": project_name,
            "stand": stand,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "run_id": full_run["id"] if full_run else None,
            "full_run": {
                "id": full_run["id"], "stand": stand, "target": full_run["target"], "started": full_run["started"],
            } if full_run is not None else None,
            "fallback_run": fallback_run,
            "cache_key_run_id": latest_finished_run_id(conn, project_name, stand),
            "sections": sections,
            "empty_sections": sorted(empty_sections),
            "dynamics_project": dynamics_project,
            "dynamics_by_section": dynamics_by_section,
            "top_slowest": top_slowest,
            "top_flaky": top_flaky,
        }
    finally:
        conn.close()

    out_path = cache_path(project_name, stand)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_cached(project_name: str, stand: str | None) -> dict | None:
    path = cache_path(project_name, stand)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
