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
    (rerun-дубликат внутри прогона) — passed затем failed. С 22.10.2026 recalc берёт
    финальную попытку (allure_report.final_attempts: без stop_ts — последнюю по
    порядку файлов, здесь failed), а не обе записи: реран внутри прогона — не два
    прогона и не смена статуса."""
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
    # хронология: passed, failed, failed (финальная попытка run_c) -> 3 записи, 1 смена статуса
    assert row["runs"] == 3
    assert row["fails"] == 2
    assert row["flips"] == 1
    assert row["score"] == pytest.approx(0.5)
    assert row["last_statuses"] == ["passed", "failed", "failed"]

    conn = get_connection()
    try:
        cached = flaky.get_stat(conn, PROJECT, STAND, full_name)
    finally:
        conn.close()
    assert cached is not None
    assert cached["runs"] == 3


def test_recalc_overwrites_previous_stats_for_same_project_stand(flaky_history):
    flaky.recalc(PROJECT, STAND, test_history=1)  # только последний прогон (run_c)
    conn = get_connection()
    try:
        row = flaky.get_stat(conn, PROJECT, STAND, flaky_history)
    finally:
        conn.close()
    assert row is not None
    assert row["runs"] == 1  # run_c содержит 2 записи (rerun-дубликат), считается финальная


def test_recalc_rerun_passed_after_failed_is_not_a_flip(db_path, isolated_allure_dir):
    """Тест упал и прошёл на реране в каждом из двух прогонов: до 22.10.2026 это давало
    последовательность failed, passed, failed, passed — 100 % нестабильности и 2 падения;
    теперь финальная попытка (по stop_ts) обоих прогонов passed — 0 flips, 0 fails."""
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        runs = [_insert_run(conn, "passed"), _insert_run(conn, "passed")]
    finally:
        conn.close()
    full_name = "tests.test_flaky_sample#test_rerun"
    for run_id in runs:
        results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
        results_dir.mkdir(parents=True, exist_ok=True)
        # файлы названы так, что «по порядку» passed шёл бы первым — порядок решает stop_ts
        (results_dir / "00-result.json").write_text(
            json.dumps({"status": "passed", "fullName": full_name, "start": 2000, "stop": 3000}), encoding="utf-8"
        )
        (results_dir / "01-result.json").write_text(
            json.dumps({"status": "failed", "fullName": full_name, "start": 0, "stop": 1000}), encoding="utf-8"
        )

    stats = flaky.recalc(PROJECT, STAND)
    assert len(stats) == 1
    assert stats[0]["runs"] == 2
    assert stats[0]["fails"] == 0
    assert stats[0]["flips"] == 0
    assert stats[0]["last_statuses"] == ["passed", "passed"]


async def test_flaky_api_list_and_history(qa_client, flaky_history):
    flaky.recalc(PROJECT, STAND)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/flaky", params={"stand": STAND, "min_runs": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["test"] == flaky_history
    assert item["runs"] == 3
    assert item["fails"] == 2
    assert item["score"] == pytest.approx(0.5)
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
    assert row["flips"] == 1


# ------------------------------------------------------------------ 14.10.2026: skipped нейтрален, параметры не схлопываются

def _write_allure_case(results_dir, filename, full_name, param_value, test_status):
    """allure-pytest кладёт параметры в `parameters` (значения — repr, в кавычках),
    а `name` — это allure-заголовок (allure.title), не pytest-имя с [id]."""
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / filename).write_text(
        json.dumps({
            "status": test_status, "fullName": full_name,
            "name": "API: справочник — создание, редактирование и удаление записи",
            "parameters": [{"name": "key", "value": f"'{param_value}'"}],
        }),
        encoding="utf-8",
    )


@pytest.fixture()
def flaky_history_with_skips(db_path, isolated_allure_dir):
    """xfail начал проходить: skipped, skipped, passed, passed — раньше это давало flip
    и тест попадал во «Флаки», хотя ни разу не падал."""
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        runs = [_insert_run(conn, "passed") for _ in range(4)]
    finally:
        conn.close()
    full_name = "tests.test_flaky_sample#test_xfail_then_ok"
    for run_id, st in zip(runs, ["skipped", "skipped", "passed", "passed"]):
        _write_allure_result(settings.ALLURE_RESULTS_DIR / str(run_id), "00-result.json", full_name, st)
    return full_name


def test_recalc_skipped_is_neutral_for_fails_and_flips(flaky_history_with_skips):
    row = flaky.recalc(PROJECT, STAND)[0]
    assert row["test"] == flaky_history_with_skips
    assert row["runs"] == 4
    assert row["fails"] == 0
    assert row["flips"] == 0, "переход skipped→passed — не нестабильность"
    assert row["score"] == 0.0
    assert row["last_statuses"] == ["skipped", "skipped", "passed", "passed"], "сырая история остаётся как есть"


@pytest.fixture()
def flaky_history_parametrized(db_path, isolated_allure_dir):
    """Один fullName, два параметра: [tag] всегда passed, [blacklist] — xfail (skipped) и один
    failed. До разделения по параметрам они склеивались в одну строку с ложными перепадами."""
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
        runs = [_insert_run(conn, "failed") for _ in range(3)]
    finally:
        conn.close()
    full_name = "tests.api.helpdesk.test_dictionaries_api.TestDictionariesApi#test_dictionary_crud"
    for i, run_id in enumerate(runs):
        d = settings.ALLURE_RESULTS_DIR / str(run_id)
        _write_allure_case(d, "00-result.json", full_name, "tag", "passed")
        _write_allure_case(d, "01-result.json", full_name, "blacklist", "failed" if i == 1 else "skipped")
    return full_name


def test_recalc_separates_parametrized_cases_by_allure_name(flaky_history_parametrized):
    stats = {s["test"]: s for s in flaky.recalc(PROJECT, STAND)}
    base = flaky_history_parametrized
    assert set(stats) == {f"{base}[tag]", f"{base}[blacklist]"}
    assert stats[f"{base}[tag]"]["flips"] == 0 and stats[f"{base}[tag]"]["fails"] == 0
    bl = stats[f"{base}[blacklist]"]
    assert bl["fails"] == 1
    assert bl["last_statuses"] == ["skipped", "failed", "skipped"]


def test_run_history_for_test_matches_parametrized_key(flaky_history_parametrized):
    base = flaky_history_parametrized
    flaky.recalc(PROJECT, STAND)
    history = flaky.run_history_for_test(PROJECT, STAND, f"{base}[blacklist]")
    assert [h["status"] for h in history] == ["skipped", "failed", "skipped"]
    assert flaky.run_history_for_test(PROJECT, STAND, base) == [], "по голому fullName параметризованный кейс не находится"


def test_test_key_and_split_roundtrip():
    assert flaky.test_key({"name": "tests.a#test_x", "params": "p1-p2"}) == "tests.a#test_x[p1-p2]"
    assert flaky.test_key({"name": "tests.a#test_x", "params": None}) == "tests.a#test_x"
    assert flaky.test_key({"name": "tests.a#test_x"}) == "tests.a#test_x"
    assert len(flaky.test_key({"name": "t#f", "params": "x" * 200})) == len("t#f") + flaky.PARAMS_KEY_LIMIT + 2
    assert flaky.split_test_key("tests.a#test_x[p1-p2]") == ("tests.a#test_x", "p1-p2")
    assert flaky.split_test_key("tests.a#test_x") == ("tests.a#test_x", None)
