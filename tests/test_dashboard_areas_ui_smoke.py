"""Смоук-тесты блока «Тесты по областям» на дашборде проекта (ui/project.html/js,
docs/missions/2026-10-02_dashboard_areas_traffic.md, этапы 2-3). Чистая логика разбора
имени/классификации/группировки уже покрыта юнит-тестами на node
(tests/js/test_dashboard_areas_logic.js + tests/test_dashboard_areas_logic_js.py) — здесь
только то, что физически завязано на разметку/подключение скриптов/CSS и не выделено в
отдельную функцию. По образцу tests/test_coverage_traffic_ui_smoke.py и
tests/test_redesign_ui_smoke.py: без браузера, через FastAPI StaticFiles + TestClient —
раздача статики и текст исходников.
"""

import pathlib
import re

import pytest

UI_DIR = pathlib.Path(__file__).resolve().parent.parent / "ui"


async def test_project_html_has_area_traffic_columns_block(client):
    resp = await client.get("/project.html")
    assert resp.status_code == 200
    html = resp.text
    # контейнер колонок и сами три колонки — реальные id из ui/project.html после правок
    # michael (коммит 9b71055), не старые area-rings-row/area-rings-box-одно-кольцо.
    assert 'id="area-traffic-columns"' in html
    assert 'id="area-traffic-col-ok"' in html
    assert 'id="area-traffic-col-problems"' in html
    assert 'id="area-traffic-col-empty"' in html
    assert 'id="area-traffic-count-ok"' in html
    assert 'id="area-traffic-count-problems"' in html
    assert 'id="area-traffic-count-empty"' in html
    # порядок трёх колонок — «Покрыто и проходит», «Есть проблемы», «Не покрыто»
    positions = [
        html.index(f'id="{i}"')
        for i in ("area-traffic-col-ok", "area-traffic-col-problems", "area-traffic-col-empty")
    ]
    assert positions == sorted(positions)
    assert "Покрыто и проходит" in html
    assert "Есть проблемы" in html
    assert "Не покрыто" in html


async def test_project_html_area_traffic_ids_present_exactly_once(client):
    resp = await client.get("/project.html")
    html = resp.text
    ids = [
        "area-traffic-columns",
        "area-traffic-col-ok",
        "area-traffic-col-problems",
        "area-traffic-col-empty",
        "area-traffic-count-ok",
        "area-traffic-count-problems",
        "area-traffic-count-empty",
    ]
    for i in ids:
        assert html.count(f'id="{i}"') == 1, f"id={i} должен встречаться ровно один раз"


async def test_project_html_serves_dashboard_areas_logic_script_in_right_order(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'src="dashboard-areas-logic.js"' in html
    # dashboard-areas-logic.js подключён после build-page-logic.js (но до run-live-logic.js/
    # project.js — порядок остальных *-logic.js не важен для этого модуля, он самодостаточен)
    order = ["build-page-logic.js", "dashboard-areas-logic.js", "project.js"]
    positions = [html.index(f'src="{name}"') for name in order]
    assert positions == sorted(positions)

    resp2 = await client.get("/dashboard-areas-logic.js")
    assert resp2.status_code == 200
    assert "DashboardAreasLogic" in resp2.text


def test_project_html_old_single_ring_markup_removed():
    """Старую разметку одинокого кольца tests/api (area-rings-row/chart-rings-row) заменили
    на три колонки — проверяем, что она не осталась рядом с новой (дубликат/мёртвая разметка)."""
    html = (UI_DIR / "project.html").read_text()
    assert 'id="area-rings-row"' not in html
    assert 'class="chart-rings-row"' not in html


def test_project_js_renders_area_traffic_columns_inside_render_dashboard():
    js = (UI_DIR / "project.js").read_text()
    assert "renderAreaRings" not in js
    assert "areaKindFromFullName" not in js
    assert "function renderAreaTrafficColumns(tests)" in js

    match = re.search(r"async function renderDashboard\([^)]*\)\s*\{(.*?)\n  \}", js, re.DOTALL)
    assert match, "не найдена функция renderDashboard() в ui/project.js"
    assert "renderAreaTrafficColumns(latestTests)" in match.group(1)


def test_project_js_uses_dashboard_areas_logic_for_sections_and_grouping():
    """Подстраховка от регрессии: рендер колонок действительно вызывает
    buildAreaSections/groupSections/classifySection/sectionHref из
    dashboard-areas-logic.js, а не дублирует логику в самом project.js."""
    js = (UI_DIR / "project.js").read_text()
    for call in (
        "DashboardAreasLogic.buildAreaSections(tests)",
        "DashboardAreasLogic.groupSections(sections)",
        "DashboardAreasLogic.classifySection(section)",
        "DashboardAreasLogic.sectionHref(projectName, section)",
    ):
        assert call in js, f"не найден вызов: {call}"


def test_project_js_area_row_click_builds_href_only_for_non_empty_sections():
    js = (UI_DIR / "project.js").read_text()
    assert 'data-href="${escapeHtml(href)}"' in js
    # closest(".area-row[data-href]") — строка без data-href (некликабельная "Сквозные
    # сценарии") не матчится селектором и клик по ней не сработает
    assert '.area-row[data-href]' in js


def test_style_css_has_no_duplicate_traffic_or_area_row_class_definitions():
    """ui/style.css: .traffic-columns/.traffic-column/.traffic-card переиспользуются со
    страницы «Покрытие» — не должны обзавестись вторым (дублирующим) определением ради
    этого блока, а новый класс .area-row должен остаться единственным (не копией
    .traffic-card под другим именем)."""
    css = (UI_DIR / "style.css").read_text()
    # .traffic-column сам по себе как отдельное правило не определён (только составные
    # селекторы вроде .traffic-column h3) — это не ошибка, а не повод для второй копии.
    for cls in (".traffic-columns", ".traffic-column-body", ".traffic-card"):
        # правило начинается с начала строки (не с отступом) — так отличаем базовое
        # определение от намеренного responsive-переопределения внутри @media (оно в этом
        # файле всегда с отступом), а не от упоминания в комментарии/составном селекторе
        # вроде .traffic-column h3 (там после имени класса нет сразу "{")
        pattern = r"(?m)^" + re.escape(cls) + r"\s*\{"
        count = len(re.findall(pattern, css))
        assert count == 1, f"{cls} должен определяться ровно один раз в ui/style.css, найдено {count}"

    area_row_pattern = r"(?m)^" + re.escape(".area-row") + r"\s*\{"
    assert len(re.findall(area_row_pattern, css)) == 1
