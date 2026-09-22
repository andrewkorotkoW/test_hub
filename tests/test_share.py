"""Публичная ссылка на отчёт прогона (app/routers/share.py): создание/отзыв/список
ссылок (qa/manager), доступ по токену без логина, маскирование секретов в логе.

Гоняет реальный pytest на фикстурном проекте (см. tests/conftest.py::_FIXTURE_TESTS),
как tests/test_run_report.py и tests/test_report_png.py.
"""
import io

from httpx import ASGITransport, AsyncClient

from app.core.runner import mask_secrets
from app.db import get_connection
from app.main import app

from .conftest import login, poll_until, register_project

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:  # pragma: no cover - PIL уже есть в зависимостях (matplotlib)
    HAS_PIL = False


def _assert_valid_png(data: bytes) -> None:
    assert data.startswith(PNG_SIGNATURE)
    if HAS_PIL:
        Image.open(io.BytesIO(data)).verify()


def _anon_client() -> AsyncClient:
    """Клиент без cookie вообще — для проверки публичных маршрутов "без логина".
    Нельзя переиспользовать фикстуру `client` вместе с `qa_client` в одном тесте:
    qa_client логинится на том же самом объекте `client` (общая cookie jar)."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _own_client(login_: str, password: str) -> AsyncClient:
    """Собственный AsyncClient с собственной cookie jar (как conftest.py::superadmin_client) —
    qa_client/manager_client/customer_client в этом файле переиспользовать одновременно с
    другим ролевым клиентом нельзя: все они делят cookie одного и того же `client`, и второй
    login() в общем клиенте затирает cookie первого."""
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://testserver")
    resp = await login(ac, login_, password)
    assert resp.status_code == 200
    return ac


async def _run_fixture_project(qa_client, project_name, project_dir, target="tests/test_sample.py"):
    await register_project(qa_client, project_name, project_dir)
    create_resp = await qa_client.post(f"/api/projects/{project_name}/runs", json={"target": target})
    assert create_resp.status_code == 201, create_resp.text
    run_id = create_resp.json()["id"]

    async def finished():
        rows = (await qa_client.get(f"/api/projects/{project_name}/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None, "прогон не завершился вовремя"
    return run_id, final


# ------------------------------------------------------------------ маскирование секретов
def test_mask_secrets_authorization_header():
    assert mask_secrets("Authorization: Bearer supersecrettoken123") == "Authorization: ***"


def test_mask_secrets_cookie_header():
    line = mask_secrets("Cookie: th_session=abcdef.sig; other=1")
    assert line == "Cookie: ***"
    assert "abcdef" not in line


def test_mask_secrets_token_query_param():
    assert mask_secrets("GET /api/x?token=abc123def HTTP/1.1") == "GET /api/x?token=*** HTTP/1.1"


def test_mask_secrets_leaves_normal_lines_untouched():
    assert mask_secrets("tests/test_sample.py::test_ok PASSED") == "tests/test_sample.py::test_ok PASSED"


async def test_run_log_masks_secrets_printed_by_test(qa_client, isolated_allure_dir, tmp_path):
    from .conftest import _with_symlinked_venv

    proj = tmp_path / "secret_proj"
    tests_dir = proj / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_secret.py").write_text(
        "def test_prints_secret():\n"
        "    print('Authorization: Bearer supersecrettoken123')\n"
        "    print('token=abc123def456')\n"
        "    assert True\n"
    )
    _with_symlinked_venv(proj)

    run_id, final = await _run_fixture_project(qa_client, "secret_proj", proj, target="tests/test_secret.py")
    assert final["status"] == "passed"

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT line FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    finally:
        conn.close()
    joined = "\n".join(r["line"] for r in rows)
    assert "supersecrettoken123" not in joined
    assert "abc123def456" not in joined


# ------------------------------------------------------------------ API создания/списка/отзыва (qa/manager)
async def test_qa_can_create_and_list_share_link(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_api_proj", runnable_project_dir)

    resp = await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "7d"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"]
    assert body["url"].endswith(f"/share/{body['token']}")
    assert body["revoked"] is False
    assert body["expires_at"] is not None

    listing = await qa_client.get(f"/api/runs/{run_id}/share")
    assert listing.status_code == 200
    tokens = [row["token"] for row in listing.json()]
    assert body["token"] in tokens


async def test_manager_can_create_share_link(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_mgr_proj", runnable_project_dir)
    manager = await _own_client("manager", "manager")
    try:
        resp = await manager.post(f"/api/runs/{run_id}/share", json={"expires": "never"})
    finally:
        await manager.aclose()
    assert resp.status_code == 201
    assert resp.json()["expires_at"] is None


async def test_customer_forbidden_to_create_share_link(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_forbidden_proj", runnable_project_dir)
    customer = await _own_client("customer", "customer")
    try:
        resp = await customer.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})
    finally:
        await customer.aclose()
    assert resp.status_code == 403


async def test_customer_forbidden_to_list_or_revoke_share_link(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_forbidden_list_proj", runnable_project_dir)
    created = await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})
    token = created.json()["token"]

    customer = await _own_client("customer", "customer")
    try:
        assert (await customer.get(f"/api/runs/{run_id}/share")).status_code == 403
        assert (await customer.delete(f"/api/runs/{run_id}/share/{token}")).status_code == 403
    finally:
        await customer.aclose()


async def test_create_share_link_unknown_run_is_404(qa_client):
    resp = await qa_client.post("/api/runs/999999/share", json={"expires": "30d"})
    assert resp.status_code == 404


async def test_qa_can_revoke_share_link(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_revoke_proj", runnable_project_dir)
    created = await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})
    token = created.json()["token"]

    revoke = await qa_client.delete(f"/api/runs/{run_id}/share/{token}")
    assert revoke.status_code == 204

    listing = (await qa_client.get(f"/api/runs/{run_id}/share")).json()
    row = next(r for r in listing if r["token"] == token)
    assert row["revoked"] is True


async def test_revoke_unknown_token_is_404(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_revoke_unknown_proj", runnable_project_dir)
    resp = await qa_client.delete(f"/api/runs/{run_id}/share/does-not-exist")
    assert resp.status_code == 404


# ------------------------------------------------------------------ публичные маршруты: без логина, по токену
async def test_public_share_page_accessible_without_login(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_public_page_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        resp = await anon.get(f"/share/{token}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_public_share_data_json_scoped_to_own_run(qa_client, isolated_allure_dir, runnable_project_dir):
    run_a, _ = await _run_fixture_project(qa_client, "share_data_proj_a", runnable_project_dir)
    run_b, _ = await _run_fixture_project(qa_client, "share_data_proj_b", runnable_project_dir)
    token_a = (await qa_client.post(f"/api/runs/{run_a}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        resp = await anon.get(f"/share/{token_a}/data.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run"]["id"] == run_a
    assert data["run"]["project"] == "share_data_proj_a"
    assert data["run"]["id"] != run_b
    assert len(data["tests"]) == 5
    assert data["counts"]["passed"] == 3 and data["counts"]["failed"] == 2
    for test in data["tests"]:
        assert set(test.keys()) == {"name", "status", "duration", "message"}


async def test_public_share_data_json_truncates_long_messages(qa_client, isolated_allure_dir, tmp_path):
    from .conftest import _with_symlinked_venv

    proj = tmp_path / "long_message_proj"
    tests_dir = proj / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_long.py").write_text(
        "def test_fails_with_long_message():\n"
        "    assert False, 'x' * 3000\n"
    )
    _with_symlinked_venv(proj)
    run_id, _ = await _run_fixture_project(qa_client, "long_message_proj", proj, target="tests/test_long.py")
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        data = (await anon.get(f"/share/{token}/data.json")).json()
    assert len(data["tests"]) == 1
    assert len(data["tests"][0]["message"]) <= 1500


async def test_public_share_report_png_is_valid(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_png_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        resp = await anon.get(f"/share/{token}/report.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    _assert_valid_png(resp.content)


async def test_public_share_allure_without_cli_reports_unavailable(qa_client, isolated_allure_dir, runnable_project_dir, monkeypatch):
    from app.core import allure_report

    monkeypatch.setattr(allure_report, "allure_cli_available", lambda: False)
    run_id, _ = await _run_fixture_project(qa_client, "share_allure_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        data = (await anon.get(f"/share/{token}/data.json")).json()
        assert data["allure_available"] is False
        assert data["allure_url"] is None

        resp = await anon.get(f"/share/{token}/allure/index.html")
    assert resp.status_code == 404


async def test_public_share_unknown_token_is_404(db_path):
    async with _anon_client() as anon:
        assert (await anon.get("/share/does-not-exist")).status_code == 404
        assert (await anon.get("/share/does-not-exist/data.json")).status_code == 404
        assert (await anon.get("/share/does-not-exist/report.png")).status_code == 404


async def test_public_share_revoked_token_is_404(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_revoked_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]
    await qa_client.delete(f"/api/runs/{run_id}/share/{token}")

    async with _anon_client() as anon:
        assert (await anon.get(f"/share/{token}")).status_code == 404
        assert (await anon.get(f"/share/{token}/data.json")).status_code == 404


async def test_public_share_expired_token_is_404(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_expired_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "7d"})).json()["token"]

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE share_links SET expires_at = '2000-01-01T00:00:00' WHERE token = ?", (token,)
        )
        conn.commit()
    finally:
        conn.close()

    async with _anon_client() as anon:
        assert (await anon.get(f"/share/{token}")).status_code == 404
        assert (await anon.get(f"/share/{token}/data.json")).status_code == 404


def test_public_page_assets_are_root_relative(client_qa_and_run=None):
    """Страница /share/<token> лежит на вложенном пути — ссылки на css/js должны быть абсолютными,
    иначе браузер ищет /share/style.css и страница остаётся пустой."""
    from pathlib import Path
    html = Path(__file__).resolve().parents[1].joinpath("ui", "share.html").read_text(encoding="utf-8")
    assert 'href="/style.css"' in html and 'src="/share.js"' in html and 'src="/common.js"' in html
    assert 'href="style.css"' not in html and 'src="share.js"' not in html
