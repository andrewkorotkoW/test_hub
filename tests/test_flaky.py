"""Смоук-тесты флаки-детектора (app/core/flaky.py, app/routers/flaky.py).

recalc() читает allure-results через app.core.allure_report.parse_results (как и
app.core.coverage, см. tests/test_coverage.py) — здесь эти результаты не порождаются
реальным pytest-прогоном, а пишутся напрямую в изолированный ALLURE_RESULTS_DIR
(isolated_allure_dir, tests/conftest.py), вместе со строками runs, вставленными
напрямую в БД: так тест проверяет именно арифметику recalc() (runs/fails/flips/score,
включая rerun-дубликаты одного fullName внутри одного прогона), не завися от
реального venv/pytest фикстурного проекта."""
import json
from urllib.parse import quote

import pytest

from app.core import flaky
from app.db import get_connection

PROJECT = "flaky_proj"
STAND = "stage"


def _insert_project_and_stand(conn):
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/does-not-matter', '.venv', '[]')",
        (PROJECT,),
    )
    conn.execute(
        "INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND)
    )
    conn.commit()


def _insert_run(conn, status="passed") -> int:
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, ?, 'all', ?, '2024-01-01T00:00:00', 'qa', '{}')",
        (PROJECT, STAND, status),
    )
    conn.commit()
    return cur.lastrowid


def _write_allure_result(results_dir, filename, full_name, test_status):
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / filename).write_text(
        json.dumps({"status": test_status, "fullName": full_name}), encoding="utf-8"
    )


@pytest.fixture()
def flaky_history(db_path, isolated_allure_dir):
    """3 прогона: passed, failed, и третий с двумя *-result.json одного fullName
    (rerun-дубликат внутри прогона) — passed затем failed, тоже считается как
    отдельные элементы хронологической последовательности статусов."""
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_a = _insert_run(conn, "passed")
        run_b = _insert_run(conn, "failed")
        run_c = _insert_run(conn, "failed")
    finally:
        conn.close()

    full_name = "tests.test_flaky_sample#test_thing"
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_a), "00-result.json", full_name, "passed")
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_b), "00-result.json", full_name, "failed")
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_c), "00-result.json", full_name, "passed")
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_c), "01-result.json", full_name, "failed")
    return full_name


def test_recalc_computes_runs_fails_flips_score(flaky_history):
    full_name = flaky_history
    stats = flaky.recalc(PROJECT, STAND)

    assert len(stats) == 1
    row = stats[0]
    assert row["test"] == full_name
    # хронология: passed, failed, passed, failed -> 4 записи, 3 смены статуса подряд
    assert row["runs"] == 4
    assert row["fails"] == 2
    assert row["flips"] == 3
    assert row["score"] == pytest.approx(1.0)
    assert row["last_statuses"] == ["passed", "failed", "passed", "failed"]

    conn = get_connection()
    try:
        cached = flaky.get_stat(conn, PROJECT, STAND, full_name)
    finally:
        conn.close()
    assert cached is not None
    assert cached["runs"] == 4


def test_recalc_overwrites_previous_stats_for_same_project_stand(flaky_history):
    flaky.recalc(PROJECT, STAND, test_history=1)  # только последний прогон (run_c)
    conn = get_connection()
    try:
        row = flaky.get_stat(conn, PROJECT, STAND, flaky_history)
    finally:
        conn.close()
    assert row is not None
    assert row["runs"] == 2  # run_c сам по себе содержит 2 записи (rerun-дубликат)


async def test_flaky_api_list_and_history(qa_client, flaky_history):
    flaky.recalc(PROJECT, STAND)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/flaky", params={"stand": STAND, "min_runs": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["test"] == flaky_history
    assert item["runs"] == 4
    assert item["fails"] == 2
    assert item["score"] == pytest.approx(1.0)
    # tmp_path-проект без .venv -> runner.discover() не находит дерево тестов,
    # nodeid остаётся best-effort None (см. app/routers/flaky.py).
    assert item["nodeid"] is None

    history_resp = await qa_client.get(
        f"/api/projects/{PROJECT}/flaky/{quote(flaky_history, safe='')}", params={"stand": STAND}
    )
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()["history"]
    assert [h["status"] for h in history] == ["passed", "failed", "passed", "failed"]


async def test_flaky_api_min_runs_filters_out_short_history(qa_client, flaky_history):
    flaky.recalc(PROJECT, STAND)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/flaky", params={"stand": STAND, "min_runs": 5})
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ------------------------------------------------------------------ роли: флаки-статистика read-only для всех трёх ролей
async def test_flaky_api_list_allows_manager(manager_client, flaky_history):
    flaky.recalc(PROJECT, STAND)
    resp = await manager_client.get(f"/api/projects/{PROJECT}/flaky", params={"stand": STAND})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


