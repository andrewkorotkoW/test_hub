"""Смоук-тесты страницы статистики (ui/stats.html) и дерева разделов в
project.html (форма запуска + форма расписаний), см. миссию
docs/missions/2026-09-26_clear_design_stats_sections.md, части 2-3.

По образцу tests/test_redesign_ui_smoke.py/tests/test_coverage_ui_routing.py:
без браузера — раздача статики + наличие ключевых id в HTML, и (там, где
поведение зависит от DOM-событий, которые здесь не исполняются) наличие
соответствующей логики в исходнике *.js."""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


async def test_stats_html_served_with_app_shell(client):
    resp = await client.get("/stats.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert html.strip().lower().startswith("<!doctype html>")
    assert 'id="app-header"' in html
    assert 'id="app-sidebar"' in html
    assert 'class="app-shell"' in html
    assert 'src="common.js"' in html


async def test_stats_html_has_sections_table_dynamics_and_top_lists(client):
    resp = await client.get("/stats.html")
    html = resp.text
    assert 'id="stats-stand-select"' in html
    assert 'id="stats-export-btn"' in html
    assert 'id="sections-rows"' in html
    assert 'id="sections-empty-box"' in html
    assert 'id="dynamics-section-select"' in html
    assert 'id="dynamics-area-chart"' in html
    assert 'id="dynamics-bar-chart"' in html
    assert 'id="top-slowest-list"' in html
    assert 'id="top-flaky-list"' in html


async def test_common_js_sidebar_has_stats_menu_item(client):
    """Пункт «Статистика» собирается renderSidebar() (common.js) и не попадает в
    статичный HTML — проверяем исходник, как test_common_js_wires_sidebar_nav_and_theme_toggle
    в tests/test_redesign_ui_smoke.py."""
    resp = await client.get("/common.js")
    js = resp.text
    assert 'href: "stats.html"' in js
    assert "Статистика" in js


def test_common_js_stats_link_needs_project_like_coverage_link():
    """Ссылка на статистику имеет смысл только с выбранным проектом — та же
    политика, что и у ссылки на покрытие (needsProject: true)."""
    common_js = (REPO_ROOT / "ui" / "common.js").read_text()
    match = re.search(r'\{\s*href:\s*"stats\.html".*?\}', common_js, re.DOTALL)
    assert match, "не найдена запись пункта меню stats.html в ui/common.js"
    assert "needsProject: true" in match.group(0)


# ------------------------------------------------------------------ дерево разделов в форме запуска (project.html)

async def test_project_html_has_sections_tree_with_search_and_presets_in_run_form(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="sections-search-input"' in html
    assert 'id="sections-presets-row"' in html
    assert 'id="sections-tree"' in html
    assert 'id="manual-target-input"' in html
    for preset in ("api", "ui", "smoke", "all"):
        assert f'data-preset="{preset}"' in html


async def test_project_html_has_sections_tree_in_schedule_form(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="sched-sections-search-input"' in html
    assert 'id="sched-sections-presets-row"' in html
    assert 'id="sched-sections-tree"' in html
    assert 'id="sched-target-input"' in html


async def test_project_html_loads_sections_tree_logic_before_project_js(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert html.index('src="sections-tree-logic.js"') < html.index('src="project.js"')


async def test_project_js_targets_use_sections_tree_logic_collect_targets():
    """selectedTarget()/форма расписаний собирают target через
    SectionsTreeLogic.collectTargets (чистая логика, покрытая
    tests/test_sections_tree_logic_js.py) — здесь только замок, что project.js
    действительно её вызывает, а не собирает target вручную по DOM."""
    project_js = (REPO_ROOT / "ui" / "project.js").read_text()
    assert "SectionsTreeLogic.collectTargets(data, new Set(checkedFileTargets(box)))" in project_js
    assert "sectionsPicker.targets()" in project_js
    assert "schedSectionsPicker.targets()" in project_js


async def test_project_js_manual_target_input_overrides_sections_picker():
    """Ручное поле под спойлером имеет приоритет над деревом, только если оно
    непустое (см. миссию: «ручное поле остаётся под спойлером»)."""
    project_js = (REPO_ROOT / "ui" / "project.js").read_text()
    match = re.search(r"function selectedTarget\(\)\s*\{([^}]*)\}", project_js)
    assert match, "не найдена функция selectedTarget() в ui/project.js"
    body = match.group(1)
    assert "manualTargetInput.value.trim()" in body
    assert "sectionsPicker.targets()" in body


async def test_project_js_smoke_preset_sets_marker_and_checks_all_files():
    """Пресет «smoke» — единственный, отсутствующий в SectionsTreeLogic.presetLeafTargets
    (это существующий pytest-маркер, не раздел файловой системы): выставляет
    marker=smoke и отмечает все файлы дерева (allLeafTargets)."""
    project_js = (REPO_ROOT / "ui" / "project.js").read_text()
    match = re.search(r'if \(preset === "smoke"\) \{([^}]*)\}', project_js)
    assert match, "не найдена ветка пресета smoke в ui/project.js"
    body = match.group(1)
    assert 'markerSelectEl.value = "smoke"' in body
    assert "SectionsTreeLogic.allLeafTargets(data)" in body


async def test_schedule_submit_falls_back_to_sections_picker_then_all():
    """POST .../schedules собирает target: ручное поле -> дерево разделов -> 'all'
    (миссия, часть 3: «в форме расписания тот же выбор разделов»)."""
    project_js = (REPO_ROOT / "ui" / "project.js").read_text()
    assert re.search(
        r'target:\s*schedTargetInput\.value\.trim\(\)\s*\|\|\s*schedSectionsPicker\.targets\(\)\.join\("\\n"\)\s*\|\|\s*"all"',
        project_js,
    ), "не найдена сборка target формы расписания (ручное поле -> дерево -> all)"


# ------------------------------------------------------------------ projects.html/coverage.html не задеты частью 2/3

async def test_projects_html_and_coverage_html_still_served_after_stats_sections_changes(client):
    for page in ("projects.html", "coverage.html"):
        resp = await client.get(f"/{page}")
        assert resp.status_code == 200, page
        assert 'id="app-sidebar"' in resp.text, page
