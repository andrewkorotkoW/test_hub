"""GET /api/runs/{id}/compare (docs/missions/2026-10-13_run_compare_and_causes.md,
часть 3) — группы new_failures/fixed/still_failing/speed, выбор базового прогона
по умолчанию, xfail -> xpass в fixed, speed-критерий.

По образцу tests/test_flaky.py: allure-результаты пишутся напрямую в изолированный
ALLURE_RESULTS_DIR (не через реальный pytest-прогон), run_test_results (кэш причины/
finished_ts) — тоже вставляется напрямую в БД, в обход record_run_results/ensure_run_results
(у них есть строки -> ensure_run_results не трогает проект/venv вовсе)."""
import json

import pytest

from app.db import get_connection

PROJECT = "cmp_proj"
STAND = "stage"


def _insert_project_and_stand(conn, project=PROJECT, stand=STAND):
    conn.execute(
        "INSERT OR IGNORE INTO projects (name, path, venv, stands) VALUES (?, '/tmp/does-not-matter', '.venv', '[]')",
        (project,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (project, stand)
    )
    conn.commit()


def _insert_run(conn, counts, target="all", marker=None, status="passed", project=PROJECT, stand=STAND, duration=100.0):
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, marker, status, started, finished, duration, requested_by, counts) "
        "VALUES (?, ?, ?, ?, ?, '2026-01-01T10:00:00', '2026-01-01T10:01:00', ?, 'qa', ?)",
        (project, stand, target, marker, status, duration, json.dumps(counts)),
    )
    conn.commit()
    return cur.lastrowid


