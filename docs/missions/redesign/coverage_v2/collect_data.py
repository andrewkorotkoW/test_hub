"""Готовит агрегированный снимок данных для мокапов карты покрытия v2
(docs/missions/redesign/coverage_v2/mockups.html, варианты D «Панель покрытия»
и E «Карта продукта») поверх уже собранного docs/missions/redesign/run_window/data.snapshot.json —
не гоняет pytest/allure заново, а переиспользует run/tests/sections оттуда и
довычисляет то, чего там не было: разбивку покрытия маршрутов по стендам
(develop/stage) на область — нужна для heatmap «область × стенд» (референс
IMG_2929) — и не встречавшиеся в тестах, но существующие в инвентаре маршрутов
области (для серых плиток «без тестов» в варианте E).

Источники (только чтение):
  docs/missions/redesign/run_window/data.snapshot.json — run, tests, sections
    (уже посчитаны там из workspace/test_hub.db + allure-results).
  <repo>/workspace/coverage/<project>/coverage.json — полный инвентарь маршрутов
    и страниц с покрытием и статусом по каждому стенду (routes[i].status.<stand>.state),
    не урезанный до agregatov, как в run_window/collect_data.py::collect_coverage.

Запуск:
    python3 collect_data.py --repo /Users/andreykorotkow/PycharmProjects/test_hub \
        --project auto_tests_vshgu_cloude > data.snapshot.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN_WINDOW_SNAPSHOT = HERE.parent / "run_window" / "data.snapshot.json"

ROUTE_AREA_RE = re.compile(r"^/api/v1/([^/]+)")


def route_area(path: str) -> str:
    m = ROUTE_AREA_RE.match(path)
    return m.group(1) if m else "служебные"


# Человекочитаемые подписи разделов — только для тех, что реально попадают в мокап
# (см. sections из run_window/data.snapshot.json и подобранные ниже нулевые области).
RU_LABELS = {
    "programs": "Программы", "buk": "БУК", "notifications": "Уведомления",
    "cas": "CAS (аутентификация)", "dictionaries": "Справочники", "e2e": "Сквозные сценарии",
    "users": "Пользователи", "test_constructor": "Конструктор тестов",
    "create_activity": "Создание активности", "learning_statistics": "Статистика обучения",
    "knowledge_base": "База знаний", "tickets": "Обращения в техподдержку",
    "practical_tasks": "Практические задания", "onboarding": "Онбординг",
    "alpina_and_mif": "Alpina и МИФ", "aos": "АОС", "certificates": "Сертификаты",
    "banner": "Баннеры", "courses": "Курсы", "polls": "Опросы", "proctoring": "Прокторинг",
    "tests": "Тесты (контроль знаний)", "game_session": "Игровые сессии", "streams": "Потоки",
    "dashboards": "Дашборды", "homework": "Домашние задания",
    "my-programs": "Мои программы", "experts": "Эксперты", "tenants": "Тенанты",
    "materials": "Материалы", "ratings": "Рейтинги", "my-materials": "Мои материалы",
    "assignments": "Назначения", "achievements": "Достижения", "helpdesk": "Хелпдеск (портал)",
    "regions": "Регионы", "statistics": "Статистика", "knowledge-base": "База знаний (API)",
    "external": "Внешние интеграции", "oauth": "OAuth", "me": "Профиль (me)",
}


def ru_label(area: str) -> str:
    return RU_LABELS.get(area, area.replace("_", " ").replace("-", " ").capitalize())


def kind_area_of(nodeid: str) -> tuple[str, str | None]:
    file_part = nodeid.split("::", 1)[0]
    parts = file_part.split("/")
    if len(parts) >= 3 and parts[0] == "tests" and parts[1] in ("api", "ui"):
        return parts[1], parts[2]
    if len(parts) >= 2 and parts[0] == "tests" and parts[1] == "e2e":
        return "e2e", None
    return parts[1] if len(parts) > 1 else "?", None


def percent_passed(tests: list[dict]) -> float | None:
    """passed / (passed+failed+broken+xfail+skipped) — тот же принцип, что и
    «кольцо статусов» на дашборде проекта (DESIGN.md: «процент passed из
    завершённых»)."""
    if not tests:
        return None
    passed = sum(1 for t in tests if t["status"] == "passed")
    return round(passed / len(tests) * 100, 1)


def build_kind_rings(tests: list[dict]) -> list[dict]:
    out = []
    for kind in ("api", "ui", "e2e"):
        subset = [t for t in tests if t["kind"] == kind]
        out.append({
            "key": kind, "label": kind.upper() if kind != "e2e" else "E2E",
            "percent": percent_passed(subset) or 0, "total": len(subset),
        })
    return out


def build_area_test_stats(tests: list[dict]) -> dict[str, dict]:
    by_area: dict[str, list[dict]] = {}
    for t in tests:
        area = t["area"] or "e2e"
        by_area.setdefault(area, []).append(t)
    return {
        area: {"percent": percent_passed(ts) or 0, "total": len(ts)}
        for area, ts in by_area.items()
    }


def build_section_rings(sections: list[dict], area_stats: dict[str, dict], top_n: int) -> list[dict]:
    ranked = sorted(sections, key=lambda r: -(r["api"] + r["ui"] + r["e2e"]))[:top_n]
    out = []
    for rec in ranked:
        stats = area_stats.get(rec["area"], {"percent": 0, "total": 0})
        out.append({
            "area": rec["area"], "label": ru_label(rec["area"]),
            "percent": stats["percent"], "total_tests": rec["api"] + rec["ui"] + rec["e2e"],
            "api": rec["api"], "ui": rec["ui"], "e2e": rec["e2e"], "run_status": rec["run_status"],
        })
    return out


def build_section_tiles(sections: list[dict], area_stats: dict[str, dict], tests: list[dict]) -> list[dict]:
    out = []
    for rec in sorted(sections, key=lambda r: -(r["api"] + r["ui"] + r["e2e"])):
        stats = area_stats.get(rec["area"], {"percent": 0, "total": 0})
        area_tests = [t for t in tests if (t["area"] or "e2e") == rec["area"]]
        out.append({
            "area": rec["area"], "label": ru_label(rec["area"]), "grey": False,
            "percent": stats["percent"], "api": rec["api"], "ui": rec["ui"], "e2e": rec["e2e"],
            "run_status": rec["run_status"],
            "items": [
                {"nodeid": t["nodeid"], "short": t["short"], "kind": t["kind"], "status": t["status"]}
                for t in sorted(area_tests, key=lambda t: t["nodeid"])[:14]
            ],
        })
    return out


ZERO_AREAS_LIMIT = 9


def build_grey_tiles(routes: list[dict], sections_areas: set[str]) -> list[dict]:
    by_area: dict[str, list[dict]] = {}
    for r in routes:
        area = route_area(r["path"])
        by_area.setdefault(area, []).append(r)
    zero = [
        (area, rs) for area, rs in by_area.items()
        if not any(r["covered"] for r in rs)
        and area not in sections_areas and area.replace("-", "_") not in sections_areas
        and area not in ("служебные", "unauthorized", "user")
    ]
    zero.sort(key=lambda pair: -len(pair[1]))
    out = []
    for area, rs in zero[:ZERO_AREAS_LIMIT]:
        out.append({
            "area": area, "label": ru_label(area), "grey": True, "percent": 0,
            "api": 0, "ui": 0, "e2e": 0, "run_status": "not_executed",
            "items": [
                {"path": r["path"], "methods": r["methods"]} for r in rs[:14]
            ],
        })
    return out


HEATMAP_TOP_N = 10


def build_heatmap(routes: list[dict], stands: list[str]) -> list[dict]:
    by_area: dict[str, list[dict]] = {}
    for r in routes:
        by_area.setdefault(route_area(r["path"]), []).append(r)
    ranked = sorted(by_area.items(), key=lambda pair: -len(pair[1]))[:HEATMAP_TOP_N]
    priority = {"failed": 4, "xfail": 3, "passed": 2, "not_executed": 1,
                "no_tests_for_stand": 0, "not_covered": 0}
    out = []
    for area, rs in ranked:
        cells = {}
        for stand in stands:
            states = [r["status"][stand]["state"] for r in rs]
            executed = [s for s in states if s in ("passed", "failed", "xfail")]
            worst = max(states, key=lambda s: priority.get(s, 0)) if states else "not_covered"
            cells[stand] = {
                "percent": round(len(executed) / len(rs) * 100, 1) if rs else 0,
                "worst_state": worst if priority.get(worst, 0) > 0 else "not_covered",
            }
        out.append({"area": area, "label": ru_label(area), "total": len(rs), "stands": cells})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--project", default="auto_tests_vshgu_cloude")
    args = parser.parse_args()

    snapshot = json.loads(RUN_WINDOW_SNAPSHOT.read_text(encoding="utf-8"))
    run, tests, sections = snapshot["run"], snapshot["tests"], snapshot["sections"]

    coverage_path = args.repo / "workspace" / "coverage" / args.project / "coverage.json"
    coverage_raw = json.loads(coverage_path.read_text(encoding="utf-8"))
    routes = coverage_raw["routes"]
    stands = coverage_raw["stands"]

    areas_route_based: dict[str, dict] = {}
    for r in routes:
        a = route_area(r["path"])
        rec = areas_route_based.setdefault(a, {"total": 0, "covered": 0})
        rec["total"] += 1
        if r["covered"]:
            rec["covered"] += 1
    areas_zero_count = sum(1 for rec in areas_route_based.values() if rec["covered"] == 0)

    routes_total, routes_covered = coverage_raw["routes_total"], coverage_raw["routes_covered"]
    pages_total, pages_covered = coverage_raw["pages_total"], coverage_raw["pages_covered"]

    area_stats = build_area_test_stats(tests)
    sections_areas = {rec["area"] for rec in sections}

    result = {
        "meta": {
            "source_repo": str(args.repo), "project": args.project,
            "note": "Снимок поверх run_window/data.snapshot.json (run/tests/sections) + "
                    "полного coverage.json с раскладкой по стендам (routes[i].status.<stand>).",
            "generated_at": coverage_raw["generated_at"],
        },
        "run": {"id": run["id"], "stand": run["stand"], "started": run["started"], "finished": run["finished"]},
        "kpi": {
            "pages_total": pages_total, "pages_covered": pages_covered,
            "routes_total": routes_total, "routes_covered": routes_covered,
            "gauge_percent": round((routes_covered + pages_covered) / (routes_total + pages_total) * 100, 1),
            "areas_total": len(areas_route_based), "areas_zero": areas_zero_count,
        },
        "stands": stands,
        "kind_rings": build_kind_rings(tests),
        "section_rings": build_section_rings(sections, area_stats, top_n=6),
        "bars": [
            {"area": rec["area"], "label": ru_label(rec["area"]), "total": rec["api"] + rec["ui"] + rec["e2e"]}
            for rec in sorted(sections, key=lambda r: -(r["api"] + r["ui"] + r["e2e"]))[:10]
        ],
        "heatmap": build_heatmap(routes, stands),
        "tiles": build_section_tiles(sections, area_stats, tests) + build_grey_tiles(routes, sections_areas),
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
