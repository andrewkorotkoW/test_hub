"""Очередь прогонов: не больше одного running на проект (app/core/runner.py).

Два прогона подряд на одном проекте — второй должен встать в очередь (queued), а не
начать выполняться параллельно с первым; после завершения первого раннер должен сам
подхватить второй из очереди (app/core/runner.py::_advance_queue) без дополнительных
вызовов со стороны теста.
"""

from .conftest import poll_until, register_project


def _find(rows, run_id):
    return next(r for r in rows if r["id"] == run_id)


async def test_second_run_queued_then_auto_starts(qa_client, isolated_allure_dir, runnable_project_dir):
    await register_project(qa_client, "queue_proj", runnable_project_dir)

    first_resp = await qa_client.post(
        "/api/projects/queue_proj/runs", json={"target": "tests/test_sample.py"}
    )
    assert first_resp.status_code == 201
    first = first_resp.json()
    assert first["status"] == "running"

    second_resp = await qa_client.post(
        "/api/projects/queue_proj/runs", json={"target": "tests/test_sample.py"}
    )
    assert second_resp.status_code == 201
    second = second_resp.json()
    assert second["status"] == "queued"
    assert second["started"] is None

    async def first_finished():
        rows = (await qa_client.get("/api/projects/queue_proj/runs")).json()
        row = _find(rows, first["id"])
        return row if row["status"] in {"passed", "failed"} else None

    first_final = await poll_until(first_finished, timeout=15)
    assert first_final is not None, "первый прогон не завершился вовремя"

    async def second_left_queue():
        rows = (await qa_client.get("/api/projects/queue_proj/runs")).json()
        row = _find(rows, second["id"])
        return row if row["status"] != "queued" else None

    second_after_dequeue = await poll_until(second_left_queue, timeout=15)
    assert second_after_dequeue is not None, "второй прогон не покинул очередь после завершения первого"
    assert second_after_dequeue["status"] in {"running", "passed", "failed"}
    assert second_after_dequeue["started"] is not None

    async def second_finished():
        rows = (await qa_client.get("/api/projects/queue_proj/runs")).json()
        row = _find(rows, second["id"])
        return row if row["status"] in {"passed", "failed"} else None

    second_final = await poll_until(second_finished, timeout=15)
    assert second_final is not None, "второй прогон не завершился вовремя после автостарта из очереди"