def _write_allure_result(results_dir, run_id, filename, full_name, status, duration=None, message=None):
    run_dir = results_dir / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "fullName": full_name}
    if duration is not None:
        payload["start"] = 0
        payload["stop"] = int(duration * 1000)
    if message:
        payload["statusDetails"] = {"message": message}
    (run_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _insert_cached_result(conn, run_id, nodeid, full_name, status, cause=None, duration=None, finished_ts=None):
    conn.execute(
        "INSERT OR REPLACE INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, nodeid, full_name, status, duration, cause, finished_ts),
    )
    conn.commit()


@pytest.fixture()
def compare_runs(db_path, isolated_allure_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        base_id = _insert_run(conn, {"passed": 3, "failed": 1, "broken": 1, "skipped": 1}, duration=60.0)
        cur_id = _insert_run(conn, {"passed": 3, "failed": 2, "broken": 0, "skipped": 0}, duration=90.0)
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR

    # test_still_failing: failed на обоих -> "Падало и падает"
    _write_allure_result(results_dir, base_id, "00-result.json", "tests.cmp#test_still_failing", "failed", message="AssertionError: boom")
    _write_allure_result(results_dir, cur_id, "00-result.json", "tests.cmp#test_still_failing", "failed", message="AssertionError: boom again")

    # test_fixed: xfail (skipped+xfail-сообщение) на базе -> passed сейчас = fixed, xfail -> xpass
    _write_allure_result(results_dir, base_id, "01-result.json", "tests.cmp#test_fixed", "skipped", message="xfail: known issue")
    _write_allure_result(results_dir, cur_id, "01-result.json", "tests.cmp#test_fixed", "passed")

    # test_new_failure: passed на базе -> failed (throttling) сейчас = new_failures
    _write_allure_result(results_dir, base_id, "02-result.json", "tests.cmp#test_new_failure", "passed")
    _write_allure_result(results_dir, cur_id, "02-result.json", "tests.cmp#test_new_failure", "failed", message="429 Too Many Requests")

    # test_speed: статус не менялся (passed/passed), длительность выросла в 5 раз (>=5с, >2x)
    _write_allure_result(results_dir, base_id, "03-result.json", "tests.cmp#test_speed", "passed", duration=2.0)
    _write_allure_result(results_dir, cur_id, "03-result.json", "tests.cmp#test_speed", "passed", duration=10.0)

    # test_broken_to_failed: broken на базе, failed сейчас -> тоже "ведро" failed = still_failing
    _write_allure_result(results_dir, base_id, "04-result.json", "tests.cmp#test_broken_to_failed", "broken", message="ConnectTimeout")
    _write_allure_result(results_dir, cur_id, "04-result.json", "tests.cmp#test_broken_to_failed", "failed", message="AssertionError: boom3")

    # test_only_in_base: не присутствует в текущем прогоне -> не должен попадать ни в одну группу
    _write_allure_result(results_dir, base_id, "05-result.json", "tests.cmp#test_only_in_base", "passed")

    conn = get_connection()
    try:
        _insert_cached_result(conn, base_id, "tests/cmp.py::test_still_failing", "tests.cmp#test_still_failing", "failed", cause="code")
        _insert_cached_result(conn, cur_id, "tests/cmp.py::test_still_failing", "tests.cmp#test_still_failing", "failed", cause="code")
        _insert_cached_result(conn, cur_id, "tests/cmp.py::test_new_failure", "tests.cmp#test_new_failure", "failed", cause="throttling")
        _insert_cached_result(conn, base_id, "tests/cmp.py::test_broken_to_failed", "tests.cmp#test_broken_to_failed", "broken", cause="stand")
        _insert_cached_result(conn, cur_id, "tests/cmp.py::test_broken_to_failed", "tests.cmp#test_broken_to_failed", "failed", cause="code")
    finally:
        conn.close()

    return {"base_id": base_id, "cur_id": cur_id}


async def test_compare_groups_new_failures_fixed_still_failing_speed(qa_client, compare_runs):
    cur_id = compare_runs["cur_id"]
    base_id = compare_runs["base_id"]
    resp = await qa_client.get(f"/api/runs/{cur_id}/compare", params={"base": base_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["base"]["id"] == base_id

    groups = body["groups"]
    new_failures_names = {t["full_name"] for t in groups["new_failures"]}
    assert new_failures_names == {"tests.cmp#test_new_failure"}
    assert groups["new_failures"][0]["cause"] == "throttling"

    fixed_names = {t["full_name"] for t in groups["fixed"]}
    assert fixed_names == {"tests.cmp#test_fixed"}
    assert groups["fixed"][0]["was_xfail"] is True

    still_failing_names = {t["full_name"] for t in groups["still_failing"]}
    assert still_failing_names == {"tests.cmp#test_still_failing", "tests.cmp#test_broken_to_failed"}

    speed_names = {t["full_name"] for t in groups["speed"]}
    assert speed_names == {"tests.cmp#test_speed"}

    # tests, присутствующий только в базовом прогоне, не попадает ни в одну группу
    all_named = new_failures_names | fixed_names | still_failing_names | speed_names
    assert "tests.cmp#test_only_in_base" not in all_named


async def test_compare_kpis_now_and_was(qa_client, compare_runs):
    cur_id = compare_runs["cur_id"]
    base_id = compare_runs["base_id"]
    resp = await qa_client.get(f"/api/runs/{cur_id}/compare", params={"base": base_id})
    kpis = resp.json()["kpis"]
    assert kpis["passed"] == {"now": 3, "was": 3}
    assert kpis["failed"]["now"] == 2
    assert kpis["failed"]["was"] == 2  # failed(1)+broken(1) схлопнуты в одно ведро
    assert kpis["duration"] == {"now": 90.0, "was": 60.0}


async def test_compare_bucket_failed_and_broken_are_one_bucket(qa_client, compare_runs):
    """test_broken_to_failed (broken -> failed) не должен попасть в fixed/new_failures,
    только в still_failing — т.к. failed+broken — одно и то же ведро (_bucket_status)."""
    cur_id = compare_runs["cur_id"]
    base_id = compare_runs["base_id"]
    resp = await qa_client.get(f"/api/runs/{cur_id}/compare", params={"base": base_id})
    groups = resp.json()["groups"]
    item = next(t for t in groups["still_failing"] if t["full_name"] == "tests.cmp#test_broken_to_failed")
    assert item["status"] == "failed"
    assert item["prev_status"] == "broken"


# ------------------------------------------------------------------ выбор базового прогона по умолчанию

async def test_compare_default_base_is_previous_finished_run_same_target_and_marker(qa_client, db_path, isolated_allure_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_a = _insert_run(conn, {"passed": 1, "failed": 0}, target="all", marker="smoke")
        run_b_other_marker = _insert_run(conn, {"passed": 1, "failed": 0}, target="all", marker="api")
        run_c = _insert_run(conn, {"passed": 1, "failed": 0}, target="all", marker="smoke")
    finally:
        conn.close()

    for run_id in (run_a, run_b_other_marker, run_c):
        _write_allure_result(settings.ALLURE_RESULTS_DIR, run_id, "00-result.json", "tests.cmp#test_x", "passed")

    resp = await qa_client.get(f"/api/runs/{run_c}/compare")
    assert resp.status_code == 200, resp.text
    # run_b (та же цель/маркер? нет — другой маркер) должен быть пропущен, база — run_a
    assert resp.json()["base"]["id"] == run_a


async def test_compare_default_base_falls_back_to_last_run_on_stand_when_no_matching_target_marker(
    qa_client, db_path, isolated_allure_dir,
):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_a = _insert_run(conn, {"passed": 1, "failed": 0}, target="all", marker="smoke")
        run_b = _insert_run(conn, {"passed": 1, "failed": 0}, target="selected", marker="api")
    finally:
        conn.close()

    for run_id in (run_a, run_b):
        _write_allure_result(settings.ALLURE_RESULTS_DIR, run_id, "00-result.json", "tests.cmp#test_x", "passed")

    resp = await qa_client.get(f"/api/runs/{run_b}/compare")
    assert resp.status_code == 200, resp.text
    # нет прогона с тем же target/marker -> запасной вариант: последний на стенде (run_a)
    assert resp.json()["base"]["id"] == run_a


async def test_compare_explicit_base_query_param_overrides_default(qa_client, compare_runs):
    cur_id = compare_runs["cur_id"]
    base_id = compare_runs["base_id"]
    resp = await qa_client.get(f"/api/runs/{cur_id}/compare", params={"base": base_id})
    assert resp.json()["base"]["id"] == base_id


async def test_compare_no_base_available_returns_404(qa_client, db_path, isolated_allure_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        only_run = _insert_run(conn, {"passed": 1, "failed": 0})
    finally:
        conn.close()
    _write_allure_result(settings.ALLURE_RESULTS_DIR, only_run, "00-result.json", "tests.cmp#test_x", "passed")

    resp = await qa_client.get(f"/api/runs/{only_run}/compare")
    assert resp.status_code == 404


async def test_compare_unknown_run_id_returns_404(qa_client, db_path):
    resp = await qa_client.get("/api/runs/999999/compare")
    assert resp.status_code == 404
