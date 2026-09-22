"""Смоук-тесты реестра известных дефектов (app/core/xfail_registry.py,
app/routers/xfail.py): статический AST-разбор @pytest.mark.xfail, recalc() по
allure-results прогона (та же схема, что и tests/test_flaky.py) и REST API."""
import json

import pytest

from app.core import xfail_registry
from app.db import get_connection

from .conftest import _with_symlinked_venv, poll_until, register_project

PROJECT = "xfail_proj"
STAND = "stage"

_TEST_FILE = '''\
import pytest


@pytest.mark.xfail(reason="known bug X")
def test_known_bug():
    assert False


def test_ok():
    assert True


class TestGroup:
    @pytest.mark.xfail(reason="known bug in class")
    def test_class_known_bug(self):
        assert False
'''


@pytest.fixture()
def xfail_project_dir(tmp_path):
    proj = tmp_path / "xfail_src_proj"
    tests_dir = proj / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_something.py").write_text(_TEST_FILE)
    return proj


# ------------------------------------------------------------------ статический AST-анализ

def test_scan_static_finds_xfail_markers_with_reason(xfail_project_dir):
    result = xfail_registry.scan_static(str(xfail_project_dir))
    assert result == {
        "tests.test_something#test_known_bug": "known bug X",
        "tests.test_something.TestGroup#test_class_known_bug": "known bug in class",
    }


def test_scan_static_ignores_missing_tests_dir(tmp_path):
    assert xfail_registry.scan_static(str(tmp_path)) == {}


# ------------------------------------------------------------------ recalc() по allure-results

def _insert_project_and_stand(conn, path):
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')",
        (PROJECT, str(path)),
    )
    conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
    conn.commit()


def _insert_run(conn) -> int:
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, ?, 'all', 'failed', '2024-01-01T00:00:00', 'qa', '{}')",
        (PROJECT, STAND),
    )
    conn.commit()
    return cur.lastrowid


