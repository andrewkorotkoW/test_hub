"""Смоук-тесты «Новых дефектов» (app/core/new_defects.py, app/routers/new_defects.py):
отбор кандидатов (cause='code', не в xfail_registry, не в confirmed_defects),
обогащение severity/steps из сырого allure-результата и решения (confirm/dismiss)."""
import json

import pytest

from app.core import new_defects, xfail_registry
from app.db import get_connection

PROJECT = "nd_proj"
STAND = "stand"


def _insert_project_and_stand(conn):
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/nd_proj', '.venv', '[]')",
        (PROJECT,),
    )
    conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
    conn.commit()


def _insert_run(conn) -> int:
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, ?, 'all', 'failed', '2026-01-01T00:00:00', 'qa', '{}')",
        (PROJECT, STAND),
    )
    conn.commit()
    return cur.lastrowid


def _insert_result(conn, run_id, nodeid, full_name, status, cause):
    conn.execute(
        "INSERT INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
        "VALUES (?, ?, ?, ?, 1.0, ?, '2026-01-01T00:01:00')",
        (run_id, nodeid, full_name, status, cause),
    )
    conn.commit()


def _write_raw_result(results_dir, filename, full_name, severity=None, steps=None, message=None, trace=None):
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fullName": full_name, "status": "failed"}
    if severity:
        payload["labels"] = [{"name": "severity", "value": severity}]
    if steps:
        payload["steps"] = steps
    details = {}
    if message:
        details["message"] = message
    if trace:
        details["trace"] = trace
    if details:
        payload["statusDetails"] = details
    (results_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


# ------------------------------------------------------------------ list_candidates

def test_list_candidates_only_cause_code_failed_or_broken(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "tests/api/test_a.py::test_a", "pkg.test_a#test_a", "failed", "code")
        _insert_result(conn, run_id, "tests/api/test_b.py::test_b", "pkg.test_b#test_b", "broken", "code")
        # отсеивается: инфраструктурная причина
        _insert_result(conn, run_id, "tests/api/test_c.py::test_c", "pkg.test_c#test_c", "failed", "session")
        # отсеивается: статус passed/skipped, даже если cause почему-то code
        _insert_result(conn, run_id, "tests/api/test_d.py::test_d", "pkg.test_d#test_d", "passed", "code")

        items = new_defects.list_candidates(conn, PROJECT, STAND, run_id)
    finally:
        conn.close()

    names = {i["full_name"] for i in items}
    assert names == {"pkg.test_a#test_a", "pkg.test_b#test_b"}


def test_list_candidates_excludes_known_xfail(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "tests/api/test_a.py::test_a", "pkg.test_a#test_a", "failed", "code")
        conn.execute(
            "INSERT INTO xfail_registry (project, stand, test, reason, first_seen, state) "
            "VALUES (?, ?, 'pkg.test_a#test_a', 'уже известно', '2025-01-01T00:00:00', 'xfail')",
            (PROJECT, STAND),
        )
        conn.commit()

        items = new_defects.list_candidates(conn, PROJECT, STAND, run_id)
    finally:
        conn.close()
    assert items == []


def test_list_candidates_excludes_already_decided(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "tests/api/test_a.py::test_a", "pkg.test_a#test_a", "failed", "code")
        new_defects.decide(conn, PROJECT, STAND, "pkg.test_a#test_a", "dismissed", "qa")

        items = new_defects.list_candidates(conn, PROJECT, STAND, run_id)
    finally:
        conn.close()
    assert items == []


def test_list_candidates_enriches_severity_area_and_steps(db_path, isolated_allure_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "tests/ui/test_a.py::test_a", "pkg.test_a#test_a", "failed", "code")
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    _write_raw_result(
        results_dir, "00-result.json", "pkg.test_a#test_a",
        severity="critical",
        steps=[{"name": "шаг 1", "status": "passed"}, {"name": "шаг 2 упал", "status": "failed"}],
        message="AssertionError: boom",
        trace="трейс",
    )

    conn = get_connection()
    try:
        items = new_defects.list_candidates(conn, PROJECT, STAND, run_id)
    finally:
        conn.close()

    assert len(items) == 1
    item = items[0]
    assert item["area"] == "front"  # tests/ui/... -> Front
    assert item["severity"] == "Critical"
    assert item["message"] == "AssertionError: boom"
    assert item["trace"] == "трейс"
    assert item["steps"] == [
        {"name": "шаг 1", "status": "passed"},
        {"name": "шаг 2 упал", "status": "failed"},
    ]


def test_list_candidates_back_area_for_api_nodeid(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn)
        _insert_result(conn, run_id, "tests/api/test_a.py::test_a", "pkg.test_a#test_a", "failed", "code")
        items = new_defects.list_candidates(conn, PROJECT, STAND, run_id)
    finally:
        conn.close()
    assert items[0]["area"] == "back"


# ------------------------------------------------------------------ decide()

def test_decide_confirmed_stores_issue_url_and_fields(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn)
        new_defects.decide(
            conn, PROJECT, STAND, "pkg.test_a#test_a", "confirmed", "qa",
            issue_url="https://tracker.example.ru/issue/PROJ-1",
            priority="Высокий", expected_result="должно быть ОК", precondition="открыта страница",
            run_id=run_id,
        )
        rows = new_defects.list_decided(conn, PROJECT, STAND)
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "confirmed"
    assert row["issue_url"] == "https://tracker.example.ru/issue/PROJ-1"
    assert row["priority"] == "Высокий"
    assert row["expected_result"] == "должно быть ОК"
    assert row["precondition"] == "открыта страница"
    assert row["decided_by"] == "qa"


def test_decide_dismissed_has_no_issue_url(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        new_defects.decide(conn, PROJECT, STAND, "pkg.test_a#test_a", "dismissed", "manager")
        rows = new_defects.list_decided(conn, PROJECT, STAND)
    finally:
        conn.close()
    assert rows[0]["status"] == "dismissed"
    assert rows[0]["issue_url"] is None


def test_decide_upserts_on_conflict(db_path, isolated_allure_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        new_defects.decide(conn, PROJECT, STAND, "pkg.test_a#test_a", "dismissed", "qa")
        new_defects.decide(
            conn, PROJECT, STAND, "pkg.test_a#test_a", "confirmed", "manager",
            issue_url="https://tracker.example.ru/issue/PROJ-1",
        )
        rows = new_defects.list_decided(conn, PROJECT, STAND)
    finally:
        conn.close()
    # одна запись (UNIQUE project/stand/test), не две — второе решение перезаписывает первое
    assert len(rows) == 1
    assert rows[0]["status"] == "confirmed"
    assert rows[0]["decided_by"] == "manager"
