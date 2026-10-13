"""GET /api/runs/{id}/causes (docs/missions/2026-10-13_run_compare_and_causes.md,
часть 3) — summary по 4 причинам, waves, tests со short_reason; ленивый пересчёт
(failure_causes.ensure_run_results) для прогона без строк в run_test_results."""
import json
from datetime import datetime

import pytest

from app.db import get_connection

PROJECT = "causes_proj"
STAND = "stage"


def _insert_project_and_stand(conn, path="/tmp/does-not-matter", venv=".venv"):
    conn.execute(
        "INSERT OR IGNORE INTO projects (name, path, venv, stands) VALUES (?, ?, ?, '[]')",
        (PROJECT, path, venv),
    )
    conn.execute(
        "INSERT OR IGNORE INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND)
    )
    conn.commit()


def _insert_run(conn, counts, status="failed"):
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, finished, duration, requested_by, counts) "
        "VALUES (?, ?, 'all', ?, '2026-01-01T10:00:00', '2026-01-01T10:10:00', 100.0, 'qa', ?)",
        (PROJECT, STAND, status, json.dumps(counts)),
    )
    conn.commit()
    return cur.lastrowid


def _write_allure_result(results_dir, run_id, filename, full_name, status, message=None):
    run_dir = results_dir / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "fullName": full_name}
    if message:
        payload["statusDetails"] = {"message": message}
    (run_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _insert_cached_result(conn, run_id, nodeid, full_name, status, cause=None, finished_ts=None):
    conn.execute(
        "INSERT OR REPLACE INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
        "VALUES (?, ?, ?, ?, NULL, ?, ?)",
        (run_id, nodeid, full_name, status, cause, finished_ts),
    )
    conn.commit()


@pytest.fixture()
def causes_run(db_path, isolated_allure_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn, {"passed": 1, "failed": 4, "broken": 0, "skipped": 0})
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR
    _write_allure_result(results_dir, run_id, "00-result.json", "tests.c#test_throttling", "failed", "429 Too Many Requests")
    _write_allure_result(results_dir, run_id, "01-result.json", "tests.c#test_session", "failed", "401 Unauthorized")
    _write_allure_result(results_dir, run_id, "02-result.json", "tests.c#test_stand", "failed", "ReadTimeout: stand did not respond")
    _write_allure_result(results_dir, run_id, "03-result.json", "tests.c#test_code", "failed", "AssertionError: boom")
    _write_allure_result(results_dir, run_id, "04-result.json", "tests.c#test_passed", "passed")

    conn = get_connection()
    try:
        _insert_cached_result(conn, run_id, "tests/c.py::test_throttling", "tests.c#test_throttling", "failed", "throttling", "2026-01-01T10:00:00")
        _insert_cached_result(conn, run_id, "tests/c.py::test_session", "tests.c#test_session", "failed", "session", "2026-01-01T10:00:10")
        _insert_cached_result(conn, run_id, "tests/c.py::test_stand", "tests.c#test_stand", "failed", "stand", "2026-01-01T10:00:20")
        _insert_cached_result(conn, run_id, "tests/c.py::test_code", "tests.c#test_code", "failed", "code", "2026-01-01T10:00:30")
        _insert_cached_result(conn, run_id, "tests/c.py::test_passed", "tests.c#test_passed", "passed", None, "2026-01-01T10:00:40")
    finally:
        conn.close()
    return run_id


async def test_causes_summary_counts_by_cause(qa_client, causes_run):
    resp = await qa_client.get(f"/api/runs/{causes_run}/causes")
    assert resp.status_code == 200, resp.text
    summary = resp.json()["summary"]
    assert summary["throttling"] == 1
    assert summary["session"] == 1
    assert summary["stand"] == 1
    assert summary["code"] == 1
    assert summary["total"] == 4


async def test_causes_tests_list_has_cause_and_short_reason(qa_client, causes_run):
    resp = await qa_client.get(f"/api/runs/{causes_run}/causes")
    tests = resp.json()["tests"]
    by_name = {t["full_name"]: t for t in tests}
    assert by_name["tests.c#test_throttling"]["cause"] == "throttling"
    assert by_name["tests.c#test_throttling"]["short_reason"] == "429 Too Many Requests"
    assert by_name["tests.c#test_code"]["short_reason"] == "AssertionError: boom"
    # passed-тест тоже возвращается (нужен для таймлайна), но без cause
    assert by_name["tests.c#test_passed"]["cause"] is None
    assert by_name["tests.c#test_passed"]["status"] == "passed"
    # nodeid подтягивается из кэша, а не остаётся fullName
    assert by_name["tests.c#test_throttling"]["nodeid"] == "tests/c.py::test_throttling"


async def test_causes_waves_detected_from_cached_finished_ts(qa_client, db_path, isolated_allure_dir):
    """5 падений throttling в пределах 2 минут -> ровно одна волна в ответе API."""
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn, {"passed": 0, "failed": 5})
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR
    conn = get_connection()
    try:
        for i in range(5):
            full_name = f"tests.c#test_w{i}"
            _write_allure_result(results_dir, run_id, f"{i:02d}-result.json", full_name, "failed", "429 Too Many Requests")
            _insert_cached_result(
                conn, run_id, f"tests/c.py::test_w{i}", full_name, "failed", "throttling",
                f"2026-01-01T10:00:{i*10:02d}",
            )
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/runs/{run_id}/causes")
    waves = resp.json()["waves"]
    assert len(waves) == 1
    assert waves[0]["cause"] == "throttling"
    assert waves[0]["count"] == 5


