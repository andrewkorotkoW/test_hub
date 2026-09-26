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

from app.schemas import PROJECT_COLOR_PALETTE

from .conftest import register_project

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


async def test_project_html_dashboard_charts_order_matches_references(client):
    """REFERENCES.md, «Итог: обязательный состав дашборда проекта…», п.2-3: сначала
    пара донат+столбцы passed/failed, затем пара площадной график+кольца по областям —
    проверяем порядок id в разметке (сами графики отрисовывает project.js)."""
    resp = await client.get("/project.html")
    html = resp.text
    ids = ["status-donut-box", "passfail-bar-box", "duration-area-box", "area-rings-box"]
    positions = [html.index(f'id="{i}"') for i in ids]
    assert positions == sorted(positions), f"порядок блоков дашборда нарушен: {ids}"


async def test_project_js_renders_runs_feed_progress_bar(client):
    """REFERENCES.md, п.4: «лента прогонов (спарклайн в строке…)» — сегментный бар
    passed/failed/skipped на основе тех же counts, что и donut/KPI (runMetrics())."""
    resp = await client.get("/project.js")
    js = resp.text
    assert "runs-feed-bar" in js
    assert "runMetrics(r)" in js


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


async def test_project_html_chart_and_list_ids_present_exactly_once(client):
    """ui/project.js (renderDashboard()) адресуется к этим id напрямую через
    getElementById — после перестройки project.html (t2) они должны остаться в
    разметке ровно по одному разу, иначе JS молча возьмёт не тот узел/упадёт."""
    resp = await client.get("/project.html")
    html = resp.text
    ids = [
        "status-donut-chart",
        "status-donut-center",
        "area-rings-row",
        "passfail-bar-chart",
        "duration-area-chart",
        "longest-tests-list",
        "runs-feed",
        "kpi-row",
    ]
    for i in ids:
        assert html.count(f'id="{i}"') == 1, f"id={i} должен встречаться ровно один раз"


async def test_project_html_has_project_color_picker(client):
    """ui/project.js рендерит палитру цвета проекта (renderColorPicker(), common.js)
    в этот контейнер — см. app/schemas.py::PROJECT_COLOR_PALETTE."""
    resp = await client.get("/project.html")
    html = resp.text
    assert html.count('id="project-color-picker"') == 1


# ---------------------------------------------------- дефолт светлой темы без вспышки

@pytest.mark.parametrize("page", ["index.html", "projects.html", "project.html"])
async def test_common_js_script_tag_is_in_head_not_at_end_of_body(client, page):
    """common.js выставляет data-theme на <html> синхронно при загрузке (до отрисовки
    body) — если <script src="common.js"> уедет в конец <body>, страница на секунду
    отрендерится с браузерной тёмной темой по умолчанию, а потом мигнёт в light."""
    resp = await client.get(f"/{page}")
    html = resp.text

    head_match = re.search(r"<head[^>]*>(.*?)</head>", html, re.DOTALL | re.IGNORECASE)
    assert head_match, f"{page}: не найден <head>"
    assert 'src="common.js"' in head_match.group(1), (
        f"{page}: <script src=\"common.js\"> должен быть в <head>, иначе возможна вспышка тёмного фона"
    )

    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    assert body_match
    assert 'src="common.js"' not in body_match.group(1), (
        f"{page}: <script src=\"common.js\"> не должен дублироваться/переезжать в конец <body>"
    )


def test_detect_preferred_theme_defaults_to_light_without_saved_or_system_preference():
    """Прямой запуск ui/common.js через node невозможен в этом окружении (node 12.13.0,
    файл использует `??` (ES2020) и выполняет document.*/localStorage.* на верхнем
    уровне модуля без DOM-шима — см. память testhub-redesign-ui-smoke-tests) — поэтому
    проверяем через исходник, как test_project_js_hides_run_buttons_row_for_customer_role
    выше: detectPreferredTheme() при отсутствии localStorage-значения и без совпадения
    ни с одним prefers-color-scheme должна фолбэчиться на "light", а не на "dark"."""
    import pathlib

    common_js = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "common.js").read_text()

    match = re.search(r"function detectPreferredTheme\(\)\s*\{(.*?)\n\}", common_js, re.DOTALL)
    assert match, "не найдена функция detectPreferredTheme() в ui/common.js"
    body = match.group(1)

    # последний return в функции — это фолбэк, когда ни сохранённое значение, ни
    # prefers-color-scheme не сработали (все предыдущие return срабатывают раньше).
    returns = re.findall(r'return\s+"(light|dark)"', body)
    assert returns, "detectPreferredTheme() не возвращает строковый литерал темы"
    assert returns[-1] == "light", (
        "последний return в detectPreferredTheme() должен быть \"light\" (дефолт светлой темы),"
        f" а не {returns[-1]!r}"
    )


