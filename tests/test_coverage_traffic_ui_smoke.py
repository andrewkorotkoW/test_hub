"""Смоук-тесты вида «Светофор» на странице покрытия (ui/coverage.html/js,
docs/missions/2026-10-01_coverage_k_and_test_sets.md, этап 1). Чистая логика
группировки/раскладки/KPI уже покрыта юнит-тестами на node (см.
tests/test_coverage_traffic_logic_js.py) — здесь только то, что физически
завязано на DOM/localStorage и не выделено в отдельную функцию: разметка
переключателя «Светофор | Схема», наличие обеих колонок/карточек в статичном
HTML, факт сохранения/чтения выбора вида из localStorage в исходнике
coverage.js, и что схема продукта (v5) не удалена вместе со своими id/JS-
функциями. По образцу tests/test_redesign_ui_smoke.py: без браузера, через
FastAPI StaticFiles + TestClient — раздача статики и текст исходников."""

import pathlib

import pytest

UI_DIR = pathlib.Path(__file__).resolve().parent.parent / "ui"


async def test_coverage_html_has_view_toggle_and_both_bodies(client):
    resp = await client.get("/coverage.html")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="view-toggle"' in html
    assert 'id="view-toggle-traffic"' in html
    assert 'id="view-toggle-scheme"' in html
    # обе разметки уже в статичном HTML (JS только переключает hidden), поэтому
    # тест не зависит от выполнения JS
    assert 'id="traffic-body"' in html
    assert 'id="scheme-body"' in html


async def test_coverage_html_has_traffic_kpi_rings_and_three_columns(client):
    resp = await client.get("/coverage.html")
    html = resp.text
    assert 'id="traffic-kpi-row"' in html
    assert 'id="traffic-rings-row"' in html
    assert 'id="traffic-summary-line"' in html
    assert 'id="traffic-columns"' in html
    assert 'id="traffic-col-ok"' in html
    assert 'id="traffic-col-problems"' in html
    assert 'id="traffic-col-empty"' in html
    # порядок трёх колонок в разметке — «Покрыто и проходит», «Есть проблемы», «Не покрыто»
    positions = [html.index(f'id="{i}"') for i in ("traffic-col-ok", "traffic-col-problems", "traffic-col-empty")]
    assert positions == sorted(positions)


async def test_coverage_html_scheme_v5_markup_not_removed(client):
    """Миссия: «Схему продукта v5 не удалять» — карта продукта (зоны/узлы/связи,
    docs/missions/2026-09-29_coverage_scheme_stage2.md) должна остаться доступной
    вторым видом, а не быть выпилена вместе со «Светофором»."""
    resp = await client.get("/coverage.html")
    html = resp.text
    assert 'id="pm-canvas"' in html
    assert 'id="pm-canvas-svg"' in html
    assert 'id="pm-ring"' in html
    assert 'id="pm-legend' in html or 'class="pm-legend"' in html
    assert 'id="pm-tip"' in html


async def test_coverage_html_serves_traffic_logic_script(client):
    resp = await client.get("/coverage.html")
    html = resp.text
    assert 'src="coverage-traffic-logic.js"' in html
    # coverage-traffic-logic.js подключён после coverage-areas-logic.js (нужен
    # AREA_LABELS_RU / statusKey) и до coverage.js, который его использует
    order = ["coverage-tree-logic.js", "coverage-areas-logic.js", "coverage-traffic-logic.js", "coverage.js"]
    positions = [html.index(f'src="{name}"') for name in order]
    assert positions == sorted(positions)

    resp2 = await client.get("/coverage-traffic-logic.js")
    assert resp2.status_code == 200
    assert "CoverageTrafficLogic" in resp2.text


def test_coverage_js_persists_view_mode_choice_in_localstorage():
    """Клик по кнопке переключателя не выделен в чистую функцию (пишет напрямую в
    window.localStorage) — без jsdom в окружении (нет в node_modules) полноценно
    прокликать нельзя, поэтому подтверждаем сам факт вызова localStorage.setItem
    с правильным ключом и оба обработчика клика по исходнику. Чтение с фоллбеком
    (нормализация значения из localStorage) уже покрыто чистым юнит-тестом
    normalizeViewMode в tests/js/test_coverage_traffic_logic.js — не дублируем
    здесь тем же способом, только состыковка с DOM."""
    js = (UI_DIR / "coverage.js").read_text()
    assert "TrafficLogic.VIEW_MODE_KEY" in js
    assert "localStorage.getItem(TrafficLogic.VIEW_MODE_KEY)" in js
    assert 'localStorage.setItem(TrafficLogic.VIEW_MODE_KEY, viewMode)' in js
    assert "viewToggleTrafficBtn.addEventListener" in js
    assert "viewToggleSchemeBtn.addEventListener" in js
    # применение выбора не ломает схему v5: applyViewMode переключает hidden на
    # обоих контейнерах, а не удаляет один из них из DOM
    assert "trafficBody.hidden = !isTraffic" in js
    assert "schemeBody.hidden = isTraffic" in js


def test_coverage_js_card_click_builds_href_only_for_non_empty_sections():
    """Сборка href по клику (project.html?name=&set=#run) выделена в чистую
    TrafficLogic.sectionHref (покрыта юнит-тестами: urlencode, null для пустого
    раздела) — здесь только то, что coverage.js действительно её использует и
    что серая карточка физически не получает data-href/обработчик клика."""
    js = (UI_DIR / "coverage.js").read_text()
    assert "TrafficLogic.sectionHref(projectName, section)" in js
    assert 'data-href="${escapeHtml(href)}"' in js
    # closest(".traffic-card[data-href]") — карточка без data-href (пустой
    # раздел) не матчится селектором и клик по ней не сработает
    assert '.traffic-card[data-href]' in js


def test_coverage_js_uses_sections_and_kpi_from_traffic_logic():
    """Подстраховка от регрессии: рендер светофора действительно вызывает
    buildSections/mergeUncoveredAreas/computeKpi/assignColumns из
    coverage-traffic-logic.js, а не дублирует логику в самом coverage.js."""
    js = (UI_DIR / "coverage.js").read_text()
    for call in (
        "TrafficLogic.buildSections(tree, statusMap, AreasLogic.AREA_LABELS_RU)",
        "TrafficLogic.mergeUncoveredAreas(treeSections, summary.zero_coverage_areas",
        "TrafficLogic.computeKpi(summary)",
        "TrafficLogic.assignColumns(sections)",
    ):
        assert call in js, f"не найден вызов: {call}"
