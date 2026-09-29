"""Готовит снимок данных для мокапов карты покрытия v5
(docs/missions/redesign/coverage_v5/mockups.html, варианты J «Карта сайта» и
K «Путь пользователя») — после того как владелец отклонил v1-v4 (списки,
таблицы, дашборды по функциям) и объяснил идею: покрытие должно быть
нарисовано как схема продукта — экраны блоками со связями, цвет = светофор,
без списков и чисел в колонках.

Источники:
  - product_map.yml — граф узлов схемы (id, зона, row/col для раскладки,
    ссылка на функцию по имени) и рёбер (навигация пользователя).
  - features_vshgu.yml — та же карта функций, что и в coverage_v4 (владелец
    принял её как список функций продукта), дополненная функциями для узлов
    схемы, которых не было в плоском списке v4 (см. комментарии "# v5:" в
    файле). node.feature в product_map.yml — это имя записи в этом файле.
  - coverage_v2/data.snapshot.json — реальный прогон #39 (develop,
    28.09.2026), тот же, что и в v2/v3/v4, для сопоставимости чисел.

Светофор узла — как в v3/v4 (status_of): red — есть failed/broken;
yellow — нет падений, но есть xfail/skipped; green — все тесты passed;
grey — под tests узла не подошёл ни один тест прогона (пусто в yml или
не нашлось совпадений).

Запуск:
    python3 collect_data.py > data.snapshot.json
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
FEATURES_YML = HERE / "features_vshgu.yml"
PRODUCT_MAP_YML = HERE / "product_map.yml"
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


def build_nodes(run_items: list[dict], feature_tests: dict[str, list[str]]) -> list[dict]:
    pm = yaml.safe_load(PRODUCT_MAP_YML.read_text(encoding="utf-8"))
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
            "row": n["row"],
            "col": n["col"],
            "feature": n["feature"],
            "status": status,
            "total_tests": len(matched),
            "tests": [
                {"short": it["nodeid"].split("::")[-1].split("/")[-1], "status": it["status"]}
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
            "note": "Схема продукта v5: узлы = экраны/разделы портала (product_map.yml), "
                    "цвет узла пересчитан по nodeid тестов реального прогона #39 (develop, "
                    "28.09.2026, coverage_v2/data.snapshot.json) через префиксы функции из "
                    "features_vshgu.yml, на которую ссылается узел. Интеграции (zone=int) "
                    "не входят в KPI «экранов покрыто» — это внешние узлы, пристыкованные "
                    "стрелкой к целевому экрану (node.target).",
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
