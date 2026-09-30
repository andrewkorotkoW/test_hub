"""Публичная ссылка на отчёт прогона (app/routers/share.py): создание/отзыв/список
ссылок (qa/manager), доступ по токену без логина, маскирование секретов в логе.

Гоняет реальный pytest на фикстурном проекте (см. tests/conftest.py::_FIXTURE_TESTS),
как tests/test_run_report.py и tests/test_report_png.py.
"""
import base64
import io
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import live, runner
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
        assert set(test.keys()) == {
            "name", "status", "duration", "message", "nodeid", "has_video", "video_duration_ms",
        }
    # прогон уже завершён (_run_fixture_project ждёт этого) — эфира быть не может.
    assert data["live_frame_url"] is None


# ------------------------------------------------------------------ эфир/видео без авторизации (контракт п.5)
async def _start_running_run(client, name, path):
    from app.core import runner

    await register_project(client, name, path)
    resp = await client.post(f"/api/projects/{name}/runs", json={"target": "tests/test_slow.py"})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["status"] == "running"
    run_id = run["id"]

    async def token_ready():
        return runner._run_tokens.get(run_id)

    token = await poll_until(token_ready, timeout=5)
    assert token, "раннер не выставил токен прогона (_run_tokens) вовремя"
    return run_id, token


async def _stop_run(client, run_id):
    await client.post(f"/api/runs/{run_id}/cancel")

    async def stopped():
        rows = (await client.get(f"/api/runs/{run_id}/report")).json()
        return rows if rows["status"] not in {"running", "queued"} else None

    await poll_until(stopped, timeout=5)


async def test_public_share_live_frame_url_only_while_running(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, _token = await _start_running_run(qa_client, "share_live_flag_proj", slow_project_dir)
    try:
        token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]
        async with _anon_client() as anon:
            running_data = (await anon.get(f"/share/{token}/data.json")).json()
        assert running_data["live_frame_url"] == f"/share/{token}/live.jpg"
    finally:
        await _stop_run(qa_client, run_id)

    async with _anon_client() as anon:
        finished_data = (await anon.get(f"/share/{token}/data.json")).json()
    assert finished_data["live_frame_url"] is None


async def test_public_share_live_jpg_serves_last_frame_without_auth(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    from app.core import live

    live.clear_all()
    run_id, run_token = await _start_running_run(qa_client, "share_live_proj", slow_project_dir)
    try:
        token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]
        jpeg = b"\xff\xd8\xff\xd9"
        upload = await qa_client.post(
            f"/api/runs/{run_id}/live",
            data={"nodeid": "tests/test_slow.py::test_hangs", "ts": "1.0", "step": "шаг"},
            files={"file": ("live.jpg", jpeg, "image/jpeg")},
            headers={"Authorization": f"Bearer {run_token}"},
        )
        assert upload.status_code == 204

        async with _anon_client() as anon:
            resp = await anon.get(f"/share/{token}/live.jpg")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == jpeg
    finally:
        await _stop_run(qa_client, run_id)
        live.clear_all()


async def test_public_share_live_jpg_404_for_unknown_or_revoked_token(qa_client, isolated_allure_dir):
    async with _anon_client() as anon:
        resp = await anon.get("/share/not-a-real-token/live.jpg")
    assert resp.status_code == 404


async def test_public_share_test_video_served_with_range_without_auth(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir
):
    run_id, run_token = await _start_running_run(qa_client, "share_video_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    webm = b"\x1aE\xdf\xa3" + b"\x00" * 32
    try:
        token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]
        upload = await qa_client.post(
            f"/api/runs/{run_id}/tests/{nodeid}/video",
            data={"duration_ms": "1500"},
            files={"file": ("test.webm", webm, "video/webm")},
            headers={"Authorization": f"Bearer {run_token}"},
        )
        assert upload.status_code == 201, upload.text

        async with _anon_client() as anon:
            full = await anon.get(f"/share/{token}/tests/{nodeid}/video")
            ranged = await anon.get(f"/share/{token}/tests/{nodeid}/video", headers={"Range": "bytes=0-3"})
        assert full.status_code == 200
        assert full.content == webm
        assert ranged.status_code == 206
        assert ranged.content == webm[0:4]
    finally:
        await _stop_run(qa_client, run_id)


