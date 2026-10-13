"""Флаки-детектор: для каждого теста считает нестабильность на основе истории
последних прогонов проекта на стенде.

Источник статусов — allure-results уже завершённых прогонов (app.core.allure_report,
как и app.core.coverage), идентификатор теста — allure fullName, а не pytest nodeid:
он не завязан на дерево тестов конкретного момента и не требует запускать
runner.discover() внутри recalc() (см. также app.core.coverage._nodeid_to_full_name,
тот же формат). recalc() хранит агрегаты в таблице flaky_stats (app.db.SCHEMA) —
вызывается раннером после каждого завершённого прогона (app/core/runner.py::_finalize),
поэтому чтения (GET /flaky) работают с уже готовой таблицей, без пересчёта на лету.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import allure_report

DEFAULT_HISTORY = 20


def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def _finished_run_ids(conn: sqlite3.Connection, project: str, stand: str, limit: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM runs WHERE project = ? AND stand = ? "
        "AND status IN ('passed', 'failed', 'cancelled') ORDER BY id DESC LIMIT ?",
        (project, stand, limit),
    ).fetchall()
    return [row["id"] for row in rows][::-1]  # по возрастанию id = в хронологическом порядке


def _cause_by_full_name(conn: sqlite3.Connection, run_id: int) -> dict[str, str | None]:
    return {
        row["full_name"]: row["cause"]
        for row in conn.execute(
            "SELECT full_name, cause FROM run_test_results WHERE run_id = ?", (run_id,)
        ).fetchall()
    }


def recalc(project: str, stand: str, test_history: int = DEFAULT_HISTORY) -> list[dict]:
    """Пересчитывает флаки-статистику по последним `test_history` завершённым
    прогонам проекта на стенде и перезаписывает flaky_stats для этой пары
    (project, stand) целиком.

    rerun-дубликаты (несколько *-result.json с одним fullName внутри одного
    прогона, например при RunCreate.repeat > 1) не схлопываются в одну запись —
    каждый идёт в общую хронологическую последовательность статусов теста тем же
    порядком, что вернул allure_report.parse_results (сортировка по имени файла
    результата — точное время старта эта функция не отдаёт, так что для тестов
    внутри одного прогона это лучшее доступное приближение к порядку выполнения).
    flips — число смен статуса между соседними элементами последовательности,
    score = flips / (runs - 1).

    Падения, классифицированные app.core.failure_causes как инфраструктурные
    (throttling/session/stand, т.е. cause != 'code' в run_test_results — см.
    docs/missions/2026-10-13_run_compare_and_causes.md, п.5), не должны считаться
    за fails/flips: волна 429 не тест сделала нестабильным, а стенд. Для них
    эффективный статус (только для подсчёта fails/flips, не для last_statuses)
    наследуется от предыдущего элемента последовательности — так инфраструктурный
    всплеск не создаёт ни fail, ни искусственный flip между соседними реальными
    статусами. Прогоны без строк в run_test_results (старые, до этой фичи) не
    знают cause — для них поведение прежнее: каждый failed/broken учитывается как
    есть."""
    conn = get_connection()
    try:
        run_ids = _finished_run_ids(conn, project, stand, test_history)

        by_test: dict[str, list[tuple[str, str | None]]] = {}
        for run_id in run_ids:
            cause_by_full_name = _cause_by_full_name(conn, run_id)
            for entry in allure_report.parse_results(_allure_dir(run_id)):
                name = entry["name"]
                by_test.setdefault(name, []).append((entry["status"], cause_by_full_name.get(name)))

        now = datetime.now().isoformat(timespec="seconds")
        stats = []
        for test_name, entries in sorted(by_test.items()):
            statuses = [status for status, _cause in entries]
            runs_count = len(statuses)
            effective: list[str] = []
            prev: str | None = None
            for status, cause in entries:
                if status in ("failed", "broken") and cause not in (None, "code"):
                    eff = prev if prev is not None else "passed"
                else:
                    eff = status
                effective.append(eff)
                prev = eff
            fails = sum(1 for s in effective if s == "failed")
            flips = sum(1 for a, b in zip(effective, effective[1:]) if a != b)
            score = flips / (runs_count - 1) if runs_count > 1 else 0.0
            stats.append({
                "project": project,
                "stand": stand,
                "test": test_name,
                "runs": runs_count,
                "fails": fails,
                "flips": flips,
                "score": score,
                "last_statuses": statuses[-test_history:],
                "updated_at": now,
            })

        conn.execute("DELETE FROM flaky_stats WHERE project = ? AND stand = ?", (project, stand))
        for s in stats:
            conn.execute(
                "INSERT INTO flaky_stats "
                "(project, stand, test, runs, fails, flips, score, last_statuses, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s["project"], s["stand"], s["test"], s["runs"], s["fails"], s["flips"],
                 s["score"], json.dumps(s["last_statuses"], ensure_ascii=False), s["updated_at"]),
            )
        conn.commit()
    finally:
        conn.close()
    return stats


def list_stats(conn: sqlite3.Connection, project: str, stand: str | None, min_runs: int) -> list[sqlite3.Row]:
    if stand:
        return conn.execute(
            "SELECT * FROM flaky_stats WHERE project = ? AND stand = ? AND runs >= ? "
            "ORDER BY score DESC, test",
            (project, stand, min_runs),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM flaky_stats WHERE project = ? AND runs >= ? ORDER BY score DESC, test",
        (project, min_runs),
    ).fetchall()


def get_stat(conn: sqlite3.Connection, project: str, stand: str, test: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM flaky_stats WHERE project = ? AND stand = ? AND test = ?",
        (project, stand, test),
    ).fetchone()


def run_history_for_test(project: str, stand: str, test: str, limit: int = DEFAULT_HISTORY) -> list[dict]:
    """Статусы конкретного теста (allure fullName) по прогонам, по одной записи на
    каждый *-result.json — отдельно от recalc()/flaky_stats, которая хранит только
    последние `last_statuses` без привязки к run_id."""
    conn = get_connection()
    try:
        run_ids = _finished_run_ids(conn, project, stand, limit)
        history = []
        for run_id in run_ids:
            for entry in allure_report.parse_results(_allure_dir(run_id)):
                if entry["name"] == test:
                    history.append({"run_id": run_id, "status": entry["status"]})
        return history
    finally:
        conn.close()


def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid -> allure fullName. Та же логика, что и в app.core.coverage и
    app.tg_bot (allure_pytest.utils.allure_full_name) — своя копия по тому же
    соглашению модулей: не тянуть межмодульную зависимость ради одной функции."""
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
    обратное сопоставление для кнопки «Прогнать» на странице флаки-тестов
    (submit_run принимает nodeid, а не fullName)."""
    index: dict[str, str] = {}
    for file_path, classes in tree.items():
        for cls_name, tests in classes.items():
            for test_name in tests:
                nodeid = f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}"
                index.setdefault(_nodeid_to_full_name(nodeid), nodeid)
    return index
