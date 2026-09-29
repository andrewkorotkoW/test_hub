"""Права ролей и окно прогона для API Sentry (app/routers/sentry.py) — п.3 и
п.4 «Тесты» в docs/missions/2026-09-29_sentry.md.

Роли: qa/manager/customer/superadmin (см. app/db.py:12 CHECK — единственные
четыре роли в этой версии, "admin" как отдельной роли нет: логин "admin" из
tests/conftest.py::superadmin_client имеет роль superadmin). require_roles
пропускает superadmin через любой набор ролей неявно (см. app/deps.py) — это
уже подтверждённое поведение (см. tests/test_share.py), не дефект, поэтому
здесь ожидаем 200 у qa и superadmin, 403 у manager/customer.

Каждый ролевой клиент — собственный AsyncClient (см. testhub-coverage-api-router
и testhub-share-public-link в памяти агента: qa_client/manager_client/customer_client
из conftest.py делят один и тот же `client`, второй login() затирает cookie
первого), поэтому используем _own_client() по образцу tests/test_share.py.
"""
import sqlite3
from datetime import datetime

from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core import sentry as sentry_client
from app.main import app

from .conftest import login, register_project

ORG = "vshgu"


def _configure_sentry(monkeypatch):
    """Глобальные настройки Sentry (без них app/routers/sentry.py::_stand_reason
    вернёт "Sentry не настроен" ещё до вызова list_issues, независимо от того,
    что подставлено в sentry_client.list_issues)."""
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "https://sentry.example.ru")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "test-token")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", ORG)


async def _own_client(login_: str, password: str) -> AsyncClient:
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://testserver")
    resp = await login(ac, login_, password)
    assert resp.status_code == 200
    return ac


