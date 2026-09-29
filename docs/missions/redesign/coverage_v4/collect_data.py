"""Готовит снимок данных для мокапов карты покрытия v4
(docs/missions/redesign/coverage_v4/mockups.html, варианты H «Функциональная
карта» и I «Список-табло») — после того как владелец посмотрел v3 (одна карта
разделов + светофор, docs/missions/redesign/coverage_v3/) и уточнил: нужен не
срез по папкам тестов, а дашборд по ВСЕМУ функционалу продукта — видно каждую
функцию и её состояние, читается как текст.

Источник структуры — черновик супервизора features_vshgu.yml (области продукта
-> функции -> префиксы путей тестов auto_tests_vshgu). Префиксы уже сверены
руками с деревом tests/ проекта auto_tests_vshgu (только чтение) и поправлены
там, где расходились с реальными путями — см. комментарий в самом yml и отчёт
задачи. Статус функции считается заново по nodeid каждого теста прогона #39
(переиспользуем docs/missions/redesign/coverage_v2/data.snapshot.json — тот же
реальный прогон, что и в v2/v3, не пересобираем ради сопоставимости чисел),
а не по агрегату из v2 tiles (тот был по папкам/areas, а не по функциям, и одна
функция может собирать тесты из нескольких areas сразу).

Светофор функции:
  красный  — среди тестов функции есть failed/broken;
  жёлтый   — нет падений, но есть xfail/skipped (частично; включая xfail —
             known defect) или совсем мало тестов не о чем говорить не будем,
             жёлтый здесь только по статусам, не по количеству;
  зелёный  — все матчнутые тесты passed;
  серый    — под префиксы функции не подошёл ни один тест из прогона (тестов
             нет вовсе, либо супервизор сознательно оставил function.tests: []).

Второй блок снимка — fallback для проектов без карты функций (демо-проект
test_hub, demo/tests/). Он строится по дереву папок tests/api/<area> (как в
v3), а не по features.yml, которого у Demo нет. Статусы api-тестов реальные:
demo/app/main.py поднят локально на 127.0.0.1:8710 (тот же порт, что и
app/config.py::Settings.TH_DEMO_PORT) и demo/tests/api прогнан один раз через
pytest -v. demo/tests/ui и demo/tests/e2e не прогонялись (нужен браузер/дольше
и не критично для одного скриншота-иллюстрации) — эти разделы помечены серым
"не прогонялись в этом снимке", это не то же самое, что "тестов нет".

Запуск:
    python3 collect_data.py > data.snapshot.json
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
FEATURES_YML = HERE / "features_vshgu.yml"
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


def load_run_items() -> list[dict]:
    """Плоский список тестов прогона #39: только записи с nodeid (route-инвентарь
    серых tiles v2 сюда не входит — у функциональной карты свой источник "серого":
    отсутствие совпавших тестов, а не отсутствие маршрута в API)."""
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


def build_features(run_items: list[dict]) -> list[dict]:
    y = yaml.safe_load(FEATURES_YML.read_text(encoding="utf-8"))
    out = []
    for area in y["areas"]:
        for feat in area["features"]:
            prefixes = feat["tests"]
            matched = [
                it for it in run_items
                if any(matches(it["nodeid"], p) for p in prefixes)
            ]
            statuses = {it["status"] for it in matched}
            status = status_of(statuses)
            matched_sorted = sorted(matched, key=lambda it: it["nodeid"])
            short = [it["nodeid"].split("::")[-1].split("/")[-1] for it in matched_sorted]
            out.append({
                "area": area["name"],
                "name": feat["name"],
                "status": status,
                "total_tests": len(matched),
                "prefixes": prefixes,
                "tests": [
                    {"short": s, "kind": "ui" if "/ui/" in it["nodeid"] else ("e2e" if it["nodeid"].startswith("tests/e2e") else "api"), "status": it["status"]}
                    for s, it in zip(short, matched_sorted)
                ],
            })
    return out


def build_areas(features: list[dict]) -> list[dict]:
    order = []
    by_area: dict[str, list[dict]] = {}
    for f in features:
        if f["area"] not in by_area:
            by_area[f["area"]] = []
            order.append(f["area"])
        by_area[f["area"]].append(f)
    return [{"name": a, "features": by_area[a]} for a in order]


DEMO_SECTIONS = [
    {"area": "auth", "label": "Авторизация", "run": True,
     "tests": [("test_login_success", "passed"), ("test_login_wrong_password", "passed"),
               ("test_login_unknown_user", "passed"), ("test_me_with_valid_token", "passed"),
               ("test_me_without_token", "passed")]},
    {"area": "catalog", "label": "Каталог", "run": True,
     "tests": [("test_list_returns_items", "passed"), ("test_list_filter_by_query_case_insensitive", "passed"),
               ("test_get_item_by_id", "passed"), ("test_get_item_not_found", "passed"),
               ("test_list_item_fields_present", "passed"), ("test_list_supports_pagination", "skipped"),
               ("test_search_supports_typos", "xfail"), ("test_catalog_is_eventually_consistent", "passed")]},
    {"area": "orders", "label": "Заказы", "run": True,
     "tests": [("test_create_order_success", "passed"), ("test_create_order_applies_discount", "failed"),
               ("test_create_order_multiple_qty_applies_discount", "failed"),
               ("test_create_order_out_of_stock_returns_400", "passed"),
               ("test_create_order_unknown_item_returns_404", "passed"),
               ("test_create_order_invalid_qty_returns_400", "passed"),
               ("test_get_order_by_id", "passed"), ("test_get_order_not_found", "passed")]},
    {"area": "users", "label": "Пользователи", "run": True,
     "tests": [("test_list_users", "passed"), ("test_list_users_contains_seed_logins", "passed")]},
    {"area": "ui/auth", "label": "UI · Авторизация", "run": False, "tests": []},
    {"area": "ui/catalog", "label": "UI · Каталог", "run": False, "tests": []},
    {"area": "e2e", "label": "E2E · Покупка", "run": False, "tests": []},
]


def build_demo() -> dict:
    sections = []
    for s in DEMO_SECTIONS:
        if not s["run"]:
            sections.append({
                "area": s["area"], "label": s["label"], "status": "grey",
                "total_tests": 0, "note": "не прогонялись в этом снимке",
                "tests": [],
            })
            continue
        statuses = {t[1] for t in s["tests"]}
        sections.append({
            "area": s["area"], "label": s["label"], "status": status_of(statuses),
            "total_tests": len(s["tests"]), "note": None,
            "tests": [{"short": n, "status": st} for n, st in s["tests"]],
        })
    return {
        "project": "Demo",
        "note": "У Demo нет tests/features.yml — карта функций недоступна, "
                "показываем fallback: те же статусы светофора, но по разделам "
                "дерева tests/, как в coverage_v3.",
        "sections": sections,
    }


def main() -> None:
    run_items, run = load_run_items()
    features = build_features(run_items)
    areas = build_areas(features)

    total = len(features)
    green = sum(1 for f in features if f["status"] == "green")
    yellow = sum(1 for f in features if f["status"] == "yellow")
    red = sum(1 for f in features if f["status"] == "red")
    grey = sum(1 for f in features if f["status"] == "grey")
    covered = green + yellow + red

    result = {
        "meta": {
            "note": "Статусы функций пересчитаны по nodeid тестов реального прогона "
                    "#39 (develop, 28.09.2026, docs/missions/redesign/coverage_v2/"
                    "data.snapshot.json) под структуру features_vshgu.yml — не "
                    "агрегат v2/v3 по папкам, а честная пересборка по функциям.",
        },
        "run": run,
        "kpi": {
            "features_total": total, "features_covered": covered,
            "features_green": green, "features_yellow": yellow,
            "features_red": red, "features_grey": grey,
        },
        "areas": areas,
        "demo_fallback": build_demo(),
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
