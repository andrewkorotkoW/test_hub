"""Тест-кейсы: собственная таблица test_cases поверх markdown-черновиков
auto_tests_vshgu (`docs/test_cases/*.md`, см. `tools/test_cases/testit_sync.py::
parse_area_file` в том репозитории — парсер здесь портирован под test_hub) и/или
ручного заведения.

Второй источник истины поверх allure, ровно по прецеденту app.core.xfail_registry:
import_drafts() апсертит записи по ключу (project, nodeid) с source='generated',
запись с source='manual' (выставляется update_case() при первой ручной правке)
повторным импортом не затирается — тот же приём, что recalc() в xfail_registry не
затирает issue_url/note.

Статус последнего прогона довешивается тем же способом, что и в xfail_registry/
flaky/coverage: nodeid -> allure fullName -> поиск в allure-results последнего
завершённого прогона стенда (app.core.stats.default_stand/latest_finished_run_id,
app.core.allure_report.parse_results)."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import settings
from . import allure_report, stats

TEMPLATE_FILE = "TEMPLATE.md"
UPDATE_MARK = "<!-- обновить -->"

HEADING_RE = re.compile(r"^### TC-[A-Za-z0-9_]+-\d+\s+(.+)$")
AUTOTEST_RE = re.compile(r"^-\s*Автотест:\s*(\S+)\s*$")
META_RE = re.compile(r"^-\s*Приоритет:\s*(\S+)\s+Тип:\s*(\S+)\s+Роли:\s*(.*)$")
PRECONDITION_RE = re.compile(r"^-\s*Предусловия:\s*(.*)$")

TESTCASES_DIR = settings.WORKSPACE_DIR / "testcases"


def attachments_dir(project: str, case_id: int) -> Path:
    return TESTCASES_DIR / project / str(case_id)


# ------------------------------------------------------------------ парсер markdown-черновиков


def _parse_table_row(line: str) -> tuple[str, str] | None:
    """"| 1 | действие | ожидаемый результат |" -> ("действие", "ожидаемый результат")."""
    line = line.strip()
    if not line.startswith("|") or not line.endswith("|"):
        return None
    parts = [p.strip() for p in line[1:-1].split("|")]
    if len(parts) != 3 or not parts[0].isdigit():
        return None
    return parts[1].replace("\\|", "|"), parts[2].replace("\\|", "|")


def _parse_case_block(block: list[str]) -> dict | None:
    heading = HEADING_RE.match(block[0])
    if heading is None:
        return None
    title = heading.group(1).strip()
    if title.endswith(UPDATE_MARK):
        title = title[: -len(UPDATE_MARK)].strip()

    nodeid: str | None = None
    priority = "medium"
    precondition: str | None = None
    steps: list[dict] = []

    for line in block[1:]:
        stripped = line.strip()
        m = AUTOTEST_RE.match(stripped)
        if m:
            nodeid = m.group(1)
            continue
        m = META_RE.match(stripped)
        if m:
            priority = m.group(1).lower()
            continue
        m = PRECONDITION_RE.match(stripped)
        if m:
            precondition = m.group(1).strip() or None
            continue
        row = _parse_table_row(stripped)
        if row:
            steps.append({"action": row[0], "expected": row[1]})

    return {"title": title, "nodeid": nodeid, "priority": priority, "precondition": precondition, "steps": steps}


def parse_area_file(path: Path) -> list[dict]:
    """Черновик области (`docs/test_cases/<area>.md`) -> список кейсов
    {title, nodeid, priority, precondition, steps: [{action, expected}]}.
    Портировано из auto_tests_vshgu `tools/test_cases/testit_sync.py::parse_area_file`,
    без полей, которых нет в схеме test_hub (tc_id/тип/роли/steps-hash/Test IT id)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    heading_idx = [i for i, l in enumerate(lines) if HEADING_RE.match(l)]

    cases = []
    for pos, start in enumerate(heading_idx):
        end = heading_idx[pos + 1] if pos + 1 < len(heading_idx) else len(lines)
        block = lines[start:end]
        while block and block[-1].strip() == "":
            block.pop()
        case = _parse_case_block(block)
        if case:
            cases.append(case)
    return cases


