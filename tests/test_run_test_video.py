"""POST/GET /api/runs/{id}/tests/{nodeid}/video — видео теста, has_video в
GET /api/runs/{id}/tests (контракт docs/missions/2026-10-01_live_stream.md, п.3-4).
"""
import hashlib
import sqlite3
from datetime import datetime
from urllib.parse import quote

from app.config import settings
from app.core import runner

from .conftest import poll_until, register_project

_WEBM_BYTES = b"\x1aE\xdf\xa3" + b"\x00" * 64  # заглушка — валидный заголовок EBML не нужен серверу


def _video_url(run_id, nodeid):
    return f"/api/runs/{run_id}/tests/{quote(nodeid, safe='')}/video"


def _insert_run(conn, project, status_):
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, NULL, 'all', ?, ?, 'qa', '{}')",
        (project, status_, now),
    )
    conn.commit()
    return cur.lastrowid


def _insert_event(conn, run_id, line, nodeid, kind):
    conn.execute(
        "INSERT INTO run_events (run_id, ts, line, nodeid, kind) VALUES (?, ?, ?, ?, ?)",
        (run_id, datetime.now().isoformat(timespec="seconds"), line, nodeid, kind),
    )
    conn.commit()


def _insert_video_row(conn, run_id, nodeid):
    conn.execute(
        "INSERT INTO run_test_videos (run_id, nodeid, path, duration_ms, size, created_at) "
        "VALUES (?, ?, 'unused.webm', 1000, 10, ?)",
        (run_id, nodeid, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


async def test_list_run_tests_includes_has_video_flag(qa_client, db_path):
    """GET /api/runs/{id}/tests — has_video по наличию строки в run_test_videos
    (контракт п.4), проверяется тем же синтетическим приёмом, что и has_frames
    в test_run_tests_api.py, независимо от POST .../video выше (эндпоинт этот
    тест не трогает)."""
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "running")
        nodeid_a = "tests/test_x.py::test_a"
        nodeid_b = "tests/test_x.py::test_b"
        _insert_event(conn, run_id, f"[TH] start {nodeid_a}", nodeid_a, "test_start")
        _insert_event(conn, run_id, f"[TH] end {nodeid_a} passed", nodeid_a, "test_end")
        _insert_event(conn, run_id, f"[TH] start {nodeid_b}", nodeid_b, "test_start")
        _insert_event(conn, run_id, f"[TH] end {nodeid_b} passed", nodeid_b, "test_end")
        _insert_video_row(conn, run_id, nodeid_a)
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert resp.status_code == 200
    items = {item["nodeid"]: item for item in resp.json()}
    assert items[nodeid_a]["has_video"] is True
    assert items[nodeid_b]["has_video"] is False


async def _start_running_run(client, name, path):
    await register_project(client, name, path)
    resp = await client.post(f"/api/projects/{name}/runs", json={"target": "tests/test_slow.py"})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["status"] == "running"
    run_id = run["id"]

    async def token_ready():
        return runner._run_tokens.get(run_id)

    token = await poll_until(token_ready, timeout=5)
    assert token, "раннер не выставил токен прогона (_run_tokens) вовремя"
    return run_id, token


async def _stop_run(client, run_id):
    await client.post(f"/api/runs/{run_id}/cancel")

    async def stopped():
        rows = (await client.get(f"/api/runs/{run_id}/report")).json()
        return rows if rows["status"] not in {"running", "queued"} else None

    await poll_until(stopped, timeout=5)


async def test_video_upload_rejects_missing_or_wrong_token(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "video_auth_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        no_token = await qa_client.post(
            _video_url(run_id, nodeid),
            data={"duration_ms": "2500"},
            files={"file": ("test.webm", _WEBM_BYTES, "video/webm")},
        )
        assert no_token.status_code == 401

        wrong_token = await qa_client.post(
            _video_url(run_id, nodeid),
            data={"duration_ms": "2500"},
            files={"file": ("test.webm", _WEBM_BYTES, "video/webm")},
            headers={"Authorization": "Bearer not-the-real-token"},
        )
        assert wrong_token.status_code == 401
    finally:
        await _stop_run(qa_client, run_id)


async def test_video_upload_rejects_when_run_not_running(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "video_finished_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    await _stop_run(qa_client, run_id)

    resp = await qa_client.post(
        _video_url(run_id, nodeid),
        data={"duration_ms": "2500"},
        files={"file": ("test.webm", _WEBM_BYTES, "video/webm")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_video_upload_rejects_oversized_file(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir, monkeypatch
):
    monkeypatch.setattr(settings, "TH_VIDEO_MAX_MB", 0)  # 0 МБ -> любой непустой файл превышает лимит
    run_id, token = await _start_running_run(qa_client, "video_size_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        resp = await qa_client.post(
            _video_url(run_id, nodeid),
            data={"duration_ms": "2500"},
            files={"file": ("test.webm", _WEBM_BYTES, "video/webm")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
    finally:
        await _stop_run(qa_client, run_id)


async def test_video_upload_saves_file_and_is_served_with_range(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir, db_path
):
    run_id, token = await _start_running_run(qa_client, "video_ok_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        resp = await qa_client.post(
            _video_url(run_id, nodeid),
            data={"duration_ms": "2500"},
            files={"file": ("test.webm", _WEBM_BYTES, "video/webm")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json() == {"nodeid": nodeid, "duration_ms": 2500, "size": len(_WEBM_BYTES)}

        expected_hash = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:16]
        saved = runner.video_dir(run_id) / f"{expected_hash}.webm"
        assert saved.read_bytes() == _WEBM_BYTES

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT nodeid, duration_ms, size FROM run_test_videos WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        assert row["nodeid"] == nodeid
        assert row["duration_ms"] == 2500
        assert row["size"] == len(_WEBM_BYTES)

        full = await qa_client.get(_video_url(run_id, nodeid))
        assert full.status_code == 200
        assert full.headers["content-type"] == "video/webm"
        assert full.content == _WEBM_BYTES

        ranged = await qa_client.get(_video_url(run_id, nodeid), headers={"Range": "bytes=2-5"})
        assert ranged.status_code == 206
        assert ranged.content == _WEBM_BYTES[2:6]
        assert ranged.headers["content-range"] == f"bytes 2-5/{len(_WEBM_BYTES)}"
    finally:
        await _stop_run(qa_client, run_id)


async def test_video_upload_replaces_previous_upload_for_same_test(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir, db_path
):
    run_id, token = await _start_running_run(qa_client, "video_replace_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        first = await qa_client.post(
            _video_url(run_id, nodeid),
            data={"duration_ms": "1000"},
            files={"file": ("first.webm", _WEBM_BYTES, "video/webm")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 201

        second_bytes = _WEBM_BYTES + b"\xff\xff"
        second = await qa_client.post(
            _video_url(run_id, nodeid),
            data={"duration_ms": "3000"},
            files={"file": ("second.webm", second_bytes, "video/webm")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 201

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT duration_ms, size FROM run_test_videos WHERE run_id = ? AND nodeid = ?",
                (run_id, nodeid),
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["duration_ms"] == 3000
        assert rows[0]["size"] == len(second_bytes)

        served = await qa_client.get(_video_url(run_id, nodeid))
        assert served.content == second_bytes
    finally:
        await _stop_run(qa_client, run_id)


async def test_get_video_404_when_not_uploaded(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, runnable_project_dir
):
    await register_project(qa_client, "video_404_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/video_404_proj/runs", json={"target": "tests/test_sample.py::test_ok"}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
        return report if report["status"] in {"passed", "failed"} else None

    assert await poll_until(finished, timeout=15) is not None

    missing = await qa_client.get(_video_url(run_id, "tests/test_sample.py::test_ok"))
    assert missing.status_code == 404
