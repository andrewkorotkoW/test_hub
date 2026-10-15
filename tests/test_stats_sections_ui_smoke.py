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
    assert 'id="dynamics-section-suggestions"' in html
    assert 'id="dynamics-area-chart"' in html
    assert 'id="dynamics-bar-chart"' in html
    assert 'id="dynamics-count-chart"' in html
    assert 'id="top-slowest-list"' in html
    assert 'id="top-flaky-list"' in html


def test_dynamics_section_field_is_custom_combobox_not_select_or_datalist():
    """Было <select> с ~70-80 option (api/* + ui/*) — ОС рендерит такой список
    развёрнутым на весь экран (см. скриншот в задаче). input+datalist это
    чинил, но ловил два своих бага: 1) нативный фильтр подсказок — только по
    НАЧАЛУ значения option (ввод «buk» не находил «ui/buk»); 2) после выбора
    значения стрелка datalist переставала открывать список повторным кликом
    (сообщено как баг). Свой список (<ul><li data-value>) снимает оба
    ограничения — фильтр includes() по подстроке, открывается по фокусу
    независимо от текущего значения."""
    html = (REPO_ROOT / "ui" / "stats.html").read_text()
    assert '<input type="text" id="dynamics-section-select" placeholder="Добавить раздел…" autocomplete="off">' in html
    assert '<ul id="dynamics-section-suggestions" class="section-combobox-list" hidden></ul>' in html
    assert '<div class="section-chips" id="dynamics-section-chips"></div>' in html
    assert '<select id="dynamics-section-select">' not in html
    assert "datalist" not in html


def test_dynamics_section_combobox_has_dropdown_arrow_hint():
    """У select/datalist была своя стрелка — визуальный намёк «это список».
    Простой <input> такого намёка не даёт сам по себе — добавлена декоративная
    стрелка (pointer-events: none, клик проходит в input под ней)."""
    html = (REPO_ROOT / "ui" / "stats.html").read_text()
    assert '<span class="section-combobox-arrow" aria-hidden="true">▾</span>' in html
    css = (REPO_ROOT / "ui" / "style.css").read_text()
    assert ".section-combobox-arrow {" in css
    assert "pointer-events: none;" in css


def test_dynamics_chart_row_has_three_equal_columns_not_two_with_empty_slot():
    """.charts-grid (repeat(2, 1fr)) с одним-единственным .chart-row внутри
    оставлял вторую колонку внешней сетки пустой — тот самый пустой блок
    рядом с двумя графиками на скриншоте. Плюс сам .chart-row теперь три
    равных графика (было 300px+остаток — пара «узкая+широкая», не подходит
    трём однотипным графикам по одной шкале прогонов)."""
    css = (REPO_ROOT / "ui" / "style.css").read_text()
    assert "#dynamics-card .charts-grid { grid-template-columns: 1fr; }" in css
    assert "#dynamics-card .chart-row { grid-template-columns: repeat(3, 1fr); }" in css


async def test_common_js_sidebar_has_stats_menu_item(client):
    """Пункт «Статистика» собирается renderSidebar() (common.js) и не попадает в
    статичный HTML — проверяем исходник, как test_common_js_wires_sidebar_nav_and_theme_toggle
    в tests/test_redesign_ui_smoke.py."""
    resp = await client.get("/common.js")
    js = resp.text
    assert 'href: "stats.html"' in js
    assert "Статистика" in js


def test_stats_js_renders_count_chart():
    js = (REPO_ROOT / "ui" / "stats.js").read_text()
    assert 'const countCanvas = document.getElementById("dynamics-count-chart");' in js
    assert 'alignToAxis(axis, s.points, "tests_total")' in js