def _write_allure_result(results_dir, filename, full_name, status, message=None):
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fullName": full_name, "status": status}
    if message:
        payload["statusDetails"] = {"message": message}
    (results_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_recalc_classifies_xfail_and_xpass(db_path, isolated_allure_dir, xfail_project_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn, xfail_project_dir)
        run_id = _insert_run(conn)
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    _write_allure_result(
        results_dir, "00-result.json", "tests.test_something#test_known_bug", "skipped", message="XFAIL known bug X"
    )
    # class-level xfail-тест на этот раз прошёл -> дефект, похоже, уже починили (xpass)
    _write_allure_result(
        results_dir, "01-result.json", "tests.test_something.TestGroup#test_class_known_bug", "passed"
    )
    _write_allure_result(results_dir, "02-result.json", "tests.test_something#test_ok", "passed")

    results = xfail_registry.recalc(PROJECT, STAND, run_id)
    by_test = {r["test"]: r["state"] for r in results}
    assert by_test == {
        "tests.test_something#test_known_bug": "xfail",
        "tests.test_something.TestGroup#test_class_known_bug": "xpass",
    }
    # test_ok никогда не был помечен xfail ни статически, ни в этом прогоне -> в реестр не попадает
    assert "tests.test_something#test_ok" not in by_test

    conn = get_connection()
    try:
        rows = {r["test"]: r for r in xfail_registry.list_entries(conn, PROJECT, STAND)}
    finally:
        conn.close()
    assert rows["tests.test_something#test_known_bug"]["reason"] == "known bug X"
    assert rows["tests.test_something#test_known_bug"]["last_run_id"] == run_id
    assert rows["tests.test_something.TestGroup#test_class_known_bug"]["state"] == "xpass"


def test_recalc_preserves_issue_url_and_note_across_reruns(db_path, isolated_allure_dir, xfail_project_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn, xfail_project_dir)
        run_a = _insert_run(conn)
    finally:
        conn.close()

    results_dir_a = settings.ALLURE_RESULTS_DIR / str(run_a)
    _write_allure_result(
        results_dir_a, "00-result.json", "tests.test_something#test_known_bug", "skipped", message="XFAIL known bug X"
    )
    xfail_registry.recalc(PROJECT, STAND, run_a)

    conn = get_connection()
    try:
        row = xfail_registry.get_entry(conn, PROJECT, xfail_registry.list_entries(conn, PROJECT, STAND)[0]["id"])
        xfail_registry.update_entry(conn, row["id"], "https://tracker.example/BUG-1", "under investigation")
    finally:
        conn.close()

    run_b = None
    conn = get_connection()
    try:
        run_b = _insert_run(conn)
    finally:
        conn.close()
    results_dir_b = settings.ALLURE_RESULTS_DIR / str(run_b)
    _write_allure_result(
        results_dir_b, "00-result.json", "tests.test_something#test_known_bug", "skipped", message="XFAIL known bug X"
    )
    xfail_registry.recalc(PROJECT, STAND, run_b)

    conn = get_connection()
    try:
        row = xfail_registry.list_entries(conn, PROJECT, STAND)[0]
    finally:
        conn.close()
    assert row["issue_url"] == "https://tracker.example/BUG-1"
    assert row["note"] == "under investigation"
    assert row["last_run_id"] == run_b


# ------------------------------------------------------------------ REST API

async def test_xfail_api_list_and_update(qa_client, db_path, isolated_allure_dir, xfail_project_dir):
    from app.config import settings

    conn = get_connection()
    try:
        _insert_project_and_stand(conn, xfail_project_dir)
        run_id = _insert_run(conn)
    finally:
        conn.close()
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    _write_allure_result(
        results_dir, "00-result.json", "tests.test_something#test_known_bug", "skipped", message="XFAIL known bug X"
    )
    xfail_registry.recalc(PROJECT, STAND, run_id)

    resp = await qa_client.get(f"/api/projects/{PROJECT}/xfail", params={"stand": STAND})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    # 2 записи: тест, реально замеченный этим прогоном (test_known_bug), и тест,
    # известный только из статического сканирования (TestGroup.test_class_known_bug,
    # ни разу не попадавший в allure-results этого стенда).
    assert len(items) == 2
    item = next(i for i in items if i["test"] == "tests.test_something#test_known_bug")
    assert item["state"] == "xfail"
    assert item["reason"] == "known bug X"

    put_resp = await qa_client.put(
        f"/api/projects/{PROJECT}/xfail/{item['id']}",
        json={"issue_url": "https://tracker.example/BUG-2", "note": "assigned"},
    )
    assert put_resp.status_code == 200, put_resp.text
    updated = put_resp.json()
    assert updated["issue_url"] == "https://tracker.example/BUG-2"
    assert updated["note"] == "assigned"


async def test_xfail_api_update_requires_qa(customer_client, db_path, xfail_project_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn, xfail_project_dir)
    finally:
        conn.close()
    resp = await customer_client.put(f"/api/projects/{PROJECT}/xfail/1", json={"issue_url": "https://x"})
    assert resp.status_code == 403


async def test_xfail_api_check_requires_qa(customer_client, db_path, xfail_project_dir):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn, xfail_project_dir)
    finally:
        conn.close()
    resp = await customer_client.post(
        f"/api/projects/{PROJECT}/xfail/check", params={"stand": STAND}, json={}
    )
    assert resp.status_code == 403


# ------------------------------------------------------------------ сквозной прогон: реальный pytest + recalc

@pytest.fixture()
def runnable_xfail_project_dir(xfail_project_dir):
    return _with_symlinked_venv(xfail_project_dir)


async def test_real_run_feeds_xfail_registry_and_check_reruns_it(
    qa_client, isolated_allure_dir, runnable_xfail_project_dir
):
    await register_project(qa_client, PROJECT, runnable_xfail_project_dir)
    stand_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": "http://example.test"}
    )
    assert stand_resp.status_code == 201, stand_resp.text

    resp = await qa_client.post(f"/api/projects/{PROJECT}/runs", json={"stand": STAND, "target": "all"})
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get(f"/api/projects/{PROJECT}/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=20)
    assert final is not None, "прогон не завершился вовремя"

    async def xfail_ready():
        items = (await qa_client.get(f"/api/projects/{PROJECT}/xfail", params={"stand": STAND})).json()["items"]
        return items or None

    items = await poll_until(xfail_ready, timeout=10)
    assert items is not None, "реестр xfail не пересчитался вовремя"
    by_test = {i["test"]: i for i in items}
    assert by_test["tests.test_something#test_known_bug"]["state"] == "xfail"
    assert by_test["tests.test_something#test_known_bug"]["nodeid"] == "tests/test_something.py::test_known_bug"

    check_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/xfail/check", params={"stand": STAND}, json={}
    )
    assert check_resp.status_code == 201, check_resp.text
    check_body = check_resp.json()
    assert check_body["count"] >= 1
    assert check_body["run_id"] != run_id
