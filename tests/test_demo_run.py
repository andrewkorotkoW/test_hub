"""Реальный прогон demo/tests/ через app/core/runner.py на фикстурной БД,
указывающей на настоящий demo/ в репозитории (DEMO_PROJECT_PATH) — проверяет, что
demo-проект действительно даёт разброс исходов (passed/failed/skipped/xfail) и что
намеренно флаки-тест (demo/tests/api/catalog/test_catalog.py
::test_catalog_is_eventually_consistent) реально даёт разные статусы между
повторами, а не просто помечен как флаки в докстринге.

Сам демо-сервис поднимается для этого тем же способом, что и в
tests/test_demo_service.py (subprocess uvicorn demo.app.main:app) — на отдельном
свободном порту, а не на settings.TH_DEMO_PORT (там может уже слушать боевой
test_hub, см. tests/conftest.py::db_path про изоляцию от workspace/test_hub.db).

Раннер вызывает venv="" -> sys.executable того же процесса, что и test_hub (см.
app/core/runner.py::_venv_python) — в этом worktree это .venv/bin/python, где уже
стоят requests/allure-pytest/playwright (requirements.txt test_hub), которых
достаточно для API-части demo/tests (маркер `api`); маркер `ui`/e2e не гоняем
здесь намеренно — им нужен установленный браузер Playwright, которого может не
быть на машине (см. README/DESIGN.md задачи не требуют этого для приёмки раннера)."""
import asyncio
import shutil
import socket
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.config import BASE_DIR
from app.db import DEMO_PROJECT_PATH

from .conftest import poll_until

_FLAKY_STATE_FILE = Path(DEMO_PROJECT_PATH) / ".state" / "flaky_calls.json"


@pytest.fixture(autouse=True)
def _reset_flaky_state():
    # Счётчик в файле переживает процессы pytest (см. demo/tests/api/catalog/test_catalog.py)
    # — без сброса результат "какой по счёту вызов" зависел бы от того, сколько раз
    # demo/tests уже гоняли на этой машине до текущего тестового прогона.
    shutil.rmtree(_FLAKY_STATE_FILE.parent, ignore_errors=True)
    yield
    shutil.rmtree(_FLAKY_STATE_FILE.parent, ignore_errors=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture()
async def demo_service_url():
    port = _free_port()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "demo.app.main:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        cwd=str(BASE_DIR),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                if proc.returncode is not None:
                    raise RuntimeError("демо-сервис упал ещё до готовности")
                try:
                    resp = await client.get(f"{base_url}/api/catalog", timeout=1)
                    if resp.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("демо-сервис не поднялся вовремя")
        yield base_url
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


async def _register_demo_project(qa_client, name: str, stand_url: str) -> None:
    resp = await qa_client.post(
        "/api/projects", json={"name": name, "path": DEMO_PROJECT_PATH, "venv": ""}
    )
    assert resp.status_code == 201, resp.text
    stand_resp = await qa_client.post(
        f"/api/projects/{name}/stands", json={"name": "test_local", "url": stand_url}
    )
    assert stand_resp.status_code == 201, stand_resp.text


async def test_demo_api_suite_has_passed_failed_skipped_and_xfail(
    qa_client, isolated_allure_dir, demo_service_url
):
    await _register_demo_project(qa_client, "demo_run_api", demo_service_url)

    resp = await qa_client.post(
        "/api/projects/demo_run_api/runs",
        json={"stand": "test_local", "target": "all", "marker": "api"},
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/demo_run_api/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed", "cancelled"} else None

    final = await poll_until(finished, timeout=60)
    assert final is not None, "прогон demo/tests (маркер api) не завершился вовремя"
    assert final["status"] == "failed"  # намеренный баг orders.py делает прогон failed

    report_resp = await qa_client.get(f"/api/runs/{run_id}/report")
    assert report_resp.status_code == 200
    report = report_resp.json()

    counts = report["counts"]
    assert counts["passed"] >= 1
    assert counts["failed"] >= 2  # test_create_order_applies_discount + multiple_qty
    assert counts["skipped"] >= 2  # pytest.mark.skip (пагинация) + xfail (allure видит его как skipped)

    xfail_tests = [
        t for t in report["tests"]
        if t["status"] == "skipped" and (t["message"] or "").upper().startswith("XFAIL")
    ]
    plain_skips = [
        t for t in report["tests"]
        if t["status"] == "skipped" and not (t["message"] or "").upper().startswith("XFAIL")
    ]
    assert xfail_tests, "не нашёл ни одного skipped-теста с XFAIL-сообщением (allure_pytest -> xfail)"
    assert plain_skips, "не нашёл обычного pytest.mark.skip среди skipped-тестов"

    failed_names = {t["name"].rsplit("#", 1)[-1] for t in report["tests"] if t["status"] == "failed"}
    assert "test_create_order_applies_discount" in failed_names
    assert "test_create_order_multiple_qty_applies_discount" in failed_names


async def test_demo_flaky_test_flips_status_across_repeats(
    qa_client, isolated_allure_dir, demo_service_url
):
    await _register_demo_project(qa_client, "demo_run_flaky", demo_service_url)

    # Счётчик в demo/.state/flaky_calls.json сброшен фикстурой _reset_flaky_state ->
    # первый вызов даёт count=1, второй count=2 (оба % 3 != 0 -> passed), третий
    # count=3 (3 % 3 == 0 -> тест намеренно падает, см. test_catalog.py). repeat=3
    # прогоняет ту же цель трижды подряд в один и тот же allure results_dir
    # (app/core/runner.py::_execute), так что все 3 исхода видны в одном report.
    resp = await qa_client.post(
        "/api/projects/demo_run_flaky/runs",
        json={
            "stand": "test_local",
            "target": "tests/api/catalog/test_catalog.py::test_catalog_is_eventually_consistent",
            "repeat": 3,
        },
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["repeat"] == 3
    run_id = run["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/demo_run_flaky/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed", "cancelled"} else None

    final = await poll_until(finished, timeout=60)
    assert final is not None, "прогон флаки-теста не завершился вовремя"
    assert final["status"] == "failed"  # 3-й повтор намеренно падает

    report = (await qa_client.get(f"/api/runs/{run_id}/report")).json()
    flaky_results = [
        t for t in report["tests"] if t["name"].endswith("test_catalog_is_eventually_consistent")
    ]
    assert len(flaky_results) == 3, "repeat=3 должен дать 3 независимых результата одного теста"
    statuses = [t["status"] for t in flaky_results]
    assert set(statuses) == {"passed", "failed"}, (
        f"ожидали разные статусы между повторами (флаки), получили {statuses}"
    )
    assert statuses.count("failed") == 1  # ровно 3-й вызов (count % 3 == 0)
