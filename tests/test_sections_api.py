"""REST API поверх app/core/sections.py (app/routers/sections.py) — GET
.../sections: кэш по mtime, права ролей, статус раздела из уже посчитанной
статистики (app/routers/stats.py). По образцу tests/test_coverage_api.py."""
import json
import os
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core import sections as sections_core
from app.core import stats
from app.db import get_connection
from app.main import app as fastapi_app

from .conftest import login, register_project

PROJECT = "sections_api_proj"
ROLE_CREDENTIALS = {"qa": ("qa", "qa"), "manager": ("manager", "manager"), "customer": ("customer", "customer")}


@pytest_asyncio.fixture()
async def role_client(db_path):
    clients: list[AsyncClient] = []

    async def make(role: str) -> AsyncClient:
        transport = ASGITransport(app=fastapi_app)
        ac = AsyncClient(transport=transport, base_url="http://testserver")
        resp = await login(ac, *ROLE_CREDENTIALS[role])
        assert resp.status_code == 200, resp.text
        clients.append(ac)
        return ac

    yield make

    for ac in clients:
        await ac.aclose()


@pytest.fixture()
def isolated_sections_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sections_core, "SECTIONS_DIR", tmp_path / "sections_cache")
    # sections router читает статус раздела из stats.load_cached() (см.
    # app/routers/sections.py::_attach_status) — без изоляции он читал бы
    # реальный workspace/stats/ репозитория, как и STATS_DIR в tests/test_stats.py.
    monkeypatch.setattr(stats, "STATS_DIR", tmp_path / "stats_cache")


def _write_test(path, tests_count=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"def test_{i}():\n    assert True\n" for i in range(tests_count))
    path.write_text(body)


@pytest.fixture()
def sections_project_dir(tmp_path):
    proj = tmp_path / "sections_api_src"
    _write_test(proj / "tests" / "api" / "notifications" / "test_a.py", tests_count=2)
    return proj


async def _register(client, project_dir, stand="stage"):
    await register_project(client, PROJECT, project_dir)
    resp = await client.post(f"/api/projects/{PROJECT}/stands", json={"name": stand, "url": ""})
    assert resp.status_code == 201, resp.text


async def test_get_sections_lazily_recalculates_and_returns_tree(
    qa_client, isolated_sections_dir, sections_project_dir
):
    await _register(qa_client, sections_project_dir)

    resp = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project"] == PROJECT
    kinds = {k["kind"]: k for k in body["kinds"]}
    assert set(kinds) == {"api"}
    area = kinds["api"]["areas"][0]
    assert area["section"] == "api/notifications"
    assert area["tests_count"] == 2
    assert len(area["files"]) == 1
    assert area["status"] is None  # ещё нет посчитанной статистики


async def test_get_sections_404_for_unknown_project(qa_client, isolated_sections_dir):
    resp = await qa_client.get("/api/projects/no_such_project/sections")
    assert resp.status_code == 404


async def test_get_sections_visible_to_manager_and_customer(
    role_client, isolated_sections_dir, sections_project_dir
):
    qa = await role_client("qa")
    await _register(qa, sections_project_dir)

    for role in ("manager", "customer"):
        client = await role_client(role)
        resp = await client.get(f"/api/projects/{PROJECT}/sections")
        assert resp.status_code == 200, resp.text
        assert resp.json()["project"] == PROJECT


async def test_get_sections_cache_invalidated_when_file_added(
    qa_client, isolated_sections_dir, sections_project_dir
):
    await _register(qa_client, sections_project_dir)
    first = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    area = first.json()["kinds"][0]["areas"][0]
    assert area["tests_count"] == 2

    _write_test(sections_project_dir / "tests" / "api" / "notifications" / "test_b.py", tests_count=1)

    second = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    area = second.json()["kinds"][0]["areas"][0]
    assert area["tests_count"] == 3
    assert len(area["files"]) == 2


async def test_get_sections_cache_invalidated_when_file_modified(
    qa_client, isolated_sections_dir, sections_project_dir
):
    await _register(qa_client, sections_project_dir)
    first = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    assert first.json()["kinds"][0]["areas"][0]["tests_count"] == 2

    path = sections_project_dir / "tests" / "api" / "notifications" / "test_a.py"
    path.write_text(
        "def test_0():\n    assert True\n\ndef test_1():\n    assert True\n\ndef test_2():\n    assert True\n"
    )
    future = time.time() + 5
    os.utime(path, (future, future))

    second = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    assert second.json()["kinds"][0]["areas"][0]["tests_count"] == 3


async def test_get_sections_no_change_serves_cached_tree_without_recompute(
    qa_client, isolated_sections_dir, sections_project_dir, monkeypatch
):
    await _register(qa_client, sections_project_dir)
    first = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    assert first.status_code == 200

    calls = []
    original_recalc = sections_core.recalc

    def spy_recalc(*args, **kwargs):
        calls.append(args)
        return original_recalc(*args, **kwargs)

    monkeypatch.setattr(sections_core, "recalc", spy_recalc)

    second = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    assert second.status_code == 200
    assert calls == []


async def test_get_sections_attaches_status_from_stats_cache(
    qa_client, isolated_sections_dir, isolated_allure_dir, sections_project_dir
):
    await _register(qa_client, sections_project_dir)

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
            "VALUES (?, 'stage', 'all', 'passed', '2024-01-01T00:00:00', 'qa', '{}')",
            (PROJECT,),
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "00-result.json").write_text(
        json.dumps({"fullName": "tests.api.notifications#test_a", "status": "passed"}), encoding="utf-8"
    )
    stats.recalc(PROJECT, "stage")

    resp = await qa_client.get(f"/api/projects/{PROJECT}/sections")
    assert resp.status_code == 200, resp.text
    area = resp.json()["kinds"][0]["areas"][0]
    assert area["status"] is not None
    assert area["status"]["section"] == "api/notifications"
    assert area["status"]["passed"] == 1
