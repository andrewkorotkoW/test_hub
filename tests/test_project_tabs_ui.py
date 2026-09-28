"""Вкладки страницы проекта (Дашборд/Запуск/Расписания/История/Флаки) и правки
пункта меню «Прогоны»/удаление «Настройки» — доводка макета A (миссия
docs/missions/redesign/v2, «Доводка project.html до макета A»).

По образцу tests/test_coverage_ui_routing.py/test_redesign_ui_smoke.py: без
браузера — раздача статики, наличие ключевых id/атрибутов в HTML и (там, где
поведение зависит от DOM-событий, не исполняемых здесь) наличие соответствующей
логики в исходнике *.js."""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

PROJECT_JS = (REPO_ROOT / "ui" / "project.js").read_text()
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()
COMMON_JS = (REPO_ROOT / "ui" / "common.js").read_text()

TAB_IDS = ["dashboard", "run", "schedules", "history", "flaky"]


# ------------------------------------------------------------------ вкладки в разметке

async def test_project_html_has_tabs_nav_with_five_tabs(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="project-tabs"' in html
    for tab in TAB_IDS:
        assert f'data-tab="{tab}"' in html
        assert f'data-tab-panel="{tab}"' in html


def test_project_html_only_dashboard_panel_visible_by_default():
    """Дашборд — вкладка по умолчанию: её панель без статичного hidden, остальные
    четыре — со статичным hidden (JS переключает при загрузке/hashchange)."""
    for tab in TAB_IDS:
        m = re.search(rf'<div class="tab-panel" data-tab-panel="{tab}"([^>]*)>', PROJECT_HTML)
        assert m, f"не найдена панель вкладки {tab!r}"
        if tab == "dashboard":
            assert "hidden" not in m.group(1)
        else:
            assert "hidden" in m.group(1)


def test_project_html_dashboard_panel_wraps_kpi_and_charts():
    """Дашборд-панель должна физически содержать KPI-ряд и карточку графиков —
    иначе переключение вкладок случайно спрятало бы их под другую вкладку."""
    m = re.search(
        r'<div class="tab-panel" data-tab-panel="dashboard"[^>]*>(.*?)<div class="tab-panel" data-tab-panel="run"',
        PROJECT_HTML,
        re.DOTALL,
    )
    assert m, "не найдено содержимое вкладки «Дашборд»"
    body = m.group(1)
    for needle in ('id="kpi-row"', 'id="dashboard-charts-card"', 'id="runs-feed-card"', 'id="xfail-card"'):
        assert needle in body


def test_project_html_run_panel_wraps_tests_and_run_cards():
    m = re.search(
        r'<div class="tab-panel" data-tab-panel="run"[^>]*>(.*?)<div class="tab-panel" data-tab-panel="schedules"',
        PROJECT_HTML,
        re.DOTALL,
    )
    assert m, "не найдено содержимое вкладки «Запуск»"
    body = m.group(1)
    assert 'id="tests-card"' in body
    assert 'id="run-card"' in body
    assert 'id="run-buttons-row"' in body


def test_project_html_schedules_history_flaky_panels_wrap_their_cards():
    checks = {
        "schedules": ('id="schedules-card"', "history"),
        "history": ('id="history-rows"', "flaky"),
        "flaky": ('id="flaky-rows"', None),
    }
    for tab, (needle, next_tab) in checks.items():
        if next_tab:
            pattern = rf'<div class="tab-panel" data-tab-panel="{tab}"[^>]*>(.*?)<div class="tab-panel" data-tab-panel="{next_tab}"'
        else:
            pattern = rf'<div class="tab-panel" data-tab-panel="{tab}"[^>]*>(.*)'
        m = re.search(pattern, PROJECT_HTML, re.DOTALL)
        assert m, f"не найдено содержимое вкладки {tab!r}"
        assert needle in m.group(1)


# ------------------------------------------------------------------ переключение вкладок — логика в project.js

def test_project_js_computes_active_tab_from_hash_defaulting_to_dashboard():
    match = re.search(r"function activeTabId\(\)\s*\{([^}]*)\}", PROJECT_JS)
    assert match, "не найдена функция activeTabId() в ui/project.js"
    body = match.group(1)
    assert "window.location.hash" in body
    assert '"dashboard"' in body


def test_project_js_listens_to_hashchange_and_toggles_panel_hidden():
    assert 'addEventListener("hashchange"' in PROJECT_JS
    match = re.search(r"function renderActiveTab\(\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена функция renderActiveTab() в ui/project.js"
    body = match.group(1)
    assert "panel.hidden = panel.dataset.tabPanel !== active" in body


def test_project_js_open_run_switches_to_run_tab():
    """Открытие прогона (лента/история/расписания/deep-link ?run=) должно
    переключать на вкладку «Запуск» — иначе run-card заполнится, но останется
    скрыт под hidden соседней вкладки."""
    match = re.search(r"async function openRun\(runId\)\s*\{([^}]*)\}", PROJECT_JS)
    assert match, "не найдена функция openRun() в ui/project.js"
    assert 'window.location.hash = "run"' in match.group(1)


# ------------------------------------------------------------------ меню: «Прогоны» -> история, «Настройки» убраны

def test_common_js_settings_item_removed_from_nav():
    assert '"Настройки"' not in COMMON_JS
    assert "app-nav-soon" not in COMMON_JS


def test_common_js_runs_item_is_dynamic_shortcut_to_history_or_projects():
    match = re.search(r'\{\s*label:\s*"Прогоны".*?\}', COMMON_JS, re.DOTALL)
    assert match, "не найдена запись пункта меню «Прогоны» в ui/common.js"
    assert "runsShortcut: true" in match.group(0)

    fn_match = re.search(r"function navItemHref\(item, projectName\)\s*\{(.*?)\n\}", COMMON_JS, re.DOTALL)
    assert fn_match, "не найдена функция navItemHref() в ui/common.js"
    body = fn_match.group(1)
    assert "item.runsShortcut" in body
    assert "#history" in body
    assert '"projects.html"' in body


def test_common_js_nav_items_have_no_soon_only_stub_entries():
    """Все пункты APP_NAV_ITEMS либо статичный href, либо runsShortcut — ни одного
    пункта без способа получить ссылку (раньше это и был признак «скоро»)."""
    match = re.search(r"const APP_NAV_ITEMS = \[(.*?)\n\];", COMMON_JS, re.DOTALL)
    assert match, "не найден APP_NAV_ITEMS в ui/common.js"
    body = match.group(1)
    entries = [e.strip() for e in re.findall(r"\{[^{}]*\}", body)]
    assert entries, "APP_NAV_ITEMS пуст"
    for entry in entries:
        assert "href:" in entry or "runsShortcut:" in entry, f"пункт меню без href/runsShortcut: {entry}"


async def test_project_html_kpi_row_and_chart_row_grid_classes_present(client):
    """DESIGN.md Layout: KPI — 6 колонок, «кольцо + столбцы» — 300px + остаток —
    базовая проверка, что нужные grid-классы не потерялись при перестройке."""
    resp = await client.get("/project.html")
    html = resp.text
    assert 'class="kpi-row"' in html
    assert 'class="chart-row"' in html
    assert 'class="dashboard-feed-grid"' in html
