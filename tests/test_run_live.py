"""POST/GET /api/runs/{id}/live, GET .../live.jpg — живой кадр UI-теста (контракт
docs/missions/2026-10-01_live_stream.md, п.1-2, app/routers/runs.py + app/core/live.py).

Как test_run_frames.py: плагина нет, кадр шлётся синтетическим multipart-запросом
с токеном прогона, взятым напрямую из runner._run_tokens.
"""
import base64

import pytest

from app.config import settings
from app.core import live, runner
from app.core.ws import hub

from .conftest import poll_until, register_project

_JPEG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def _clear_live_state():
    """live._frames/_last_broadcast_at — модульные dict, не привязанные к
    db_path/tmp_path конкретного теста (run_id снова начинается с 1 в каждом
    тесте из-за AUTOINCREMENT на свежей БД) — без явной чистки кадр, оставленный
    одним тестом, был бы виден следующему под тем же run_id."""
    live.clear_all()
    yield
    live.clear_all()


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


async def test_live_upload_rejects_missing_or_wrong_token(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "live_auth_proj", slow_project_dir)
    try:
        no_token = await qa_client.post(
            f"/api/runs/{run_id}/live",
            data={"nodeid": "tests/test_slow.py::test_hangs", "ts": "1.0", "step": "open"},
            files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        assert no_token.status_code == 401

        wrong_token = await qa_client.post(
            f"/api/runs/{run_id}/live",
            data={"nodeid": "tests/test_slow.py::test_hangs", "ts": "1.0", "step": "open"},
            files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
            headers={"Authorization": "Bearer not-the-real-token"},
        )
        assert wrong_token.status_code == 401
    finally:
        await _stop_run(qa_client, run_id)


async def test_live_upload_rejects_when_run_not_running(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "live_finished_proj", slow_project_dir)
    await _stop_run(qa_client, run_id)

    resp = await qa_client.post(
        f"/api/runs/{run_id}/live",
        data={"nodeid": "tests/test_slow.py::test_hangs", "ts": "1.0", "step": ""},
        files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_live_upload_broadcasts_and_serves_live_jpg(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "live_ok_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        sent = []
        orig_broadcast = hub.broadcast

        async def spy_broadcast(rid, message):
            sent.append((rid, message))
            await orig_broadcast(rid, message)

        hub.broadcast = spy_broadcast
        try:
            resp = await qa_client.post(
                f"/api/runs/{run_id}/live",
                data={"nodeid": nodeid, "ts": "12.5", "step": "открыт логин"},
                files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            hub.broadcast = orig_broadcast
        assert resp.status_code == 204
        assert resp.content == b""

        assert len(sent) == 1
        rid, message = sent[0]
        assert rid == run_id
        assert message["type"] == "live"
        assert message["nodeid"] == nodeid
        assert message["step"] == "открыт логин"
        assert message["ts"] == 12.5
        assert base64.b64decode(message["jpeg_b64"]) == _JPEG_BYTES

        jpg = await qa_client.get(f"/api/runs/{run_id}/live.jpg")
        assert jpg.status_code == 200
        assert jpg.headers["content-type"] == "image/jpeg"
        assert jpg.content == _JPEG_BYTES
    finally:
        await _stop_run(qa_client, run_id)


async def test_live_throttles_broadcast_but_keeps_latest_frame_in_memory(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "live_throttle_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        sent = []
        orig_broadcast = hub.broadcast

        async def spy_broadcast(rid, message):
            sent.append((rid, message))

        hub.broadcast = spy_broadcast
        try:
            first = await qa_client.post(
                f"/api/runs/{run_id}/live",
                data={"nodeid": nodeid, "ts": "1.0", "step": "шаг 1"},
                files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert first.status_code == 204

            second_bytes = _JPEG_BYTES + b"\x00"
            second = await qa_client.post(
                f"/api/runs/{run_id}/live",
                data={"nodeid": nodeid, "ts": "1.05", "step": "шаг 2"},
                files={"file": ("live.jpg", second_bytes, "image/jpeg")},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert second.status_code == 204
        finally:
            hub.broadcast = orig_broadcast

        # Кадр пришёл раньше, чем через 0.2с после первой рассылки — WS-сообщение
        # для него не уходит (лишние отбрасываются), но последний кадр в памяти
        # всё равно обновился (live.jpg отдаёт его).
        assert len(sent) == 1
        assert sent[0][1]["step"] == "шаг 1"

        jpg = await qa_client.get(f"/api/runs/{run_id}/live.jpg")
        assert jpg.content == second_bytes
    finally:
        await _stop_run(qa_client, run_id)


async def test_live_jpg_404_when_no_frame_yet(
    qa_client, isolated_allure_dir, isolated_frames_dir, runnable_project_dir
):
    await register_project(qa_client, "live_404_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/live_404_proj/runs", json={"target": "tests/test_sample.py::test_ok"}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    jpg = await qa_client.get(f"/api/runs/{run_id}/live.jpg")
    assert jpg.status_code == 404


async def test_live_jpg_404_unknown_run(qa_client, isolated_allure_dir, isolated_frames_dir):
    resp = await qa_client.get("/api/runs/999999/live.jpg")
    assert resp.status_code == 404


async def test_live_jpg_expires_after_ttl(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir, monkeypatch
):
    run_id, token = await _start_running_run(qa_client, "live_ttl_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        resp = await qa_client.post(
            f"/api/runs/{run_id}/live",
            data={"nodeid": nodeid, "ts": "1.0", "step": ""},
            files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

        jpg = await qa_client.get(f"/api/runs/{run_id}/live.jpg")
        assert jpg.status_code == 200

        real_time = live.time.time
        monkeypatch.setattr(live.time, "time", lambda: real_time() + 301)
        expired = await qa_client.get(f"/api/runs/{run_id}/live.jpg")
        assert expired.status_code == 404
    finally:
        await _stop_run(qa_client, run_id)
