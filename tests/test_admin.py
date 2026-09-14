"""Суперадминка (/api/admin/*): доступ только роли superadmin, обзор счётчиков,
пагинация/поиск/сортировка выгрузки таблиц, отсутствие утечки password_hash,
запрет удалить себя, каскадное удаление событий прогона и миграция роли
существующей БД со старой схемой users.
"""

import sqlite3

import pytest

from app.db import get_connection, hash_password, init_db

from .conftest import poll_until, register_project

ADMIN_ENDPOINTS = [
    ("get", "/api/admin/overview", None),
    ("get", "/api/admin/users", None),
    ("get", "/api/admin/runs", None),
    ("put", "/api/admin/users/qa", {"role": "manager"}),
    ("delete", "/api/admin/users/qa", None),
]


@pytest.mark.parametrize("method, url, payload", ADMIN_ENDPOINTS)
async def test_qa_forbidden_on_admin_endpoints(qa_client, method, url, payload):
    resp = await qa_client.request(method, url, json=payload)
    assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}, ожидался 403"


@pytest.mark.parametrize("method, url, payload", ADMIN_ENDPOINTS)
async def test_manager_forbidden_on_admin_endpoints(manager_client, method, url, payload):
    resp = await manager_client.request(method, url, json=payload)
    assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}, ожидался 403"


@pytest.mark.parametrize("method, url, payload", ADMIN_ENDPOINTS)
async def test_customer_forbidden_on_admin_endpoints(customer_client, method, url, payload):
    resp = await customer_client.request(method, url, json=payload)
    assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}, ожидался 403"


async def test_superadmin_can_reach_qa_only_endpoints(superadmin_client):
    # superadmin имеет всё, что qa (require_roles("qa") пропускает и superadmin, см. app/deps.py)
    resp = await superadmin_client.get("/api/users")
    assert resp.status_code == 200


async def test_overview_counts_match_fixture_data(superadmin_client):
    resp = await superadmin_client.get("/api/admin/overview")
    assert resp.status_code == 200
    body = resp.json()
    # seed: qa, manager, customer, admin
    assert body["counts"]["users"] == 4
    assert body["counts"]["projects"] == 2  # bike_fit, Velo_bot
    assert body["counts"]["stands"] == 0
    assert body["counts"]["runs"] == 0
    assert body["counts"]["run_events"] == 0
    assert body["runs_by_status"] == {}
    assert body["recent_runs"] == []


async def test_overview_reflects_new_run(superadmin_client, qa_client, isolated_allure_dir, runnable_project_dir):
    await register_project(qa_client, "overview_proj", runnable_project_dir)
    create_resp = await qa_client.post(
        "/api/projects/overview_proj/runs", json={"target": "tests/test_sample.py"}
    )
    run_id = create_resp.json()["id"]

    resp = await superadmin_client.get("/api/admin/overview")
    body = resp.json()
    assert body["counts"]["runs"] == 1
    assert body["counts"]["projects"] == 3
    assert any(r["id"] == run_id for r in body["recent_runs"])


async def test_users_password_hash_not_leaked(superadmin_client):
    resp = await superadmin_client.get("/api/admin/users")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    for row in body["items"]:
        assert "password_hash" not in row
        assert set(row.keys()) == {"login", "role", "onboarded"}


async def test_users_pagination(superadmin_client, qa_client):
    for i in range(5):
        resp = await qa_client.post(
            "/api/users", json={"login": f"extra_{i}", "password": "x", "role": "customer"}
        )
        assert resp.status_code == 201

    resp = await superadmin_client.get("/api/admin/users?page=1&per_page=3&sort=login&order=asc")
    body = resp.json()
    assert body["total"] == 9  # 4 seed + 5 extra
    assert body["page"] == 1
    assert len(body["items"]) == 3
    logins_page1 = [u["login"] for u in body["items"]]
    assert logins_page1 == sorted(logins_page1)

    resp2 = await superadmin_client.get("/api/admin/users?page=2&per_page=3&sort=login&order=asc")
    body2 = resp2.json()
    logins_page2 = [u["login"] for u in body2["items"]]
    assert set(logins_page1).isdisjoint(logins_page2)


async def test_users_search_filters_by_login(superadmin_client, qa_client):
    await qa_client.post("/api/users", json={"login": "zebra_user", "password": "x", "role": "customer"})

    resp = await superadmin_client.get("/api/admin/users?q=zebra")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["login"] == "zebra_user"


async def test_users_sort_desc(superadmin_client):
    resp = await superadmin_client.get("/api/admin/users?sort=login&order=desc")
    body = resp.json()
    logins = [u["login"] for u in body["items"]]
    assert logins == sorted(logins, reverse=True)


