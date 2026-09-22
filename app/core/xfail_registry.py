"""Реестр известных дефектов (xfail/xpass): какие тесты помечены
@pytest.mark.xfail в исходниках, и что показывает последний прогон на стенде.

Источник данных — оба сразу:
- статический AST-разбор проекта (scan_static) находит тесты с декоратором
  pytest.mark.xfail(reason=...) даже без единого прогона — reason берётся из
  исходников;
- allure-results уже завершённого прогона (app.core.allure_report.parse_results,
  тот же источник, что и app.core.flaky/app.core.coverage) классифицируют, что
  реально произошло на конкретном стенде: тест либо снова ожидаемо не прошёл
  (xfail), либо неожиданно прошёл (xpass — сигнал, что дефект, возможно, уже
  починили и маркер можно снимать).

recalc() вызывается раннером после каждого завершённого прогона (см.
app/core/runner.py::_finalize, рядом с app.core.flaky.recalc — оба обновления
независимы и не конфликтуют) и upsert'ит таблицу xfail_registry (app.db.SCHEMA)
per (project, stand, test); issue_url/note, отредактированные вручную через
PUT /api/projects/{name}/xfail/{id}, при пересчёте не затираются."""
from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import allure_report


def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


# ------------------------------------------------------------------ статический AST-анализ

def _parse_module(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _xfail_decorator_reason(decorators: list[ast.expr]) -> tuple[bool, str | None]:
    """Есть ли среди декораторов @pytest.mark.xfail (с вызовом или без) и, если
    есть, reason из kwarg reason=... либо первого позиционного строкового
    аргумента (as pytest.mark.xfail("reason") тоже валиден)."""
    for dec in decorators:
        call = dec if isinstance(dec, ast.Call) else None
        func = call.func if call is not None else dec
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "xfail"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "mark"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "pytest"
        ):
            continue
        reason = None
        if call is not None:
            for kw in call.keywords:
                if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    reason = kw.value.value
            if reason is None and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                reason = call.args[0].value
        return True, reason
    return False, None


def scan_static(project_path: str) -> dict[str, str | None]:
    """allure fullName -> reason для тестов, помеченных @pytest.mark.xfail в
    tests/**/test_*.py (тот же корень, что app.core.coverage.discover_tests) —
    даёт реестр известных дефектов даже без единого прогона проекта на стенде."""
    root = Path(project_path) / "tests"
    result: dict[str, str | None] = {}
    if not root.is_dir():
        return result

    for file_path in sorted(root.glob("**/test_*.py")):
        tree = _parse_module(file_path)
        if tree is None:
            continue
        rel = file_path.relative_to(project_path).as_posix()

        def _handle(func_node: ast.FunctionDef | ast.AsyncFunctionDef, cls_name: str | None) -> None:
            has_marker, reason = _xfail_decorator_reason(func_node.decorator_list)
            if not has_marker:
                return
            nodeid = f"{rel}::" + (f"{cls_name}::" if cls_name else "") + func_node.name
            result[_nodeid_to_full_name(nodeid)] = reason

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                _handle(node, None)
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test_"):
                        _handle(sub, node.name)

    return result


# ------------------------------------------------------------------ allure-results прогона

def _reason_from_message(message: str) -> str | None:
    """"XFAIL <reason>\\n\\n<traceback>" -> "<reason>"; голое "XFAIL" (без
    причины, allure_pytest.listener шлёт именно так, если pytest.mark.xfail
    без reason=) -> None."""
    first_line = message.split("\n", 1)[0]
    reason = first_line[len("XFAIL"):].strip() if first_line.upper().startswith("XFAIL") else first_line.strip()
    return reason or None


