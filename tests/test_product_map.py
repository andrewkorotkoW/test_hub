"""Юнит-тесты app/core/product_map.py: разбор и валидация tests/product_map.yml
(parse_layout/load_layout), fallback по дереву разделов тестов (без файла карты)
и расчёт светофора узла по allure-results прогона (recalc()) — по образцу
tests/test_xfail.py (nodeid -> fullName -> allure-results на фикстурных
allure-results, без .venv и без боевого проекта VSHGU).

app.core.product_map.PRODUCT_MAP_DIR вычисляется один раз при импорте модуля
(settings.WORKSPACE_DIR / "product_map"), поэтому изолируется монки-патчем
самого атрибута модуля (см. tests/test_coverage_api.py::isolated_coverage_dir),
а не settings.WORKSPACE_DIR."""

import json

import pytest
import yaml

from app.core import product_map
from app.db import get_connection

PROJECT = "pm_proj"
STAND = "stage"


# ------------------------------------------------------------------ фикстуры

@pytest.fixture()
def isolated_product_map_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(product_map, "PRODUCT_MAP_DIR", tmp_path / "product_map")


VALID_MAP = {
    "zones": [
        {"id": "main", "label": "Основное", "x": 0, "y": 0, "w": 400, "h": 300},
        {"id": "int", "label": "Интеграции", "x": 0, "y": 320, "w": 400, "h": 60},
    ],
    "nodes": [
        {"id": "orders", "label": "Заказы", "zone": "main", "x": 10, "y": 10, "w": 120, "h": 40,
         "tests": ["tests/api/orders"]},
        {"id": "orders_ui", "label": "Заказы (UI)", "zone": "main", "x": 10, "y": 60, "w": 120, "h": 40,
         "tests": ["tests/ui/orders/test_orders_ui"]},
        {"id": "empty_screen", "label": "Без тестов", "zone": "main", "x": 10, "y": 110, "w": 120, "h": 40},
        {"id": "health", "label": "Здоровье", "zone": "main", "x": 10, "y": 160, "w": 120, "h": 40,
         "tests": ["tests/api/health"]},
        {"id": "flow", "label": "Сквозной сценарий", "zone": "main", "x": 10, "y": 210, "w": 120, "h": 40,
         "tests": ["tests/e2e"]},
        {"id": "gateway", "label": "Платёжный шлюз", "zone": "int", "x": 10, "y": 330, "w": 120, "h": 30},
    ],
    "edges": [{"from": "orders", "to": "orders_ui"}],
}


def _write_map(tests_dir, data=None, filename="product_map.yml", raw_text=None):
    tests_dir.mkdir(parents=True, exist_ok=True)
    path = tests_dir / filename
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
    elif filename.endswith(".json"):
        path.write_text(json.dumps(data if data is not None else VALID_MAP), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data if data is not None else VALID_MAP, allow_unicode=True), encoding="utf-8")
    return path


_ORDERS_TESTS_SRC = '''\
def test_list_orders():
    assert True


def test_get_order():
    assert True


def test_create_order():
    assert True


def test_update_order():
    assert True


def test_delete_order():
    assert True


def test_search_orders():
    assert True
'''

_ORDERS_UI_SRC = '''\
def test_open_orders():
    assert True
'''

_HEALTH_SRC = '''\
def test_ping():
    assert True
'''

_E2E_SRC = '''\
def test_full_checkout():
    assert True
'''


@pytest.fixture()
def pm_project_dir(tmp_path):
    proj = tmp_path / "pm_src_proj"
    (proj / "tests" / "api" / "orders").mkdir(parents=True)
    (proj / "tests" / "api" / "orders" / "test_orders.py").write_text(_ORDERS_TESTS_SRC)
    (proj / "tests" / "ui" / "orders").mkdir(parents=True)
    (proj / "tests" / "ui" / "orders" / "test_orders_ui.py").write_text(_ORDERS_UI_SRC)
    (proj / "tests" / "api" / "health").mkdir(parents=True)
    (proj / "tests" / "api" / "health" / "test_health.py").write_text(_HEALTH_SRC)
    (proj / "tests" / "e2e").mkdir(parents=True)
    (proj / "tests" / "e2e" / "test_checkout.py").write_text(_E2E_SRC)
    return proj


