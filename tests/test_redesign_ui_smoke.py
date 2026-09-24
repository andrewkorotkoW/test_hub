"""Смоук-тесты редизайна дашбордов (ui/common.js — токены темы+shell, ui/project.html/js —
дашборд проекта, ui/coverage.html/ui/xfail.html/ui/share.html — новый стиль+мобильная
адаптация). По образцу tests/test_coverage_ui_routing.py: без браузера, только то, что
проверяемо через FastAPI StaticFiles + TestClient — раздача статики, наличие ключевых
id/классов новой разметки в HTML и (там, где поведение зависит от роли и решается в JS,
а не на сервере) наличие соответствующей логики в исходнике *.js. Полноценный рендер и
переключение темы в браузере здесь не проверяются.
"""

import re

import pytest


# Страницы с общим shell (сайдбар + хедер), собранным renderHeader()/renderSidebar() из
# common.js в id="app-header"/id="app-sidebar". share.html сознательно вне этого списка —
# у неё свой статичный header без сайдбара (публичный read-only отчёт, см. ui/share.html).
SHELL_PAGES = ["projects.html", "project.html", "coverage.html", "xfail.html"]


@pytest.mark.parametrize("page", SHELL_PAGES)
async def test_shell_pages_served_with_valid_html_and_app_header(client, page):
    resp = await client.get(f"/{page}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert html.strip().lower().startswith("<!doctype html>")
    assert "<html" in html and "</html>" in html
    assert "<body" in html and "</body>" in html
    assert 'id="app-header"' in html
    assert 'id="app-sidebar"' in html
    assert 'class="app-shell"' in html
    # renderHeader()/renderSidebar() (common.js) заполняют #app-header/#app-sidebar через
    # JS при загрузке страницы — без выполнения JS они пустые в статически отданном HTML.
    assert '<header id="app-header" class="site-header"></header>' in html
    assert '<aside id="app-sidebar" class="app-sidebar"></aside>' in html
    assert 'src="common.js"' in html


async def test_projects_html_has_grid_and_add_project_block(client):
    resp = await client.get("/projects.html")
    html = resp.text
    assert 'id="projects-grid" class="project-grid"' in html
    assert 'id="add-project-btn"' in html


async def test_project_html_has_kpi_row_and_dashboard_charts(client):
    resp = await client.get("/project.html")
    html = resp.text
    # KPI-карточки: контейнер статичен, сами .kpi-tile рендерятся project.js из ответа
    # API (kpiTileHtml()) — без выполнения JS в разметке будет только заглушка загрузки.
    assert 'id="kpi-row"' in html
    assert 'class="kpi-row"' in html
    assert 'id="dashboard-charts-card"' in html
    assert 'id="status-donut-box"' in html
    assert 'id="area-rings-box"' in html
    assert 'id="passfail-bar-box"' in html
    assert 'id="duration-area-box"' in html
    assert 'id="tests-tree"' in html
    assert 'id="run-buttons-row"' in html


async def test_coverage_html_has_areas_and_tree_blocks(client):
    resp = await client.get("/coverage.html")
    html = resp.text
    assert 'id="summary-card"' in html
    assert 'id="chart-treemap-box"' in html
    assert 'id="chart-areas-table-box"' in html
    assert 'id="areas-table"' in html
    assert 'id="chart-tree-box"' in html
    # сворачиваемые секции: треугольники-переключатели (▾/▸), не гамбургер-меню сайдбара
    assert 'id="charts-toggle-btn"' in html and "▾" in html
    assert 'id="tree-toggle-btn"' in html and "▸" in html


async def test_xfail_html_has_toolbar_and_table(client):
    resp = await client.get("/xfail.html")
    html = resp.text
    assert 'id="xfail-toolbar-card"' in html
    assert 'id="xfail-stand-select"' in html
    assert 'id="xfail-check-all-btn"' in html
    assert 'id="xfail-rows"' in html


async def test_share_html_served_without_sidebar_shell(client):
    """share.html — публичный read-only отчёт без логина, поэтому намеренно без
    сайдбара/меню (нечего скрывать по ролям — там нет ролей вообще)."""
    resp = await client.get("/share.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert html.strip().lower().startswith("<!doctype html>")
    assert "<html" in html and "</html>" in html
    assert "<body" in html and "</body>" in html
    assert 'id="app-header"' not in html
    assert 'id="app-sidebar"' not in html
    assert 'class="site-header"' in html
    assert 'id="run-card"' in html
    assert 'id="report-rows"' in html
    assert 'src="/common.js"' in html


async def test_unknown_redesigned_page_returns_404(client):
    resp = await client.get("/project-does-not-exist.html")
    assert resp.status_code == 404


# ---------------------------------------------------------------- сайдбар/тема — common.js

async def test_common_js_wires_sidebar_nav_and_theme_toggle(client):
    """Пункты меню сайдбара и переключатель темы собираются в JS (renderSidebar()) и не
    попадают в статичный HTML — проверяем наличие самой логики в раздаваемом common.js:
    ключ localStorage, атрибут data-theme, id кнопки-переключателя и пункты меню."""
    resp = await client.get("/common.js")
    assert resp.status_code == 200
    js = resp.text
    assert 'THEME_STORAGE_KEY = "testhub-theme"' in js
    assert "data-theme" in js
    assert 'id="theme-toggle-btn"' in js
    assert 'id="app-burger-btn"' in js
    for label in ("Проекты", "Покрытие", "Xfail", "Расписания"):
        assert label in js


# ------------------------------------------------- роль customer на project.html: кнопки запуска

async def test_project_js_hides_run_buttons_row_for_customer_role():
    """project.html не рендерится сервером под конкретную роль — кнопки запуска везде
    присутствуют в статичной разметке (#run-buttons-row без hidden, см. ui/project.html).
    Их скрытие для customer — чисто клиентская логика в project.js (см. ui/project.js:61):
    `if (user.role === "customer") { ...#run-buttons-row.hidden = true; }`. Без выполнения
    JS проверяем именно наличие этой логики в исходнике, а не финальный рендер."""
    import pathlib

    project_js = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "project.js").read_text()

    match = re.search(
        r'if\s*\(\s*user\.role\s*===\s*"customer"\s*\)\s*\{([^}]*)\}',
        project_js,
    )
    assert match, "не найдена ветка `user.role === \"customer\"` в ui/project.js"
    assert 'getElementById("run-buttons-row")' in match.group(1)
    assert ".hidden = true" in match.group(1)


async def test_project_html_run_buttons_row_has_no_static_hidden_attribute():
    """Дополняет предыдущий тест: в самой разметке #run-buttons-row не спрятан статично —
    иначе роли qa/manager (которым кнопки нужны) тоже остались бы без них."""
    import pathlib

    project_html = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "project.html").read_text()
    m = re.search(r'<div class="run-buttons" id="run-buttons-row">', project_html)
    assert m, "не найден #run-buttons-row в ui/project.html"
    # сам открывающий тег #run-buttons-row не должен нести статичный hidden
    assert "hidden" not in m.group(0)