async def _make_project_with_linked_stand(qa_client, tmp_path, project, stand="develop"):
    await register_project(qa_client, project, tmp_path)
    resp = await qa_client.post(
        f"/api/projects/{project}/stands",
        json={
            "name": stand,
            "url": "https://develop.example.ru",
            "sentry_project": "frontend",
            "sentry_environment": "develop",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _insert_run(db_path, project, stand, started=None, finished=None, status_="passed"):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, finished, requested_by, counts) "
            "VALUES (?, ?, 'all', ?, ?, ?, 'qa', '{}')",
            (project, stand, status_, started, finished),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ------------------------------------------------------------------ права ролей: /sentry/issues по стенду

async def test_qa_gets_200_on_stand_sentry_issues(qa_client, tmp_path, monkeypatch):
    monkeypatch.setattr(sentry_client, "list_issues", lambda *a, **kw: [])
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_proj1")
    resp = await qa_client.get("/api/projects/sentry_roles_proj1/stands/develop/sentry/issues")
    assert resp.status_code == 200


async def test_superadmin_gets_200_on_stand_sentry_issues(qa_client, tmp_path, monkeypatch):
    monkeypatch.setattr(sentry_client, "list_issues", lambda *a, **kw: [])
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_proj2")
    superadmin = await _own_client("admin", "admin")
    try:
        resp = await superadmin.get("/api/projects/sentry_roles_proj2/stands/develop/sentry/issues")
    finally:
        await superadmin.aclose()
    assert resp.status_code == 200


async def test_manager_forbidden_on_stand_sentry_issues(qa_client, tmp_path):
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_proj3")
    manager = await _own_client("manager", "manager")
    try:
        resp = await manager.get("/api/projects/sentry_roles_proj3/stands/develop/sentry/issues")
    finally:
        await manager.aclose()
    assert resp.status_code == 403


async def test_customer_forbidden_on_stand_sentry_issues(qa_client, tmp_path):
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_proj4")
    customer = await _own_client("customer", "customer")
    try:
        resp = await customer.get("/api/projects/sentry_roles_proj4/stands/develop/sentry/issues")
    finally:
        await customer.aclose()
    assert resp.status_code == 403


# ------------------------------------------------------------------ права ролей: /runs/{id}/sentry

async def test_qa_gets_200_on_run_sentry(qa_client, tmp_path, db_path, monkeypatch):
    monkeypatch.setattr(sentry_client, "list_issues", lambda *a, **kw: [])
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_run1")
    run_id = _insert_run(db_path, "sentry_roles_run1", "develop", started="2026-09-29T10:00:00")
    resp = await qa_client.get(f"/api/runs/{run_id}/sentry")
    assert resp.status_code == 200


async def test_superadmin_gets_200_on_run_sentry(qa_client, tmp_path, db_path, monkeypatch):
    monkeypatch.setattr(sentry_client, "list_issues", lambda *a, **kw: [])
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_run2")
    run_id = _insert_run(db_path, "sentry_roles_run2", "develop", started="2026-09-29T10:00:00")
    superadmin = await _own_client("admin", "admin")
    try:
        resp = await superadmin.get(f"/api/runs/{run_id}/sentry")
    finally:
        await superadmin.aclose()
    assert resp.status_code == 200


async def test_manager_forbidden_on_run_sentry(qa_client, tmp_path, db_path):
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_run3")
    run_id = _insert_run(db_path, "sentry_roles_run3", "develop", started="2026-09-29T10:00:00")
    manager = await _own_client("manager", "manager")
    try:
        resp = await manager.get(f"/api/runs/{run_id}/sentry")
    finally:
        await manager.aclose()
    assert resp.status_code == 403


async def test_customer_forbidden_on_run_sentry(qa_client, tmp_path, db_path):
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_roles_run4")
    run_id = _insert_run(db_path, "sentry_roles_run4", "develop", started="2026-09-29T10:00:00")
    customer = await _own_client("customer", "customer")
    try:
        resp = await customer.get(f"/api/runs/{run_id}/sentry")
    finally:
        await customer.aclose()
    assert resp.status_code == 403


# ------------------------------------------------------------------ окно прогона: только issues окна (+5 мин), is_new

def _issue(id_, first_seen, last_seen=None):
    return sentry_client.SentryIssue(
        id=id_,
        title=f"issue {id_}",
        culprit=None,
        level="error",
        count=1,
        user_count=1,
        first_seen=first_seen,
        last_seen=last_seen or first_seen,
        permalink=f"https://sentry.example.ru/issues/{id_}/",
    )


async def test_run_sentry_window_filters_and_marks_new_issues(qa_client, tmp_path, db_path, monkeypatch):
    _configure_sentry(monkeypatch)
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_window_proj")
    # окно прогона: 10:00:00..10:30:00 (+5 мин хвоста -> до 10:35:00)
    run_id = _insert_run(
        db_path, "sentry_window_proj", "develop",
        started="2026-09-29T10:00:00", finished="2026-09-29T10:30:00",
    )

    issues = [
        _issue("before_start_still_active", "2026-09-29T09:00:00Z", last_seen="2026-09-29T10:05:00Z"),
        _issue("before_start_resolved_before_run", "2026-09-29T08:00:00Z", last_seen="2026-09-29T09:00:00Z"),
        _issue("inside_window", "2026-09-29T10:10:00Z"),
        _issue("at_window_end_boundary", "2026-09-29T10:35:00Z"),
        _issue("after_window_tail", "2026-09-29T11:00:00Z"),
        _issue("no_first_seen", None, last_seen="2026-09-29T10:20:00Z"),
    ]
    monkeypatch.setattr(sentry_client, "list_issues", lambda *a, **kw: issues)

    resp = await qa_client.get(f"/api/runs/{run_id}/sentry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True

    by_id = {item["id"]: item for item in data["issues"]}
    assert set(by_id) == {
        "before_start_still_active",
        "inside_window",
        "at_window_end_boundary",
        "no_first_seen",
    }
    assert "before_start_resolved_before_run" not in by_id, "issue, затихший до начала прогона, не должен попадать в окно"
    assert "after_window_tail" not in by_id, "issue, появившийся после хвоста окна, не должен попадать в окно"

    assert by_id["before_start_still_active"]["is_new"] is False, "issue появился до начала прогона — не новый"
    assert by_id["inside_window"]["is_new"] is True
    assert by_id["at_window_end_boundary"]["is_new"] is True, "граница +5 мин включительна"
    assert by_id["no_first_seen"]["is_new"] is False, "без firstSeen нельзя утверждать, что issue новый"


async def test_run_sentry_window_uses_now_as_end_when_run_still_running(qa_client, tmp_path, db_path, monkeypatch):
    """Незавершённый прогон (finished IS NULL) — окно до datetime.now() + 5 мин,
    не до бесконечности: issue из далёкого будущего всё равно отфильтровывается."""
    _configure_sentry(monkeypatch)
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_window_running_proj")
    run_id = _insert_run(
        db_path, "sentry_window_running_proj", "develop",
        started=datetime.now().isoformat(timespec="seconds"), finished=None, status_="running",
    )
    far_future = _issue("far_future", "2099-01-01T00:00:00Z")
    monkeypatch.setattr(sentry_client, "list_issues", lambda *a, **kw: [far_future])

    resp = await qa_client.get(f"/api/runs/{run_id}/sentry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["issues"] == []


async def test_run_sentry_unknown_run_is_404(qa_client):
    resp = await qa_client.get("/api/runs/999999/sentry")
    assert resp.status_code == 404


async def test_run_sentry_run_without_stand_is_disconnected(qa_client, db_path):
    run_id = _insert_run(db_path, "no_such_project", None, started="2026-09-29T10:00:00")
    resp = await qa_client.get(f"/api/runs/{run_id}/sentry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["reason"] == "У прогона не указан стенд"


async def test_run_sentry_propagates_client_error_as_disconnected(qa_client, tmp_path, db_path, monkeypatch):
    _configure_sentry(monkeypatch)
    await _make_project_with_linked_stand(qa_client, tmp_path, "sentry_error_proj")
    run_id = _insert_run(db_path, "sentry_error_proj", "develop", started="2026-09-29T10:00:00")

    def raise_unauthorized(*a, **kw):
        raise sentry_client.SentryUnauthorized("Sentry: неверный или просроченный токен либо нет доступа к проекту")

    monkeypatch.setattr(sentry_client, "list_issues", raise_unauthorized)

    resp = await qa_client.get(f"/api/runs/{run_id}/sentry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert "токен" in data["reason"]