# ------------------------------------------------------------------ parse_layout: валидация

def test_parse_layout_valid_map():
    layout = product_map.parse_layout(VALID_MAP)
    assert {z["id"] for z in layout["zones"]} == {"main", "int"}
    assert {n["id"] for n in layout["nodes"]} == {
        "orders", "orders_ui", "empty_screen", "health", "flow", "gateway",
    }
    assert layout["edges"] == [{"from": "orders", "to": "orders_ui"}]
    # canvas не задан явно -> считается по границам зон (max x+w, max y+h) + 30
    assert layout["canvas"] == {"width": 400 + 30, "height": 380 + 30}
    empty = next(n for n in layout["nodes"] if n["id"] == "empty_screen")
    assert empty["tests"] == []
    assert empty["target"] is None


def test_parse_layout_explicit_canvas_used():
    data = {**VALID_MAP, "canvas": {"width": 999, "height": 888}}
    layout = product_map.parse_layout(data)
    assert layout["canvas"] == {"width": 999, "height": 888}


def test_parse_layout_not_a_dict():
    with pytest.raises(product_map.ProductMapError):
        product_map.parse_layout([1, 2, 3])


def test_parse_layout_missing_zones():
    data = {"nodes": VALID_MAP["nodes"]}
    with pytest.raises(product_map.ProductMapError, match="zones"):
        product_map.parse_layout(data)


def test_parse_layout_missing_nodes():
    data = {"zones": VALID_MAP["zones"]}
    with pytest.raises(product_map.ProductMapError, match="nodes"):
        product_map.parse_layout(data)


def test_parse_layout_duplicate_zone_id():
    data = {**VALID_MAP, "zones": VALID_MAP["zones"] + [VALID_MAP["zones"][0]]}
    with pytest.raises(product_map.ProductMapError, match="повторяющийся id зоны"):
        product_map.parse_layout(data)


def test_parse_layout_duplicate_node_id():
    data = {**VALID_MAP, "nodes": VALID_MAP["nodes"] + [VALID_MAP["nodes"][0]]}
    with pytest.raises(product_map.ProductMapError, match="повторяющийся id узла"):
        product_map.parse_layout(data)


def test_parse_layout_node_unknown_zone():
    bad_node = {**VALID_MAP["nodes"][0], "id": "bad", "zone": "no_such_zone"}
    data = {**VALID_MAP, "nodes": VALID_MAP["nodes"] + [bad_node]}
    with pytest.raises(product_map.ProductMapError, match="неизвестную зону"):
        product_map.parse_layout(data)


def test_parse_layout_edge_unknown_node():
    data = {**VALID_MAP, "edges": [{"from": "orders", "to": "no_such_node"}]}
    with pytest.raises(product_map.ProductMapError, match="неизвестный узел"):
        product_map.parse_layout(data)


def test_parse_layout_edge_unknown_source_node():
    data = {**VALID_MAP, "edges": [{"from": "no_such_node", "to": "orders"}]}
    with pytest.raises(product_map.ProductMapError, match="неизвестный узел"):
        product_map.parse_layout(data)


def test_parse_layout_node_target_unknown_node():
    bad_node = {**VALID_MAP["nodes"][0], "id": "bad_target", "target": "no_such_node"}
    data = {**VALID_MAP, "nodes": VALID_MAP["nodes"] + [bad_node]}
    with pytest.raises(product_map.ProductMapError, match="target"):
        product_map.parse_layout(data)


def test_parse_layout_node_tests_not_list_of_strings():
    bad_node = {**VALID_MAP["nodes"][0], "id": "bad_tests", "tests": "tests/api/orders"}
    data = {**VALID_MAP, "nodes": VALID_MAP["nodes"] + [bad_node]}
    with pytest.raises(product_map.ProductMapError, match="tests"):
        product_map.parse_layout(data)


