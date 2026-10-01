"""Галочка «Эфир»: env TH_LIVE=1 реально доходит до pytest-подпроцесса только когда
live=true (docs/missions/2026-10-01_live_stream.md, «Уточнение владельца 01.10»).
tests/test_runs_live_flag.py уже проверяет поле `live` в ответах API и лимит
TH_LIVE_MAX_TESTS — здесь не дублируем это, а гоняем реальный pytest на фикстурном
проекте, чтобы убедиться, что TH_LIVE доходит до окружения теста (тот же приём, что
tests/test_run_env_and_marker.py: probe.json дампит os.environ из pytest_configure).
"""
import json
import sys

from .conftest import poll_until, register_project

_PROBE_CONFTEST = '''\
import json
import os
from pathlib import Path


def pytest_configure(config):
    probe = {"th_live": os.environ.get("TH_LIVE")}
    Path(__file__).parent.joinpath("probe.json").write_text(json.dumps(probe))
'''

_TWO_TESTS = '''\
def test_one():
    assert True


def test_two():
    assert True
'''


def _probe_project_dir(tmp_path, test_content):
    proj = tmp_path / "live_proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(test_content)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe(project_dir):
    return json.loads((project_dir / "probe.json").read_text())


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


async def test_live_true_sets_th_live_env_and_report_live_flag(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path, _TWO_TESTS)
    await register_project(qa_client, "live_flag_proj", proj_dir)

    run_id, final = await _run_and_wait(
        qa_client, "live_flag_proj", {"target": "tests/test_probe.py::test_one", "live": True}
    )
    assert final["status"] == "passed", final
    assert final["live"] is True

    probe = _read_probe(proj_dir)
    assert probe["th_live"] == "1"

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    assert report["live"] is True


async def test_live_false_by_default_does_not_set_th_live_env(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path, _TWO_TESTS)
    await register_project(qa_client, "no_live_flag_proj", proj_dir)

    run_id, final = await _run_and_wait(
        qa_client, "no_live_flag_proj", {"target": "tests/test_probe.py::test_one"}
    )
    assert final["status"] == "passed", final
    assert final["live"] is False

    probe = _read_probe(proj_dir)
    assert probe["th_live"] is None


