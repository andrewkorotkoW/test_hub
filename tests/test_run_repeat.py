"""RunCreate.repeat: одна и та же цель прогоняется несколько раз подряд в одном
прогоне (app/core/runner.py::_execute), а по завершении раннер сам запускает
пересчёт флаки-статистики (app/core/flaky.py::recalc) фоновой задачей из _finalize.

pytest-repeat не входит в requirements.txt, поэтому раннер делает repeat отдельными
последовательными subprocess-запусками pytest в один --alluredir — allure-pytest сам
называет файлы результатов случайным uuid на каждый запуск, так что все repeat
результатов одного теста накапливаются в одном results_dir без коллизий имён."""
from .conftest import poll_until, register_project


async def test_repeat_runs_target_multiple_times_and_feeds_flaky(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    await register_project(qa_client, "repeat_proj", runnable_project_dir)
    stand_resp = await qa_client.post(
        "/api/projects/repeat_proj/stands", json={"name": "stage", "url": "http://example.test"}
    )
    assert stand_resp.status_code == 201, stand_resp.text

    resp = await qa_client.post(
        "/api/projects/repeat_proj/runs",
        json={"stand": "stage", "target": "tests/test_sample.py::test_ok", "repeat": 3},
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["repeat"] == 3
    run_id = run["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/repeat_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=20)
    assert final is not None, "прогон не завершился вовремя"
    assert final["status"] == "passed", final

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    # repeat=3 одного и того же теста -> 3 независимых *-result.json в одном прогоне
    assert report["counts"]["passed"] == 3
    assert len(report["tests"]) == 3

    async def flaky_ready():
        flaky_resp = await qa_client.get(
            "/api/projects/repeat_proj/flaky", params={"stand": "stage", "min_runs": 1}
        )
        items = flaky_resp.json()["items"]
        return items or None

    # Пересчёт флаки-статистики уходит в фоновую задачу из _finalize и не блокирует
    # ответ на POST /runs — опрашиваем, а не проверяем сразу после poll_until(finished).
    items = await poll_until(flaky_ready, timeout=10)
    assert items is not None, "флаки-статистика не появилась вовремя"
    assert items[0]["runs"] == 3
    assert items[0]["fails"] == 0
    assert items[0]["score"] == 0.0