def test_parse_layout_missing_required_string_field():
    bad_zone = {"id": "z2", "x": 0, "y": 0, "w": 10, "h": 10}  # нет label
    data = {**VALID_MAP, "zones": VALID_MAP["zones"] + [bad_zone]}
    with pytest.raises(product_map.ProductMapError, match="label"):
        product_map.parse_layout(data)


def test_parse_layout_edges_not_a_list():
    data = {**VALID_MAP, "edges": {"from": "orders", "to": "orders_ui"}}
    with pytest.raises(product_map.ProductMapError, match="edges"):
        product_map.parse_layout(data)


# ------------------------------------------------------------------ load_layout: файл/fallback

def test_load_layout_reads_valid_yml_file(tmp_path):
    _write_map(tmp_path / "tests")
    layout = product_map.load_layout(str(tmp_path))
    assert layout["source"] == "file"
    assert layout["message"] is None
    assert {n["id"] for n in layout["nodes"]} == {n["id"] for n in VALID_MAP["nodes"]}


def test_load_layout_reads_valid_json_file(tmp_path):
    _write_map(tmp_path / "tests", filename="product_map.json")
    layout = product_map.load_layout(str(tmp_path))
    assert layout["source"] == "file"
    assert {z["id"] for z in layout["zones"]} == {"main", "int"}


def test_load_layout_missing_file_falls_back(tmp_path):
    layout = product_map.load_layout(str(tmp_path))
    assert layout["source"] == "fallback"
    assert "не найден" in layout["message"]
    assert layout["zones"] == []
    assert layout["nodes"] == []


def test_load_layout_broken_schema_falls_back(tmp_path):
    # edges ссылаются на несуществующий узел -> parse_layout бросает ProductMapError,
    # load_layout должен молча откатиться на fallback, а не пробросить исключение наружу
    bad = {**VALID_MAP, "edges": [{"from": "orders", "to": "no_such_node"}]}
    _write_map(tmp_path / "tests", data=bad)
    layout = product_map.load_layout(str(tmp_path))
    assert layout["source"] == "fallback"
    assert "повреждена" in layout["message"]
    assert "product_map.yml" in layout["message"]


def test_load_layout_broken_yaml_syntax_falls_back(tmp_path):
    _write_map(tmp_path / "tests", raw_text="zones: [this is not: valid: yaml:")
    layout = product_map.load_layout(str(tmp_path))
    assert layout["source"] == "fallback"
    assert "повреждена" in layout["message"]


def test_load_layout_prefers_yml_over_yaml_and_json(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "product_map.yml").write_text(yaml.safe_dump(VALID_MAP, allow_unicode=True), encoding="utf-8")
    other = {**VALID_MAP, "zones": [{"id": "other_zone", "label": "Другая", "x": 0, "y": 0, "w": 10, "h": 10}],
             "nodes": []}
    # nodes пуст -> other сам по себе некорректен, но это не важно: .yml должен победить раньше чтения .json
    (tests_dir / "product_map.json").write_text(json.dumps(other), encoding="utf-8")
    layout = product_map.load_layout(str(tmp_path))
    assert layout["source"] == "file"
    assert {z["id"] for z in layout["zones"]} == {"main", "int"}


# ------------------------------------------------------------------ fallback по дереву разделов

def test_fallback_layout_builds_zones_per_kind(pm_project_dir):
    layout = product_map.load_layout(str(pm_project_dir))
    assert layout["source"] == "fallback"
    zone_ids = {z["id"] for z in layout["zones"]}
    assert zone_ids == {"api", "ui", "e2e"}
    zone_labels = {z["id"]: z["label"] for z in layout["zones"]}
    assert zone_labels == {"api": "API", "ui": "UI", "e2e": "E2E"}
    assert layout["edges"] == []


def test_fallback_layout_node_per_area(pm_project_dir):
    layout = product_map.load_layout(str(pm_project_dir))
    nodes_by_id = {n["id"]: n for n in layout["nodes"]}
    assert nodes_by_id["api:api/orders"]["label"] == "orders"
    assert nodes_by_id["api:api/orders"]["zone"] == "api"
    assert nodes_by_id["api:api/orders"]["tests"] == ["tests/api/orders"]
    assert nodes_by_id["ui:ui/orders"]["label"] == "orders"
    assert nodes_by_id["e2e:e2e"]["label"] == "E2E"
    assert nodes_by_id["e2e:e2e"]["tests"] == ["tests/e2e"]


