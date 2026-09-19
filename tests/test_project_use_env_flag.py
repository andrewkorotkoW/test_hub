"""use_env_flag персистится через CRUD проектов (app/schemas.py, app/routers/projects.py).

POST /api/projects принимает use_env_flag (по умолчанию False) и возвращает его в
payload; PUT /api/projects/{name} умеет включать и выключать флаг, а без явного
use_env_flag в теле сохраняет прежнее значение (как path/venv в test_qa_crud.py).
"""


async def test_create_project_with_use_env_flag_true_persists(qa_client, tmp_path):
    project_dir = tmp_path / "env_flag_proj"
    project_dir.mkdir()
    create_resp = await qa_client.post(
        "/api/projects",
        json={"name": "env_flag_proj", "path": str(project_dir), "venv": ".venv", "use_env_flag": True},
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["use_env_flag"] is True

    list_resp = await qa_client.get("/api/projects")
    row = next(p for p in list_resp.json() if p["name"] == "env_flag_proj")
    assert row["use_env_flag"] is True


async def test_create_project_without_use_env_flag_defaults_false(qa_client, tmp_path):
    project_dir = tmp_path / "plain_proj"
    project_dir.mkdir()
    create_resp = await qa_client.post(
        "/api/projects", json={"name": "plain_proj", "path": str(project_dir), "venv": ".venv"}
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["use_env_flag"] is False


async def test_update_project_can_toggle_use_env_flag_on(qa_client):
    resp = await qa_client.put("/api/projects/bike_fit", json={"use_env_flag": True})
    assert resp.status_code == 200
    assert resp.json()["use_env_flag"] is True


async def test_update_project_without_use_env_flag_keeps_previous_value(qa_client):
    on_resp = await qa_client.put("/api/projects/bike_fit", json={"use_env_flag": True})
    assert on_resp.json()["use_env_flag"] is True

    # use_env_flag не передан -> должно сохраниться прежнее (True), как path/venv выше
    kept_resp = await qa_client.put("/api/projects/bike_fit", json={"venv": ".venv"})
    assert kept_resp.status_code == 200
    assert kept_resp.json()["use_env_flag"] is True


async def test_update_project_can_toggle_use_env_flag_off(qa_client, tmp_path):
    project_dir = tmp_path / "toggle_proj"
    project_dir.mkdir()
    create_resp = await qa_client.post(
        "/api/projects",
        json={"name": "toggle_proj", "path": str(project_dir), "venv": ".venv", "use_env_flag": True},
    )
    assert create_resp.json()["use_env_flag"] is True

    off_resp = await qa_client.put("/api/projects/toggle_proj", json={"use_env_flag": False})
    assert off_resp.status_code == 200
    assert off_resp.json()["use_env_flag"] is False