async def test_public_share_test_video_404_when_not_uploaded(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_video_missing_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]
    async with _anon_client() as anon:
        resp = await anon.get(f"/share/{token}/tests/tests/test_sample.py::test_ok/video")
    assert resp.status_code == 404


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

    monkeypatch.setattr(allure_report, "resolve_allure_bin", lambda: None)
    run_id, _ = await _run_fixture_project(qa_client, "share_allure_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        data = (await anon.get(f"/share/{token}/data.json")).json()
        assert data["allure_available"] is False
        assert data["allure_url"] is None

        # не 404 — понятная страница-заглушка вместо "битой" ссылки (см. TH_ALLURE_BIN)
        resp = await anon.get(f"/share/{token}/allure/index.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "TH_ALLURE_BIN" in resp.text


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


# ------------------------------------------------------------------ share без авторизации: видео и живой кадр
# (контракт п.5, docs/missions/2026-10-01_live_stream.md — "Share-страница показывает
# видео и последний живой кадр так же, как основное окно, без авторизации").
_JPEG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_WEBM_BYTES = b"\x1aE\xdf\xa3" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _clear_live_state_for_share_tests():
    """Как tests/test_run_live.py::_clear_live_state — модульное состояние
    app/core/live.py не привязано к db_path/tmp_path конкретного теста."""
    live.clear_all()
    yield
    live.clear_all()


async def _start_running_run_for_share(client, name, path):
    await register_project(client, name, path)
    resp = await client.post(f"/api/projects/{name}/runs", json={"target": "tests/test_slow.py"})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["status"] == "running"
    run_id = run["id"]

    async def token_ready():
        return runner._run_tokens.get(run_id)

    token = await poll_until(token_ready, timeout=5)
    assert token, "раннер не выставил токен прогона (_run_tokens) вовремя"
    return run_id, token


async def _stop_run_for_share(client, run_id):
    await client.post(f"/api/runs/{run_id}/cancel")

    async def stopped():
        rows = (await client.get(f"/api/runs/{run_id}/report")).json()
        return rows if rows["status"] not in {"running", "queued"} else None

    await poll_until(stopped, timeout=5)


def _api_video_url(run_id, nodeid):
    return f"/api/runs/{run_id}/tests/{quote(nodeid, safe='')}/video"


def _share_video_url(token, nodeid):
    return f"/share/{token}/tests/{quote(nodeid, safe='')}/video"


async def test_public_share_live_jpg_without_session(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token_ = await _start_running_run_for_share(qa_client, "share_live_proj", slow_project_dir)
    try:
        upload = await qa_client.post(
            f"/api/runs/{run_id}/live",
            data={"nodeid": "tests/test_slow.py::test_hangs", "ts": "1.0", "step": "шаг"},
            files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
            headers={"Authorization": f"Bearer {token_}"},
        )
        assert upload.status_code == 204

        share_token = (
            await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})
        ).json()["token"]

        async with _anon_client() as anon:
            resp = await anon.get(f"/share/{share_token}/live.jpg")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == _JPEG_BYTES
    finally:
        await _stop_run_for_share(qa_client, run_id)


async def test_public_share_live_jpg_404_without_frame(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_live_404_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        resp = await anon.get(f"/share/{token}/live.jpg")
    assert resp.status_code == 404


async def test_public_share_live_jpg_unknown_or_revoked_token_is_404(
    qa_client, isolated_allure_dir, isolated_frames_dir, slow_project_dir
):
    run_id, token_ = await _start_running_run_for_share(qa_client, "share_live_bad_token_proj", slow_project_dir)
    try:
        await qa_client.post(
            f"/api/runs/{run_id}/live",
            data={"nodeid": "tests/test_slow.py::test_hangs", "ts": "1.0", "step": ""},
            files={"file": ("live.jpg", _JPEG_BYTES, "image/jpeg")},
            headers={"Authorization": f"Bearer {token_}"},
        )
        created = await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})
        share_token = created.json()["token"]
        await qa_client.delete(f"/api/runs/{run_id}/share/{share_token}")

        async with _anon_client() as anon:
            assert (await anon.get("/share/not-a-real-token/live.jpg")).status_code == 404
            # отозванный токен — доступ к живому кадру пропадает вместе с остальным
            assert (await anon.get(f"/share/{share_token}/live.jpg")).status_code == 404
    finally:
        await _stop_run_for_share(qa_client, run_id)


