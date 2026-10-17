"""REST API «Новых дефектов» (app/routers/new_defects.py) через app/main.py —
по образцу tests/test_xfail.py/test_sentry_api.py: db_path + qa_client/
manager_client фикстуры из tests/conftest.py."""
import httpx
import pytest

from app.config import settings
from app.core import youtrack
from app.db import get_connection

PROJECT = "nd_api_proj"
STAND = "stand"


@pytest.fixture(autouse=True)
def _youtrack_unconfigured_by_default(monkeypatch):
    """Тесты не должны зависеть от реального workspace/.env (владелец настроил
    там боевой TH_YOUTRACK_* для продакшен-инстанса, см. app/core/youtrack.py) —
    по умолчанию YouTrack тут всегда "не настроен"; youtrack_configured ниже
    явно переопределяет на тестовые значения там, где это нужно сценарию."""
    monkeypatch.setattr(settings, "TH_YOUTRACK_URL", "")
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", "")
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "")


@pytest.fixture()
def project_and_stand(db_path):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/nd_api_proj', '.venv', '[]')",
            (PROJECT,),
        )
        conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
            "VALUES (?, ?, 'all', 'failed', '2026-01-01T00:00:00', 'qa', '{}')",
            (PROJECT, STAND),
        )
        run_id = cur.lastrowid
        conn.execute(
            "INSERT INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
            "VALUES (?, 'tests/api/test_a.py::test_a', 'pkg.test_a#test_a', 'failed', 1.0, 'code', "
            "'2026-01-01T00:01:00')",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


@pytest.fixture()
def youtrack_configured(monkeypatch):
    monkeypatch.setattr(settings, "TH_YOUTRACK_URL", "https://tracker.example.ru")
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "PROJ-1")


async def test_list_returns_candidate_connected_false_without_youtrack(qa_client, project_and_stand):
    run_id = project_and_stand
    resp = await qa_client.get(
        f"/api/projects/{PROJECT}/new-defects", params={"stand": STAND, "run_id": run_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert len(data["items"]) == 1
    assert data["items"][0]["full_name"] == "pkg.test_a#test_a"


async def test_list_connected_true_when_youtrack_configured(qa_client, project_and_stand, youtrack_configured):
    run_id = project_and_stand
    resp = await qa_client.get(
        f"/api/projects/{PROJECT}/new-defects", params={"stand": STAND, "run_id": run_id}
    )
    assert resp.json()["connected"] is True


async def test_decide_dismissed_works_without_youtrack(qa_client, project_and_stand):
    run_id = project_and_stand
    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "dismissed"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "dismissed"
    assert body["issue_url"] is None

    # повторный GET списка кандидатов больше не содержит этот тест
    listed = await qa_client.get(
        f"/api/projects/{PROJECT}/new-defects", params={"stand": STAND, "run_id": run_id}
    )
    assert listed.json()["items"] == []


async def test_decide_confirmed_without_youtrack_returns_503(qa_client, project_and_stand):
    run_id = project_and_stand
    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "confirmed"},
    )
    assert resp.status_code == 503


async def test_decide_confirmed_posts_to_youtrack_and_stores_issue_url(
    qa_client, project_and_stand, youtrack_configured, monkeypatch
):
    run_id = project_and_stand

    def fake_post(url, *, headers=None, params=None, json=None, timeout=None):
        def handler(request):
            return httpx.Response(200, json={"id": "4-999"})
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            return c.post(url, headers=headers, params=params, json=json, timeout=timeout)

    monkeypatch.setattr(youtrack.httpx, "post", fake_post)

    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={
            "full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "confirmed",
            "priority": "Высокий", "expected_result": "ОР", "precondition": "ПУ",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["issue_url"] == "https://tracker.example.ru/issue/PROJ-1"
    assert body["priority"] == "Высокий"


async def test_customer_cannot_decide(customer_client, project_and_stand, youtrack_configured):
    run_id = project_and_stand
    resp = await customer_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "dismissed"},
    )
    assert resp.status_code == 403


async def test_manager_can_decide(manager_client, project_and_stand):
    run_id = project_and_stand
    resp = await manager_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "dismissed"},
    )
    assert resp.status_code == 201
