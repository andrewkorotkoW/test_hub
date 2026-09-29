"""Готовит снимок данных для финального мокапа карты покрытия v5
(docs/missions/redesign/coverage_v5/mockups.html) — единственная схема продукта
по раскладке, утверждённой владельцем 29.09 (sketch_approved.svg/.png): три
зоны колонками (Внешка / Проверяющий / Админка) + полоса интеграций снизу.
Варианты J/K из предыдущего этапа (карта сайта / путь пользователя) владелец
отклонил в пользу этой раскладки, см. отчёт задачи.

Источники:
  - product_map.json — граф схемы: зоны и узлы с их пиксельными координатами
    (x/y/w/h скопированы из sketch_approved.svg — раскладка рисуется строго
    по нему, см. docs/missions/redesign/coverage_v5/sketch_approved.svg),
    рёбра навигации и привязка узла к функции (node.feature).
  - features_vshgu.yml — та же карта функций, что и в coverage_v4 (владелец
    принял её как список функций продукта), дополненная тремя функциями для
    узлов схемы, которых не было в плоском списке (см. комментарии "# v5:").
  - coverage_v2/data.snapshot.json — реальный прогон #39 (develop,
    28.09.2026), тот же, что и в v2/v3/v4/предыдущем этапе v5, для
    сопоставимости чисел.

Светофор узла — как в v3/v4: red — есть failed/broken; yellow — нет падений,
но есть xfail/skipped; green — все тесты passed; grey — под tests узла не
подошёл ни один тест прогона (пусто в yml или не нашлось совпадений).

Запуск:
    python3 collect_data.py > data.snapshot.json
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
FEATURES_YML = HERE / "features_vshgu.yml"
PRODUCT_MAP_JSON = HERE / "product_map.json"
V2_SNAPSHOT = HERE.parent / "coverage_v2" / "data.snapshot.json"


def load_run_items() -> tuple[list[dict], dict]:
    v2 = json.loads(V2_SNAPSHOT.read_text(encoding="utf-8"))
    items = []
    for tile in v2["tiles"]:
        for it in tile["items"]:
            if "nodeid" in it:
                items.append(it)
    return items, v2["run"]


def matches(nodeid: str, prefix: str) -> bool:
    if not nodeid.startswith(prefix):
        return False
    rest = nodeid[len(prefix):]
    return rest == "" or rest[0] in ("/", ".")


def status_of(statuses: set[str]) -> str:
    if not statuses:
        return "grey"
    if "failed" in statuses or "broken" in statuses:
        return "red"
    if "xfail" in statuses or "skipped" in statuses:
        return "yellow"
    return "green"


def load_feature_tests() -> dict[str, list[str]]:
    y = yaml.safe_load(FEATURES_YML.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for area in y["areas"]:
        for feat in area["features"]:
            out[feat["name"]] = feat["tests"]
    return out


def build_nodes(run_items: list[dict], feature_tests: dict[str, list[str]]) -> tuple[list[dict], list[dict], list[dict]]:
    pm = json.loads(PRODUCT_MAP_JSON.read_text(encoding="utf-8"))
    nodes = []
    for n in pm["nodes"]:
        prefixes = feature_tests.get(n["feature"], [])
        matched = [it for it in run_items if any(matches(it["nodeid"], p) for p in prefixes)]
        statuses = {it["status"] for it in matched}
        status = status_of(statuses)
        matched_sorted = sorted(matched, key=lambda it: it["nodeid"])
        node = {
            "id": n["id"],
            "label": n["label"],
            "zone": n["zone"],
            "x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"],
            "feature": n["feature"],
            "status": status,
            "total_tests": len(matched),
            "tests": [
                {
                    "short": it["nodeid"].split("::")[-1].split("/")[-1],
                    "kind": "ui" if "/ui/" in it["nodeid"] else ("e2e" if it["nodeid"].startswith("tests/e2e") else "api"),
                    "status": it["status"],
                }
                for it in matched_sorted
            ],
        }
        if "target" in n:
            node["target"] = n["target"]
        nodes.append(node)
    return nodes, pm["zones"], pm["edges"]


def main() -> None:
    run_items, run = load_run_items()
    feature_tests = load_feature_tests()
    nodes, zones, edges = build_nodes(run_items, feature_tests)

    screens = [n for n in nodes if n["zone"] != "int"]
    total = len(screens)
    green = sum(1 for n in screens if n["status"] == "green")
    yellow = sum(1 for n in screens if n["status"] == "yellow")
    red = sum(1 for n in screens if n["status"] == "red")
    grey = sum(1 for n in screens if n["status"] == "grey")
    covered = green + yellow + red

    result = {
        "meta": {
            "note": "Финальная схема продукта v5 (раскладка утверждена 29.09, "
                    "sketch_approved.svg): узлы = экраны/разделы портала "
                    "(product_map.json), цвет узла — светофор по nodeid тестов "
                    "реального прогона #39 (develop, 28.09.2026, "
                    "coverage_v2/data.snapshot.json) через префиксы функции из "
                    "features_vshgu.yml, на которую ссылается узел. Интеграции "
                    "(zone=int) не входят в KPI «экранов покрыто» — это внешние "
                    "узлы, пристыкованные стрелкой к целевому экрану (node.target).",
        },
        "run": run,
        "kpi": {
            "screens_total": total, "screens_covered": covered,
            "screens_green": green, "screens_yellow": yellow,
            "screens_red": red, "screens_grey": grey,
        },
        "zones": zones,
        "nodes": nodes,
        "edges": edges,
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
