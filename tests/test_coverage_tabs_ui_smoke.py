"""Страница «Покрытие» в четыре вкладки (20.10.2026): Светофор | Схема | Области |
Маршруты — вместо одного свитка на 23 000 px с разделом «Подробно». Панель вкладок
со стендом и тулбар фильтров вкладки «Маршруты» липкие; карта маршрутов —
аккордеон по областям (чистые правила — tests/js/test_coverage_map_logic.js).
Здесь статикой проверяем разметку, DOM-код и стили (как остальные *_ui_smoke)."""
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui"
HTML = (UI_DIR / "coverage.html").read_text()
TRAFFIC_DOM_JS = (UI_DIR / "coverage-traffic-dom.js").read_text()
MAP_DOM_JS = (UI_DIR / "coverage-map-dom.js").read_text()
SETUP_JS = (UI_DIR / "coverage-setup.js").read_text()
STYLE_CSS = (UI_DIR / "style.css").read_text()


def test_html_has_four_tabs_in_sticky_bar_with_shared_stand_select():
    bar = HTML[HTML.index('id="coverage-tabs-bar"'):HTML.index('id="coverage-view-card"')]
    for view in ("traffic", "scheme", "areas", "routes"):
        assert f'data-view="{view}"' in bar, view
        assert f'id="view-toggle-{view}"' in bar, view
    assert 'role="tablist"' in bar and 'id="cov-stand-select"' in bar
    assert ".coverage-tabs-bar { position: sticky;" in STYLE_CSS


def test_html_has_a_body_per_tab_and_no_details_spoiler():
    for body in ("traffic-body", "scheme-body", "areas-body", "routes-body"):
        assert f'id="{body}"' in HTML, body
    assert "coverage-details-spoiler" not in HTML and "<details" not in HTML
    assert 'id="charts-toggle"' not in HTML, "карточка «Диаграммы» больше не сворачивается — она и есть вкладка «Области»"
    # что на какой вкладке
    areas = HTML[HTML.index('id="areas-body"'):HTML.index('id="routes-body"')]
    routes = HTML[HTML.index('id="routes-body"'):]
    for needle in ('id="areas-block-box"', 'id="chart-rings-box"', 'id="chart-status-box"'):
        assert needle in areas, needle
    for needle in ('id="coverage-toolbar-card"', 'id="coverage-map"', 'id="coverage-detail"', 'id="chart-graph-box"',
                   'id="routes-expand-all"', 'id="routes-collapse-all"'):
        assert needle in routes, needle
    assert '<script src="coverage-map-logic.js"></script>' in HTML


def test_apply_view_mode_switches_four_bodies_and_syncs_hash():
    fn = TRAFFIC_DOM_JS[TRAFFIC_DOM_JS.index("function applyViewMode()"):TRAFFIC_DOM_JS.index("function setViewMode(mode)")]
    for needle in (
        "trafficBody.hidden = !isTraffic", "schemeBody.hidden = !isScheme",
        "coverageViewCard.hidden = !(isTraffic || isScheme)",
        'areasBody.hidden = viewMode !== "areas"', 'routesBody.hidden = viewMode !== "routes"',
        "TrafficLogic.VIEW_TITLES[viewMode]", 'btn.setAttribute("aria-selected", String(active))',
        "history.replaceState(null, \"\", `#${viewMode}`)",
    ):
        assert needle in fn, needle
    assert "TrafficLogic.VIEW_MODES.includes(hashMode)" in TRAFFIC_DOM_JS, "#hash в URL открывает вкладку"
    assert 'window.addEventListener("hashchange"' in TRAFFIC_DOM_JS


def test_cross_tab_actions_switch_to_routes_tab():
    """Фильтр области из «Тестов по областям», связи теста и граф живут на вкладке
    «Маршруты» — клики с других вкладок переключают туда, а не ведут в пустоту."""
    areas_dom = (UI_DIR / "coverage-areas-dom.js").read_text()
    diagrams_dom = (UI_DIR / "coverage-diagrams-dom.js").read_text()
    assert 'if (areaFilter) setViewMode("routes");' in areas_dom
    assert 'setViewMode("routes");' in MAP_DOM_JS[MAP_DOM_JS.index("async function openTestDetail(nodeid)"):]
    assert 'setViewMode("routes");' in diagrams_dom[diagrams_dom.index("function setGraphScopeToTest(nodeid)"):]
    assert "applyChartsCollapsed" not in diagrams_dom and "applyChartsCollapsed" not in SETUP_JS


def test_route_map_is_accordion_driven_by_map_logic():
    render = MAP_DOM_JS[MAP_DOM_JS.index("function routeAreaHtml("):MAP_DOM_JS.index("function toggleRouteArea(name)")]
    for needle in (
        "MapLogic.areaRouteStats(area, stand, opts)",
        "MapLogic.shouldExpandArea(area.area, {",
        "MapLogic.areasForRoutes(summary.map, highlightedRoutes)",
        'data-area-toggle="${escapeHtml(area.area)}" aria-expanded="${expanded}"',
        '<div class="route-area-grid" ${expanded ? "" : "hidden"}>',
        '<span class="route-area-n">${stats.covered}/${stats.total}</span>',
    ):
        assert needle in render, needle
    assert "routesExpandAllBtn.addEventListener" in MAP_DOM_JS and "routesCollapseAllBtn.addEventListener" in MAP_DOM_JS
    assert "const MapLogic = window.CoverageMapLogic;" in MAP_DOM_JS
    assert "function routeMatchesFilters(" not in MAP_DOM_JS, "фильтр маршрутов — в чистой логике, не дублируется в DOM-коде"


def test_style_css_sticky_toolbar_and_accordion_rules():
    for needle in (
        ".coverage-toolbar-card { position: sticky;",
        ".coverage-toolbar-card { position: sticky; top: 94px;",
        "#coverage-detail-card { position: sticky; top: 178px;",
        # «Связи» вровень с верхом «Карты маршрутов» (у .card свой margin-top) и
        # фиксированная колонка имени области, чтобы полосы стояли в одну линию (21.10)
        "overflow: auto; margin-top: 0; }",
        "flex: 0 0 210px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
        ".route-area-head {",
        ".route-area-grid[hidden] { display: none; }",
        ".route-area-selected {",
    ):
        assert needle in STYLE_CSS, needle
    assert ".charts-header {" not in STYLE_CSS
    # .coverage-details-spoiler остаётся — его использует «Состав набора» на project.html