def test_fallback_layout_no_tests_dir_is_empty_without_crashing(tmp_path):
    layout = product_map.load_layout(str(tmp_path / "does_not_exist"))
    assert layout["source"] == "fallback"
    assert layout["zones"] == []
    assert layout["nodes"] == []
    assert layout["canvas"]["width"] > 0
    assert layout["canvas"]["height"] > 0


def test_map_signature_file_changes_with_mtime_and_size(tmp_path):
    path = _write_map(tmp_path / "tests")
    sig1 = product_map.map_signature(str(tmp_path))
    assert sig1[0] == "file"
    path.write_text(path.read_text(encoding="utf-8") + "\n# comment\n", encoding="utf-8")
    sig2 = product_map.map_signature(str(tmp_path))
    assert sig1 != sig2


def test_map_signature_fallback_matches_sections_mtime_signature(pm_project_dir):
    from app.core import sections
    assert product_map.map_signature(str(pm_project_dir)) == ["fallback", *sections.mtime_signature(str(pm_project_dir))]


# ------------------------------------------------------------------ recalc(): светофор по allure-results

def _insert_project_and_stand(conn, path):
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')",
        (PROJECT, str(path)),
    )
    conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
    conn.commit()


def _insert_run(conn, status="failed") -> int:
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, ?, 'all', ?, '2024-01-01T00:00:00', 'qa', '{}')",
        (PROJECT, STAND, status),
    )
    conn.commit()
    return cur.lastrowid