def test_stats_js_section_combobox_filters_by_substring_and_opens_on_focus():
    js = (REPO_ROOT / "ui" / "stats.js").read_text()
    # фильтр — includes() по подстроке, не только по началу значения (это и
    # была часть бага с datalist)
    assert "sectionLabel(s).toLowerCase().includes(q)" in js
    # список открывается по фокусу независимо от текущего значения поля —
    # в отличие от нативной стрелки datalist, переставшей открываться повторным
    # кликом после уже выбранного значения (сообщённый баг)
    assert 'dynamicsSectionSelect.addEventListener("focus", () => renderSectionSuggestions(dynamicsSectionSelect.value));' in js
    # выбор подсказки/удаление чипа — mousedown (раньше blur поля), иначе клик терялся
    assert 'dynamicsSectionSuggestions.addEventListener("mousedown", (ev) => {' in js
    assert 'dynamicsSectionChips.addEventListener("mousedown", (ev) => {' in js


def test_stats_js_supports_multi_select_sections_as_chips():
    """Раньше было одно значение (замена при новом выборе) — теперь массив
    selectedSections, добавление не заменяет уже выбранные (см. обращение
    пользователя: «выборка из 3-4 тестов», «добавить к уже выбранному + ещё
    раздел»). "" — псевдо-раздел «Весь проект» (data.dynamics_project), тоже
    выбираемый как чип наравне с обычными разделами."""
    js = (REPO_ROOT / "ui" / "stats.js").read_text()
    assert "let selectedSections = [];" in js
    assert 'function sectionLabel(value) {\n    return value === "" ? "Весь проект" : value;\n  }' in js
    assert "if (!selectedSections.includes(value) && selectedSections.length < MAX_SELECTED_SECTIONS) {" in js
    assert "selectedSections.push(value);" in js
    assert "function removeSection(value) {" in js
    assert "selectedSections = selectedSections.filter((s) => s !== value);" in js
    # кнопка выбора раздела больше НЕ заменяет значение поля на выбранный
    # раздел (старое поведение single-select) — поле всегда очищается
    assert 'dynamicsSectionSelect.value = "";' in js


def test_stats_js_suggestion_mousedown_prevents_default_to_keep_list_open():
    """Баг: после chooseSection() список сразу пустел — клик по НЕфокусируемому
    <li> по умолчанию снимает фокус с поля (блюр), что триггерило
    closeSectionSuggestions() сразу после того, как chooseSection только что
    перерисовал список оставшихся вариантов. preventDefault() на mousedown
    отменяет этот блюр, список остаётся открытым для продолжения выбора
    (множественный выбор — без него после первого чипа пришлось бы заново
    кликать в поле)."""
    js = (REPO_ROOT / "ui" / "stats.js").read_text()
    match = re.search(
        r'dynamicsSectionSuggestions\.addEventListener\("mousedown", \(ev\) => \{([^}]*)\}\);',
        js,
    )
    assert match, "не найден обработчик mousedown подсказок в ui/stats.js"
    body = match.group(1)
    assert "ev.preventDefault();" in body
    assert body.index("ev.preventDefault();") < body.index("toggleSection(li.dataset.value);")


def test_stats_js_selected_sections_stay_in_list_bold_and_toggle_off():
    """Раньше выбранный раздел вычитался из подсказок (candidates.filter(s =>
    !selectedSections.includes(s))) — после выбора он пропадал из списка, не
    видно, что уже отмечено, не глядя на чипы выше. Теперь список не
    фильтрует — помечает выбранные классом .selected (жирным в style.css),
    а клик/Enter по уже выбранному через toggleSection() снимает выбор, а не
    остаётся мёртвым кликом по кнопке, которая и так не должна дублировать."""
    js = (REPO_ROOT / "ui" / "stats.js").read_text()
    assert "const candidates = [\"\", ...dynamicsSections];" in js
    assert "filter((s) => !selectedSections.includes(s))" not in js
    assert 'selected ? \' class="selected"\' : ""' in js
    assert "function toggleSection(value) {" in js
    assert "if (selectedSections.includes(value)) removeSection(value);" in js
    assert "else chooseSection(value);" in js
    assert "if (li) toggleSection(li.dataset.value);" in js
    assert "toggleSection(items[activeIndex >= 0 ? activeIndex : 0].dataset.value);" in js
    css = (REPO_ROOT / "ui" / "style.css").read_text()
    assert ".section-combobox-list li.selected { font-weight: 700; }" in css