def _numbered_steps(raw_steps: list[dict]) -> list[dict]:
    return [
        {"n": i + 1, "action": s["action"], "expected": s["expected"], "attachments": []}
        for i, s in enumerate(raw_steps)
    ]


def _section_from_nodeid(nodeid: str) -> str:
    """Раздел кейса тем же приёмом, что и app.core.sections.discover(): nodeid
    `tests/api/buk/test_x.py::...` -> "api/buk" (у e2e — один раздел "e2e" без
    разбивки на области, см. app.core.sections/app.core.stats)."""
    file_part = nodeid.split("::", 1)[0]
    parts = Path(file_part).parts
    if parts and parts[0] == "tests":
        parts = parts[1:]
    if not parts:
        return "misc"
    kind = parts[0]
    if kind in ("api", "ui"):
        return f"{kind}/{parts[1]}" if len(parts) > 1 else kind
    if kind == "e2e":
        return "e2e"
    return kind


# ------------------------------------------------------------------ импорт черновиков


def import_drafts(conn: sqlite3.Connection, project_row: sqlite3.Row) -> dict:
    """Читает `<project.path>/docs/test_cases/*.md`, апсертит test_cases по ключу
    (project, nodeid) с source='generated'. Записи с уже выставленным
    source='manual' не трогает — повторный импорт не должен затирать ручные
    правки (см. описание модуля)."""
    docs_dir = Path(project_row["path"]) / "docs" / "test_cases"
    result = {"files": 0, "imported": 0, "updated": 0, "skipped_manual": 0}
    if not docs_dir.is_dir():
        return result

    project = project_row["name"]
    now = datetime.now().isoformat(timespec="seconds")

    for path in sorted(docs_dir.glob("*.md")):
        if path.name == TEMPLATE_FILE:
            continue
        result["files"] += 1
        for case in parse_area_file(path):
            if not case["nodeid"]:
                # Черновики без автотеста в этом конвейере не встречаются (см.
                # generate.py) — кейсы без nodeid заводятся вручную (create_manual).
                continue
            existing = conn.execute(
                "SELECT * FROM test_cases WHERE project = ? AND nodeid = ?", (project, case["nodeid"])
            ).fetchone()
            if existing and existing["source"] == "manual":
                result["skipped_manual"] += 1
                continue

            section = _section_from_nodeid(case["nodeid"])
            steps_json = json.dumps(_numbered_steps(case["steps"]), ensure_ascii=False)
            if existing:
                conn.execute(
                    "UPDATE test_cases SET section = ?, title = ?, steps = ?, precondition = ?, priority = ?, "
                    "source = 'generated', updated_at = ? WHERE id = ?",
                    (section, case["title"], steps_json, case["precondition"], case["priority"], now, existing["id"]),
                )
                result["updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO test_cases "
                    "(project, section, title, steps, precondition, priority, nodeid, source, updated_at, updated_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'generated', ?, NULL)",
                    (project, section, case["title"], steps_json, case["precondition"], case["priority"], case["nodeid"], now),
                )
                result["imported"] += 1

    conn.commit()
    return result


# ------------------------------------------------------------------ ручное создание/правка


def create_manual(
    conn: sqlite3.Connection,
    project: str,
    section: str,
    title: str,
    precondition: str | None,
    priority: str,
    steps: list[dict],
    nodeid: str | None,
    user_login: str,
) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    steps_json = json.dumps(_numbered_steps(steps), ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO test_cases "
        "(project, section, title, steps, precondition, priority, nodeid, source, updated_at, updated_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)",
        (project, section, title, steps_json, precondition, priority, nodeid, now, user_login),
    )
    conn.commit()
    return get_case(conn, project, cur.lastrowid)


