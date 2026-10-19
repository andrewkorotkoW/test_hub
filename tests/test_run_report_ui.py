"""Окно прогона после замечаний владельца 19.10.2026 (макет
https://claude.ai/code/artifact/b94de6e1-30a1-4278-9140-92c7cb79804b):
1) «Сплит» не пустой — при входе в завершённый прогон сразу выбран первый упавший
   тест, рейка сгруппирована failed/broken/passed/skipped, окно теста не ниже рейки;
2) «Итог прогона» — упавшие первыми, колонка «Причина» (короткое сообщение + бейдж
   причины), фильтр по причине, имя теста открывает его в «Сплите»;
3) PNG-график — под спойлером и грузится лениво, вместо него строка-сводка.

Чистая логика — ui/run-report-logic.js (tests/js/test_run_report_logic.js); здесь
статикой проверяем разметку/DOM-код/стили, как tests/test_run_form_collapse_ui.py."""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()
STYLE_CSS = (REPO_ROOT / "ui" / "style.css").read_text()
RUN_WINDOW_JS = (REPO_ROOT / "ui" / "project-run-window.js").read_text()
PROJECT_SETUP_JS = (REPO_ROOT / "ui" / "project-setup.js").read_text()


# ------------------------------------------------------------------ разметка

async def test_project_html_run_stats_strip_between_status_bar_and_split(client):
    html = (await client.get("/project.html")).text
    status_bar = html.index('class="run-status-bar"')
    stats = html.index('id="run-stats"')
    split = html.index('id="run-split"')
    assert status_bar < stats < split
    for needle in ('id="run-stat-stand"', 'id="run-stat-started"', 'id="run-stat-duration"',
                   'id="run-stat-pass-rate"', 'id="run-stat-causes"'):
        assert needle in html
    # бейджи passed/failed/broken/skipped переехали в сводку (одни на карточку)
    assert html.count('id="summary-badges"') == 1
    assert stats < html.index('id="summary-badges"') < split


async def test_project_html_report_chart_under_lazy_spoiler(client):
    html = (await client.get("/project.html")).text
    spoiler = re.search(r'<details id="report-chart-spoiler"[^>]*\bhidden\b[^>]*>(.*?)</details>', html, re.S)
    assert spoiler, "график отчёта должен быть внутри <details id=report-chart-spoiler hidden>"
    assert 'id="report-chart"' in spoiler.group(1)
    assert 'src=' not in spoiler.group(1)  # src ставится в JS только при открытии спойлера


async def test_project_html_report_table_has_cause_column_and_filter(client):
    html = (await client.get("/project.html")).text
    assert "<th>Тест</th><th>Статус</th><th>Причина</th><th>Длительность</th>" in html
    filters = html.index('class="report-filters"')
    assert html.index('id="report-cause-filter"') > filters


def test_project_html_loads_run_report_logic_before_run_window():
    assert PROJECT_HTML.index('src="run-report-logic.js"') < PROJECT_HTML.index('src="project-run-window.js"')


# ------------------------------------------------------------------ стили

def test_style_css_split_stretch_and_new_blocks():
    assert "grid-template-columns: 260px minmax(0, 1fr); gap: 14px; align-items: stretch;" in STYLE_CSS
    for needle in (".run-stats {", ".run-stats[hidden] { display: none; }", ".test-group {",
                   ".cause-chip {", ".cause-chip[aria-current=\"true\"]", "td.report-reason .msg {",
                   ".report-chart-spoiler"):
        assert needle in STYLE_CSS


# ------------------------------------------------------------------ DOM-код

def test_run_window_js_autoselects_first_failed_on_finished_run():
    fn = RUN_WINDOW_JS[RUN_WINDOW_JS.index("async function refreshSplitTests(runId)"):]
    fn = fn[: fn.index("async function openTestInSplit(nodeid)")]
    assert 'if (!selectedNodeid && isFinished && hasMarkup && viewMode === "split")' in fn
    assert "RunReportLogic.firstTestToSelect(splitTests, RunWindowSplitLogic.normalizeTestStatus)" in fn
    assert "await selectTest(first)" in fn


