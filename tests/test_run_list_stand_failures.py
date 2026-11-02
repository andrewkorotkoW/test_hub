"""GET /api/projects/{name}/runs::stand_failures — доля инфраструктурных причин
(app/core/failure_causes.py::INFRA_CAUSES) у самого прогона, независимо от
delta_prev (который None для первого прогона на стенде). Это единственный вход
для бейджа «· N стенд» у «% passed» на дашборде (docs/missions/2026-11-02_review_fixes.md,
п.1, ui/project-dashboard.js::standBadgeText) — сам бейдж и порог >50% чистая
JS-логика, покрыта tests/js/test_project_dashboard_source_badge.js."""
import json

from app.db import get_connection

from .conftest import register_project

PROJECT = "stand_failures_proj"
STAND = "stage"


def _insert_run(counts, status="failed") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
            "VALUES (?, ?, 'all', ?, '2026-01-01T10:00:00', 'qa', ?)",
            (PROJECT, STAND, status, json.dumps(counts)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_cached_result(run_id, nodeid, status, cause=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
            "VALUES (?, ?, ?, ?, NULL, ?, '2026-01-01T10:00:00')",
            (run_id, nodeid, nodeid, status, cause),
        )
        conn.commit()
    finally:
        conn.close()


async def test_list_runs_stand_failures_counts_only_infra_causes(qa_client, isolated_allure_dir, tmp_path):
    (tmp_path / "src").mkdir()
    await register_project(qa_client, PROJECT, tmp_path / "src")
    await qa_client.post(f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": ""})
    run_id = _insert_run({"passed": 1, "failed": 3})
    _insert_cached_result(run_id, "tests/c.py::test_throttling", "failed", "throttling")
    _insert_cached_result(run_id, "tests/c.py::test_stand", "failed", "stand")
    _insert_cached_result(run_id, "tests/c.py::test_code", "failed", "code")

    resp = await qa_client.get(f"/api/projects/{PROJECT}/runs")
    assert resp.status_code == 200, resp.text
    payload = next(r for r in resp.json() if r["id"] == run_id)
    assert payload["stand_failures"] == 2  # throttling + stand, code не считается


async def test_list_runs_stand_failures_zero_when_not_yet_classified(qa_client, isolated_allure_dir, tmp_path):
    """Прогон без строк в run_test_results (причины ещё не пересчитаны лениво) —
    stand_failures = 0, а не ошибка/None: список прогонов не зовёт
    failure_causes.ensure_run_results, только прямой COUNT по уже посчитанному."""
    (tmp_path / "src").mkdir()
    await register_project(qa_client, PROJECT, tmp_path / "src")
    await qa_client.post(f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": ""})
    run_id = _insert_run({"passed": 1, "failed": 1})

    resp = await qa_client.get(f"/api/projects/{PROJECT}/runs")
    assert resp.status_code == 200, resp.text
    payload = next(r for r in resp.json() if r["id"] == run_id)
    assert payload["stand_failures"] == 0
