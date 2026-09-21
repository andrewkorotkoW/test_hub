"""RunCreate.target как список nodeid, разделённых переводом строки
(app/core/runner.py::_execute, target.splitlines() -> отдельные аргументы pytest).

UI посылает несколько выбранных в дереве тестов nodeid не через пробел (параметризованные
имена вида `test_delta[a b]` сами содержат пробелы), а через перевод строки — раннер
разбивает target построчно и добавляет каждую непустую строку отдельным аргументом
pytest. Гоняют реальный pytest на фикстурном мини-проекте (тот же паттерн, что и в
test_run_env_and_marker.py: conftest.py фикстурного проекта дампит в probe.json
sys.argv процесса через pytest_configure, .venv/bin/python — симлинк на sys.executable).
"""
import json
import sys

from .conftest import poll_until

_PROBE_CONFTEST = '''\
import json
import sys
from pathlib import Path


def pytest_configure(config):
    probe = {"argv": sys.argv}
    Path(__file__).parent.joinpath("probe.json").write_text(json.dumps(probe))
'''

# 3 обычных теста + 1 параметризованный с пробелом в имени одного из вариантов —
# именно из-за таких имён раннер не может разделять nodeid пробелом, только переводом строки.
_MULTI_TESTS = '''\
import pytest


def test_alpha():
    assert True


def test_beta():
    assert True


def test_gamma():
    assert True


@pytest.mark.parametrize("value", ["a b", "c"])
def test_delta(value):
    assert True
'''


def _probe_project_dir(tmp_path):
    proj = tmp_path / "probe_proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(_MULTI_TESTS)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe(project_dir):
    return json.loads((project_dir / "probe.json").read_text())


def _nodeid_args(argv):
    return [a for a in argv if "test_probe.py" in a]


async def _create_project(client, name, path):
    resp = await client.post(
        "/api/projects", json={"name": name, "path": str(path), "venv": ".venv"}
    )
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


async def test_target_multi_nodeid_runs_exactly_selected_tests(
    qa_client, isolated_allure_dir, tmp_path
):
    proj_dir = _probe_project_dir(tmp_path)
    await _create_project(qa_client, "multi_target_proj", proj_dir)

    selected = [
        "tests/test_probe.py::test_alpha",
        "tests/test_probe.py::test_gamma",
        "tests/test_probe.py::test_delta[a b]",
    ]
    run_id, final = await _run_and_wait(
        qa_client, "multi_target_proj", {"target": "\n".join(selected)}
    )
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    # переданы ровно выбранные nodeid как отдельные аргументы (в т.ч. с пробелом внутри
    # одного аргумента, а не разбитые на два) — и ничего сверх этого.
    assert _nodeid_args(probe["argv"]) == selected

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    assert report["counts"]["passed"] == 3
    ran_names = {t["name"] for t in report["tests"]}
    assert len(report["tests"]) == 3
    assert any(n.endswith("test_alpha") for n in ran_names)
    assert any(n.endswith("test_gamma") for n in ran_names)
    assert any("test_delta" in n for n in ran_names)
    assert not any(n.endswith("test_beta") for n in ran_names)
    assert not any(n.endswith("test_delta[c]") for n in ran_names)


async def test_target_single_nodeid_runs_exactly_one_test(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path)
    await _create_project(qa_client, "single_target_proj", proj_dir)

    run_id, final = await _run_and_wait(
        qa_client, "single_target_proj", {"target": "tests/test_probe.py::test_beta"}
    )
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert _nodeid_args(probe["argv"]) == ["tests/test_probe.py::test_beta"]

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    assert report["counts"]["passed"] == 1
    assert len(report["tests"]) == 1
    assert report["tests"][0]["name"].endswith("test_beta")


async def test_target_list_without_marker_runs_successfully(qa_client, isolated_allure_dir, tmp_path):
    """marker необязателен: RunCreate.marker по умолчанию None, и список target
    сам по себе не требует маркера для отбора тестов."""
    proj_dir = _probe_project_dir(tmp_path)
    await _create_project(qa_client, "list_no_marker_proj", proj_dir)

    selected = ["tests/test_probe.py::test_alpha", "tests/test_probe.py::test_beta"]
    run_id, final = await _run_and_wait(
        qa_client, "list_no_marker_proj", {"target": "\n".join(selected)}
    )
    assert final["status"] == "passed", final

    probe = _read_probe(proj_dir)
    assert "-m" not in probe["argv"]
    assert _nodeid_args(probe["argv"]) == selected

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    assert report["counts"]["passed"] == 2
    assert len(report["tests"]) == 2


async def test_target_with_nonexistent_nodeid_fails_run(qa_client, isolated_allure_dir, tmp_path):
    """Текущее поведение (не требует изменений в коде): pytest не находит nodeid
    в списке target, завершается с ненулевым кодом возврата на этапе сбора тестов
    (до выполнения тестов вообще) -> раннер помечает прогон как failed, а не passed
    с частичными результатами."""
    proj_dir = _probe_project_dir(tmp_path)
    await _create_project(qa_client, "missing_nodeid_proj", proj_dir)

    selected = ["tests/test_probe.py::test_alpha", "tests/test_probe.py::test_does_not_exist"]
    run_id, final = await _run_and_wait(
        qa_client, "missing_nodeid_proj", {"target": "\n".join(selected)}
    )
    assert final["status"] == "failed", final

    probe = _read_probe(proj_dir)
    assert _nodeid_args(probe["argv"]) == selected

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    assert report["counts"].get("passed", 0) == 0
