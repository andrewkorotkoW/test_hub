"""Раскрывающееся дерево разделов (миссия docs/missions/2026-10-05_run_page_sections_list.md,
коммит michael dd57a87a): свёрнутые по умолчанию узлы, клик по заголовку (не по чекбоксу)
раскрывает узел, пресеты-переключатели с подсветкой активного и строкой итога «Выбрано: N
файлов · API x · UI y», общий пикер на вкладках «Запуск» (#sections-tree/#sections-presets-row)
и «Расписания» (#sched-sections-tree/#sched-sections-presets-row).

Чистая логика (сортировка по пресету, счётчики, раскрытие по поиску/пресету, человекочитаемые
имена) уже разобрана юнит-тестами на node — tests/js/test_sections_tree_logic.js /
tests/test_sections_tree_logic_js.py. Здесь — то, что физически в DOM-коде project.js
(createSectionsPicker/buildSectionsTreeHtml/setupTreeEvents) и в разметке project.html, не
исполняемое в node (project.js — один верхнеуровневый IIFE с document на верхнем уровне,
см. test_project_tabs_ui.py/test_build_page_ui.py про тот же приём): проверяем статикой
HTML/исходника JS без браузера.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT_JS = (REPO_ROOT / "ui" / "project.js").read_text()
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()
STYLE_CSS = (REPO_ROOT / "ui" / "style.css").read_text()


# ------------------------------------------------------------------ разметка обеих вкладок

async def test_project_html_has_sections_tree_blocks_for_run_tab(client):
    resp = await client.get("/project.html")
    html = resp.text
    for needle in (
        'id="sections-search-input"', 'id="sections-presets-row"', 'id="sections-summary-line"',
        'id="sections-tree"',
    ):
        assert needle in html


async def test_project_html_has_sections_tree_blocks_for_schedules_tab(client):
    resp = await client.get("/project.html")
    html = resp.text
    for needle in (
        'id="sched-sections-search-input"', 'id="sched-sections-presets-row"',
        'id="sched-sections-summary-line"', 'id="sched-sections-tree"',
    ):
        assert needle in html


def test_run_tab_has_four_presets_including_smoke():
    m = re.search(r'<div class="run-buttons" id="sections-presets-row">(.*?)</div>', PROJECT_HTML, re.DOTALL)
    assert m, "не найден блок пресетов вкладки «Запуск»"
    body = m.group(1)
    presets = re.findall(r'data-preset="(\w+)"', body)
    assert presets == ["api", "ui", "smoke", "all"]


def test_schedules_tab_has_only_three_presets_no_smoke_button():
    """Миссия явно требует ту же картину на «Расписаниях», но без маркера smoke
    (бэкенд расписаний такого не поддерживает) — кнопки Smoke там быть не должно."""
    m = re.search(r'<div class="run-buttons" id="sched-sections-presets-row">(.*?)</div>', PROJECT_HTML, re.DOTALL)
    assert m, "не найден блок пресетов вкладки «Расписания»"
    body = m.group(1)
    presets = re.findall(r'data-preset="(\w+)"', body)
    assert presets == ["api", "ui", "all"]
    assert "smoke" not in body


def test_sections_tree_logic_script_loaded_before_project_js():
    order = ["sections-tree-logic.js", "project.js"]
    positions = [PROJECT_HTML.index(f'src="{name}"') for name in order]
    assert positions == sorted(positions)


# ------------------------------------------------------------------ свёрнуто по умолчанию

def test_sections_picker_starts_with_empty_expanded_set():
    """createSectionsPicker: expanded — пустой Set и в начальном объявлении, и после
    каждого setData() (загрузка дерева) — узлы свёрнуты, пока пользователь/поиск/пресет
    не раскроют что-то явно."""
    assert re.search(r"let expanded = new Set\(\);", PROJECT_JS)
    set_data_match = re.search(r"setData\(newData\) \{([^}]*)\}", PROJECT_JS, re.DOTALL)
    assert set_data_match, "не найден setData() в createSectionsPicker"
    assert "expanded = new Set();" in set_data_match.group(1)


def test_build_sections_tree_html_hides_children_when_node_not_open():
    """buildSectionsTreeHtml: .tree-classes/.tree-tests контейнеры областей/файлов
    получают атрибут hidden, когда узел не в expandedKeys (kindOpen/areaOpen=false) —
    иначе дерево рисовалось бы развёрнутым несмотря на 'свёрнуто по умолчанию'
    в expanded."""
    m = re.search(r"function buildSectionsTreeHtml\(filtered, checkedTargets, expandedKeys\) \{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert m, "не найдена функция buildSectionsTreeHtml()"
    body = m.group(1)
    assert '<div class="tree-classes"${kindOpen ? "" : " hidden"}>' in body
    assert '<div class="tree-tests"${areaOpen ? "" : " hidden"}>' in body


def test_node_head_html_reflects_open_state_in_aria_expanded():
    """nodeHeadHtml(opts) — aria-expanded на заголовке узла должен отражать тот же
    open, который buildSectionsTreeHtml передаёт как kindOpen/areaOpen."""
    m = re.search(r"function nodeHeadHtml\(opts\) \{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert m, "не найдена функция nodeHeadHtml()"
    body = m.group(1)
    assert 'aria-expanded="${opts.open ? "true" : "false"}"' in body


# ------------------------------------------------------------------ чекбокс не сворачивает узел

def test_tree_events_checkbox_click_does_not_trigger_header_toggle():
    """setupTreeEvents: клик по input.tree-check должен выходить раньше, чем код
    дойдёт до onHeaderToggle — проверка это гарантирует (а не чекбокс отдельно
    обрабатывает раскрытие где-то ещё)."""
    m = re.search(r"const toggleFromEvent = \(ev\) => \{(.*?)\n    \};", PROJECT_JS, re.DOTALL)
    assert m, "не найдена toggleFromEvent() в setupTreeEvents"
    body = m.group(1)
    first_line = body.strip().splitlines()[0]
    assert 'ev.target.matches("input.tree-check")' in first_line
    assert "return;" in first_line


def test_tree_node_head_checkbox_is_inside_header_markup():
    """Чекбокс физически внутри .tree-node-head (один клик-хэндлер на всю шапку) —
    без этого проверка выше ничего не гарантирует на реальной разметке."""
    m = re.search(r"function nodeHeadHtml\(opts\) \{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert m
    body = m.group(1)
    head_div = re.search(r'<div class="tree-node-head"[^>]*>(.*?)</div>\s*`', body, re.DOTALL)
    assert head_div, "не найдена разметка .tree-node-head"
    assert 'input type="checkbox" class="tree-check tree-parent"' in head_div.group(1)


# ------------------------------------------------------------------ пресет-переключатели: подсветка + сортировка

def test_update_preset_buttons_toggles_active_class_by_dataset_preset():
    m = re.search(r"function updatePresetButtons\(\) \{(.*?)\n    \}", PROJECT_JS, re.DOTALL)
    assert m, "не найдена updatePresetButtons()"
    body = m.group(1)
    assert 'btn.classList.toggle("active", btn.dataset.preset === activePreset)' in body


def test_preset_click_handler_sorts_tree_and_sets_active_preset():
    m = re.search(r'presetsRow\.addEventListener\("click", \(ev\) => \{(.*?)\n      \}\);', PROJECT_JS, re.DOTALL)
    assert m, "не найден обработчик клика по пресетам"
    body = m.group(1)
    assert "activePreset = preset;" in body
    assert "SectionsTreeLogic.expandedKeysForPreset(data.kinds, preset)" in body


def test_render_sorts_kinds_for_active_preset_before_building_html():
    m = re.search(r"function render\(\) \{(.*?)\n    \}", PROJECT_JS, re.DOTALL)
    assert m, "не найдена render() в createSectionsPicker"
    body = m.group(1)
    assert "SectionsTreeLogic.sortKindsForPreset(filtered.kinds, activePreset)" in body
    assert "buildSectionsTreeHtml({ kinds: sortedKinds }" in body


def test_sections_preset_btn_active_class_styled_in_css():
    assert re.search(r"(?m)^\.sections-preset-btn\.active\s*\{", STYLE_CSS)


# ------------------------------------------------------------------ строка итога: наличие и обновление

def test_summary_line_rendered_on_every_render_call():
    m = re.search(r"function render\(\) \{(.*?)\n    \}", PROJECT_JS, re.DOTALL)
    assert m
    assert "updateSummaryLine();" in m.group(1)


def test_summary_line_updates_on_manual_leaf_checkbox_change():
    """onLeafChange хук срабатывает на каждое 'change' события чекбокса-листа
    (ручной клик пользователя, не через пресет) и обновляет ту же строку итога,
    что и render() после пресета/поиска."""
    m = re.search(r"setupTreeEvents\(box, \{(.*?)\n    \}\);", PROJECT_JS, re.DOTALL)
    assert m, "не найден вызов setupTreeEvents() в createSectionsPicker"
    body = m.group(1)
    assert "onLeafChange: updateSummaryLine," in body


def test_update_summary_line_counts_total_api_ui_and_smoke_marker():
    m = re.search(r"function updateSummaryLine\(\) \{(.*?)\n    \}", PROJECT_JS, re.DOTALL)
    assert m, "не найдена updateSummaryLine()"
    body = m.group(1)
    assert "SectionsTreeLogic.countCheckedByKind(data, new Set(checkedFileTargets(box)))" in body
    assert "counts.total" in body and "counts.api" in body and "counts.ui" in body
    assert 'line += " · маркер: smoke";' in body


# ------------------------------------------------------------------ общий пикер на обеих вкладках

def test_both_tabs_use_the_same_create_sections_picker_factory():
    assert re.search(
        r"const sectionsPicker = createSectionsPicker\(\s*"
        r"sectionsTreeBox, sectionsSearchInput, sectionsPresetsRow, markerSelect, sectionsSummaryLine\s*\);",
        PROJECT_JS,
    )
    assert re.search(
        r"const schedSectionsPicker = createSectionsPicker\(\s*"
        r"schedSectionsTreeBox, schedSectionsSearchInput, schedSectionsPresetsRow, schedMarkerSelect, "
        r"schedSectionsSummaryLine\s*\);",
        PROJECT_JS,
    )


async def test_both_tabs_load_sections_data_into_both_pickers(client):
    m = re.search(r"async function loadSections\(\) \{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert m, "не найдена loadSections()"
    body = m.group(1)
    assert "sectionsPicker.setData(data);" in body
    assert "schedSectionsPicker.setData(data);" in body