async def test_runs_pagination_and_sort(superadmin_client, qa_client, isolated_allure_dir, runnable_project_dir):
    await register_project(qa_client, "runs_list_proj", runnable_project_dir)
    run_ids = []
    for _ in range(3):
        create_resp = await qa_client.post(
            "/api/projects/runs_list_proj/runs", json={"target": "tests/test_sample.py"}
        )
        run_id = create_resp.json()["id"]
        run_ids.append(run_id)

        async def finished(rid=run_id):
            rows = (await qa_client.get("/api/projects/runs_list_proj/runs")).json()
            row = next(r for r in rows if r["id"] == rid)
            return row if row["status"] in {"passed", "failed"} else None

        assert await poll_until(finished, timeout=15) is not None

    resp = await superadmin_client.get("/api/admin/runs?sort=id&order=desc&per_page=2&page=1")
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    ids = [r["id"] for r in body["items"]]
    assert ids == sorted(ids, reverse=True)


async def test_admin_update_user_role_and_password(superadmin_client, client):
    resp = await superadmin_client.put("/api/admin/users/customer", json={"role": "manager"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"

    resp = await superadmin_client.put("/api/admin/users/customer", json={"password": "new-pw"})
    assert resp.status_code == 200

    login_resp = await client.post("/api/login", json={"login": "customer", "password": "new-pw"})
    assert login_resp.status_code == 200


async def test_admin_cannot_delete_self(superadmin_client):
    resp = await superadmin_client.delete("/api/admin/users/admin")
    assert resp.status_code == 400


async def test_admin_can_delete_other_user(superadmin_client):
    resp = await superadmin_client.delete("/api/admin/users/customer")
    assert resp.status_code == 204

    resp = await superadmin_client.get("/api/admin/users?q=customer")
    assert resp.json()["total"] == 0


async def test_admin_delete_unknown_user_is_404(superadmin_client):
    resp = await superadmin_client.delete("/api/admin/users/does-not-exist")
    assert resp.status_code == 404


async def test_delete_run_cascades_run_events(
    superadmin_client, qa_client, isolated_allure_dir, runnable_project_dir
):
    await register_project(qa_client, "cascade_proj", runnable_project_dir)
    create_resp = await qa_client.post(
        "/api/projects/cascade_proj/runs", json={"target": "tests/test_sample.py"}
    )
    run_id = create_resp.json()["id"]

    async def finished():
        rows = (await qa_client.get("/api/projects/cascade_proj/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    assert await poll_until(finished, timeout=15) is not None

    conn = get_connection()
    try:
        events_before = conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert events_before > 0

    resp = await superadmin_client.delete(f"/api/admin/runs/{run_id}")
    assert resp.status_code == 204

    conn = get_connection()
    try:
        run_row = conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
        events_after = conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert run_row is None
    assert events_after == 0


async def test_cannot_delete_running_run(superadmin_client, qa_client, isolated_allure_dir, slow_project_dir):
    from app.core import runner

    await register_project(qa_client, "running_del_proj", slow_project_dir)
    create_resp = await qa_client.post(
        "/api/projects/running_del_proj/runs", json={"target": "tests/test_slow.py"}
    )
    run_id = create_resp.json()["id"]

    async def process_registered():
        return runner._active_procs.get(run_id)

    proc = await poll_until(process_registered, timeout=5)
    assert proc is not None

    try:
        resp = await superadmin_client.delete(f"/api/admin/runs/{run_id}")
        assert resp.status_code == 409
    finally:
        cancel_resp = await qa_client.post(f"/api/runs/{run_id}/cancel")
        assert cancel_resp.status_code == 200


def test_role_migration_preserves_existing_users_and_allows_superadmin(tmp_path, monkeypatch):
    from app.config import settings

    old_db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(old_db_path)
    conn.execute(
        "CREATE TABLE users ("
        "login TEXT PRIMARY KEY,"
        "password_hash TEXT NOT NULL,"
        "role TEXT NOT NULL CHECK (role IN ('qa', 'manager', 'customer')),"
        "onboarded INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, ?, ?)",
        ("legacy_qa", hash_password("legacy_qa"), "qa", 1),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        legacy = conn.execute("SELECT * FROM users WHERE login = ?", ("legacy_qa",)).fetchone()
        assert legacy is not None
        assert legacy["role"] == "qa"
        assert legacy["password_hash"].startswith("scrypt$")

        # CHECK теперь допускает superadmin, старая БД не осталась без него,
        # и seed-суперадмин был добавлен при инициализации.
        admin_row = conn.execute("SELECT * FROM users WHERE login = 'admin'").fetchone()
        assert admin_row is not None
        assert admin_row["role"] == "superadmin"

        conn.execute(
            "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, 'superadmin', 0)",
            ("another_admin", hash_password("x")),
        )
        conn.commit()
    finally:
        conn.close()