def _raw_label_names(results_dir: Path) -> dict[str, set[str]]:
    """fullName -> набор значений labels из *-result.json — дополнительный (помимо
    message) признак xfail, см. описание задачи. allure_report.parse_results
    сознательно не отдаёт labels наружу (tests/test_share.py фиксирует ровно 4
    публичных поля результата), поэтому читаем те же файлы отдельно, только для
    этой проверки."""
    labels: dict[str, set[str]] = {}
    if not results_dir.is_dir():
        return labels
    for path in results_dir.glob("*-result.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        full_name = data.get("fullName") or data.get("name")
        if not full_name:
            continue
        values = {str(lbl.get("value", "")).lower() for lbl in (data.get("labels") or []) if isinstance(lbl, dict)}
        labels.setdefault(full_name, set()).update(values)
    return labels


def _classify_run_entry(
    entry: dict, labels: dict[str, set[str]], known_from_source: set[str]
) -> tuple[str, str | None] | None:
    """(state, reason) по одной записи allure-results, либо None, если запись не
    даёт никакого xfail/xpass-сигнала. xfail определяется самой записью (status +
    message/label), xpass — только по сочетанию status=passed с уже известным из
    исходников xfail-маркером (см. описание задачи п.1а)."""
    name = entry["name"]
    message = entry.get("message") or ""
    has_xfail_signal = message.upper().startswith("XFAIL") or "xfail" in labels.get(name, set())
    if entry["status"] in ("skipped", "failed") and has_xfail_signal:
        return "xfail", _reason_from_message(message)
    if entry["status"] == "passed" and name in known_from_source:
        return "xpass", None
    return None


def recalc(project: str, stand: str, run_id: int) -> list[dict]:
    """Upsert xfail_registry по результатам прогона run_id проекта на стенде:
    объединяет статический реестр (scan_static) с тем, что реально показал этот
    прогон. Тесты, не затронутые этим прогоном, не трогаются (last_run_id/state
    остаются от предыдущего пересчёта); issue_url/note всегда сохраняются."""
    conn = get_connection()
    try:
        project_row = conn.execute("SELECT path FROM projects WHERE name = ?", (project,)).fetchone()
        if project_row is None:
            return []

        static = scan_static(project_row["path"])
        results_dir = _allure_dir(run_id)
        entries = allure_report.parse_results(results_dir)
        labels = _raw_label_names(results_dir)

        run_state: dict[str, tuple[str, str | None]] = {}
        for entry in entries:
            classified = _classify_run_entry(entry, labels, set(static))
            if classified is not None:
                run_state[entry["name"]] = classified

        now = datetime.now().isoformat(timespec="seconds")
        results = []
        for full_name in sorted(set(static) | set(run_state)):
            existing = conn.execute(
                "SELECT * FROM xfail_registry WHERE project = ? AND stand = ? AND test = ?",
                (project, stand, full_name),
            ).fetchone()
            observed = run_state.get(full_name)

            state = observed[0] if observed else (existing["state"] if existing else "xfail")
            reason = (
                static.get(full_name)
                or (observed[1] if observed else None)
                or (existing["reason"] if existing else None)
            )
            last_run_id = run_id if observed else (existing["last_run_id"] if existing else None)
            first_seen = existing["first_seen"] if existing else now

            if existing:
                conn.execute(
                    "UPDATE xfail_registry SET reason = ?, last_run_id = ?, state = ? WHERE id = ?",
                    (reason, last_run_id, state, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO xfail_registry "
                    "(project, stand, test, reason, first_seen, last_run_id, state, issue_url, note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
                    (project, stand, full_name, reason, first_seen, last_run_id, state),
                )
            results.append({"project": project, "stand": stand, "test": full_name, "state": state})

        conn.commit()
        return results
    finally:
        conn.close()


# ------------------------------------------------------------------ чтение/правка реестра

def list_entries(conn: sqlite3.Connection, project: str, stand: str | None) -> list[sqlite3.Row]:
    if stand:
        return conn.execute(
            "SELECT * FROM xfail_registry WHERE project = ? AND stand = ? ORDER BY state DESC, test",
            (project, stand),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM xfail_registry WHERE project = ? ORDER BY state DESC, test", (project,)
    ).fetchall()


def get_entry(conn: sqlite3.Connection, project: str, entry_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM xfail_registry WHERE project = ? AND id = ?", (project, entry_id)
    ).fetchone()


def update_entry(conn: sqlite3.Connection, entry_id: int, issue_url: str | None, note: str | None) -> None:
    conn.execute(
        "UPDATE xfail_registry SET issue_url = ?, note = ? WHERE id = ?", (issue_url, note, entry_id)
    )
    conn.commit()


# ------------------------------------------------------------------ nodeid <-> fullName

def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid -> allure fullName. Та же логика, что и в app.core.flaky,
    app.core.coverage и app.tg_bot (allure_pytest.utils.allure_full_name) — своя
    копия по тому же соглашению модулей: не тянуть межмодульную зависимость ради
    одной функции."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def full_name_index(tree: dict) -> dict[str, str]:
    """allure fullName -> pytest nodeid по дереву тестов (runner.discover()) —
    обратное сопоставление для кнопки «Проверить» (submit_run принимает nodeid,
    а не fullName)."""
    index: dict[str, str] = {}
    for file_path, classes in tree.items():
        for cls_name, tests in classes.items():
            for test_name in tests:
                nodeid = f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}"
                index.setdefault(_nodeid_to_full_name(nodeid), nodeid)
    return index
