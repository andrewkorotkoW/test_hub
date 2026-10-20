"""Схема продукта на странице покрытия — разводка связей v2 (замечание владельца
20.10.2026 «чёткие линии соединения»): связи рендерятся как <path> со скруглёнными
углами из CoverageSchemeLogic.pmEdgesWithRoutes/pmPathD, с двумя стрелками (обычная и
акцентная), при наведении на узел его связи и соседи подсвечиваются, остальное
приглушается. Чистая логика (Дейкстра со штрафами, разнесённые концы, path) —
tests/js/test_coverage_scheme_logic.js; здесь статикой проверяем DOM-код и стили,
как tests/test_coverage_traffic_ui_smoke.py."""
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEME_DOM_JS = (REPO_ROOT / "ui" / "coverage-scheme-dom.js").read_text()
SCHEME_LOGIC_JS = (REPO_ROOT / "ui" / "coverage-scheme-logic.js").read_text()
STYLE_CSS = (REPO_ROOT / "ui" / "style.css").read_text()


def test_scheme_dom_renders_routed_paths_with_two_arrow_markers():
    render = SCHEME_DOM_JS[SCHEME_DOM_JS.index("function renderProductMapCanvas()"):]
    render = render[: render.index("function renderProductMap()")]
    assert "CoverageSchemeLogic.pmEdgesWithRoutes(productMap)" in render
    assert "CoverageSchemeLogic.pmPathD(e.pts, 6)" in render
    assert '<path class="pm-edge' in render and "<polyline" not in render
    assert 'id="pm-arrow"' in render and 'id="pm-arrow-hot"' in render
    assert 'markerUnits="userSpaceOnUse"' in render  # стрелка не зависит от толщины линии


def test_scheme_dom_highlights_edges_and_neighbors_on_hover_and_focus():
    assert "function highlightNodeEdges(nodeId)" in SCHEME_DOM_JS
    bind = SCHEME_DOM_JS[SCHEME_DOM_JS.index("function bindProductMapNodeEvents()"):]
    bind = bind[: bind.index("function renderProductMapCanvas()")]
    assert "highlightNodeEdges(node.id)" in bind and "highlightNodeEdges(null)" in bind
    for event in ('"mouseenter"', '"mouseleave"', '"focus"', '"blur"'):
        assert event in bind


def test_scheme_logic_exports_v2_routing_api():
    for name in ("pmSpreadAnchors", "pmEdgesWithRoutes", "pmPathD", "pmSegmentHugs", "pmNodeSide"):
        assert f"{name}: {name}," in SCHEME_LOGIC_JS
    assert "const HUG_FACTOR = 1.5;" in SCHEME_LOGIC_JS


def test_style_css_edges_crisp_and_hover_dimming():
    assert "stroke-width: 2;" in STYLE_CSS[STYLE_CSS.index(".pm-edges .pm-edge {"):][:200]
    for needle in (".pm-arrow-head-hot { fill: var(--accent); }",
                   ".pm-canvas.pm-hover .pm-edge { stroke-opacity: .14; }",
                   ".pm-canvas.pm-hover .pm-edge.pm-edge-hot {",
                   "marker-end: url(#pm-arrow-hot)",
                   ".pm-canvas.pm-hover .pm-node.pm-node-hot"):
        assert needle in STYLE_CSS
