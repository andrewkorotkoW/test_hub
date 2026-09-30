"""GET /api/runs/{id}/tests, .../tests/{nodeid}/log, .../tests/{nodeid}/frames и
WS /ws/runs/{id} с разметкой по nodeid/kind (этап 2 окна прогона).

Вместо реального прогона с плагином (тот делается отдельной миссией) события
run_events вставляются в БД напрямую — так же надёжно проверяет разбор/выдачу,
но без гонки с настоящим subprocess pytest (см. и мотивацию в мисии: "тестировать
логику разбора ... синтетическими данными, не полагаясь на реальный прогон").
"""
import hashlib
import json
import sqlite3
from datetime import datetime
from urllib.parse import quote

from starlette.testclient import TestClient

from app.core import runner
from app.main import app

from .conftest import register_project


def _insert_run(conn, project, status_, requested_by="qa"):
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, NULL, 'all', ?, ?, ?, '{}')",
        (project, status_, now, requested_by),
    )
    conn.commit()
    return cur.lastrowid


def _insert_event(conn, run_id, line, nodeid, kind):
    conn.execute(
        "INSERT INTO run_events (run_id, ts, line, nodeid, kind) VALUES (?, ?, ?, ?, ?)",
        (run_id, datetime.now().isoformat(timespec="seconds"), line, nodeid, kind),
    )
    conn.commit()


async def test_list_run_tests_while_running_uses_live_th_events(qa_client, db_path):
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "running")
        nodeid_a = "tests/test_x.py::test_a"
        nodeid_b = "tests/test_x.py::test_b"
        _insert_event(conn, run_id, f"[TH] start {nodeid_a}", nodeid_a, "test_start")
        _insert_event(conn, run_id, "console output", nodeid_a, "line")
        _insert_event(conn, run_id, f"[TH] end {nodeid_a} passed", nodeid_a, "test_end")
        h = hashlib.sha1(nodeid_a.encode()).hexdigest()[:16]
        _insert_event(conn, run_id, f"{h}/1.png", nodeid_a, "frame")
        _insert_event(conn, run_id, f"[TH] start {nodeid_b}", nodeid_b, "test_start")
        # nodeid_b ещё без "end" -> статус running, has_frames=False
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert resp.status_code == 200
    items = {item["nodeid"]: item for item in resp.json()}
    assert items[nodeid_a] == {
        "nodeid": nodeid_a, "full_name": "tests.test_x#test_a", "status": "passed", "has_frames": True,
        "has_video": False,
    }
    assert items[nodeid_b] == {
        "nodeid": nodeid_b, "full_name": "tests.test_x#test_b", "status": "running", "has_frames": False,
        "has_video": False,
    }


async def test_list_run_tests_after_finish_falls_back_to_full_name_for_unknown_project(
    qa_client, isolated_allure_dir, db_path
):
    """Проект "any_proj" не зарегистрирован (нет строки в projects) — статическое
    дерево тестов (runner.discover()) недоступно, поэтому nodeid деградирует до
    allure fullName (лучше, чем падать), но full_name отдаётся всегда."""
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "passed")
    finally:
        conn.close()

    results_dir = runner.allure_dir(run_id)
    results_dir.mkdir(parents=True)
    (results_dir / "abc-result.json").write_text(
        json.dumps(
            {"fullName": "tests.test_x#test_marked", "name": "test_marked", "status": "passed", "start": 0, "stop": 1000}
        )
    )

    resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "nodeid": "tests.test_x#test_marked",
            "full_name": "tests.test_x#test_marked",
            "status": "passed",
            "has_frames": False,
            "has_video": False,
        }
    ]


async def test_list_run_tests_after_finish_maps_allure_full_name_to_pytest_nodeid(
    qa_client, isolated_allure_dir, runnable_project_dir, db_path
):
    """Живой прогон #40 VSHGU показал: allure отдаёт только fullName
    (tests.ui...TestX#test_x), а кадры/лог пишутся под pytest nodeid
    (tests/ui/...py::TestX::test_x) — без сопоставления UI не находил кадры
    (has_frames=false). GET /tests должен приводить fullName к nodeid через
    статическое дерево тестов проекта (runner.discover()), как это уже делают
    app/routers/flaky.py и app/routers/xfail.py."""
    await register_project(qa_client, "with_tree_proj", runnable_project_dir)
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "with_tree_proj", "passed")
    finally:
        conn.close()

    results_dir = runner.allure_dir(run_id)
    results_dir.mkdir(parents=True)
    (results_dir / "abc-result.json").write_text(
        json.dumps(
            {"fullName": "tests.test_sample#test_ok", "name": "test_ok", "status": "passed", "start": 0, "stop": 1000}
        )
    )

    resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "nodeid": "tests/test_sample.py::test_ok",
            "full_name": "tests.test_sample#test_ok",
            "status": "passed",
            "has_frames": False,
            "has_video": False,
        }
    ]


