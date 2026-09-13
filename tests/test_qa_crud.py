"""qa выполняет полный CRUD для проектов, стендов и пользователей.

Каждый тест работает на своей изолированной тестовой БД (фикстура db_path/client
из conftest.py), поэтому откатывать изменения вручную не требуется.
"""


async def test_qa_project_crud(qa_client):
    create_resp = await qa_client.post(
        "/api/projects", json={"name": "demo_proj", "path": "/tmp/demo_proj", "venv": ".venv"}
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["name"] == "demo_proj"
    assert body["path"] == "/tmp/demo_proj"
    assert body["stands"] == []

    list_resp = await qa_client.get("/api/projects")
    assert "demo_proj" in {p["name"] for p in list_resp.json()}

    update_resp = await qa_client.put("/api/projects/demo_proj", json={"path": "/tmp/demo_proj_v2"})
    assert update_resp.status_code == 200
    assert update_resp.json()["path"] == "/tmp/demo_proj_v2"

    delete_resp = await qa_client.delete("/api/projects/demo_proj")
    assert delete_resp.status_code == 204

    list_resp = await qa_client.get("/api/projects")
    assert "demo_proj" not in {p["name"] for p in list_resp.json()}


async def test_qa_project_create_duplicate_conflicts(qa_client):
    resp = await qa_client.post(
        "/api/projects", json={"name": "bike_fit", "path": "/anything", "venv": ".venv"}
    )
    assert resp.status_code == 409


async def test_qa_project_update_missing_is_404(qa_client):
    resp = await qa_client.put("/api/projects/does_not_exist", json={"path": "/x"})
    assert resp.status_code == 404


async def test_qa_stand_crud(qa_client):
    create_resp = await qa_client.post(
        "/api/projects/bike_fit/stands",
        json={"name": "staging", "url": "http://staging.example", "login": "op"},
    )
    assert create_resp.status_code == 201
    stand = create_resp.json()
    assert stand["name"] == "staging"
    stand_id = stand["id"]

    list_resp = await qa_client.get("/api/projects/bike_fit/stands")
    assert any(s["id"] == stand_id for s in list_resp.json())

    update_resp = await qa_client.put(
        f"/api/projects/bike_fit/stands/{stand_id}", json={"url": "http://staging2.example"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["url"] == "http://staging2.example"
    # name/login не переданы в update body -> должны сохраниться прежними
    assert update_resp.json()["name"] == "staging"
    assert update_resp.json()["login"] == "op"

    delete_resp = await qa_client.delete(f"/api/projects/bike_fit/stands/{stand_id}")
    assert delete_resp.status_code == 204

    list_resp = await qa_client.get("/api/projects/bike_fit/stands")
    assert all(s["id"] != stand_id for s in list_resp.json())


async def test_qa_user_crud(qa_client):
    create_resp = await qa_client.post(
        "/api/users", json={"login": "new_customer", "password": "pw123", "role": "customer"}
    )
    assert create_resp.status_code == 201
    assert create_resp.json() == {"login": "new_customer", "role": "customer", "onboarded": False}

    list_resp = await qa_client.get("/api/users")
    assert "new_customer" in {u["login"] for u in list_resp.json()}

    update_resp = await qa_client.put(
        "/api/users/new_customer", json={"role": "manager", "onboarded": True}
    )
    assert update_resp.status_code == 200
    assert update_resp.json() == {"login": "new_customer", "role": "manager", "onboarded": True}

    delete_resp = await qa_client.delete("/api/users/new_customer")
    assert delete_resp.status_code == 204

    list_resp = await qa_client.get("/api/users")
    assert "new_customer" not in {u["login"] for u in list_resp.json()}


async def test_qa_user_create_duplicate_conflicts(qa_client):
    resp = await qa_client.post(
        "/api/users", json={"login": "qa", "password": "x", "role": "qa"}
    )
    assert resp.status_code == 409


async def test_qa_updated_user_password_can_login(qa_client, client):
    resp = await qa_client.put("/api/users/customer", json={"password": "new-pass"})
    assert resp.status_code == 200

    login_resp = await client.post(
        "/api/login", json={"login": "customer", "password": "new-pass"}
    )
    assert login_resp.status_code == 200

    old_login_resp = await client.post(
        "/api/login", json={"login": "customer", "password": "customer"}
    )
    assert old_login_resp.status_code == 401