def test_common_js_color_palette_matches_backend_palette():
    """ui/common.js держит свою копию PROJECT_COLOR_PALETTE (для renderColorPicker()
    без похода на бэкенд) — она должна дословно совпадать с app/schemas.py, иначе
    клик по цвету из UI будет отклонён бэкендом как значение вне палитры (422)."""
    import pathlib

    common_js = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "common.js").read_text()

    match = re.search(r"const PROJECT_COLOR_PALETTE\s*=\s*\[(.*?)\];", common_js, re.DOTALL)
    assert match, "не найдена PROJECT_COLOR_PALETTE в ui/common.js"
    js_colors = re.findall(r'"(#[0-9a-fA-F]{3,8})"', match.group(1))
    assert js_colors == list(PROJECT_COLOR_PALETTE)


async def test_project_html_run_buttons_row_has_no_static_hidden_attribute():
    """Дополняет предыдущий тест: в самой разметке #run-buttons-row не спрятан статично —
    иначе роли qa/manager (которым кнопки нужны) тоже остались бы без них."""
    import pathlib

    project_html = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "project.html").read_text()
    m = re.search(r'<div class="run-buttons" id="run-buttons-row">', project_html)
    assert m, "не найден #run-buttons-row в ui/project.html"
    # сам открывающий тег #run-buttons-row не должен нести статичный hidden
    assert "hidden" not in m.group(0)


# ------------------------------------------------- manual_only-стенд (stage): блок пресетов + модалка подтверждения
async def test_project_html_has_manual_run_block_and_confirm_modal(client):
    """ui/project.js::updateRunControlsForStand/openManualRunModal адресуются к этим id
    напрямую (см. app/tg_bot.py-аналог confirm_manual, но здесь — веб-версия того же
    UX). Полноценный клик/чекбокс/модалка проверяются только вручную в браузере — тут
    только то, что серверная разметка отдаёт нужные крючки для JS."""
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="manual-run-block" class="manual-run-block" hidden' in html
    assert 'id="manual-run-stand-name"' in html
    assert 'id="manual-run-presets"' in html
    assert 'id="manual-run-selected-btn"' in html
    assert 'id="manual-run-modal-overlay" class="modal-overlay" hidden' in html
    assert 'id="manual-run-modal-text"' in html
    assert 'id="manual-run-confirm-checkbox"' in html
    assert 'id="manual-run-cancel-btn"' in html
    assert 'id="manual-run-confirm-btn" class="primary" disabled' in html


async def test_project_js_confirm_click_posts_confirm_manual_true_to_runs_endpoint(client):
    """Замок соответствия между кнопкой «Запустить» модалки и телом POST /runs — если
    confirm_manual потеряется при рефакторинге project.js, этот тест это поймает
    раньше проверки в браузере (по образцу test_coverage_js_calls_all_five_router_endpoints)."""
    resp = await client.get("/project.js")
    js = resp.text
    assert re.search(r"/api/projects/\$\{[^}]*\}/runs`", js)
    assert re.search(r"confirm_manual:\s*true", js)


async def test_manual_run_confirm_flow_reaches_page_and_proxies_confirm_manual_to_post_runs(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    """Бэкенд-интеграционная проверка того же пути, которым идёт кнопка «Запустить»
    модалки ui/project.js (POST .../runs с confirm_manual: true) — через реальный
    FastAPI TestClient (ASGITransport), без браузера. Само поведение чекбокса/модалки
    (клиентский JS) этим не покрывается и проверялось только вручную — юнит-тестов на
    чистый DOM/события в этом репозитории нет (см. tests/test_coverage_tree_logic_js.py
    и др.: только там, где логика вынесена в чистый JS-модуль без DOM)."""
    await register_project(qa_client, "manual_ui_proj", runnable_project_dir)
    stand_resp = await qa_client.post(
        "/api/projects/manual_ui_proj/stands", json={"name": "stage", "url": ""}
    )
    assert stand_resp.status_code == 201, stand_resp.text
    stand = stand_resp.json()
    patch_resp = await qa_client.patch(
        f"/api/projects/manual_ui_proj/stands/{stand['id']}", json={"manual_only": True}
    )
    assert patch_resp.status_code == 200, patch_resp.text

    page = await qa_client.get("/project.html?name=manual_ui_proj")
    assert page.status_code == 200

    stands = (await qa_client.get("/api/projects/manual_ui_proj/stands")).json()
    assert next(s for s in stands if s["name"] == "stage")["manual_only"] is True

    # То же тело, что собирает manualRunConfirmBtn.addEventListener в project.js.
    resp = await qa_client.post(
        "/api/projects/manual_ui_proj/runs",
        json={"stand": "stage", "target": "tests/test_sample.py", "marker": None, "confirm_manual": True},
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["stand"] == "stage"
    assert run["target"] == "tests/test_sample.py"