async def test_public_share_video_without_session(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir
):
    run_id, token_ = await _start_running_run_for_share(qa_client, "share_video_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        upload = await qa_client.post(
            _api_video_url(run_id, nodeid),
            data={"duration_ms": "2500"},
            files={"file": ("test.webm", _WEBM_BYTES, "video/webm")},
            headers={"Authorization": f"Bearer {token_}"},
        )
        assert upload.status_code == 201, upload.text

        share_token = (
            await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})
        ).json()["token"]

        async with _anon_client() as anon:
            full = await anon.get(_share_video_url(share_token, nodeid))
            assert full.status_code == 200
            assert full.headers["content-type"] == "video/webm"
            assert full.content == _WEBM_BYTES

            ranged = await anon.get(
                _share_video_url(share_token, nodeid), headers={"Range": "bytes=2-5"}
            )
            assert ranged.status_code == 206
            assert ranged.content == _WEBM_BYTES[2:6]
            assert ranged.headers["content-range"] == f"bytes 2-5/{len(_WEBM_BYTES)}"
    finally:
        await _stop_run_for_share(qa_client, run_id)


async def test_public_share_video_404_when_not_uploaded(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "share_video_404_proj", runnable_project_dir)
    token = (await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})).json()["token"]

    async with _anon_client() as anon:
        resp = await anon.get(_share_video_url(token, "tests/test_sample.py::test_ok"))
    assert resp.status_code == 404


async def test_public_share_video_unknown_or_revoked_token_is_404(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir
):
    run_id, token_ = await _start_running_run_for_share(qa_client, "share_video_bad_token_proj", slow_project_dir)
    nodeid = "tests/test_slow.py::test_hangs"
    try:
        await qa_client.post(
            _api_video_url(run_id, nodeid),
            data={"duration_ms": "1000"},
            files={"file": ("test.webm", _WEBM_BYTES, "video/webm")},
            headers={"Authorization": f"Bearer {token_}"},
        )
        created = await qa_client.post(f"/api/runs/{run_id}/share", json={"expires": "30d"})
        share_token = created.json()["token"]
        await qa_client.delete(f"/api/runs/{run_id}/share/{share_token}")

        async with _anon_client() as anon:
            assert (await anon.get(_share_video_url("not-a-real-token", nodeid))).status_code == 404
            assert (await anon.get(_share_video_url(share_token, nodeid))).status_code == 404
    finally:
        await _stop_run_for_share(qa_client, run_id)


async def test_public_share_video_scoped_to_own_run(
    qa_client, isolated_allure_dir, isolated_frames_dir, isolated_video_dir, slow_project_dir
):
    """Share-ссылка прогона A не должна отдавать видео теста, загруженное только
    в прогон B, даже если nodeid у обоих совпадает (тот же сценарий изоляции,
    что и test_public_share_data_json_scoped_to_own_run выше, — запрос ищет
    запись по run_test_videos.run_id из самой ссылки, не по nodeid глобально)."""
    nodeid = "tests/test_slow.py::test_hangs"
    run_a, token_a = await _start_running_run_for_share(qa_client, "share_video_scope_a", slow_project_dir)
    try:
        share_token = (
            await qa_client.post(f"/api/runs/{run_a}/share", json={"expires": "30d"})
        ).json()["token"]
    finally:
        await _stop_run_for_share(qa_client, run_a)

    run_b, token_b = await _start_running_run_for_share(qa_client, "share_video_scope_b", slow_project_dir)
    try:
        upload_b = await qa_client.post(
            _api_video_url(run_b, nodeid),
            data={"duration_ms": "1000"},
            files={"file": ("b.webm", _WEBM_BYTES, "video/webm")},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert upload_b.status_code == 201

        # прогон A не грузил видео для этого nodeid — share-ссылка прогона A
        # не должна найти запись, принадлежащую прогону B.
        async with _anon_client() as anon:
            resp = await anon.get(_share_video_url(share_token, nodeid))
        assert resp.status_code == 404
    finally:
        await _stop_run_for_share(qa_client, run_b)