async def test_get_run_test_log_filters_by_nodeid_and_kind(qa_client, db_path):
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "running")
        nodeid = "tests/ui/test_x.py::TestGroup::test_foo[a b]"
        other_nodeid = "tests/ui/test_x.py::test_bar"
        _insert_event(conn, run_id, f"[TH] start {nodeid}", nodeid, "test_start")
        _insert_event(conn, run_id, "line one", nodeid, "line")
        step_line = f"[TH] step {nodeid} 1 клик"
        _insert_event(conn, run_id, step_line, nodeid, "step")
        _insert_event(conn, run_id, "line two", nodeid, "line")
        _insert_event(conn, run_id, f"[TH] end {nodeid} passed", nodeid, "test_end")
        _insert_event(conn, run_id, "unrelated line", other_nodeid, "line")
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/runs/{run_id}/tests/{quote(nodeid, safe='')}/log")
    assert resp.status_code == 200
    assert resp.json() == ["line one", step_line, "line two"]


async def test_get_run_test_frames_lists_steps_and_urls(qa_client, isolated_frames_dir, db_path):
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "running")
        nodeid = "tests/ui/test_x.py::test_foo"
        h = hashlib.sha1(nodeid.encode()).hexdigest()[:16]
        _insert_event(conn, run_id, f"{h}/1.png", nodeid, "frame")
        _insert_event(conn, run_id, f"{h}/2.png", nodeid, "frame")
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/runs/{run_id}/tests/{quote(nodeid, safe='')}/frames")
    assert resp.status_code == 200
    assert resp.json() == [
        {"step": 1, "url": f"/api/runs/{run_id}/frames/{h}/1.png"},
        {"step": 2, "url": f"/api/runs/{run_id}/frames/{h}/2.png"},
    ]


async def test_list_run_tests_after_finish_has_frames_matches_by_pytest_nodeid(
    qa_client, isolated_allure_dir, isolated_frames_dir, runnable_project_dir, db_path
):
    """Кадры (POST /runs/{id}/frames) всегда пишутся под pytest nodeid (плагин
    передаёт его напрямую, а не allure fullName) — has_frames после завершения
    прогона должен считаться по nodeid, приведённому из allure fullName, а не по
    самому fullName (см. run 40 VSHGU: has_frames был false, хотя кадры были)."""
    await register_project(qa_client, "with_tree_proj2", runnable_project_dir)
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "with_tree_proj2", "passed")
        nodeid = "tests/test_sample.py::TestGroup::test_class_a"
        h = hashlib.sha1(nodeid.encode()).hexdigest()[:16]
        _insert_event(conn, run_id, f"{h}/1.png", nodeid, "frame")
    finally:
        conn.close()

    results_dir = runner.allure_dir(run_id)
    results_dir.mkdir(parents=True)
    (results_dir / "abc-result.json").write_text(
        json.dumps(
            {
                "fullName": "tests.test_sample.TestGroup#test_class_a",
                "name": "test_class_a",
                "status": "passed",
                "start": 0,
                "stop": 1000,
            }
        )
    )

    resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "nodeid": nodeid,
            "full_name": "tests.test_sample.TestGroup#test_class_a",
            "status": "passed",
            "has_frames": True,
            "has_video": False,
        }
    ]


async def test_get_run_test_log_and_frames_404_for_unknown_run(qa_client):
    log_resp = await qa_client.get("/api/runs/999999/tests/whatever/log")
    assert log_resp.status_code == 404
    frames_resp = await qa_client.get("/api/runs/999999/tests/whatever/frames")
    assert frames_resp.status_code == 404


def test_ws_history_replays_nodeid_kind_and_frame_url(db_path):
    """WS-хендлер (app/routers/runs.py::run_events_ws) должен реплеить историю с
    type по kind и полем nodeid — та же форма, что и live-broadcast (_log_line/
    upload_frame). httpx.AsyncClient(ASGITransport) не поддерживает WebSocket,
    поэтому здесь синхронный starlette.testclient.TestClient (тоже поверх ASGI,
    без реального сокета)."""
    client = TestClient(app)
    login = client.post("/api/login", json={"login": "qa", "password": "qa"})
    assert login.status_code == 200

    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "running")
        nodeid = "tests/x.py::test_a"
        _insert_event(conn, run_id, f"[TH] start {nodeid}", nodeid, "test_start")
        h = hashlib.sha1(nodeid.encode()).hexdigest()[:16]
        _insert_event(conn, run_id, f"{h}/1.png", nodeid, "frame")
        _insert_event(conn, run_id, "plain line outside any test", None, "line")
    finally:
        conn.close()

    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        first = ws.receive_json()
        second = ws.receive_json()
        third = ws.receive_json()

    assert first == {
        "type": "test_start", "run_id": run_id, "line": f"[TH] start {nodeid}", "nodeid": nodeid,
    }
    assert second == {
        "type": "frame", "run_id": run_id, "nodeid": nodeid, "step": 1,
        "url": f"/api/runs/{run_id}/frames/{h}/1.png",
    }
    assert third == {
        "type": "line", "run_id": run_id, "line": "plain line outside any test", "nodeid": None,
    }
