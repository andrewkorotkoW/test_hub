"""REST API вкладки «Задачи» (app/routers/youtrack_tasks.py) через app/main.py —
по образцу tests/test_new_defects_api.py: db_path + qa_client/manager_client
фикстуры из tests/conftest.py, свой httpx.get-мок (в отличие от _install_youtrack_mock
там же, который мокает httpx.post для комментариев)."""
import httpx
import pytest

from app.config import settings
from app.core import youtrack


@pytest.fixture(autouse=True)
def _youtrack_unconfigured_by_default(monkeypatch):
    """См. tests/test_new_defects_api.py — тесты не должны зависеть от реального
    workspace/.env, по умолчанию YouTrack тут всегда "не настроен"."""
    monkeypatch.setattr(settings, "TH_YOUTRACK_URL", "")
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", "")
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "")


@pytest.fixture()
def youtrack_configured(monkeypatch):
    monkeypatch.setattr(settings, "TH_YOUTRACK_URL", "https://tracker.example.ru")
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "PROJ-1")


def _install_youtrack_issues_mock(monkeypatch, issues: list[dict]):
    """Мокает httpx.get (list_my_issues), возвращает список захваченных
    httpx.Request — проверяем и результат, и реально отправленный query."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=issues)

    def fake_get(url, *, headers=None, params=None, timeout=None):
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            return c.get(url, headers=headers, params=params, timeout=timeout)

    monkeypatch.setattr(youtrack.httpx, "get", fake_get)
    return calls


async def test_my_tasks_without_youtrack_returns_connected_false(qa_client):
    resp = await qa_client.get("/api/youtrack/my-tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["tasks"] == []


async def test_my_tasks_requires_qa_role(client, manager_client, customer_client):
    for forbidden_client in (manager_client, customer_client):
        resp = await forbidden_client.get("/api/youtrack/my-tasks")
        assert resp.status_code == 403


async def test_my_tasks_returns_parsed_and_sorted_tasks(qa_client, youtrack_configured, monkeypatch):
    issues = [
        {
            "idReadable": "PROJ-10",
            "summary": "Старая задача",
            "project": {"shortName": "PROJ"},
            "customFields": [{"name": "Design", "value": {"name": "Blocked"}}],
            "updated": 1700000000000,
        },
        {
            "idReadable": "PROJ-20",
            "summary": "Свежая задача",
            "project": {"shortName": "PROJ"},
            "customFields": [{"name": "Design", "value": {"name": "In Progress"}}],
            "updated": 1800000000000,
        },
        {
            "idReadable": "PROJ-30",
            "summary": "Без статуса",
            "project": {"shortName": "PROJ"},
            "customFields": [{"name": "Assignee", "value": {"name": "Кто-то"}}],
            "updated": None,
        },
    ]
    calls = _install_youtrack_issues_mock(monkeypatch, issues)

    resp = await qa_client.get("/api/youtrack/my-tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True

    # отправлен правильный фильтр — assignee: me, а не for: me (регрессия
    # 18.10.2026: for: me возвращал весь шлейф — репортер/наблюдатель/
    # комментатор, а не только реального исполнителя)
    assert len(calls) == 1
    sent_query = calls[0].url.params["query"]
    assert sent_query == "assignee: me #Unresolved"

    tasks = body["tasks"]
    assert [t["id"] for t in tasks] == ["PROJ-20", "PROJ-10", "PROJ-30"]
    assert tasks[0]["status"] == "In Progress"
    assert tasks[1]["status"] == "Blocked"
    assert tasks[2]["status"] is None
    assert tasks[0]["url"] == "https://tracker.example.ru/issue/PROJ-20"


async def test_my_tasks_youtrack_error_returns_connected_false(qa_client, youtrack_configured, monkeypatch):
    def fake_get(url, *, headers=None, params=None, timeout=None):
        return httpx.Response(401, request=httpx.Request("GET", url))

    monkeypatch.setattr(youtrack.httpx, "get", fake_get)

    resp = await qa_client.get("/api/youtrack/my-tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["reason"]