def test_run_window_js_rail_grouped_only_when_finished():
    fn = RUN_WINDOW_JS[RUN_WINDOW_JS.index("function renderTestsRail()"):]
    fn = fn[: fn.index("function updateWindowPill()")]
    assert "RunReportLogic.railGroups(splitTests, isFinished, RunWindowSplitLogic.normalizeTestStatus)" in fn
    assert 'class="test-group"' in fn


def test_run_window_js_report_rows_sorted_filtered_and_open_in_split():
    fn = RUN_WINDOW_JS[RUN_WINDOW_JS.index("function renderReportRows()"):]
    fn = fn[: fn.index("reportRows.addEventListener")]
    assert "RunReportLogic.sortForReport(currentTests, RunWindowSplitLogic.normalizeTestStatus)" in fn
    assert "RunReportLogic.filterByCause(sorted, activeReportCause)" in fn
    assert 'colspan="4"' in fn
    row_fn = RUN_WINDOW_JS[RUN_WINDOW_JS.index("function reportRowHtml(t, i)"):RUN_WINDOW_JS.index("function renderReportRows()")]
    assert 'class="report-open-test"' in row_fn
    assert "RunCompareLogic.causeTag(t)" in row_fn
    assert 't.short_reason' in row_fn
    handler = RUN_WINDOW_JS[RUN_WINDOW_JS.index("reportRows.addEventListener"):]
    handler = handler[: handler.index("statusFilter.addEventListener")]
    assert 'closest("a.report-open-test")' in handler
    assert "openTestInSplit(decodeURIComponent(link.dataset.nodeid))" in handler
    assert '<td colspan="4"><pre class="trace-pre">' in handler


def test_run_window_js_chart_loads_lazily_and_resets_on_open_run():
    assert 'reportChartSpoiler.addEventListener("toggle"' in RUN_WINDOW_JS
    render = RUN_WINDOW_JS[RUN_WINDOW_JS.index("function renderReport(payload, runId)"):]
    render = render[: render.index("reportChartSpoiler.addEventListener")]
    assert "if (reportChartSpoiler.open) reportChart.src" in render
    assert "renderRunStats(payload)" in render and "renderCauseFilter(payload)" in render
    open_run = RUN_WINDOW_JS[RUN_WINDOW_JS.index("async function openRun(runId)"):]
    open_run = open_run[: open_run.index("await refreshReport(runId)")]
    for needle in ("runStats.hidden = true;", "reportChartSpoiler.hidden = true;", "reportChartSpoiler.open = false;",
                   'activeReportCause = "all";', "reportChartRunId = null;"):
        assert needle in open_run


def test_compare_tab_always_available_even_for_running_run():
    # просьба владельца 19.10.2026: «Сравнить с…» не прятать у идущего прогона
    fn = RUN_WINDOW_JS[RUN_WINDOW_JS.index("function applyViewMode()"):]
    fn = fn[: fn.index("runViewToggle.addEventListener")]
    assert 'const showCompare = viewMode === "compare";' in fn
    assert 'if (viewMode === "causes" && !isFinished) viewMode = "split";' in fn
    assert "runViewToggle.hidden = false;" in fn
    assert 'else if (b.dataset.view === "causes") b.hidden = !isFinished;' in fn
    assert "cmpRunningNote.hidden = isFinished;" in fn
    assert "isFinished && viewMode === \"compare\"" not in fn
    assert 'id="cmp-running-note"' in PROJECT_HTML
    assert 'const cmpRunningNote = document.getElementById("cmp-running-note");' in PROJECT_SETUP_JS


def test_style_css_hidden_attribute_wins_over_flex_blocks():
    # display:flex у класса перебивал hidden — пустая янтарная полоска над кнопками
    # запуска (скрин владельца 19.10.2026)
    assert ".run-form-summary[hidden], .marker-conflict-hint[hidden], .report-cause-filter[hidden] { display: none; }" in STYLE_CSS


def test_project_setup_js_declares_report_dom_refs():
    for needle in ('const reportChartSpoiler = document.getElementById("report-chart-spoiler");',
                   'const reportCauseFilter = document.getElementById("report-cause-filter");',
                   'const runStats = document.getElementById("run-stats");',
                   'const runStatCauses = document.getElementById("run-stat-causes");'):
        assert needle in PROJECT_SETUP_JS
