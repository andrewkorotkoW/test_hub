"""Вкладка «Прогоны» проекта (бывшая «История», project.html#history, 20.10.2026):
таблица на всю высоту вкладки, фильтры (стенд · статус · кто · сборка · период ·
поиск) с памятью в localStorage, колонка «Результат · Δ» (полоса + pass-rate +
счётчики + дельта), форматы даты/длительности/цели через чистую
ui/runs-history-logic.js (tests/js/test_runs_history_logic.js). Здесь статикой —
разметка, DOM-код, стили."""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui"
PROJECT_HTML = (UI_DIR / "project.html").read_text()
DASHBOARD_JS = (UI_DIR / "project-dashboard.js").read_text()
STYLE_CSS = (UI_DIR / "style.css").read_text()


def _history_panel():
    m = re.search(r'<div class="tab-panel" data-tab-panel="history"[^>]*>(.*?)<div class="tab-panel" data-tab-panel="flaky"', PROJECT_HTML, re.DOTALL)
    assert m
    return m.group(1)


def test_tab_is_named_runs_like_the_sidebar_and_has_filters():
    assert '<a href="#history" data-tab="history">Прогоны</a>' in PROJECT_HTML
    panel = _history_panel()
    for needle in ('id="hist-filters"', 'id="hist-stand"', 'id="hist-status"', 'id="hist-by"', 'id="hist-label"',
                   'id="hist-period"', 'id="hist-search"', 'id="hist-reset"', 'id="hist-count"'):
        assert needle in panel, needle
    assert '<option value="active">' in panel, "running+queued одним пунктом"
    assert "table-scroll" not in panel, "таблица на всю высоту вкладки, без окна в 420px"
    assert 'class="table-wrap table-sticky-head"' in panel
    assert '<script src="runs-history-logic.js"></script>' in PROJECT_HTML


def test_dashboard_js_renders_history_through_runs_history_logic():
    assert "const HistLogic = window.RunsHistoryLogic;" in DASHBOARD_JS
    for needle in (
        "HistLogic.filterRuns(runs, histFilters, new Date())",
        "HistLogic.filterOptions(runs)",
        "HistLogic.runResult(r)",
        "HistLogic.fmtStarted(r.started, now)",
        "HistLogic.targetSummary(r.target)",
        "HistLogic.runTags(r)",
        "RunReportLogic.fmtRunDuration(r.duration)",
        "localStorage.setItem(HIST_FILTERS_KEY, JSON.stringify(histFilters))",
        'class="status-pill status-pill-sm ${escapeHtml(r.status)}"',
        "historyDeltaHtml(r)",
    ):
        assert needle in DASHBOARD_JS, needle
    load = DASHBOARD_JS[DASHBOARD_JS.index("async function loadHistory()"):]
    assert "renderHistoryTable();" in load and "fmtDuration(r.duration)" not in load


def test_style_css_history_rules():
    for needle in (".hist-filters {", ".hist-bar {", ".hist-seg-failed {", ".hist-rate.bad {", ".hist-delta {",
                   ".status-pill-sm {", ".status-pill.cancelled {", ".table-wrap.table-sticky-head thead th {"):
        assert needle in STYLE_CSS, needle
