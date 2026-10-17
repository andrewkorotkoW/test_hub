"""«Новые дефекты»: падения прогона с причиной «код» (см. app/core/failure_causes.py
— не троттлинг/потеря сессии/стенд не ответил), которых ещё нет ни в реестре
известных дефектов (app/core/xfail_registry.py — тесты с @pytest.mark.xfail в
исходниках), ни среди уже решённых руками QA (confirmed_defects — эта задача).

Кандидат не найден автоматикой заново при каждом прогоне — он либо подтверждается
(комментарий в YouTrack, app/core/youtrack.py, плюс запись confirmed_defects со
status='confirmed'), либо отклоняется («Пропустить», status='dismissed', без
отправки куда-либо) — в обоих случаях тест перестаёт всплывать в списке кандидатов
для этого (project, stand), сколько бы раз он ни падал дальше. Это НЕ то же самое,
что xfail_registry: туда тест попадает только через реальный @pytest.mark.xfail
в коде и пересчитывается каждым прогоном (app.core.xfail_registry.recalc) — здесь
же решение разовое и ручное, записи этой таблицы recalc не трогает и не читает."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import settings
from . import xfail_registry

SEVERITY_RU = {
    "blocker": "Blocker",
    "critical": "Critical",
    "normal": "Major",
    "minor": "Minor",
    "trivial": "Trivial",
}


def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def _back_or_front(nodeid: str) -> str:
    if nodeid.startswith("tests/ui/") or "/ui/" in nodeid:
        return "front"
    return "back"


def _read_result_details(results_dir: Path, wanted_full_names: set[str]) -> dict[str, dict]:
    """fullName -> {severity, steps, message, trace} из *-result.json — поля,
    которых сознательно нет в allure_report.parse_results (см. её докстринг и
    app.core.xfail_registry._raw_label_names про тот же приём: читаем файлы
    отдельно, только когда эти поля реально нужны)."""
    out: dict[str, dict] = {}
    if not results_dir.is_dir():
        return out
    for path in results_dir.glob("*-result.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        full_name = data.get("fullName") or data.get("name")
        if not full_name or full_name not in wanted_full_names:
            continue
        details = data.get("statusDetails") or {}
        severity = next(
            (lbl.get("value") for lbl in (data.get("labels") or []) if lbl.get("name") == "severity"),
            None,
        )
        steps = [
            {"name": s.get("name"), "status": s.get("status")}
            for s in (data.get("steps") or [])
            if isinstance(s, dict)
        ]
        out[full_name] = {
            "severity": SEVERITY_RU.get(severity, severity),
            "steps": steps,
            "message": details.get("message"),
            "trace": details.get("trace"),
        }
    return out


def list_candidates(conn: sqlite3.Connection, project: str, stand: str, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT nodeid, full_name, status, cause, finished_ts FROM run_test_results "
        "WHERE run_id = ? AND cause = 'code' AND status IN ('failed', 'broken') "
        "ORDER BY full_name",
        (run_id,),
    ).fetchall()
    if not rows:
        return []

    known = {r["test"] for r in xfail_registry.list_entries(conn, project, stand)}
    decided = {
        r["test"]
        for r in conn.execute(
            "SELECT test FROM confirmed_defects WHERE project = ? AND stand = ?", (project, stand)
        ).fetchall()
    }
    pending = [r for r in rows if r["full_name"] not in known and r["full_name"] not in decided]
    if not pending:
        return []

    details = _read_result_details(_allure_dir(run_id), {r["full_name"] for r in pending})

    candidates = []
    for r in pending:
        d = details.get(r["full_name"], {})
        candidates.append({
            "nodeid": r["nodeid"],
            "full_name": r["full_name"],
            "status": r["status"],
            "area": _back_or_front(r["nodeid"]),
            "severity": d.get("severity"),
            "message": d.get("message"),
            "trace": d.get("trace"),
            "steps": d.get("steps") or [],
            "finished_ts": r["finished_ts"],
            "run_id": run_id,
        })
    return candidates


def count_pending(conn: sqlite3.Connection, project: str, stand: str, run_id: int) -> int:
    return len(list_candidates(conn, project, stand, run_id))


def decide(
    conn: sqlite3.Connection,
    project: str,
    stand: str,
    test: str,
    status: str,
    decided_by: str,
    *,
    issue_url: str | None = None,
    priority: str | None = None,
    expected_result: str | None = None,
    precondition: str | None = None,
    run_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO confirmed_defects "
        "(project, stand, test, status, issue_url, priority, expected_result, precondition, "
        "run_id, decided_by, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (project, stand, test) DO UPDATE SET "
        "status = excluded.status, issue_url = excluded.issue_url, priority = excluded.priority, "
        "expected_result = excluded.expected_result, precondition = excluded.precondition, "
        "run_id = excluded.run_id, decided_by = excluded.decided_by, decided_at = excluded.decided_at",
        (
            project, stand, test, status, issue_url, priority, expected_result, precondition,
            run_id, decided_by, datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def list_decided(conn: sqlite3.Connection, project: str, stand: str | None = None) -> list[sqlite3.Row]:
    if stand:
        return conn.execute(
            "SELECT * FROM confirmed_defects WHERE project = ? AND stand = ? ORDER BY decided_at DESC",
            (project, stand),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM confirmed_defects WHERE project = ? ORDER BY decided_at DESC", (project,)
    ).fetchall()
