"""REST API поверх app/core/stats.py (app/routers/stats.py) — GET .../stats,
CSV-выгрузка, права ролей, кэш по id последнего прогона. По образцу
tests/test_coverage_api.py/tests/test_flaky.py: allure-results/runs пишутся
напрямую, без реального venv/pytest фикстурного проекта."""
import csv
import io
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core import stats
from app.db import get_connection
from app.main import app as fastapi_app

from .conftest import login, register_project

PROJECT = "stats_api_proj"
ROLE_CREDENTIALS = {"qa": ("qa", "qa"), "manager": ("manager", "manager"), "customer": ("customer", "customer")}


@pytest.fixture(autouse=True)
def isolated_stats_dir(tmp_path, monkeypatch):
    """См. tests/test_stats.py::isolated_stats_dir — без изоляции recalc()/load_cached()
    писали бы и читали кэш из реального workspace/stats/ репозитория."""
    monkeypatch.setattr(stats, "STATS_DIR", tmp_path / "stats_cache")


@pytest_asyncio.fixture()
async def role_client(db_path):
    """Фабрика независимых AsyncClient (каждый на своей cookie-сессии) — см.
    tests/test_coverage_api.py::role_client, продублировано здесь по той же
    причине: qa_client/manager_client/customer_client делят одну cookie-сессию."""
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


def _write_result(run_id, prefix, full_name, status, *, start=0, stop=1000):
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{prefix}-result.json").write_text(
        json.dumps({"fullName": full_name, "status": status, "start": start, "stop": stop}), encoding="utf-8"
    )


def _insert_run(project, stand, status="passed", target="all") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
            "VALUES (?, ?, ?, ?, '2024-01-01T00:00:00', 'qa', '{}')",
            (project, stand, target, status),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@pytest.fixture()
def stats_api_project_dir(tmp_path):
    proj = tmp_path / "stats_api_src"
    (proj / "tests" / "api" / "notifications").mkdir(parents=True)
    return proj


async def _register(qa_client, project_dir, stand="stage"):
    await register_project(qa_client, PROJECT, project_dir)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/stands", json={"name": stand, "url": ""})
    assert resp.status_code == 201, resp.text


async def test_get_stats_lazily_recalculates_and_returns_summary(
    qa_client, isolated_allure_dir, stats_api_project_dir
):
    await _register(qa_client, stats_api_project_dir)
    run_id = _insert_run(PROJECT, "stage")
    _write_result(run_id, "00", "tests.api.notifications#test_a", "passed")
    _write_result(run_id, "01", "tests.api.notifications#test_b", "failed")

    resp = await qa_client.get(f"/api/projects/{PROJECT}/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project"] == PROJECT
    assert body["stand"] == "stage"
    assert body["run_id"] == run_id
    section = next(s for s in body["sections"] if s["section"] == "api/notifications")
    assert section["tests_total"] == 2
    assert section["passed"] == 1
    assert section["failed"] == 1
    assert section["passed_percent"] == 50.0


async def test_get_stats_uses_default_stand_when_not_specified(qa_client, isolated_allure_dir, stats_api_project_dir):
    await _register(qa_client, stats_api_project_dir, stand="develop")
    resp = await qa_client.get(f"/api/projects/{PROJECT}/stats")
    assert resp.status_code == 200, resp.text
    assert resp.json()["stand"] == "develop"


async def test_get_stats_404_for_unknown_project(qa_client, isolated_allure_dir):
    resp = await qa_client.get("/api/projects/no_such_project/stats")
    assert resp.status_code == 404


async def test_get_stats_visible_to_manager_and_customer(role_client, isolated_allure_dir, stats_api_project_dir):
    qa = await role_client("qa")
    await _register(qa, stats_api_project_dir)

    for role in ("manager", "customer"):
        client = await role_client(role)
        resp = await client.get(f"/api/projects/{PROJECT}/stats")
        assert resp.status_code == 200, resp.text
        assert resp.json()["project"] == PROJECT


async def test_get_stats_csv_export_content_and_headers(qa_client, isolated_allure_dir, stats_api_project_dir):
    await _register(qa_client, stats_api_project_dir)
    run_id = _insert_run(PROJECT, "stage")
    _write_result(run_id, "00", "tests.api.notifications#test_a", "passed")

    resp = await qa_client.get(f"/api/projects/{PROJECT}/stats/sections.csv")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert f'filename="{PROJECT}_stats_sections.csv"' in resp.headers["content-disposition"]

    text = resp.text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == [
        "раздел", "тестов", "passed", "failed", "xfail", "skipped",
        "доля passed, %", "средняя длительность, с", "флаки", "активных xfail", "покрытие маршрутов, %",
    ]
    data_row = next(r for r in rows[1:] if r[0] == "api/notifications")
    assert data_row[1] == "1"  # тестов
    assert data_row[2] == "1"  # passed
    assert data_row[6] == "100.0"  # доля passed, %


async def test_get_stats_csv_export_visible_to_customer(qa_client, role_client, isolated_allure_dir, stats_api_project_dir):
    await _register(qa_client, stats_api_project_dir)
    customer = await role_client("customer")
    resp = await customer.get(f"/api/projects/{PROJECT}/stats/sections.csv")
    assert resp.status_code == 200, resp.text


# ------------------------------------------------------------------ кэш по id последнего прогона

async def test_get_stats_cache_invalidated_by_new_finished_run(qa_client, isolated_allure_dir, stats_api_project_dir):
    await _register(qa_client, stats_api_project_dir)
    run_a = _insert_run(PROJECT, "stage")
    _write_result(run_a, "00", "tests.api.notifications#test_a", "passed")

    first = await qa_client.get(f"/api/projects/{PROJECT}/stats")
    assert first.json()["run_id"] == run_a
    assert first.json()["sections"][0]["tests_total"] == 1

    run_b = _insert_run(PROJECT, "stage")
    _write_result(run_b, "00", "tests.api.notifications#test_a", "passed")
    _write_result(run_b, "01", "tests.api.notifications#test_b", "failed")

    second = await qa_client.get(f"/api/projects/{PROJECT}/stats")
    assert second.json()["run_id"] == run_b
    section = next(s for s in second.json()["sections"] if s["section"] == "api/notifications")
    assert section["tests_total"] == 2


async def test_get_stats_no_new_run_serves_from_cache_without_recompute(
    qa_client, isolated_allure_dir, stats_api_project_dir, monkeypatch
):
    await _register(qa_client, stats_api_project_dir)
    run_a = _insert_run(PROJECT, "stage")
    _write_result(run_a, "00", "tests.api.notifications#test_a", "passed")

    first = await qa_client.get(f"/api/projects/{PROJECT}/stats")
    assert first.status_code == 200

    calls = []
    original_recalc = stats.recalc

    def spy_recalc(*args, **kwargs):
        calls.append(args)
        return original_recalc(*args, **kwargs)

    monkeypatch.setattr(stats, "recalc", spy_recalc)

    second = await qa_client.get(f"/api/projects/{PROJECT}/stats")
    assert second.status_code == 200
    assert calls == []  # без нового завершённого прогона кэш не пересчитывается
