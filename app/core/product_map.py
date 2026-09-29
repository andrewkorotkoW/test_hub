"""Карта продукта (страница «Покрытие» как схема продукта): зоны -> узлы (экраны/
функции) -> связи, со светофором покрытия по последнему прогону стенда.

Источник разметки — файл `<project_path>/tests/product_map.yml` (или `.yaml`/`.json`),
формат см. parse_layout(). Если файла нет (или он повреждён) — раскладка строится по
дереву разделов тестов (app.core.sections, тот же приём, что у формы запуска), без
падений: зона на каждый tests/api|ui|e2e, узел на раздел (подпапку).

Сопоставление узла с тестами — по префиксам путей/nodeid из поля `tests` узла, статус
светофора — тем же способом, что и app.core.xfail_registry/app.core.coverage: nodeid
(AST-скан tests/**/test_*.py) -> allure fullName -> статус из allure-results последнего
завершённого прогона стенда. Каждый модуль хранит свою копию `_nodeid_to_full_name` по
уже сложившемуся в проекте соглашению (см. комментарий в xfail_registry) — тянуть ради
одной функции межмодульную зависимость не стоит.

Кэш — JSON на диск (app.core.coverage/app.core.sections), но ключ инвалидации свой:
раскладка пересчитывается при изменении файла карты (или дерева тестов для fallback),
а статус каждого стенда — при появлении нового завершённого прогона на нём (см.
app.routers.product_map._cache_is_current)."""
from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

from ..config import settings
from . import allure_report, sections

PRODUCT_MAP_DIR = settings.WORKSPACE_DIR / "product_map"

_STATUS_PRIORITY = {"failed": 5, "broken": 4, "skipped": 3, "xfail": 2, "passed": 1, "unknown": 0}
_STATE_BY_STATUS = {
    "failed": "red", "broken": "red",
    "skipped": "yellow", "xfail": "yellow",
    "passed": "green",
    "unknown": "grey",
}
_KIND_LABELS = {"api": "API", "ui": "UI", "e2e": "E2E"}


class ProductMapError(ValueError):
    """Некорректный файл карты продукта — вызывающая сторона (load_layout) ловит
    её сама и откатывается на схему по дереву тестов, наружу не пробрасывается."""


# ------------------------------------------------------------------ разбор/валидация файла карты

