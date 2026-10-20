"""Блок «Тесты по областям» на странице покрытия — вариант A (замечание владельца
20.10.2026 «не нравится сам вывод инфы»): вместо treemap — строка на область
(имя · тестов · полоса статусов · счётчики · % · последний результат · маршруты),
по клику раскрывается «вафля» тестов; статус — последний известный результат на
стенде (last_results из GET /coverage/tree), а не только последний прогон.
Чистая логика — tests/js/test_coverage_areas_logic.js; здесь статикой проверяем
DOM-код, разметку и стили (как tests/test_coverage_scheme_ui_smoke.py)."""
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui"
AREAS_DOM_JS = (UI_DIR / "coverage-areas-dom.js").read_text()
AREAS_LOGIC_JS = (UI_DIR / "coverage-areas-logic.js").read_text()
COVERAGE_HTML = (UI_DIR / "coverage.html").read_text()
STYLE_CSS = (UI_DIR / "style.css").read_text()


def test_treemap_is_gone_from_scenario_and_markup():
    assert not (UI_DIR / "coverage-treemap-dom.js").exists()
    assert "coverage-treemap-dom.js" not in COVERAGE_HTML
    assert 'id="chart-treemap-body"' not in COVERAGE_HTML and 'id="areas-table"' not in COVERAGE_HTML
    for name in ("coverage-setup.js", "coverage.js", "coverage-tree-dom.js"):
        js = (UI_DIR / name).read_text()
        assert "renderTreemap" not in js and "renderAreasTable" not in js, name
    assert "squarify" not in AREAS_LOGIC_JS and "STATUS_COLORS" not in AREAS_LOGIC_JS


def test_areas_dom_uses_last_results_with_fallback_to_statuses():
    fn = AREAS_DOM_JS[AREAS_DOM_JS.index("function areasStatusMap()"):]
    fn = fn[: fn.index("function areaBarHtml")]
    assert "treeApiData.last_results" in fn
    assert "treeApiData.statuses" in fn, "старый сервер без last_results — статусы последнего прогона"


def test_areas_dom_renders_rows_waffle_and_wires_clicks():
    for needle in (
        "AreasLogic.buildAreaRows(treeApiData.tree || {}, areasStatusMap())",
        "AreasLogic.groupRowsByKind(rows, areasSortMode, areasHideEmpty)",
        "AreasLogic.matchRouteStats(row, routeStats)",
        'data-ab-row="${escapeHtml(row.key)}"',
        'data-ab-area="${escapeHtml(row.matchArea)}"',
        'data-ab-nodeid="${escapeHtml(t.nodeid)}"',
        "openTestDetail(cell.dataset.abNodeid)",
        "selectAreaFilter(name.dataset.abArea)",
        "toggleAreaRow(row.dataset.abRow)",
        'row.percent === null ? "—" : row.percent + " %"',
    ):
        assert needle in AREAS_DOM_JS, needle
    # цвета — классами из style.css (цвета темы), не инлайн-hex
    assert "#2eaa4a" not in AREAS_DOM_JS and 'fill="' not in AREAS_DOM_JS


def test_route_area_bars_widget_merged_into_areas_block():
    """Виджет «Маршруты по областям» (полосы покрытия маршрутов по областям) выглядел
    как дубль нового блока — влит в него: колонка «Маршруты» с мини-полосой и чипы
    областей маршрутов без папки тестов (AreasLogic.unmatchedRouteAreas)."""
    assert 'id="chart-areas-box"' not in COVERAGE_HTML and "Маршруты по областям" not in COVERAGE_HTML
    for name in ("coverage-setup.js", "coverage.js", "coverage-diagrams-dom.js", "coverage-areas-dom.js"):
        js = (UI_DIR / name).read_text()
        assert "renderAreaBars" not in js and "chartAreasBody" not in js, name
    assert ".area-bar-row" not in STYLE_CSS
    assert "AreasLogic.unmatchedRouteAreas(summary ? summary.map : [], rows)" in AREAS_DOM_JS
    assert '<span class="ab-rbar"><span style="width:${pct.toFixed(1)}%"></span></span>' in AREAS_DOM_JS
    assert 'class="ab-rchip${areaFilter === a.area ? " active" : ""}" data-ab-area="${escapeHtml(a.area)}"' in AREAS_DOM_JS
    for needle in (".ab-rbar {", ".ab-rchip {", ".ab-rchip.active {"):
        assert needle in STYLE_CSS, needle


def test_areas_dom_persists_sort_and_hide_empty():
    assert 'localStorage.setItem(AREAS_SORT_KEY, areasSortMode)' in AREAS_DOM_JS
    assert 'localStorage.setItem(AREAS_HIDE_EMPTY_KEY' in AREAS_DOM_JS
    assert "renderAreasBlock()" in AREAS_DOM_JS


def test_coverage_html_has_areas_block_controls_and_legend():
    assert 'id="areas-block-box"' in COVERAGE_HTML
    assert 'id="areas-sort-chips"' in COVERAGE_HTML
    for mode in ("failed", "size", "name"):
        assert f'data-ab-sort="{mode}"' in COVERAGE_HTML
    assert 'id="areas-hide-empty"' in COVERAGE_HTML
    assert "нет результата" in COVERAGE_HTML
    assert "последний известный результат" in COVERAGE_HTML
    assert '<script src="coverage-areas-dom.js"></script>' in COVERAGE_HTML


def test_style_css_areas_block_is_theme_aware():
    # «нет результата» — токен темы, задан и в тёмной, и в светлой
    assert STYLE_CSS.count("--ab-none-fill:") == 2 and STYLE_CSS.count("--ab-none-stroke:") == 2
    for needle in (
        ".ab-row, .ab-head-row {",
        ".ab-bar { display: flex;",
        ".ab-seg.ab-failed { background: var(--tm-failed); }",
        ".ab-cell { width: 13px;",
        ".ab-cell.ab-passed { background: var(--tm-passed);",
        ".ab-pct.none { color: var(--text-muted);",
        ".ab-row-selected {",
        ".ab-chip.active {",
    ):
        assert needle in STYLE_CSS, needle
    assert ".tm-cell" not in STYLE_CSS and ".chart-treemap-body" not in STYLE_CSS
