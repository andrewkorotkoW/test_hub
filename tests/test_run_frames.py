"""POST/GET /api/runs/{id}/frames — приём кадров UI-теста от плагина проекта
тестов и их отдача (этап 2 окна прогона, app/routers/runs.py).

Плагина в этой задаче нет (отдельная миссия в auto_tests_vshgu/demo) — кадры
шлются синтетическим multipart-запросом, как если бы их прислал pytest. Токен
прогона берём напрямую из runner._run_tokens (тот же словарь, что реально
получает pytest в env TH_RUN_TOKEN — см. test_run_events_nodeid.py, где он
проверяется по-настоящему через subprocess).
"""
import base64
import hashlib
import sqlite3

from app.config import settings
from app.core import runner

from .conftest import poll_until, register_project

# 1x1 прозрачный PNG.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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


async def test_upload_frame_rejects_missing_or_wrong_token(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "frames_auth_proj", slow_project_dir)
    try:
        no_token = await qa_client.post(
            f"/api/runs/{run_id}/frames",
            data={"nodeid": "tests/test_slow.py::test_hangs", "step": "1"},
            files={"file": ("frame.png", _PNG_BYTES, "image/png")},
        )
        assert no_token.status_code == 401

        wrong_token = await qa_client.post(
            f"/api/runs/{run_id}/frames",
            data={"nodeid": "tests/test_slow.py::test_hangs", "step": "1"},
            files={"file": ("frame.png", _PNG_BYTES, "image/png")},
            headers={"Authorization": "Bearer not-the-real-token"},
        )
        assert wrong_token.status_code == 401
    finally:
        await _stop_run(qa_client, run_id)


async def test_upload_frame_saves_file_event_and_is_served_back(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir, db_path
):
    run_id, token = await _start_running_run(qa_client, "frames_ok_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        resp = await qa_client.post(
            f"/api/runs/{run_id}/frames",
            data={"nodeid": nodeid, "step": "3"},
            files={"file": ("frame.png", _PNG_BYTES, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
        url = resp.json()["url"]
        expected_hash = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:16]
        assert url == f"/api/runs/{run_id}/frames/{expected_hash}/3.png"

        saved = runner.frames_dir(run_id) / expected_hash / "3.png"
        assert saved.read_bytes() == _PNG_BYTES

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT nodeid, kind, line FROM run_events WHERE run_id = ? AND kind = 'frame'", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        assert row["nodeid"] == nodeid
        assert row["line"] == f"{expected_hash}/3.png"

        served = await qa_client.get(url)
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/png"
        assert served.content == _PNG_BYTES
    finally:
        await _stop_run(qa_client, run_id)


async def test_upload_frame_rejects_oversized_file(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir, monkeypatch
):
    monkeypatch.setattr(settings, "TH_FRAME_MAX_BYTES", 10)
    run_id, token = await _start_running_run(qa_client, "frames_size_proj", slow_project_dir)
    try:
        resp = await qa_client.post(
            f"/api/runs/{run_id}/frames",
            data={"nodeid": "tests/test_slow.py::test_hangs", "step": "1"},
            files={"file": ("frame.png", _PNG_BYTES, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 413
    finally:
        await _stop_run(qa_client, run_id)


async def test_upload_frame_enforces_max_per_run(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir, monkeypatch
):
    monkeypatch.setattr(settings, "TH_FRAME_MAX_PER_RUN", 1)
    run_id, token = await _start_running_run(qa_client, "frames_limit_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        first = await qa_client.post(
            f"/api/runs/{run_id}/frames",
            data={"nodeid": nodeid, "step": "1"},
            files={"file": ("frame.png", _PNG_BYTES, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 201

        second = await qa_client.post(
            f"/api/runs/{run_id}/frames",
            data={"nodeid": nodeid, "step": "2"},
            files={"file": ("frame.png", _PNG_BYTES, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 429
    finally:
        await _stop_run(qa_client, run_id)


async def test_upload_frame_rejects_when_run_not_running(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token = await _start_running_run(qa_client, "frames_finished_proj", slow_project_dir)
    await _stop_run(qa_client, run_id)

    resp = await qa_client.post(
        f"/api/runs/{run_id}/frames",
        data={"nodeid": "tests/test_slow.py::test_hangs", "step": "1"},
        files={"file": ("frame.png", _PNG_BYTES, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_get_frame_file_404_for_unknown_run_hash_or_step(
    qa_client, isolated_allure_dir, isolated_frames_dir, runnable_project_dir
):
    # несуществующий run_id — до проверки хэша.
    got = await qa_client.get("/api/runs/999999/frames/0123456789abcdef/1.png")
    assert got.status_code == 404

    await register_project(qa_client, "frames_404_proj", runnable_project_dir)
    resp = await qa_client.post(
        "/api/projects/frames_404_proj/runs", json={"target": "tests/test_sample.py::test_ok"}
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
        return report if report["status"] in {"passed", "failed"} else None

    assert await poll_until(finished, timeout=15) is not None

    # существующий прогон, но некорректный формат хэша — не должен пытаться читать файл.
    bad_hash = await qa_client.get(f"/api/runs/{run_id}/frames/not-a-hash/1.png")
    assert bad_hash.status_code == 404

    # существующий прогон, валидный формат хэша, файла нет.
    missing_frame = await qa_client.get(f"/api/runs/{run_id}/frames/0123456789abcdef/1.png")
    assert missing_frame.status_code == 404