def test_stats_js_outside_click_uses_composed_path_not_contains():
    """document click-слушатель должен закрывать список только при клике ВНЕ
    комбобокса. contains(ev.target) ломался: к моменту всплытия click
    выбранный <li> уже отсоединён chooseSection()'ом (innerHTML
    пересобран) — отсоединённый узел всегда not-contains, список закрывался
    сразу после выбора. composedPath() фиксирует путь на момент диспетчеризации,
    до пересборки."""
    js = (REPO_ROOT / "ui" / "stats.js").read_text()
    assert 'if (!ev.composedPath().includes(dynamicsSectionCombobox)) closeSectionSuggestions();' in js


def test_stats_js_dynamics_charts_use_union_axis_across_selected_sections():
    """Разные разделы затрагиваются разными прогонами — объединение run_id по
    всем выбранным сериям, а не ось одной серии (так было до множественного
    выбора, когда серия всегда была ровно одна)."""
    js = (REPO_ROOT / "ui" / "stats.js").read_text()
    assert "function unionRunAxis(seriesList) {" in js
    assert "function alignToAxis(axis, points, field) {" in js
    assert "const multi = seriesList.length > 1;" in js
    # одна серия (по умолчанию или один выбранный раздел) — тот же вид
    # графиков, что был раньше (без легенды, заливка градиентом на area)
    assert "legend: multi," in js


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
    tests/test_sections_tree_logic_js.py) — здесь только замок, что сценарий
    project.html действительно её вызывает, а не собирает target вручную по DOM.
    collectTargets/sectionsPicker.targets() — в ui/project-sections-picker.js,
    schedSectionsPicker.targets() (форма расписания) — в ui/project-setup.js
    (оба файла делят один lexical scope, см. шапку project-setup.js)."""
    sections_picker_js = (REPO_ROOT / "ui" / "project-sections-picker.js").read_text()
    setup_js = (REPO_ROOT / "ui" / "project-setup.js").read_text()
    assert "SectionsTreeLogic.collectTargets(data, new Set(checkedFileTargets(box)))" in sections_picker_js
    assert "sectionsPicker.targets()" in sections_picker_js
    assert "schedSectionsPicker.targets()" in setup_js


async def test_project_js_manual_target_input_overrides_sections_picker():
    """Ручное поле под спойлером имеет приоритет над деревом, только если оно
    непустое (см. миссию: «ручное поле остаётся под спойлером»)."""
    project_js = (REPO_ROOT / "ui" / "project-sections-picker.js").read_text()
    match = re.search(r"function selectedTarget\(\)\s*\{([^}]*)\}", project_js)
    assert match, "не найдена функция selectedTarget() в ui/project-sections-picker.js"
    body = match.group(1)
    assert "manualTargetInput.value.trim()" in body
    assert "sectionsPicker.targets()" in body


async def test_project_js_smoke_preset_sets_marker_and_checks_all_files():
    """Пресет «smoke» — единственный, отсутствующий в SectionsTreeLogic.presetLeafTargets
    (это существующий pytest-маркер, не раздел файловой системы): выставляет
    marker=smoke и отмечает все файлы дерева (allLeafTargets)."""
    project_js = (REPO_ROOT / "ui" / "project-sections-picker.js").read_text()
    match = re.search(r'if \(preset === "smoke"\) \{([^}]*)\}', project_js)
    assert match, "не найдена ветка пресета smoke в ui/project-sections-picker.js"
    body = match.group(1)
    assert 'markerSelectEl.value = "smoke"' in body
    assert "SectionsTreeLogic.allLeafTargets(data)" in body


async def test_schedule_submit_falls_back_to_sections_picker_then_all():
    """POST .../schedules собирает target: ручное поле -> дерево разделов -> 'all'
    (миссия, часть 3: «в форме расписания тот же выбор разделов»). Форма
    расписаний — в ui/project-setup.js."""
    project_js = (REPO_ROOT / "ui" / "project-setup.js").read_text()
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