def _write_allure_result(results_dir, filename, full_name, status, message=None):
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fullName": full_name, "status": status}
    if message:
        payload["statusDetails"] = {"message": message}
    (results_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _fmap(module_dotted, test):
    return f"{module_dotted}#{test}"


def test_recalc_computes_traffic_light_per_node(
    db_path, isolated_allure_dir, isolated_product_map_dir, pm_project_dir
):
    from app.config import settings

    _write_map(pm_project_dir / "tests")

    conn = get_connection()
    try:
        _insert_project_and_stand(conn, pm_project_dir)
        run_id = _insert_run(conn)
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    orders_module = "tests.api.orders.test_orders"
    _write_allure_result(results_dir, "00-result.json", _fmap(orders_module, "test_list_orders"), "passed")
    _write_allure_result(results_dir, "01-result.json", _fmap(orders_module, "test_get_order"), "passed")
    _write_allure_result(results_dir, "02-result.json", _fmap(orders_module, "test_create_order"), "passed")
    _write_allure_result(results_dir, "03-result.json", _fmap(orders_module, "test_update_order"), "passed")
    _write_allure_result(results_dir, "04-result.json", _fmap(orders_module, "test_delete_order"), "failed")
    _write_allure_result(results_dir, "05-result.json", _fmap(orders_module, "test_search_orders"), "passed")
    _write_allure_result(
        results_dir, "06-result.json", _fmap("tests.ui.orders.test_orders_ui", "test_open_orders"),
        "skipped", message="XFAIL known limitation",
    )
    _write_allure_result(results_dir, "07-result.json", _fmap("tests.api.health.test_health", "test_ping"), "passed")
    _write_allure_result(results_dir, "08-result.json", _fmap("tests.e2e.test_checkout", "test_full_checkout"), "passed")

    conn = get_connection()
    try:
        result = product_map.recalc(PROJECT, conn)
    finally:
        conn.close()

    assert result["source"] == "file"
    stand_data = result["stands"][STAND]
    assert stand_data["run_id"] == run_id
    nodes = stand_data["nodes"]

    # 6 тестов покрывают orders, один упал -> красный, счётчики полные, sample_tests обрезаны до 5
    orders = nodes["orders"]
    assert orders["state"] == "red"
    assert orders["tests_count"] == {"api": 6, "ui": 0, "other": 0, "total": 6}
    assert len(orders["sample_tests"]) == 5

    # единственный тест skipped+xfail -> жёлтый
    orders_ui = nodes["orders_ui"]
    assert orders_ui["state"] == "yellow"
    assert orders_ui["tests_count"] == {"api": 0, "ui": 1, "other": 0, "total": 1}

    # узел без поля tests вовсе -> тестов нет -> серый, нулевые счётчики
    empty_screen = nodes["empty_screen"]
    assert empty_screen["state"] == "grey"
    assert empty_screen["tests_count"] == {"api": 0, "ui": 0, "other": 0, "total": 0}
    assert empty_screen["sample_tests"] == []

    # полностью проходящий узел -> зелёный
    health = nodes["health"]
    assert health["state"] == "green"
    assert health["tests_count"]["api"] == 1

    # e2e-тест вне tests/api и tests/ui -> учитывается как "other"
    flow = nodes["flow"]
    assert flow["state"] == "green"
    assert flow["tests_count"] == {"api": 0, "ui": 0, "other": 1, "total": 1}

    # узел без совпадающих тестов из фикстуры проекта -> тоже серый (тестов нет вообще)
    gateway = nodes["gateway"]
    assert gateway["state"] == "grey"
    assert gateway["tests_count"]["total"] == 0


def test_recalc_broken_status_maps_to_red(db_path, isolated_allure_dir, isolated_product_map_dir, pm_project_dir):
    from app.config import settings

    _write_map(pm_project_dir / "tests")
    conn = get_connection()
    try:
        _insert_project_and_stand(conn, pm_project_dir)
        run_id = _insert_run(conn)
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    _write_allure_result(results_dir, "00-result.json", _fmap("tests.api.health.test_health", "test_ping"), "broken")

    conn = get_connection()
    try:
        result = product_map.recalc(PROJECT, conn)
    finally:
        conn.close()

    assert result["stands"][STAND]["nodes"]["health"]["state"] == "red"


def test_recalc_node_with_tests_but_no_run_yet_is_grey_with_nonzero_count(
    db_path, isolated_allure_dir, isolated_product_map_dir, pm_project_dir
):
    """Узел, у которого есть покрывающие тесты, но на стенде ещё ни разу не было
    завершённого прогона (run_id is None) — тоже серый, но, в отличие от узла без
    тестов вовсе, tests_count.total > 0 (это различие использует всплывашка в UI,
    см. ui/coverage.js::showProductMapTip)."""
    _write_map(pm_project_dir / "tests")
    conn = get_connection()
    try:
        _insert_project_and_stand(conn, pm_project_dir)
    finally:
        conn.close()

    conn = get_connection()
    try:
        result = product_map.recalc(PROJECT, conn)
    finally:
        conn.close()

    stand_data = result["stands"][STAND]
    assert stand_data["run_id"] is None
    health = stand_data["nodes"]["health"]
    assert health["state"] == "grey"
    assert health["tests_count"]["total"] == 1


def test_recalc_unknown_project_raises(db_path, isolated_product_map_dir):
    conn = get_connection()
    try:
        with pytest.raises(ValueError, match="не найден"):
            product_map.recalc("no_such_project", conn)
    finally:
        conn.close()


def test_recalc_writes_and_load_cached_reads_back(
    db_path, isolated_allure_dir, isolated_product_map_dir, pm_project_dir
):
    _write_map(pm_project_dir / "tests")
    conn = get_connection()
    try:
        _insert_project_and_stand(conn, pm_project_dir)
    finally:
        conn.close()

    assert product_map.load_cached(PROJECT) is None

    conn = get_connection()
    try:
        result = product_map.recalc(PROJECT, conn)
    finally:
        conn.close()

    cached = product_map.load_cached(PROJECT)
    assert cached == result


def test_load_cached_missing_or_corrupt_returns_none(tmp_path, isolated_product_map_dir):
    assert product_map.load_cached("no_such_project") is None
    path = product_map.cache_path("no_such_project")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert product_map.load_cached("no_such_project") is None
