"""Готовит снимок данных для мокапов карты покрытия v3
(docs/missions/redesign/coverage_v3/mockups.html, варианты F «Одна карта»
и G «Светофор») — третий заход после того, как владелец отклонил v1
(tree/heatmap/sunburst) и v2 (D панель, E карта продукта) со словами «нужно
что-то универсальное, на одном дашборде и понятное; куча цифр — не знаешь,
куда смотреть».

v3 не гоняет pytest/allure/coverage заново — переиспользует уже собранный
и закоммиченный docs/missions/redesign/coverage_v2/data.snapshot.json (тот,
в свою очередь, слит из run_window/data.snapshot.json + живого coverage.json
на момент прогона #39). Причина не собирать по новой: в текущем worktree
проект в реальном репозитории с тех пор переименован
(auto_tests_vshgu_cloude -> VSHGU) и в нём завёлся демо-проект — пересборка
дала бы несопоставимые с v1/v2 данные. Числа в этом снимке — реальные, просто
переагрегированные под светофор вместо героев предыдущих макетов (панель KPI,
heatmap, кольца по областям).

Ключевая идея v3 (универсальность): единственный обязательный источник —
дерево разделов теста (sections) + статус исполнения тестов в разделе
(run_status). Это есть у любого проекта test_hub с сидированными sections.json
и хотя бы одним прогоном. Инвентарь маршрутов (routes/coverage.json) —
необязательное обогащение: если его нет, "серых" разделов ("не покрыто")
среди tiles может не быть вовсе — экран от этого не меняется, просто пусто
в этой корзине светофора.

Запуск (без аргументов, все данные уже в data.snapshot.json v2):
    python3 collect_data.py > data.snapshot.json
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2_SNAPSHOT = HERE.parent / "coverage_v2" / "data.snapshot.json"


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def status_of(run_status: str, grey: bool) -> str:
    """Светофор: зелёный passed, жёлтый xfail/skipped (частично или известный
    дефект), красный failed/broken (есть падения), серый — тестов нет."""
    if grey:
        return "grey"
    if run_status == "passed":
        return "green"
    if run_status in ("xfail", "skipped"):
        return "yellow"
    if run_status in ("failed", "broken"):
        return "red"
    return "grey"  # not_executed — раздел есть в дереве, но в этом прогоне не исполнялся


def build_sections(tiles: list[dict]) -> list[dict]:
    out = []
    for t in tiles:
        status = status_of(t["run_status"], t["grey"])
        total_tests = t["api"] + t["ui"] + t["e2e"]
        if t["grey"]:
            items = [
                {"kind": "route", "label": it["path"], "detail": ",".join(it["methods"])}
                for it in t["items"][:6]
            ]
            n_routes = len(t["items"])
            routes_word = plural_ru(n_routes, "маршрут", "маршрута", "маршрутов")
            detail_line = f"{n_routes} {routes_word} API в инвентаре, ни один не покрыт тестом"
        else:
            items = [
                {"kind": it["kind"], "label": it["short"], "detail": it["status"]}
                for it in t["items"][:6]
            ]
            parts = [f"API {t['api']}"] if t["api"] else []
            if t["ui"]:
                parts.append(f"UI {t['ui']}")
            if t["e2e"]:
                parts.append(f"E2E {t['e2e']}")
            tests_word = plural_ru(total_tests, "тест", "теста", "тестов")
            detail_line = f"{total_tests} {tests_word} · " + " · ".join(parts)
        out.append({
            "area": t["area"], "label": t["label"], "status": status,
            "run_status": t["run_status"], "total_tests": total_tests,
            "api": t["api"], "ui": t["ui"], "e2e": t["e2e"],
            "detail_line": detail_line, "items": items,
        })
    # крупные разделы первыми — так плитки/карточки с самой заметной площадью
    # окажутся там, куда падает взгляд в первую очередь.
    out.sort(key=lambda s: (-s["total_tests"], s["label"]))
    return out


def main() -> None:
    v2 = json.loads(V2_SNAPSHOT.read_text(encoding="utf-8"))
    sections = build_sections(v2["tiles"])

    green = sum(1 for s in sections if s["status"] == "green")
    yellow = sum(1 for s in sections if s["status"] == "yellow")
    red = sum(1 for s in sections if s["status"] == "red")
    grey = sum(1 for s in sections if s["status"] == "grey")
    total = len(sections)
    covered = green + yellow + red

    result = {
        "meta": {
            "note": "Снимок поверх docs/missions/redesign/coverage_v2/data.snapshot.json "
                    "(реальный прогон #39, develop, 28.09.2026, проект auto_tests_vshgu_cloude) — "
                    "не пересобрано заново, см. docstring collect_data.py.",
            "generated_from": str(V2_SNAPSHOT.relative_to(HERE.parent.parent.parent.parent)),
        },
        "run": v2["run"],
        "kpi": {
            "sections_total": total, "sections_covered": covered,
            "sections_green": green, "sections_yellow": yellow,
            "sections_red": red, "sections_grey": grey,
            "covered_percent": round(covered / total * 100, 1) if total else 0,
        },
        "sections": sections,
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
