"""Видео-заглушки для прогонов демо-проекта (app/core/demo_video.py, docs/missions/
2026-10-01_live_stream.md, раздел «Демо-проект»). Для скорости и изоляции проверяется
на фикстурном мини-проекте (runnable_project_dir из conftest), а не на настоящем
demo/ (для него реальный прогон уже проверяется в tests/test_demo_run.py) — сидированный
проект Demo (app/db.py::_seed_demo_project) для этого перенацеливается на фикстурный
путь прямым UPDATE в БД, как test_schedule.py делает для sched_proj."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import demo_video, runner
from app.db import DEMO_PROJECT_NAME, get_connection as db_get_connection
from app.main import app as fastapi_app

from .conftest import poll_until

STAND = "local"


def _write_allure_result(results_dir, filename, full_name, status):
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / filename).write_text(json.dumps({"fullName": full_name, "status": status}), encoding="utf-8")


def _point_demo_at(conn, project_dir):
    conn.execute(
        "UPDATE projects SET path = ?, venv = ? WHERE name = ?",
        (str(project_dir), ".venv", DEMO_PROJECT_NAME),
    )
    conn.commit()


def _insert_demo_run(conn, status="passed"):
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, finished, duration, requested_by, counts) "
        "VALUES (?, ?, 'all', ?, '2026-01-01T00:00:00', '2026-01-01T00:01:00', 2.0, 'tour', '{}')",
        (DEMO_PROJECT_NAME, STAND, status),
    )
    conn.commit()
    return cur.lastrowid


# ------------------------------------------------------------------ on_run_finished (юнит)

async def test_on_run_finished_attaches_stub_videos_to_first_two_passed_tests(
    db_path, isolated_allure_dir, isolated_video_dir, runnable_project_dir
):
    conn = db_get_connection()
    try:
        _point_demo_at(conn, runnable_project_dir)
        run_id = _insert_demo_run(conn)
    finally:
        conn.close()

    results_dir = runner.allure_dir(run_id)
    # a/b/c — имена файлов сортируются parse_results()'ом лексикографически, поэтому
    # порядок совпадает с порядком full_name ниже: два passed раньше failed.
    _write_allure_result(results_dir, "a-result.json", "tests.test_sample#test_ok", "passed")
    _write_allure_result(results_dir, "b-result.json", "tests.test_sample#test_ok_two", "passed")
    _write_allure_result(results_dir, "c-result.json", "tests.test_sample#test_fail", "failed")

    await demo_video.on_run_finished(run_id)

    conn = db_get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM run_test_videos WHERE run_id = ? ORDER BY nodeid", (run_id,)
        ).fetchall()
    finally:
        conn.close()

    assert [r["nodeid"] for r in rows] == [
        "tests/test_sample.py::test_ok",
        "tests/test_sample.py::test_ok_two",
    ]
    for row in rows:
        assert row["size"] > 0
        assert row["duration_ms"] == demo_video.STUB_DURATION_MS
        video_path = runner.video_dir(run_id) / f"{demo_video._nodeid_hash(row['nodeid'])}.webm"
        assert video_path.is_file()
        assert video_path.read_bytes()[:4] == b"\x1aE\xdf\xa3"  # EBML magic — настоящий webm


async def test_on_run_finished_skips_failed_tests(
    db_path, isolated_allure_dir, isolated_video_dir, runnable_project_dir
):
    conn = db_get_connection()
    try:
        _point_demo_at(conn, runnable_project_dir)
        run_id = _insert_demo_run(conn, status="failed")
    finally:
        conn.close()

    _write_allure_result(
        runner.allure_dir(run_id), "a-result.json", "tests.test_sample#test_fail", "failed"
    )

    await demo_video.on_run_finished(run_id)

    conn = db_get_connection()
    try:
        rows = conn.execute("SELECT * FROM run_test_videos WHERE run_id = ?", (run_id,)).fetchall()
    finally:
        conn.close()
    assert rows == []


async def test_on_run_finished_is_idempotent(
    db_path, isolated_allure_dir, isolated_video_dir, runnable_project_dir
):
    conn = db_get_connection()
    try:
        _point_demo_at(conn, runnable_project_dir)
        run_id = _insert_demo_run(conn)
    finally:
        conn.close()

    _write_allure_result(
        runner.allure_dir(run_id), "a-result.json", "tests.test_sample#test_ok", "passed"
    )

    await demo_video.on_run_finished(run_id)
    await demo_video.on_run_finished(run_id)

    conn = db_get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM run_test_videos WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


async def test_on_run_finished_is_noop_for_other_projects(db_path, isolated_allure_dir):
    conn = db_get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES ('other_proj', '/tmp/x', '.venv', '[]')"
        )
        conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, finished, duration, requested_by, counts) "
            "VALUES ('other_proj', ?, 'all', 'passed', '2026-01-01T00:00:00', '2026-01-01T00:01:00', 1.0, 'x', '{}')",
            (STAND,),
        )
        conn.commit()
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    await demo_video.on_run_finished(run_id)

    conn = db_get_connection()
    try:
        rows = conn.execute("SELECT * FROM run_test_videos WHERE run_id = ?", (run_id,)).fetchall()
    finally:
        conn.close()
    assert rows == []


async def test_on_run_finished_is_noop_for_unknown_run_id(db_path):
    await demo_video.on_run_finished(999999)  # не должно падать


async def test_on_run_finished_warns_and_noops_without_stub_assets(
    db_path, isolated_allure_dir, isolated_video_dir, runnable_project_dir, monkeypatch, tmp_path
):
    monkeypatch.setattr(demo_video, "ASSETS_DIR", tmp_path / "no_such_assets")
    conn = db_get_connection()
    try:
        _point_demo_at(conn, runnable_project_dir)
        run_id = _insert_demo_run(conn)
    finally:
        conn.close()
    _write_allure_result(
        runner.allure_dir(run_id), "a-result.json", "tests.test_sample#test_ok", "passed"
    )

    await demo_video.on_run_finished(run_id)

    conn = db_get_connection()
    try:
        rows = conn.execute("SELECT * FROM run_test_videos WHERE run_id = ?", (run_id,)).fetchall()
    finally:
        conn.close()
    assert rows == []


# ------------------------------------------------------------------ интеграция с runner._finalize + API

@pytest.fixture()
def _registered_hook():
    runner.register_finalize_hook(demo_video.on_run_finished)
    yield
    runner.unregister_finalize_hook(demo_video.on_run_finished)


async def test_real_demo_run_gets_video_and_has_video_flag_via_api(
    db_path, isolated_allure_dir, isolated_video_dir, runnable_project_dir, _registered_hook
):
    conn = db_get_connection()
    try:
        _point_demo_at(conn, runnable_project_dir)
    finally:
        conn.close()

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/login", json={"login": "qa", "password": "qa"})
        assert resp.status_code == 200

        run_resp = await client.post(
            f"/api/projects/{DEMO_PROJECT_NAME}/runs", json={"stand": STAND, "target": "all"}
        )
        assert run_resp.status_code == 201, run_resp.text
        run_id = run_resp.json()["id"]

        async def finished():
            rows = (await client.get(f"/api/projects/{DEMO_PROJECT_NAME}/runs")).json()
            row = next(r for r in rows if r["id"] == run_id)
            return row if row["status"] in {"passed", "failed", "cancelled"} else None

        final = await poll_until(finished, timeout=30)
        assert final is not None, "фикстурный прогон Demo не завершился вовремя"

        # _finalize запускает demo_video.on_run_finished фоновой asyncio-задачей
        # (см. runner.py) — она выполняется уже ПОСЛЕ того, как статус прогона
        # стал passed/failed, поэтому has_video ждём отдельным поллингом.
        async def has_video():
            tests = (await client.get(f"/api/runs/{run_id}/tests")).json()
            return tests if any(t["has_video"] for t in tests) else None

        tests = await poll_until(has_video, timeout=10)
        assert tests is not None, f"видео так и не появилось: {(await client.get(f'/api/runs/{run_id}/tests')).json()}"
        with_video = [t for t in tests if t["has_video"]]
        assert all(t["status"] == "passed" for t in with_video)

        nodeid = with_video[0]["nodeid"]
        video_resp = await client.get(f"/api/runs/{run_id}/tests/{nodeid}/video")
        assert video_resp.status_code == 200
        assert video_resp.content[:4] == b"\x1aE\xdf\xa3"

        range_resp = await client.get(
            f"/api/runs/{run_id}/tests/{nodeid}/video", headers={"Range": "bytes=0-3"}
        )
        assert range_resp.status_code == 206
        assert range_resp.content == b"\x1aE\xdf\xa3"
