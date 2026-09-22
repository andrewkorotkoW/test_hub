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
