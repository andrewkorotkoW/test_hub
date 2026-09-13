"""GET /api/runs/{id}/report (разбор allure-results) и построчные run_events в БД.

Оба теста гоняют реальный pytest на фикстурном проекте (3 passed + 2 failed, см.
conftest.py::_FIXTURE_TESTS) с --alluredir, который app/core/runner.py::_execute
подставляет автоматически на каждый прогон.
"""

from app.db import get_connection

from .conftest import poll_until, register_project


def _find(rows, run_id):
    return next(r for r in rows if r["id"] == run_id)


async def _run_fixture_project(qa_client, project_name, project_dir):
    await register_project(qa_client, project_name, project_dir)
    create_resp = await qa_client.post(
        f"/api/projects/{project_name}/runs", json={"target": "tests/test_sample.py"}
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    async def finished():
        rows = (await qa_client.get(f"/api/projects/{project_name}/runs")).json()
        row = _find(rows, run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None, "прогон не завершился вовремя"
    return run_id, final


async def test_report_counts_and_failed_test_details(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, final = await _run_fixture_project(qa_client, "report_proj", runnable_project_dir)
    assert final["status"] == "failed"  # фикстура содержит 2 падающих теста

    report_resp = await qa_client.get(f"/api/runs/{run_id}/report")
    assert report_resp.status_code == 200
    report = report_resp.json()

    assert report["counts"] == {"passed": 3, "failed": 2, "broken": 0, "skipped": 0}
    assert len(report["tests"]) == 5

    failed = [t for t in report["tests"] if t["status"] == "failed"]
    passed = [t for t in report["tests"] if t["status"] == "passed"]
    assert len(failed) == 2
    assert len(passed) == 3

    for test in report["tests"]:
        assert test["duration"] is not None and test["duration"] >= 0

    for test in failed:
        assert test["message"], f"у упавшего теста {test['name']} пустое сообщение"
        assert "assert" in test["message"].lower()


async def test_run_events_recorded_for_completed_run(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "events_proj", runnable_project_dir)

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT line FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) > 0, "после завершения прогона не появилось ни одной строки run_events"
    assert any(row["line"].strip() for row in rows), "все строки run_events пустые"
