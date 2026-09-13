"""POST /api/runs/{id}/cancel убивает subprocess зависшего прогона.

Фикстурный проект (slow_project_dir) содержит один тест с time.sleep(8) — вызов cancel
должен перевести прогон в status=cancelled и убить subprocess задолго до того, как
sleep(8) успеет завершиться сам по себе.
"""

import os

import pytest

from app.core import runner

from .conftest import poll_until, register_project


def _find(rows, run_id):
    return next(r for r in rows if r["id"] == run_id)


async def test_cancel_running_run_kills_subprocess(qa_client, isolated_allure_dir, slow_project_dir):
    await register_project(qa_client, "slow_proj", slow_project_dir)

    create_resp = await qa_client.post(
        "/api/projects/slow_proj/runs", json={"target": "tests/test_slow.py"}
    )
    assert create_resp.status_code == 201
    run = create_resp.json()
    assert run["status"] == "running"
    run_id = run["id"]

    async def process_registered():
        return runner._active_procs.get(run_id)

    proc = await poll_until(process_registered, timeout=5)
    assert proc is not None, "раннер не зарегистрировал subprocess прогона как активный"
    pid = proc.pid

    cancel_resp = await qa_client.post(f"/api/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200

    async def run_cancelled():
        rows = (await qa_client.get("/api/projects/slow_proj/runs")).json()
        row = _find(rows, run_id)
        return row if row["status"] == "cancelled" else None

    # sleep(8) в фикстуре — если бы cancel не убивал процесс, а просто ждал его
    # естественного завершения, этот poll истёк бы по таймауту раньше, чем sleep закончится.
    final = await poll_until(run_cancelled, timeout=5)
    assert final is not None, "прогон не перешёл в status=cancelled после отмены"
    assert final["finished"] is not None

    assert run_id not in runner._active_procs, "subprocess не был убран из активных после отмены"

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_cancel_unknown_run_is_404(qa_client):
    resp = await qa_client.post("/api/runs/999999/cancel")
    assert resp.status_code == 404


async def test_cancel_terminal_run_is_409(qa_client, isolated_allure_dir, runnable_project_dir):
    await register_project(qa_client, "finished_proj", runnable_project_dir)
    create_resp = await qa_client.post(
        "/api/projects/finished_proj/runs", json={"target": "tests/test_sample.py"}
    )
    run_id = create_resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/finished_proj/runs")).json()
        row = _find(rows, run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None, "прогон не завершился вовремя"

    cancel_resp = await qa_client.post(f"/api/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 409
