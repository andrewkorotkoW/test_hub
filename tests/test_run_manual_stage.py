"""manual_only у стенда + пресеты запуска + защита submit_run (app/db.py,
app/core/runner.py::submit_run, app/routers/runs.py, app/routers/projects.py —
CRUD /stands/{stand}/presets, app/schemas.py::RunCreate.confirm_manual).

Реальный auto_tests_vshgu_cloude/stage НИКОГДА не гоняется здесь по-настоящему
(VSHGU_PROJECT_PATH указывает на боевой репозиторий на диске автора) — для success-
кейсов submit_run используется свой фикстурный мини-проект (runnable_project_dir,
как в test_run_queue.py/test_run_cancel.py) с ВРУЧНУЮ выставленным через API
manual_only=1 на одном из его стендов. Сид auto_tests_vshgu_cloude проверяется
только чтением состояния (стенды/пресеты), без единого POST /runs на него.
"""
import json
import sys

from app.config import settings
from app.db import VSHGU_PROJECT_NAME, VSHGU_STAGE_PRESETS

from .conftest import login, poll_until, register_project

_PROBE_CONFTEST = '''\
import json
import sys
from pathlib import Path


def pytest_configure(config):
    probe = {"argv": sys.argv}
    Path(__file__).parent.joinpath("probe.json").write_text(json.dumps(probe))
'''

_MARKER_TESTS = '''\
import pytest


def test_unmarked():
    assert True


@pytest.mark.smoke
def test_smoke():
    assert True
'''


def _probe_project_dir(tmp_path, dirname="manual_probe_proj"):
    proj = tmp_path / dirname
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(_MARKER_TESTS)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe(project_dir):
    return json.loads((project_dir / "probe.json").read_text())


