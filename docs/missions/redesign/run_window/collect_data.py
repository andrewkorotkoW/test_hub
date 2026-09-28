"""Выгружает реальные данные test_hub для мокапа docs/missions/redesign/run_window/mockups.html.

Не часть app/ui — вспомогательный скрипт для этапа 1 (только макеты), см. миссию
docs/missions/2026-09-29_run_window_coverage_map.md. Ничего не исполняет, кроме чтения
уже готовых workspace/test_hub.db, workspace/allure-results/<run_id>/*-result.json,
workspace/sections/<project>/sections.json и workspace/coverage/<project>/coverage.json.

В этом worktree (`cyber_office/workspace/worktrees/c26fcb90`) `workspace/test_hub.db`
пустой (свежий git worktree, см. соседние мокапы redesign/v2 и redesign/variants) —
поэтому источник данных передаётся явно через --repo (путь к рабочему репозиторию
test_hub с реальной историей прогонов), а не берётся из settings.DB_PATH текущего
воркдира. Запуск:

    python3 collect_data.py --repo /Users/andreykorotkow/PycharmProjects/test_hub \
        --project auto_tests_vshgu_cloude > data.snapshot.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

# Конвертер nodeid -> allure fullName — 1:1 копия app/core/coverage.py::_nodeid_to_full_name
# (не импортируем app.*, чтобы скрипт не зависел от FastAPI/settings и работал системным python3).
def nodeid_to_full_name(nodeid: str) -> str:
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


RESULT_LINE_RE = re.compile(
    r"^(?P<nodeid>\S+\.py::\S+?)\s+(?P<status>PASSED|FAILED|SKIPPED|XFAIL|XPASS|RERUN|ERROR)\s+\[\s*(?P<pct>\d+)%\]"
)
STATUS_MAP = {
    "PASSED": "passed", "XPASS": "passed", "FAILED": "failed", "ERROR": "failed",
    "SKIPPED": "skipped", "XFAIL": "xfail", "RERUN": "rerun",
}


def kind_area_of(nodeid: str) -> tuple[str, str | None]:
    file_part = nodeid.split("::", 1)[0]
    parts = file_part.split("/")
    # tests/<kind>/<area>/... .py — тот же контур, что и app/core/sections.py::_scan_kind
    if len(parts) >= 3 and parts[0] == "tests" and parts[1] in ("api", "ui"):
        return parts[1], parts[2]
    if len(parts) >= 2 and parts[0] == "tests" and parts[1] == "e2e":
        return "e2e", None
    return parts[1] if len(parts) > 1 else "?", None


def collect_run_and_tests(conn: sqlite3.Connection, repo: Path, project: str) -> tuple[dict, list[dict], dict]:
    row = conn.execute(
        "SELECT id, project, stand, target, status, started, finished, duration, counts "
        "FROM runs WHERE project = ? ORDER BY id DESC LIMIT 1",
        (project,),
    ).fetchone()
    run_id, _, stand, target, status, started, finished, duration, counts_raw = row
    counts = json.loads(counts_raw)

    events = conn.execute(
        "SELECT ts, line FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()

    # allure-results: точные длительности/сообщения/трейсы по fullName.
    allure_dir = repo / "workspace" / "allure-results" / str(run_id)
    allure_by_full_name: dict[str, dict] = {}
    for path in sorted(allure_dir.glob("*-result.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        full_name = data.get("fullName") or data.get("name")
        start, stop = data.get("start"), data.get("stop")
        duration_s = (stop - start) / 1000.0 if isinstance(start, (int, float)) and isinstance(stop, (int, float)) else None
        allure_by_full_name[full_name] = {
            "path": path,
            "display_name": data.get("name"),
            "status": data.get("status"),
            "duration": duration_s,
            "message": (data.get("statusDetails") or {}).get("message"),
            "trace": (data.get("statusDetails") or {}).get("trace"),
            "steps": data.get("steps") or [],
        }

    # Финальный статус по nodeid (последняя строка результата — реран замещает предыдущую попытку).
    order = 0
    last_by_nodeid: dict[str, dict] = {}
    for ts, line in events:
        m = RESULT_LINE_RE.match(line)
        if not m:
            continue
        order += 1
        nodeid = m.group("nodeid")
        pytest_status = STATUS_MAP[m.group("status")]
        last_by_nodeid[nodeid] = {
            "ts": ts, "order": order, "pytest_status": pytest_status,
            "raw": m.group("status"), "pct": int(m.group("pct")),
        }

    tests = []
    for nodeid, info in last_by_nodeid.items():
        if info["pytest_status"] == "rerun":
            continue  # промежуточная попытка, финальный статус придёт следующей строкой
        kind, area = kind_area_of(nodeid)
        full_name = nodeid_to_full_name(nodeid)
        allure = allure_by_full_name.get(full_name)
        tests.append({
            "nodeid": nodeid,
            "short": nodeid.split("::")[-1],
            "file": nodeid.split("::", 1)[0],
            "kind": kind,
            "area": area,
            "status": info["pytest_status"],
            "order": info["order"],
            "ts": info["ts"],
            "pct": info["pct"],
            "duration": round(allure["duration"], 2) if allure and allure["duration"] is not None else None,
            "display_name": allure["display_name"] if allure else None,
            "has_allure": allure is not None,
        })
    tests.sort(key=lambda t: t["order"])

    run_out = {
        "id": run_id, "project": project, "stand": stand, "target": target, "status": status,
        "started": started, "finished": finished, "duration_sec": duration, "counts": counts,
        "total_lines": order, "total_tests": len(tests),
    }
    return run_out, tests, allure_by_full_name


def pick_examples(tests: list[dict], allure_by_full_name: dict, repo: Path, run_id: int) -> dict:
    """Разворачивает консоль/шаги для нескольких показательных тестов: упавший API
    (с реальными HTTP-строками), упавший и падающий по таймауту UI (с реальными
    allure-шагами), прошедший UI, прошедший и пропущенный API — все статусы реальные."""
    wanted_nodeids = []
    by_status_kind: dict[tuple[str, str], list[dict]] = {}
    for t in tests:
        by_status_kind.setdefault((t["status"], t["kind"]), []).append(t)

    def take(status: str, kind: str, n: int = 1) -> list[dict]:
        return by_status_kind.get((status, kind), [])[:n]

    wanted = (
        take("failed", "api", 1)
        + take("failed", "ui", 2)
        + take("broken" if by_status_kind.get(("broken", "ui")) else "failed", "ui", 0)
        + take("passed", "ui", 1)
        + take("passed", "api", 1)
        + take("skipped", "api", 1)
        + take("xfail", "api", 1)
    )
    # статус "broken" в allure не совпадает с pytest FAILED/PASSED напрямую — берём его отдельно
    # среди тестов, у которых allure-статус broken (таймаут Playwright), через full_name.
    broken_examples = [
        (full_name, data) for full_name, data in allure_by_full_name.items() if data["status"] == "broken"
    ][:1]

    examples: dict[str, dict] = {}

    def full_name_for(nodeid: str) -> str:
        return nodeid_to_full_name(nodeid)

    for t in wanted:
        full_name = full_name_for(t["nodeid"])
        allure = allure_by_full_name.get(full_name)
        examples[t["nodeid"]] = {
            "kind": t["kind"], "status": t["status"],
            "display_name": allure["display_name"] if allure else t["short"],
            "message": allure["message"] if allure else None,
            "steps": [
                {"name": s.get("name"), "status": s.get("status"),
                 "duration": round((s.get("stop", 0) - s.get("start", 0)) / 1000.0, 1)}
                for s in (allure["steps"] if allure else [])
            ],
        }

    for full_name, allure in broken_examples:
        # найдём nodeid этого теста по совпадению display в tests (kind_area_of по файлу из fullName)
        matching = [t for t in tests if nodeid_to_full_name(t["nodeid"]) == full_name]
        if not matching:
            continue
        t = matching[0]
        examples[t["nodeid"]] = {
            "kind": t["kind"], "status": "broken",
            "display_name": allure["display_name"],
            "message": allure["message"],
            "steps": [
                {"name": s.get("name"), "status": s.get("status"),
                 "duration": round((s.get("stop", 0) - s.get("start", 0)) / 1000.0, 1)}
                for s in allure["steps"]
            ],
        }

    return examples


DIVIDER_RE = re.compile(r"^_+\s*(.+?)\s*_+$")


def _class_dot_test(nodeid: str) -> str:
    """tests/x/test_y.py::TestClass::test_z[params] -> 'TestClass.test_z' — так pytest
    подписывает блок в секции FAILURES (см. divider-строку __________ Class.test __________)."""
    _, _, rest = nodeid.partition("::")
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    if len(segments) > 1:
        return f"{segments[-2]}.{test}"
    return test


def console_lines_for(conn: sqlite3.Connection, run_id: int, nodeid: str) -> list[str]:
    """Реальная консоль этого теста: строка объявления результата (то, что pytest
    печатает по ходу прогона) плюс — если тест упал/сломался — его блок из секции
    FAILURES (traceback, HTTP-запросы/ответы, captured log). Для прошедших/пропущенных
    тестов pytest по умолчанию ничего, кроме итоговой строки, не печатает — это не
    урезание данных, а реальное поведение раннера (verbose-режим без -s)."""
    rows = conn.execute(
        "SELECT id, line FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    lines = []
    for _, line in rows:
        m = RESULT_LINE_RE.match(line)
        if m and m.group("nodeid") == nodeid:
            lines.append(line)

    class_dot_test = _class_dot_test(nodeid)
    in_failures = False
    in_block = False
    block: list[str] = []
    for _, line in rows:
        if "FAILURES" in line and line.strip("= ") == "FAILURES":
            in_failures = True
            continue
        if "short test summary info" in line:
            break
        if not in_failures:
            continue
        m = DIVIDER_RE.match(line)
        if m:
            if in_block:
                break  # следующий блок FAILURES — наш уже закончился
            in_block = m.group(1) == class_dot_test
            continue
        if in_block:
            block.append(line)

    return lines + (["", "=" * 35 + " FAILURES " + "=" * 35] + block if block else [])


def collect_sections(repo: Path, project: str) -> list[dict]:
    path = repo / "workspace" / "sections" / project / "sections.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    by_area: dict[str, dict] = {}
    for kind_entry in data["kinds"]:
        kind = kind_entry["kind"]
        for area_entry in kind_entry["areas"]:
            area = area_entry["area"] or "e2e"
            rec = by_area.setdefault(area, {"area": area, "api": 0, "ui": 0, "e2e": 0, "files": 0})
            rec[kind] += area_entry["tests_count"]
            rec["files"] += len(area_entry["files"])
    return sorted(by_area.values(), key=lambda r: -(r["api"] + r["ui"] + r["e2e"]))


def apply_run_status_to_sections(sections: list[dict], tests: list[dict]) -> None:
    priority = {"failed": 4, "broken": 4, "xfail": 3, "skipped": 2, "passed": 1}
    worst: dict[str, str] = {}
    for t in tests:
        area = t["area"] or "e2e"
        cur = worst.get(area)
        if cur is None or priority.get(t["status"], 0) > priority.get(cur, 0):
            worst[area] = t["status"]
    for rec in sections:
        rec["run_status"] = worst.get(rec["area"], "not_executed")


ROUTE_AREA_RE = re.compile(r"^/api/v1/([^/]+)")


def route_area(path: str) -> str:
    m = ROUTE_AREA_RE.match(path)
    if m:
        return m.group(1)
    return "служебные"


def collect_coverage(repo: Path, project: str) -> dict:
    path = repo / "workspace" / "coverage" / project / "coverage.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    areas: dict[str, dict] = {}
    for route in data["routes"]:
        area = route_area(route["path"])
        rec = areas.setdefault(area, {"area": area, "total": 0, "covered": 0})
        rec["total"] += 1
        if route["covered"]:
            rec["covered"] += 1
    areas_out = sorted(areas.values(), key=lambda r: -r["total"])

    pages_out = []
    for page in data["pages"]:
        nodeids_by_kind: dict[str, list[str]] = {"api": [], "ui": [], "e2e": []}
        for t in page["tests"]:
            kind, _ = kind_area_of(t["nodeid"])
            if kind in nodeids_by_kind:
                nodeids_by_kind[kind].append(t["nodeid"])
        states = [st["state"] for st in page["status"].values()]
        best = "not_covered"
        for candidate in ("failed", "xfail", "passed", "not_executed", "no_tests_for_stand", "not_covered"):
            if candidate in states:
                best = candidate
                break
        pages_out.append({
            "path": page["path"], "covered": page["covered"], "state": best,
            "api": nodeids_by_kind["api"], "ui": nodeids_by_kind["ui"], "e2e": nodeids_by_kind["e2e"],
        })

    # компактная выборка маршрутов на область для санбёрста (реальные, без урезания статистики).
    routes_sample: dict[str, list[dict]] = {}
    for route in data["routes"]:
        area = route_area(route["path"])
        routes_sample.setdefault(area, []).append({
            "path": route["path"], "methods": route["methods"], "covered": route["covered"],
        })

    return {
        "generated_at": data["generated_at"], "stands": data["stands"],
        "routes_total": data["routes_total"], "routes_covered": data["routes_covered"],
        "pages_total": data["pages_total"], "pages_covered": data["pages_covered"],
        "test_status": data["test_status"],
        "areas": areas_out, "pages": pages_out, "routes_by_area": routes_sample,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--project", default="auto_tests_vshgu_cloude")
    args = parser.parse_args()

    db_path = args.repo / "workspace" / "test_hub.db"
    conn = sqlite3.connect(db_path)
    try:
        run_out, tests, allure_by_full_name = collect_run_and_tests(conn, args.repo, args.project)
        examples = pick_examples(tests, allure_by_full_name, args.repo, run_out["id"])
        for nodeid in list(examples):
            examples[nodeid]["console"] = console_lines_for(conn, run_out["id"], nodeid)
        sections = collect_sections(args.repo, args.project)
        apply_run_status_to_sections(sections, tests)
        coverage = collect_coverage(args.repo, args.project)
    finally:
        conn.close()

    result = {
        "meta": {
            "source_repo": str(args.repo),
            "project": args.project,
            "note": "Снимок реальной БД test_hub с историей прогонов (см. workspace-mtime), "
                    "не текущий пустой worktree — см. заметку в mockups.html.",
        },
        "run": run_out,
        "tests": tests,
        "examples": examples,
        "sections": sections,
        "coverage": coverage,
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
