"""GET /api/runs/{id}/report.png и /api/runs/{id}/trend.png (app/routers/runs.py).

Гоняет реальный pytest на фикстурном проекте (см. tests/conftest.py::_FIXTURE_TESTS),
как tests/test_run_report.py, и проверяет, что оба PNG-эндпоинта отдают валидный PNG
(сигнатура + PIL.verify, как в tests/test_charts.py), а также их поведение на
несуществующем run_id и без аутентификации.
"""

from .conftest import poll_until, register_project

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:  # pragma: no cover - PIL уже есть в зависимостях (matplotlib)
    HAS_PIL = False


def _assert_valid_png(data: bytes) -> None:
    assert isinstance(data, bytes)
    assert len(data) > 0
    assert data.startswith(PNG_SIGNATURE)
    if HAS_PIL:
        import io

        img = Image.open(io.BytesIO(data))
        img.verify()


def _find(rows, run_id):
    return next(r for r in rows if r["id"] == run_id)


async def _run_fixture_project(qa_client, project_name, project_dir):
    await register_project(qa_client, project_name, project_dir)
    create_resp = await qa_client.post(
        f"/api/projects/{project_name}/runs", json={"target": "tests/test_sample.py"}
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    async def finished():
        rows = (await qa_client.get(f"/api/projects/{project_name}/runs")).json()
        row = _find(rows, run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=15)
    assert final is not None, "прогон не завершился вовремя"
    return run_id, final


async def test_report_png_returns_valid_png(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "report_png_proj", runnable_project_dir)

    resp = await qa_client.get(f"/api/runs/{run_id}/report.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    _assert_valid_png(resp.content)


async def test_trend_png_returns_valid_png(qa_client, isolated_allure_dir, runnable_project_dir):
    run_id, _ = await _run_fixture_project(qa_client, "trend_png_proj", runnable_project_dir)

    resp = await qa_client.get(f"/api/runs/{run_id}/trend.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    _assert_valid_png(resp.content)


async def test_report_png_unknown_run_id_is_404(qa_client):
    resp = await qa_client.get("/api/runs/999999/report.png")
    assert resp.status_code == 404


async def test_trend_png_unknown_run_id_is_404(qa_client):
    resp = await qa_client.get("/api/runs/999999/trend.png")
    assert resp.status_code == 404


# get_current_user (см. tests/test_auth.py::test_protected_endpoint_without_cookie_is_401)
# без сессии отвечает 401 — report.png/trend.png используют тот же Depends(get_current_user).
async def test_report_png_without_cookie_is_401(client):
    resp = await client.get("/api/runs/1/report.png")
    assert resp.status_code == 401


async def test_trend_png_without_cookie_is_401(client):
    resp = await client.get("/api/runs/1/trend.png")
    assert resp.status_code == 401
