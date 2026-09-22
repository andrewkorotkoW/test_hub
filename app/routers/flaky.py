"""REST API поверх app/core/flaky.py — нестабильные (флаки) тесты проекта.

Идентификатор теста в БД (flaky_stats.test) — allure fullName (см. app/core/flaky.py),
а не pytest nodeid: nodeid нужен только для кнопки «Прогнать» на странице проекта
(POST /runs принимает nodeid в target), поэтому GET /flaky обогащает каждую запись
полем nodeid — best-effort по дереву тестов (runner.discover()), None, если тест
статически уже не находится (переименован/удалён)."""
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core import flaky, runner
from ..deps import get_db, require_roles
from ..schemas import FlakyTestHistory, FlakyTestHistoryEntry, FlakyTestList, FlakyTestStat

router = APIRouter(prefix="/api/projects", tags=["flaky"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


@router.get("/{name}/flaky")
async def list_flaky(
    name: str,
    stand: str | None = None,
    min_runs: int = 3,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> FlakyTestList:
    project = _get_project_or_404(conn, name)
    rows = flaky.list_stats(conn, name, stand, min_runs)

    discovered = await runner.discover(project["path"], project["venv"])
    nodeid_by_full_name = flaky.full_name_index(discovered.get("tree") or {})

    items = [
        FlakyTestStat(
            project=r["project"],
            stand=r["stand"],
            test=r["test"],
            nodeid=nodeid_by_full_name.get(r["test"]),
            runs=r["runs"],
            fails=r["fails"],
            flips=r["flips"],
            score=r["score"],
            last_statuses=json.loads(r["last_statuses"]),
            updated_at=r["updated_at"],
        )
        for r in rows
    ]
    return FlakyTestList(items=items)


@router.get("/{name}/flaky/{test_id}")
def get_flaky_test(
    name: str,
    test_id: str,
    stand: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> FlakyTestHistory:
    _get_project_or_404(conn, name)
    stat = flaky.get_stat(conn, name, stand, test_id)
    if stat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found in flaky stats")

    history = flaky.run_history_for_test(name, stand, test_id)
    return FlakyTestHistory(
        test=test_id,
        stand=stand,
        history=[FlakyTestHistoryEntry(**h) for h in history],
    )