def _require_str(d: dict, key: str, where: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductMapError(f"{where}: поле {key!r} обязательно и должно быть непустой строкой")
    return value


def _num(d: dict, key: str, default: float = 0.0) -> float:
    value = d.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProductMapError(f"поле {key!r} должно быть числом, получено {value!r}")
    return float(value)


def _normalize_tests(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raise ProductMapError("поле 'tests' узла должно быть списком строк")
    return list(raw)


def parse_layout(data: object) -> dict:
    """Валидирует и нормализует уже распарсенный YAML/JSON карты продукта в
    {"zones", "nodes", "edges", "canvas"}. Формат:
    zones: [{id, label, x, y, w, h}]
    nodes: [{id, label, zone, x, y, w, h, tests: [префиксы nodeid/пути], target?: id узла}]
    edges: [{from, to}]
    canvas: {width, height}  (необязательно — иначе считается по границам зон)."""
    if not isinstance(data, dict):
        raise ProductMapError("карта продукта должна быть объектом верхнего уровня")

    raw_zones = data.get("zones")
    raw_nodes = data.get("nodes")
    if not isinstance(raw_zones, list) or not raw_zones:
        raise ProductMapError("карта продукта должна содержать непустой список 'zones'")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ProductMapError("карта продукта должна содержать непустой список 'nodes'")

    zones = []
    zone_ids: set[str] = set()
    for raw_zone in raw_zones:
        if not isinstance(raw_zone, dict):
            raise ProductMapError("каждая зона должна быть объектом")
        zone_id = _require_str(raw_zone, "id", "zone")
        if zone_id in zone_ids:
            raise ProductMapError(f"повторяющийся id зоны: {zone_id!r}")
        zone_ids.add(zone_id)
        zones.append({
            "id": zone_id,
            "label": _require_str(raw_zone, "label", f"zone {zone_id!r}"),
            "x": _num(raw_zone, "x"), "y": _num(raw_zone, "y"),
            "w": _num(raw_zone, "w"), "h": _num(raw_zone, "h"),
        })

    nodes = []
    node_ids: set[str] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise ProductMapError("каждый узел должен быть объектом")
        node_id = _require_str(raw_node, "id", "node")
        if node_id in node_ids:
            raise ProductMapError(f"повторяющийся id узла: {node_id!r}")
        node_ids.add(node_id)
        zone_ref = _require_str(raw_node, "zone", f"node {node_id!r}")
        if zone_ref not in zone_ids:
            raise ProductMapError(f"узел {node_id!r} ссылается на неизвестную зону {zone_ref!r}")
        target = raw_node.get("target")
        if target is not None and not isinstance(target, str):
            raise ProductMapError(f"узел {node_id!r}: поле 'target' должно быть строкой")
        nodes.append({
            "id": node_id,
            "label": _require_str(raw_node, "label", f"node {node_id!r}"),
            "zone": zone_ref,
            "x": _num(raw_node, "x"), "y": _num(raw_node, "y"),
            "w": _num(raw_node, "w"), "h": _num(raw_node, "h"),
            "tests": _normalize_tests(raw_node.get("tests")),
            "target": target,
        })

    for node in nodes:
        if node["target"] is not None and node["target"] not in node_ids:
            raise ProductMapError(f"узел {node['id']!r}: target {node['target']!r} — неизвестный узел")

    edges = []
    raw_edges = data.get("edges") or []
    if not isinstance(raw_edges, list):
        raise ProductMapError("поле 'edges' должно быть списком")
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            raise ProductMapError("каждая связь должна быть объектом")
        src = _require_str(raw_edge, "from", "edge")
        dst = _require_str(raw_edge, "to", "edge")
        if src not in node_ids or dst not in node_ids:
            raise ProductMapError(f"связь {src!r} -> {dst!r} ссылается на неизвестный узел")
        edges.append({"from": src, "to": dst})

    raw_canvas = data.get("canvas")
    if raw_canvas is not None and not isinstance(raw_canvas, dict):
        raise ProductMapError("поле 'canvas' должно быть объектом {width, height}")
    max_x = max((z["x"] + z["w"] for z in zones), default=100.0)
    max_y = max((z["y"] + z["h"] for z in zones), default=100.0)
    canvas = {
        "width": _num(raw_canvas or {}, "width", max_x + 30),
        "height": _num(raw_canvas or {}, "height", max_y + 30),
    }

    return {"zones": zones, "nodes": nodes, "edges": edges, "canvas": canvas}


def _map_file_path(project_path: str) -> Path | None:
    tests_dir = Path(project_path) / "tests"
    for name in ("product_map.yml", "product_map.yaml", "product_map.json"):
        candidate = tests_dir / name
        if candidate.is_file():
            return candidate
    return None


def _load_map_file(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


# ------------------------------------------------------------------ fallback: дерево тестов

def _fallback_layout(project_path: str) -> dict:
    """Зона на каждый tests/api|ui|e2e, узел на раздел (подпапку) — то же дерево, что
    у формы запуска (app.core.sections.discover), только разложенное колонками слева
    направо с процедурными координатами (реальных координат для fallback-раскладки
    взять неоткуда — у неё нет утверждённого макета)."""
    tree = sections.discover(project_path)
    zone_w, zone_gap, node_h, node_gap_y, header_h, zone_x0, zone_y = 260, 20, 40, 15, 60, 30, 40

    zones: list[dict] = []
    nodes: list[dict] = []
    zone_x = zone_x0
    for kind_node in tree["kinds"]:
        areas = kind_node["areas"]
        zone_h = header_h + len(areas) * (node_h + node_gap_y)
        zones.append({
            "id": kind_node["kind"],
            "label": _KIND_LABELS.get(kind_node["kind"], kind_node["kind"].upper()),
            "x": zone_x, "y": zone_y, "w": zone_w, "h": zone_h,
        })
        for i, area in enumerate(areas):
            nodes.append({
                "id": f"{kind_node['kind']}:{area['section']}",
                "label": area["area"] or _KIND_LABELS.get(kind_node["kind"], kind_node["kind"].upper()),
                "zone": kind_node["kind"],
                "x": zone_x + 15, "y": zone_y + header_h + i * (node_h + node_gap_y),
                "w": zone_w - 30, "h": node_h,
                "tests": [area["target"]],
                "target": None,
            })
        zone_x += zone_w + zone_gap

    max_y = max((z["y"] + z["h"] for z in zones), default=zone_y + header_h)
    return {
        "zones": zones, "nodes": nodes, "edges": [],
        "canvas": {"width": zone_x + 10, "height": max_y + 30},
    }


def map_signature(project_path: str) -> list:
    """Дёшево посчитать признак изменения раскладки: для файла — путь/mtime/размер,
    для fallback — mtime_signature дерева тестов (app.core.sections)."""
    map_path = _map_file_path(project_path)
    if map_path is not None:
        stat = map_path.stat()
        return ["file", str(map_path), round(stat.st_mtime, 3), stat.st_size]
    return ["fallback", *sections.mtime_signature(project_path)]


def load_layout(project_path: str) -> dict:
    """{"source": "file"|"fallback", "message": str|None, "zones", "nodes", "edges",
    "canvas"} — если файла карты нет или он не проходит валидацию, откат на
    _fallback_layout() без исключений наружу."""
    map_path = _map_file_path(project_path)
    if map_path is None:
        fallback = _fallback_layout(project_path)
        return {
            **fallback, "source": "fallback",
            "message": "Файл карты продукта не найден (tests/product_map.yml) — схема построена по дереву тестов.",
        }
    try:
        data = _load_map_file(map_path)
        layout = parse_layout(data)
        return {**layout, "source": "file", "message": None}
    except (ProductMapError, yaml.YAMLError, ValueError, OSError) as exc:
        fallback = _fallback_layout(project_path)
        return {
            **fallback, "source": "fallback",
            "message": f"Карта продукта {map_path.name} повреждена ({exc}) — схема построена по дереву тестов.",
        }


# ------------------------------------------------------------------ nodeid <-> fullName, статус

def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid -> allure fullName — своя копия, см. описание модуля."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def _classify_allure_status(entry: dict) -> str:
    if entry["status"] == "skipped" and entry.get("message") and "xfail" in entry["message"].lower():
        return "xfail"
    return entry["status"]


def _latest_finished_run(conn: sqlite3.Connection, project: str, stand: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM runs WHERE project = ? AND stand = ? AND status IN ('passed', 'failed', 'cancelled') "
        "ORDER BY id DESC LIMIT 1",
        (project, stand),
    ).fetchone()


def latest_run_id(conn: sqlite3.Connection, project: str, stand: str) -> int | None:
    run = _latest_finished_run(conn, project, stand)
    return run["id"] if run else None


def _discover_test_nodeids(project_path: str) -> list[str]:
    """Все pytest nodeid тестов проекта (tests/**/test_*.py) — тот же AST-обход, что
    в app.core.xfail_registry.scan_static, только без фильтра по xfail-маркеру."""
    root = Path(project_path) / "tests"
    nodeids: list[str] = []
    if not root.is_dir():
        return nodeids

    for file_path in sorted(root.glob("**/test_*.py")):
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = file_path.relative_to(project_path).as_posix()

        def _handle(func_node: ast.FunctionDef | ast.AsyncFunctionDef, cls_name: str | None) -> None:
            if not func_node.name.startswith("test_"):
                return
            nodeids.append(f"{rel}::" + (f"{cls_name}::" if cls_name else "") + func_node.name)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _handle(node, None)
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _handle(sub, node.name)

    return nodeids


def _test_matches_prefix(nodeid: str, prefix: str) -> bool:
    """nodeid узла карты продукта сопоставляется с префиксом из поля `tests` — префикс
    может быть каталогом (tests/api/orders), файлом без расширения
    (tests/api/orders/test_orders) или полноценным nodeid с ::Class::test — сравнение
    всегда идёт по сегментам пути, а не наивным str.startswith (иначе "tests/api/order"
    ошибочно поймал бы "tests/api/orders")."""
    file_part, _, rest = nodeid.partition("::")
    file_no_ext = file_part[:-3] if file_part.endswith(".py") else file_part
    candidate = file_no_ext if not rest else f"{file_no_ext}::{rest}"

    prefix_norm = prefix[:-3] if prefix.endswith(".py") else prefix
    prefix_norm = prefix_norm.rstrip("/")

    if candidate == prefix_norm or candidate.startswith(prefix_norm + "::"):
        return True
    return file_no_ext == prefix_norm or file_no_ext.startswith(prefix_norm + "/")


def _test_display_name(nodeid: str) -> str:
    segments = nodeid.split("::")
    return "::".join(segments[-2:]) if len(segments) > 2 else segments[-1]


def _node_status(node: dict, all_nodeids: list[str], by_full_name: dict[str, str], run_id: int | None) -> dict:
    matched = sorted({nid for nid in all_nodeids if any(_test_matches_prefix(nid, p) for p in node["tests"])})
    empty_counts = {"api": 0, "ui": 0, "other": 0, "total": 0}
    if not matched:
        return {"state": "grey", "run_id": run_id, "tests_count": empty_counts, "sample_tests": []}

    counts = {"api": 0, "ui": 0, "other": 0}
    for nid in matched:
        file_part = nid.split("::", 1)[0]
        if file_part.startswith("tests/api/"):
            counts["api"] += 1
        elif file_part.startswith("tests/ui/"):
            counts["ui"] += 1
        else:
            counts["other"] += 1

    statuses = [by_full_name.get(_nodeid_to_full_name(nid), "unknown") for nid in matched]
    worst = max(statuses, key=lambda s: _STATUS_PRIORITY.get(s, 0))
    return {
        "state": _STATE_BY_STATUS.get(worst, "grey"),
        "run_id": run_id,
        "tests_count": {**counts, "total": len(matched)},
        "sample_tests": [{"nodeid": nid, "name": _test_display_name(nid)} for nid in matched[:5]],
    }


# ------------------------------------------------------------------ публичный API: recalc/load_cached

def cache_path(project_name: str) -> Path:
    return PRODUCT_MAP_DIR / project_name / "product_map.json"


def recalc(project_name: str, conn: sqlite3.Connection) -> dict:
    """Пересчитывает карту продукта (раскладку + статус каждого узла на каждом
    зарегистрированном стенде) и кладёт результат в
    workspace/product_map/<project>/product_map.json."""
    project = conn.execute("SELECT * FROM projects WHERE name = ?", (project_name,)).fetchone()
    if project is None:
        raise ValueError(f"проект {project_name} не найден")
    stands = [
        row["name"]
        for row in conn.execute("SELECT name FROM stands WHERE project = ? ORDER BY name", (project_name,)).fetchall()
    ]

    layout = load_layout(project["path"])
    all_nodeids = _discover_test_nodeids(project["path"])

    stands_out: dict[str, dict] = {}
    for stand in stands:
        run_id = latest_run_id(conn, project_name, stand)
        entries = allure_report.parse_results(_allure_dir(run_id)) if run_id is not None else []
        by_full_name = {entry["name"]: _classify_allure_status(entry) for entry in entries}
        nodes_status = {
            node["id"]: _node_status(node, all_nodeids, by_full_name, run_id) for node in layout["nodes"]
        }
        stands_out[stand] = {"run_id": run_id, "nodes": nodes_status}

    result = {
        "project": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": layout["source"],
        "message": layout["message"],
        "map_signature": map_signature(project["path"]),
        "canvas": layout["canvas"],
        "zones": layout["zones"],
        "nodes": layout["nodes"],
        "edges": layout["edges"],
        "stands": stands_out,
    }

    out_path = cache_path(project_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_cached(project_name: str) -> dict | None:
    path = cache_path(project_name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