async def test_causes_no_waves_when_failures_are_not_clustered(qa_client, causes_run):
    """4 разных причины, по одной каждая, в фикстуре causes_run — волна требует
    >=5 падений одной причины за 2 минуты, здесь такого нет."""
    resp = await qa_client.get(f"/api/runs/{causes_run}/causes")
    assert resp.json()["waves"] == []


async def test_causes_unknown_run_id_returns_404(qa_client, db_path):
    resp = await qa_client.get("/api/runs/999999/causes")
    assert resp.status_code == 404


# ------------------------------------------------------------------ ленивый пересчёт (ensure_run_results)

async def test_causes_lazily_computes_run_test_results_when_missing(qa_client, db_path, isolated_allure_dir, tmp_path):
    """Прогон без единой строки в run_test_results (как если бы он был запущен до
    этой фичи) — GET /runs/{id}/causes должен сам досчитать причины через
    failure_causes.ensure_run_results, а не просто вернуть пустую сводку."""
    from app.config import settings

    project_dir = tmp_path / "no_venv_project"
    project_dir.mkdir()

    conn = get_connection()
    try:
        _insert_project_and_stand(conn, path=str(project_dir), venv=".venv")
        run_id = _insert_run(conn, {"passed": 0, "failed": 1})
    finally:
        conn.close()

    _write_allure_result(
        settings.ALLURE_RESULTS_DIR, run_id, "00-result.json",
        "tests.c#test_throttling", "failed", "429 Too Many Requests",
    )

    # перед запросом убеждаемся, что кэша действительно нет
    conn = get_connection()
    try:
        assert conn.execute("SELECT 1 FROM run_test_results WHERE run_id = ?", (run_id,)).fetchone() is None
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/runs/{run_id}/causes")
    assert resp.status_code == 200, resp.text
    summary = resp.json()["summary"]
    assert summary["throttling"] == 1
    assert summary["total"] == 1

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT cause FROM run_test_results WHERE run_id = ? AND full_name = ?",
            (run_id, "tests.c#test_throttling"),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["cause"] == "throttling"


async def test_causes_lazy_recompute_is_idempotent_on_second_request(qa_client, db_path, isolated_allure_dir, tmp_path):
    """Повторный запрос не должен задвоить строки run_test_results (ensure_run_results
    должен считать прогон уже посчитанным и ничего не трогать повторно)."""
    from app.config import settings

    project_dir = tmp_path / "no_venv_project"
    project_dir.mkdir()

    conn = get_connection()
    try:
        _insert_project_and_stand(conn, path=str(project_dir), venv=".venv")
        run_id = _insert_run(conn, {"passed": 0, "failed": 1})
    finally:
        conn.close()
    _write_allure_result(
        settings.ALLURE_RESULTS_DIR, run_id, "00-result.json",
        "tests.c#test_throttling", "failed", "429 Too Many Requests",
    )

    first = await qa_client.get(f"/api/runs/{run_id}/causes")
    second = await qa_client.get(f"/api/runs/{run_id}/causes")
    assert first.status_code == second.status_code == 200
    assert first.json()["summary"] == second.json()["summary"]

    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM run_test_results WHERE run_id = ?", (run_id,)).fetchone()["c"]
    finally:
        conn.close()
    assert count == 1


def test_record_run_results_xdist_run_takes_time_and_final_status_from_allure(db_path, isolated_allure_dir):
    """Прогон под xdist (stands.workers > 0, run 66 на k8s 13.10.2026): событий test_end
    в run_events нет вовсе, поэтому (а) finished_ts берётся из allure `stop` — иначе
    detect_waves не находила волны 429; (б) при реране финальный статус — у последней
    по времени попытки, а не у последнего файла по имени (uuid — случайный порядок:
    для run 66 получалось 129 падений вместо финальных)."""
    from app.config import settings
    from app.core import failure_causes as fc

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_id = _insert_run(conn, {"passed": 1, "failed": 1, "broken": 0, "skipped": 0})
    finally:
        conn.close()
    run_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    base_ms = 1_760_000_000_000
    # реран: файл с passed сортируется по имени РАНЬШЕ, но по времени — ПОЗЖЕ файла с failed
    (run_dir / "a-result.json").write_text(json.dumps({
        "fullName": "tests.c#test_flaky", "status": "passed", "start": base_ms + 20_000, "stop": base_ms + 25_000,
    }), encoding="utf-8")
    (run_dir / "b-result.json").write_text(json.dumps({
        "fullName": "tests.c#test_flaky", "status": "failed", "start": base_ms, "stop": base_ms + 5_000,
        "statusDetails": {"message": "429 Too Many Requests"},
    }), encoding="utf-8")
    (run_dir / "c-result.json").write_text(json.dumps({
        "fullName": "tests.c#test_429", "status": "failed", "start": base_ms, "stop": base_ms + 7_000,
        "statusDetails": {"message": "429 Too Many Requests"},
    }), encoding="utf-8")

    fc.record_run_results(run_id, PROJECT, STAND, {})

    conn = get_connection()
    try:
        rows = {r["nodeid"]: dict(r) for r in conn.execute(
            "SELECT * FROM run_test_results WHERE run_id = ?", (run_id,)
        ).fetchall()}
    finally:
        conn.close()
    assert rows["tests.c#test_flaky"]["status"] == "passed"
    assert rows["tests.c#test_flaky"]["cause"] is None
    assert rows["tests.c#test_429"]["cause"] == "throttling"
    expected_ts = datetime.fromtimestamp((base_ms + 7_000) / 1000).isoformat(timespec="seconds")
    assert rows["tests.c#test_429"]["finished_ts"] == expected_ts
    assert fc.detect_waves([{"cause": "throttling", "finished_ts": expected_ts}] * 5)
