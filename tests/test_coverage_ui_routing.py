"""Страница «Покрытие» (ui/coverage.html, ui/coverage.js) — часть, проверяемая без
браузера: FastAPI-раздача статики (app/main.py монтирует ui/ через StaticFiles на "/")
и то, что вызываемые страницей API-ручки (5 штук в app/routers/coverage.py) реально
существуют и отвечают в паре с ней. Полноценное поведение JS (fetch/рендер таблицы)
покрывается только в браузере и здесь не тестируется.
"""

import re

import pytest

from app.core import coverage

from .conftest import register_project


@pytest.fixture()
def isolated_coverage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "COVERAGE_DIR", tmp_path / "coverage")


async def test_coverage_html_served(client):
    resp = await client.get("/coverage.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert 'id="summary-card"' in resp.text
    assert 'id="cov-stand-select"' in resp.text


async def test_coverage_js_served(client):
    resp = await client.get("/coverage.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


async def test_coverage_js_calls_all_five_router_endpoints(client):
    """Замок соответствия между ui/coverage.js и app/routers/coverage.py: если один
    из 5 путей роутера переименуют без обновления фронта, этот тест это поймает
    раньше браузерного прогона."""
    resp = await client.get("/coverage.js")
    js = resp.text
    for pattern in (
        r"/api/projects/\$\{[^}]*\}/coverage`",
        r"/api/projects/\$\{[^}]*\}/coverage/recalc`",
        r"/api/projects/\$\{[^}]*\}/coverage/routes`",
        r"/api/projects/\$\{[^}]*\}/coverage/route\?",
        r"/api/projects/\$\{[^}]*\}/coverage/test\?",
    ):
        assert re.search(pattern, js), f"не найден вызов, соответствующий {pattern!r}"


async def test_coverage_html_reachable_for_registered_project(qa_client, isolated_coverage_dir, tmp_path):
    """Смоук самого роутинга целиком: страница отдаётся, а API, которое она дёргает
    для конкретного зарегистрированного проекта, действительно отвечает 200."""
    project_dir = tmp_path / "ui_routing_proj"
    (project_dir / "tests").mkdir(parents=True)
    (project_dir / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    await register_project(qa_client, "ui_routing_proj", project_dir)

    page = await qa_client.get("/coverage.html?name=ui_routing_proj")
    assert page.status_code == 200

    summary = await qa_client.get("/api/projects/ui_routing_proj/coverage")
    assert summary.status_code == 200
    assert summary.json()["project"] == "ui_routing_proj"


async def test_unknown_static_page_returns_404(client):
    resp = await client.get("/coverage-does-not-exist.html")
    assert resp.status_code == 404