async def _create_stand(client, project, name, url=""):
    resp = await client.post(f"/api/projects/{project}/stands", json={"name": name, "url": url})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _set_manual_only(client, project, stand_id, manual_only=True):
    resp = await client.patch(
        f"/api/projects/{project}/stands/{stand_id}", json={"manual_only": manual_only}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wait_finished(client, project_name, run_id, timeout=15):
    async def finished():
        rows = (await client.get(f"/api/projects/{project_name}/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=timeout)
    assert final is not None, "прогон не завершился вовремя"
    return final


# ------------------------------------------------------------------ 1. сид manual_only
async def test_seed_manual_only_flags_for_vshgu_stands(qa_client):
    stands = (await qa_client.get(f"/api/projects/{VSHGU_PROJECT_NAME}/stands")).json()
    by_name = {s["name"]: s for s in stands}
    assert by_name["stage"]["manual_only"] is True
    assert by_name["develop"]["manual_only"] is False


async def test_seed_does_not_set_manual_only_for_other_projects_stands(qa_client):
    # У прочих (не vshgu) проектов стенды не сидируются автоматически — создаём
    # стенд вручную через тот же API, которым пользуется UI, и проверяем, что
    # manual_only по умолчанию 0 (StandCreate не принимает этот флаг вовсе).
    stand = await _create_stand(qa_client, "bike_fit", "prod")
    assert stand["manual_only"] is False


# ------------------------------------------------------------------ 2. пресеты
async def test_seed_presets_for_vshgu_stage(qa_client):
    resp = await qa_client.get(f"/api/projects/{VSHGU_PROJECT_NAME}/stands/stage/presets")
    assert resp.status_code == 200
    presets = resp.json()
    assert len(presets) == 6
    got = [(p["name"], p["target"], p["marker"]) for p in presets]
    expected = list(VSHGU_STAGE_PRESETS)
    assert got == expected


# 403 для manager/customer на POST/PUT/DELETE пресета покрыт в test_roles_crud.py
# (WRITE_REQUESTS, записи на /stands/stage/presets) — по аналогии со стилем всех
# остальных проверок 403 в этом файле.


async def test_qa_can_create_edit_delete_custom_preset(qa_client):
    create_resp = await qa_client.post(
        f"/api/projects/{VSHGU_PROJECT_NAME}/stands/stage/presets",
        json={"name": "Custom", "target": "tests/custom", "marker": "custom_marker"},
    )
    assert create_resp.status_code == 201, create_resp.text
    preset = create_resp.json()
    preset_id = preset["id"]
    assert preset["name"] == "Custom"
    assert preset["target"] == "tests/custom"
    assert preset["marker"] == "custom_marker"

    list_after_create = (
        await qa_client.get(f"/api/projects/{VSHGU_PROJECT_NAME}/stands/stage/presets")
    ).json()
    assert len(list_after_create) == 7
    assert any(p["id"] == preset_id and p["name"] == "Custom" for p in list_after_create)

    edit_resp = await qa_client.put(
        f"/api/projects/{VSHGU_PROJECT_NAME}/stands/stage/presets/{preset_id}",
        json={"name": "Custom Renamed", "target": "tests/renamed"},
    )
    assert edit_resp.status_code == 200, edit_resp.text
    edited = edit_resp.json()
    assert edited["name"] == "Custom Renamed"
    assert edited["target"] == "tests/renamed"
    # marker не передан в PUT -> должен остаться прежним (частичное обновление)
    assert edited["marker"] == "custom_marker"

    list_after_edit = (
        await qa_client.get(f"/api/projects/{VSHGU_PROJECT_NAME}/stands/stage/presets")
    ).json()
    assert any(p["id"] == preset_id and p["name"] == "Custom Renamed" for p in list_after_edit)

    delete_resp = await qa_client.delete(
        f"/api/projects/{VSHGU_PROJECT_NAME}/stands/stage/presets/{preset_id}"
    )
    assert delete_resp.status_code == 204, delete_resp.text

    list_after_delete = (
        await qa_client.get(f"/api/projects/{VSHGU_PROJECT_NAME}/stands/stage/presets")
    ).json()
    assert len(list_after_delete) == 6
    assert all(p["id"] != preset_id for p in list_after_delete)


# ------------------------------------------------------------------ 3. submit_run/manual_only
async def test_run_on_manual_only_stand_without_confirm_returns_409(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    await register_project(qa_client, "manual_proj", runnable_project_dir)
    stand = await _create_stand(qa_client, "manual_proj", "stage")
    await _set_manual_only(qa_client, "manual_proj", stand["id"], True)

    resp = await qa_client.post(
        "/api/projects/manual_proj/runs", json={"stand": "stage", "target": "tests/test_sample.py"}
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "stage" in detail
    # без confirm_manual прогон не должен появиться в списке (для этого стенда)
    rows = (await qa_client.get("/api/projects/manual_proj/runs")).json()
    assert rows == []


async def test_run_on_manual_only_stand_with_confirm_creates_run(
    qa_client, isolated_allure_dir, tmp_path
):
    proj_dir = _probe_project_dir(tmp_path, "manual_confirmed_proj_dir")
    await register_project(qa_client, "manual_confirmed_proj", proj_dir)
    stand = await _create_stand(qa_client, "manual_confirmed_proj", "stage")
    await _set_manual_only(qa_client, "manual_confirmed_proj", stand["id"], True)

    resp = await qa_client.post(
        "/api/projects/manual_confirmed_proj/runs",
        json={
            "stand": "stage",
            "target": "tests/test_probe.py",
            "marker": "smoke",
            "confirm_manual": True,
        },
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["target"] == "tests/test_probe.py"
    assert run["marker"] == "smoke"
    assert run["stand"] == "stage"
    assert run["requested_by"] == "qa"

    final = await _wait_finished(qa_client, "manual_confirmed_proj", run["id"])
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert "-m" in probe["argv"]
    assert probe["argv"][probe["argv"].index("-m") + 1] == "smoke"


async def test_run_on_manual_only_stand_confirm_but_service_login_still_409(
    qa_client, isolated_allure_dir, runnable_project_dir, db_path
):
    await register_project(qa_client, "manual_bot_proj", runnable_project_dir)
    stand = await _create_stand(qa_client, "manual_bot_proj", "stage")
    await _set_manual_only(qa_client, "manual_bot_proj", stand["id"], True)

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as bot_client:
        login_resp = await login(
            bot_client, settings.TH_TG_SERVICE_LOGIN, settings.TH_TG_SERVICE_PASSWORD
        )
        assert login_resp.status_code == 200

        resp = await bot_client.post(
            "/api/projects/manual_bot_proj/runs",
            json={"stand": "stage", "target": "tests/test_sample.py", "confirm_manual": True},
        )
    assert resp.status_code == 409, resp.text

    rows = (await qa_client.get("/api/projects/manual_bot_proj/runs")).json()
    assert rows == []


async def test_run_on_regular_stand_without_confirm_unaffected(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    # Регрессия обратной совместимости: manual_only=0 (значение по умолчанию для
    # стенда, созданного через API, как и develop у auto_tests_vshgu_cloude) не
    # требует confirm_manual — поведение не изменилось задачей.
    await register_project(qa_client, "regular_proj", runnable_project_dir)
    stand = await _create_stand(qa_client, "regular_proj", "develop")
    assert stand["manual_only"] is False

    resp = await qa_client.post(
        "/api/projects/regular_proj/runs", json={"stand": "develop", "target": "tests/test_sample.py"}
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["stand"] == "develop"

    final = await _wait_finished(qa_client, "regular_proj", run["id"])
    assert final["status"] == "failed", final  # _FIXTURE_TESTS содержит и падающие тесты