async def test_flaky_api_list_allows_customer(customer_client, flaky_history):
    flaky.recalc(PROJECT, STAND)
    resp = await customer_client.get(f"/api/projects/{PROJECT}/flaky", params={"stand": STAND})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


async def test_flaky_api_history_allows_customer(customer_client, flaky_history):
    flaky.recalc(PROJECT, STAND)
    resp = await customer_client.get(
        f"/api/projects/{PROJECT}/flaky/{quote(flaky_history, safe='')}", params={"stand": STAND}
    )
    assert resp.status_code == 200, resp.text


# ------------------------------------------------------------------ causes-aware recalc (docs/missions/
# 2026-10-13_run_compare_and_causes.md, п.5): падения cause != 'code' не считаются
# за fails/flips, иначе одна волна 429 делает флаки половину проекта.

def _insert_run_test_result(conn, run_id, full_name, status, cause):
    conn.execute(
        "INSERT INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
        "VALUES (?, ?, ?, ?, NULL, ?, NULL)",
        (run_id, full_name, full_name, status, cause),
    )
    conn.commit()


@pytest.fixture()
def flaky_history_with_stand_failure(db_path, isolated_allure_dir):
    """4 прогона: passed, failed(cause=stand), passed, failed(cause=code) — третий
    (стендовое падение) не должен увеличить fails/flips, последний (code) должен."""
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        run_a = _insert_run(conn, "passed")
        run_b = _insert_run(conn, "failed")
        run_c = _insert_run(conn, "passed")
        run_d = _insert_run(conn, "failed")
    finally:
        conn.close()

    full_name = "tests.test_flaky_sample#test_stand_noise"
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_a), "00-result.json", full_name, "passed")
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_b), "00-result.json", full_name, "failed")
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_c), "00-result.json", full_name, "passed")
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_d), "00-result.json", full_name, "failed")

    conn = get_connection()
    try:
        _insert_run_test_result(conn, run_b, full_name, "failed", "stand")
        _insert_run_test_result(conn, run_d, full_name, "failed", "code")
    finally:
        conn.close()
    return full_name


def test_recalc_stand_cause_failure_does_not_count_as_fail_or_flip(flaky_history_with_stand_failure):
    full_name = flaky_history_with_stand_failure
    stats = flaky.recalc(PROJECT, STAND)

    assert len(stats) == 1
    row = stats[0]
    # эффективная хронология: passed, passed(наследует от предыдущего, cause=stand
    # не считается), passed, failed(cause=code) -> 1 fail, 1 flip (passed -> failed)
    assert row["fails"] == 1
    assert row["flips"] == 1
    assert row["score"] == pytest.approx(1 / 3)
    # last_statuses показывает реальную историю (включая стендовое падение), а не
    # эффективную — см. docstring flaky.recalc
    assert row["last_statuses"] == ["passed", "failed", "passed", "failed"]
    assert row["runs"] == 4


@pytest.fixture()
def flaky_history_all_infra_causes(db_path, isolated_allure_dir):
    """Волна инфраструктурных падений разных причин (throttling/session/stand) —
    ни одна не должна увеличить fails/flips для теста, который иначе стабильно passed."""
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        runs = [_insert_run(conn, "passed") for _ in range(2)] + [_insert_run(conn, "failed") for _ in range(3)] + [_insert_run(conn, "passed")]
    finally:
        conn.close()

    full_name = "tests.test_flaky_sample#test_infra_noise"
    statuses = ["passed", "passed", "failed", "failed", "failed", "passed"]
    causes = [None, None, "throttling", "session", "stand", None]
    conn = get_connection()
    try:
        for run_id, test_status, cause in zip(runs, statuses, causes):
            _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_id), "00-result.json", full_name, test_status)
            if cause is not None:
                _insert_run_test_result(conn, run_id, full_name, test_status, cause)
    finally:
        conn.close()
    return full_name


def test_recalc_throttling_session_stand_causes_never_count_as_fail_or_flip(flaky_history_all_infra_causes):
    full_name = flaky_history_all_infra_causes
    stats = flaky.recalc(PROJECT, STAND)
    assert len(stats) == 1
    row = stats[0]
    assert row["fails"] == 0
    assert row["flips"] == 0
    assert row["score"] == pytest.approx(0.0)
    assert row["last_statuses"] == ["passed", "passed", "failed", "failed", "failed", "passed"]


def test_recalc_without_run_test_results_keeps_old_behavior(flaky_history):
    """Прогоны без строк в run_test_results (старые, до этой фичи) — cause всегда
    None -> каждое failed/broken считается как есть, как раньше (регресс уже
    покрыт основным тестом test_recalc_computes_runs_fails_flips_score выше —
    здесь дублируем проверку явно, чтобы она не зависела от реализации causes)."""
    full_name = flaky_history
    stats = flaky.recalc(PROJECT, STAND)
    row = stats[0]
    assert row["test"] == full_name
    assert row["fails"] == 2
    assert row["flips"] == 3
