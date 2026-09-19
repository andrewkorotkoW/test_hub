"""use_env_flag+stand -> `--env <stand>`/HEADLESS=1, RunCreate.marker -> `-m <marker>`
(app/core/runner.py::_execute).

Гоняют реальный pytest на фикстурном мини-проекте (как test_run_queue.py/
test_run_cancel.py: .venv/bin/python — симлинк на sys.executable), чей conftest.py
сам дампит в probe.json argv процесса и os.environ["HEADLESS"] через pytest_configure.
Так проверка не зависит от того, понимает ли pytest семантику --env (только
регистрирует его через pytest_addoption, чтобы не упасть на unrecognized arguments) —
только от того, что раннер реально передал эти args/env в subprocess.
"""
import json
import sys

from .conftest import poll_until, register_project

_PROBE_CONFTEST = '''\
import json
import os
import sys
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption("--env", action="store", default=None)


def pytest_configure(config):
    probe = {
        "argv": sys.argv,
        "headless": os.environ.get("HEADLESS"),
        "env_option": config.getoption("--env"),
    }
    Path(__file__).parent.joinpath("probe.json").write_text(json.dumps(probe))
'''

_PLAIN_TEST = '''\
def test_probe():
    assert True
'''

_MARKER_TESTS = '''\
import pytest


def test_unmarked():
    assert True


@pytest.mark.smoke
def test_smoke():
    assert True
'''


def _probe_project_dir(tmp_path, test_content):
    proj = tmp_path / "probe_proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(test_content)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe(project_dir):
    return json.loads((project_dir / "probe.json").read_text())


async def _create_project(client, name, path, use_env_flag=False):
    resp = await client.post(
        "/api/projects",
        json={"name": name, "path": str(path), "venv": ".venv", "use_env_flag": use_env_flag},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_stand(client, project, name, url=""):
    resp = await client.post(f"/api/projects/{project}/stands", json={"name": name, "url": url})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _run_and_wait(client, project_name, body, timeout=15):
    resp = await client.post(f"/api/projects/{project_name}/runs", json=body)
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await client.get(f"/api/projects/{project_name}/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=timeout)
    assert final is not None, "прогон не завершился вовремя"
    return run_id, final


async def test_use_env_flag_with_stand_passes_env_and_headless(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path, _PLAIN_TEST)
    await _create_project(qa_client, "env_flag_proj", proj_dir, use_env_flag=True)
    await _create_stand(qa_client, "env_flag_proj", "develop")

    run_id, final = await _run_and_wait(
        qa_client, "env_flag_proj", {"stand": "develop", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert probe["headless"] == "1"
    assert probe["env_option"] == "develop"
    assert "--env" in probe["argv"]
    assert probe["argv"][probe["argv"].index("--env") + 1] == "develop"


async def test_use_env_flag_without_stand_does_not_pass_env_or_headless(
    qa_client, isolated_allure_dir, tmp_path
):
    proj_dir = _probe_project_dir(tmp_path, _PLAIN_TEST)
    await _create_project(qa_client, "env_flag_no_stand_proj", proj_dir, use_env_flag=True)

    run_id, final = await _run_and_wait(
        qa_client, "env_flag_no_stand_proj", {"target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert probe["headless"] is None
    assert probe["env_option"] is None
    assert "--env" not in probe["argv"]


async def test_use_env_flag_off_with_stand_does_not_pass_env_or_headless(
    qa_client, isolated_allure_dir, tmp_path
):
    proj_dir = _probe_project_dir(tmp_path, _PLAIN_TEST)
    await _create_project(qa_client, "no_env_flag_proj", proj_dir, use_env_flag=False)
    await _create_stand(qa_client, "no_env_flag_proj", "develop")

    run_id, final = await _run_and_wait(
        qa_client, "no_env_flag_proj", {"stand": "develop", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert probe["headless"] is None
    assert probe["env_option"] is None
    assert "--env" not in probe["argv"]


async def test_marker_passed_adds_dash_m(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path, _MARKER_TESTS)
    await _create_project(qa_client, "marker_proj", proj_dir)

    run_id, final = await _run_and_wait(
        qa_client, "marker_proj", {"target": "tests/test_probe.py", "marker": "smoke"}
    )
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert "-m" in probe["argv"]
    assert probe["argv"][probe["argv"].index("-m") + 1] == "smoke"

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    # -m smoke должен реально отфильтровать коллекцию pytest, а не просто попасть в argv:
    # из двух тестов (unmarked + smoke) должен выполниться только помеченный.
    assert report["counts"]["passed"] == 1
    assert len(report["tests"]) == 1
    assert report["tests"][0]["name"].endswith("test_smoke")


async def test_marker_absent_does_not_add_dash_m(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path, _MARKER_TESTS)
    await _create_project(qa_client, "no_marker_proj", proj_dir)

    run_id, final = await _run_and_wait(qa_client, "no_marker_proj", {"target": "tests/test_probe.py"})
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert "-m" not in probe["argv"]

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    assert report["counts"]["passed"] == 2
    assert len(report["tests"]) == 2