def update_case(
    conn: sqlite3.Connection,
    case_id: int,
    title: str,
    precondition: str | None,
    priority: str,
    steps: list[dict],
    nodeid: str | None,
    user_login: str,
) -> dict | None:
    row = conn.execute("SELECT project FROM test_cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        return None
    now = datetime.now().isoformat(timespec="seconds")
    steps_json = json.dumps(_numbered_steps(steps), ensure_ascii=False)
    conn.execute(
        "UPDATE test_cases SET title = ?, precondition = ?, priority = ?, steps = ?, nodeid = ?, "
        "source = 'manual', updated_at = ?, updated_by = ? WHERE id = ?",
        (title, precondition, priority, steps_json, nodeid, now, user_login, case_id),
    )
    conn.commit()
    return get_case(conn, row["project"], case_id)


# ------------------------------------------------------------------ статус последнего прогона


def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid -> allure fullName. Своя копия по тому же соглашению модулей,
    что и app.core.flaky/coverage/xfail_registry (app/core/xfail_registry.py:243-256)."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def _bucket_status(entry: dict) -> str:
    """passed/failed/xfail/skipped — своя копия app.core.stats._bucket_status
    (broken схлопывается в failed, xfail — по префиксу "xfail" в message)."""
    status = entry["status"]
    if status == "broken":
        return "failed"
    if status == "skipped" and entry.get("message") and "xfail" in entry["message"].lower():
        return "xfail"
    return status


def _status_map(conn: sqlite3.Connection, project: str) -> dict[str, str]:
    """allure fullName -> статус, по последнему завершённому прогону стенда по
    умолчанию (app.core.stats.default_stand — тот же выбор, что у /stats)."""
    stand = stats.default_stand(conn, project)
    if not stand:
        return {}
    run_id = stats.latest_finished_run_id(conn, project, stand)
    if not run_id:
        return {}
    entries = allure_report.parse_results(_allure_dir(run_id))
    return {entry["name"]: _bucket_status(entry) for entry in entries}


# ------------------------------------------------------------------ чтение


def _case_payload(row: sqlite3.Row, status: str | None) -> dict:
    return {
        "id": row["id"],
        "project": row["project"],
        "section": row["section"],
        "title": row["title"],
        "steps": json.loads(row["steps"] or "[]"),
        "precondition": row["precondition"],
        "priority": row["priority"],
        "nodeid": row["nodeid"],
        "source": row["source"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
        "status": status,
        "attachments": [],
    }


def get_case(conn: sqlite3.Connection, project: str, case_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM test_cases WHERE project = ? AND id = ?", (project, case_id)
    ).fetchone()
    if row is None:
        return None
    status = None
    if row["nodeid"]:
        status = _status_map(conn, project).get(_nodeid_to_full_name(row["nodeid"]))
    return _case_payload(row, status)


def _matches_query(row: sqlite3.Row, q: str) -> bool:
    steps = json.loads(row["steps"] or "[]")
    haystack = " ".join([row["title"]] + [s.get("action", "") + " " + s.get("expected", "") for s in steps])
    return q.lower() in haystack.lower()


def _build_tree(cases: list[dict]) -> dict:
    kinds: dict[str, dict] = {}
    for case in cases:
        section = case["section"] or "misc"
        kind, _, area = section.partition("/")
        kind_bucket = kinds.setdefault(kind, {"kind": kind, "areas": {}})
        area_bucket = kind_bucket["areas"].setdefault(area, {"area": area or None, "section": section, "cases": []})
        area_bucket["cases"].append(case)

    return {
        "kinds": [
            {"kind": kind, "areas": [kinds[kind]["areas"][a] for a in sorted(kinds[kind]["areas"])]}
            for kind in sorted(kinds)
        ]
    }


def list_tree(
    conn: sqlite3.Connection,
    project: str,
    section: str | None = None,
    status: str | None = None,
    has_test: bool | None = None,
    q: str | None = None,
) -> dict:
    rows = conn.execute(
        "SELECT * FROM test_cases WHERE project = ? ORDER BY section, title", (project,)
    ).fetchall()
    status_map = _status_map(conn, project)

    cases = []
    for row in rows:
        if section is not None and row["section"] != section:
            continue
        if has_test is True and not row["nodeid"]:
            continue
        if has_test is False and row["nodeid"]:
            continue
        case_status = status_map.get(_nodeid_to_full_name(row["nodeid"])) if row["nodeid"] else None
        if status is not None and (case_status or "none") != status:
            continue
        if q and not _matches_query(row, q):
            continue
        cases.append(_case_payload(row, case_status))

    return _build_tree(cases)
