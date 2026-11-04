"""Раскрывающееся дерево разделов (миссия docs/missions/2026-10-05_run_page_sections_list.md,
коммит michael dd57a87a): свёрнутые по умолчанию узлы, клик по заголовку (не по чекбоксу)
раскрывает узел, пресеты-переключатели с подсветкой активного и строкой итога «Выбрано: N
файлов · API x · UI y», общий пикер на вкладках «Запуск» (#sections-tree/#sections-products-row/
#sections-kinds-row) и «Расписания» (#sched-sections-tree/#sched-sections-products-row/
#sched-sections-kinds-row).

С docs/missions/2026-11-03_product_presets.md пикер — пара продукт×вид вместо одного
activePreset: ряд «Что» (data-product=lms|helpdesk|lrs|all, productsRow) и ряд «Как»
(data-preset=api|ui|smoke|e2e|regression|mobile|integration, kindsRow) — два отдельных
DOM-ряда и два колбэка (updateProductButtons/updateKindButtons), общий applyPresetChange()
после клика по любому из них (project-sections-picker.js).

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
PROJECT_SECTIONS_PICKER_JS = (REPO_ROOT / "ui" / "project-sections-picker.js").read_text()
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()
STYLE_CSS = (REPO_ROOT / "ui" / "style.css").read_text()


# ------------------------------------------------------------------ разметка обеих вкладок

async def test_project_html_has_sections_tree_blocks_for_run_tab(client):
    resp = await client.get("/project.html")
    html = resp.text
    for needle in (
        'id="sections-search-input"', 'id="sections-products-row"', 'id="sections-kinds-row"',
        'id="sections-summary-line"', 'id="sections-tree"',
    ):
        assert needle in html


async def test_project_html_has_sections_tree_blocks_for_schedules_tab(client):
    resp = await client.get("/project.html")
    html = resp.text
    for needle in (
        'id="sched-sections-search-input"', 'id="sched-sections-products-row"',
        'id="sched-sections-kinds-row"', 'id="sched-sections-summary-line"', 'id="sched-sections-tree"',
    ):
        assert needle in html


def test_run_tab_has_seven_presets_including_smoke_e2e_regression_and_mobile():
    """E2E — тоже пресет-маркер (как Smoke), но не «отметить всё дерево»:
    псевдо-раздел tests/e2e уже содержит ровно размеченные @pytest.mark.e2e
    тесты (включая лежащие в tests/ui/*, см. app.core.sections
    ._e2e_virtual_files), поэтому кнопка ведёт себя как API/UI — раскрывает
    и отмечает только этот раздел, плюс подстраховочно ставит маркер e2e.
    Regression — весь функционал кроме внешних интеграций (см.
    SectionsTreeLogic.presetLeafTargets/REGRESSION_EXCLUDED_AREAS), без
    отдельного маркера — сам маркер regression зарегистрирован в pytest.ini
    auto_tests_vshgu, но ни на один тест не навешан. Mobile — только область
    tests/ui/mobile, заодно включает #mobile-checkbox (см.
    test_mobile_preset_button_checks_mobile_checkbox). «Всё» с 03.11 переехало
    в ряд «Что» (data-product="all") и больше не пресет вида — семь кнопок
    ряда «Как» это только виды, без «Всё»."""
    m = re.search(r'<div class="run-buttons" id="sections-kinds-row">(.*?)</div>', PROJECT_HTML, re.DOTALL)
    assert m, "не найден ряд «Как» вкладки «Запуск»"
    body = m.group(1)
    presets = re.findall(r'data-preset="(\w+)"', body)
    assert presets == ["api", "ui", "smoke", "e2e", "regression", "mobile", "integration"]


def test_run_tab_product_row_has_lms_helpdesk_lrs_all():
    """Ряд «Что» (data-product) — ровно четыре продукта, LMS первым (решение
    владельца 03.11: LMS — основной продукт платформы)."""
    m = re.search(r'<div class="run-buttons" id="sections-products-row">(.*?)</div>', PROJECT_HTML, re.DOTALL)
    assert m, "не найден ряд «Что» вкладки «Запуск»"
    body = m.group(1)
    products = re.findall(r'data-product="(\w+)"', body)
    assert products == ["lms", "helpdesk", "lrs", "all"]


def test_marker_select_lists_e2e_on_run_and_schedule_forms():
    for select_id in ("marker-select", "sched-marker-select"):
        m = re.search(rf'<select id="{select_id}">(.*?)</select>', PROJECT_HTML, re.DOTALL)
        assert m, f"не найден селект {select_id}"
        options = re.findall(r'<option value="([^"]*)"', m.group(1))
        assert options == ["", "smoke", "api", "ui", "e2e"], options


def test_schedules_tab_has_same_presets_as_run_form_except_mobile():
    """На «Расписаниях» — тот же ряд «Что» (продукты буквально совпадают, продукт не
    привязан к флагу mobile) и тот же ряд «Как», что в «Запуске» (schedules.marker
    давно есть, планировщик и «Запустить сейчас» передают его в runner.submit_run —
    ограничение «бэкенд не поддерживает smoke» снято), включая Integration — нет
    только Mobile: он включает #mobile-checkbox (MOBILE=1), а у расписаний флага
    mobile нет."""
    products_m = re.search(r'<div class="run-buttons" id="sched-sections-products-row">(.*?)</div>', PROJECT_HTML, re.DOTALL)
    assert products_m, "не найден ряд «Что» вкладки «Расписания»"
    products = re.findall(r'data-product="(\w+)"', products_m.group(1))
    assert products == ["lms", "helpdesk", "lrs", "all"]

    kinds_m = re.search(r'<div class="run-buttons" id="sched-sections-kinds-row">(.*?)</div>', PROJECT_HTML, re.DOTALL)
    assert kinds_m, "не найден ряд «Как» вкладки «Расписания»"
    body = kinds_m.group(1)
    presets = re.findall(r'data-preset="(\w+)"', body)
    assert presets == ["api", "ui", "smoke", "e2e", "regression", "integration"]
    assert "mobile" not in body


def test_sections_tree_logic_script_loaded_before_project_js():
    order = ["sections-tree-logic.js", "project.js"]
    positions = [PROJECT_HTML.index(f'src="{name}"') for name in order]
    assert positions == sorted(positions)


# ------------------------------------------------------------------ свёрнуто по умолчанию

def test_sections_picker_starts_with_empty_expanded_set():
    """createSectionsPicker: expanded — пустой Set и в начальном объявлении, и после
    каждого setData() (загрузка дерева) — узлы свёрнуты, пока пользователь/поиск/пресет
    не раскроют что-то явно."""
    assert re.search(r"let expanded = new Set\(\);", PROJECT_SECTIONS_PICKER_JS)
    set_data_match = re.search(r"setData\(newData\) \{([^}]*)\}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert set_data_match, "не найден setData() в createSectionsPicker"
    assert "expanded = new Set();" in set_data_match.group(1)


def test_build_sections_tree_html_hides_children_when_node_not_open():
    """buildSectionsTreeHtml: .tree-classes/.tree-tests контейнеры областей/файлов
    получают атрибут hidden, когда узел не в expandedKeys (kindOpen/areaOpen=false) —
    иначе дерево рисовалось бы развёрнутым несмотря на 'свёрнуто по умолчанию'
    в expanded."""
    m = re.search(r"function buildSectionsTreeHtml\(filtered, checkedTargets, expandedKeys\) \{(.*?)\n  \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена функция buildSectionsTreeHtml()"
    body = m.group(1)
    assert '<div class="tree-classes"${kindOpen ? "" : " hidden"}>' in body
    assert '<div class="tree-tests"${areaOpen ? "" : " hidden"}>' in body


def test_node_head_html_reflects_open_state_in_aria_expanded():
    """nodeHeadHtml(opts) — aria-expanded на заголовке узла должен отражать тот же
    open, который buildSectionsTreeHtml передаёт как kindOpen/areaOpen."""
    m = re.search(r"function nodeHeadHtml\(opts\) \{(.*?)\n  \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена функция nodeHeadHtml()"
    body = m.group(1)
    assert 'aria-expanded="${opts.open ? "true" : "false"}"' in body


# ------------------------------------------------------------------ чекбокс не сворачивает узел

def test_tree_events_checkbox_click_does_not_trigger_header_toggle():
    """setupTreeEvents: клик по input.tree-check (лист дерева точечного выбора),
    по .tkind-cb (тристейт-чекбокс строки вида) и по .area-chip (плашка области,
    docs/missions/2026-11-03_area_chips.md) должен выходить раньше, чем код дойдёт
    до onHeaderToggle (раскрытие узла) — порядок проверок в toggleFromEvent это
    гарантирует."""
    m = re.search(r"const toggleFromEvent = \(ev\) => \{(.*?)\n    \};", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена toggleFromEvent() в setupTreeEvents"
    body = m.group(1)
    head_idx = body.index('ev.target.closest(".tree-node-head")')
    for needle in (
        'ev.target.closest(".tkind-cb")',
        'ev.target.closest(".area-chip")',
        'ev.target.matches("input.tree-check")',
    ):
        idx = body.index(needle)
        assert idx < head_idx, f"{needle} должен проверяться раньше .tree-node-head (раскрытия)"
    assert "return;" in body


def test_tree_node_head_checkbox_is_inside_header_markup():
    """Чекбокс физически внутри .tree-node-head (один клик-хэндлер на всю шапку) —
    без этого проверка выше ничего не гарантирует на реальной разметке."""
    m = re.search(r"function nodeHeadHtml\(opts\) \{(.*?)\n  \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m
    body = m.group(1)
    head_div = re.search(r'<div class="tree-node-head"[^>]*>(.*?)</div>\s*`', body, re.DOTALL)
    assert head_div, "не найдена разметка .tree-node-head"
    assert 'input type="checkbox" class="tree-check tree-parent"' in head_div.group(1)


# ------------------------------------------------------------------ пресет-переключатели: подсветка + сортировка

def test_update_preset_buttons_toggles_active_class_by_dataset_preset():
    """Два ряда — две функции: updateProductButtons (ряд «Что») подсвечивает активный
    продукт; updateKindButtons (ряд «Как») подсвечивает активный вид и гасит (.dim)
    виды, недоступные для текущего продукта (SectionsTreeLogic.kindAvailableForProduct)."""
    m = re.search(r"function updateProductButtons\(\) \{(.*?)\n    \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена updateProductButtons()"
    assert 'btn.classList.toggle("active", btn.dataset.product === product)' in m.group(1)

    m2 = re.search(r"function updateKindButtons\(\) \{(.*?)\n    \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m2, "не найдена updateKindButtons()"
    body = m2.group(1)
    assert 'btn.classList.toggle("active", btnKind === kind)' in body
    assert 'btn.classList.toggle("dim", !SectionsTreeLogic.kindAvailableForProduct(btnKind, product))' in body


def test_preset_click_handler_sorts_tree_and_sets_active_preset():
    """Клик по виду (ряд «Как», kindsRow) выставляет kind (повторный клик по уже
    активному виду снимает его) и зовёт общий applyPresetChange(), который (как и
    клик по продукту, productsRow) пересчитывает раскрытые узлы через
    SectionsTreeLogic.expandedKeysForPreset."""
    m = re.search(r'kindsRow\.addEventListener\("click", \(ev\) => \{(.*?)\n      \}\);', PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найден обработчик клика по ряду «Как»"
    body = m.group(1)
    assert "kind = kind === clicked ? null : clicked;" in body
    assert "applyPresetChange();" in body

    apply_m = re.search(r"function applyPresetChange\(\) \{(.*?)\n    \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert apply_m, "не найдена applyPresetChange()"
    assert "SectionsTreeLogic.expandedKeysForPreset(data.kinds, kind)" in apply_m.group(1)


def test_render_sorts_kinds_for_active_preset_before_building_html():
    m = re.search(r"function render\(\) \{(.*?)\n    \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена render() в createSectionsPicker"
    body = m.group(1)
    assert "SectionsTreeLogic.sortKindsForPreset(filtered.kinds, kind)" in body
    assert "buildSectionsTreeHtml({ kinds: sortedKinds }" in body


def test_sections_preset_btn_active_class_styled_in_css():
    """С 03.11 правило — голова группы селекторов (вместе с варианта
    [data-preset].active/[data-product].active — см. комментарий про
    специфичность в style.css), не отдельное правило само по себе."""
    assert re.search(r"(?m)^\.sections-preset-btn\.active,$", STYLE_CSS)


# ------------------------------------------------------------------ строка итога: наличие и обновление

def test_summary_line_rendered_on_every_render_call():
    m = re.search(r"function render\(\) \{(.*?)\n    \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m
    assert "updateSummaryLine();" in m.group(1)


def test_summary_line_updates_on_manual_leaf_checkbox_change():
    """onLeafChange хук срабатывает на каждое 'change' события чекбокса-листа
    (ручной клик пользователя, не через пресет) и делает полный render() — строка
    вида/плашки областей (docs/missions/2026-11-03_area_chips.md) считаются по
    всему checked, точечным DOM-патчем (как раньше делал updateSummaryLine один)
    их не обновить; render() сам зовёт updateSummaryLine() в конце
    (test_summary_line_rendered_on_every_render_call)."""
    m = re.search(r"setupTreeEvents\(box, \{(.*?)\n    \}\);", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найден вызов setupTreeEvents() в createSectionsPicker"
    body = m.group(1)
    leaf_m = re.search(r"onLeafChange\(\) \{(.*?)\n      \},", body, re.DOTALL)
    assert leaf_m, "не найден onLeafChange() в вызове setupTreeEvents()"
    assert "snapshotChecked();" in leaf_m.group(1)
    assert "render();" in leaf_m.group(1)


def test_update_summary_line_shows_whatever_marker_is_currently_selected():
    """Строка итога читает сам селект (не activePreset) — маркер показывается
    и когда выставлен вручную из списка, без клика по кнопке."""
    m = re.search(r"function updateSummaryLine\(\) \{(.*?)\n    \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена updateSummaryLine()"
    body = m.group(1)
    assert "SectionsTreeLogic.countCheckedByKind(data, new Set(checkedFileTargets(box)))" in body
    assert "counts.total" in body and "counts.api" in body and "counts.ui" in body
    assert 'const marker = markerSelectEl ? markerSelectEl.value : "";' in body
    assert "if (marker) line += ` · маркер: ${marker}`;" in body


def test_e2e_preset_click_checks_only_e2e_section_not_whole_tree():
    """В отличие от smoke (presetLeafTargets без доп. фильтра — все файлы продукта),
    у e2e псевдо-раздел tests/e2e уже содержит ровно нужные тесты — applyPresetChange
    отмечает presetLeafTargets(data, { product, kind }) с kind="e2e", не allLeafTargets
    (его не зовёт больше никто в этом файле — проверено отдельно ниже)."""
    m = re.search(r"function applyPresetChange\(\) \{(.*?)\n    \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена applyPresetChange()"
    body = m.group(1)
    assert 'else if (kind === "e2e") markerSelectEl.value = "e2e";' in body
    assert "SectionsTreeLogic.presetLeafTargets(data, { product, kind })" in body
    assert "allLeafTargets" not in PROJECT_SECTIONS_PICKER_JS


def test_marker_select_change_highlights_matching_preset_button_without_touching_checked_files():
    m = re.search(r'markerSelectEl\.addEventListener\("change", \(\) => \{(.*?)\n      \}\);', PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найден обработчик change на селекте маркера"
    body = m.group(1)
    assert "kind = markerSelectEl.value || null;" in body
    assert "updateKindButtons();" in body
    assert "checked" not in body  # визуальная подсветка, выбор файлов не трогает


# ------------------------------------------------------------------ общий пикер на обеих вкладках

def test_both_tabs_use_the_same_create_sections_picker_factory():
    """createSectionsPicker теперь берёт отдельные productsRow/kindsRow (два ряда) и
    opts ({mobile, onStateChange}) — расписание передаёт mobile: false (у него нет
    кнопки Mobile в разметке, см. test_schedules_tab_has_same_presets_as_run_form_except_mobile),
    форма запуска — onStateChange, который дёргает updateBuildChip() (чип «Сборка: …»)
    и updateLiveCheckboxState() (докрутка «Эфир»/маркер-конфликта на клик по новой
    строке вида/плашке области — они меняют checked мимо "change"/кликов по
    sectionsProductsRow/sectionsKindsRow, см. docs/missions/2026-11-03_area_chips.md)."""
    picker_m = re.search(
        r"const sectionsPicker = createSectionsPicker\(\s*"
        r"sectionsTreeBox, sectionsSearchInput, sectionsProductsRow, sectionsKindsRow, markerSelect, "
        r"sectionsSummaryLine,\s*"
        r"\{(.*?)\}\s*\);",
        PROJECT_SECTIONS_PICKER_JS, re.DOTALL,
    )
    assert picker_m, "не найден const sectionsPicker = createSectionsPicker(...)"
    opts_body = picker_m.group(1)
    assert "mobile: true," in opts_body
    assert "updateBuildChip();" in opts_body
    assert "updateLiveCheckboxState();" in opts_body

    assert re.search(
        r"const schedSectionsPicker = createSectionsPicker\(\s*"
        r"schedSectionsTreeBox, schedSectionsSearchInput, schedSectionsProductsRow, schedSectionsKindsRow, "
        r"schedMarkerSelect, schedSectionsSummaryLine,\s*"
        r"\{ mobile: false \}\s*\);",
        PROJECT_SECTIONS_PICKER_JS,
    )


async def test_both_tabs_load_sections_data_into_both_pickers(client):
    m = re.search(r"async function loadSections\(\) \{(.*?)\n  \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена loadSections()"
    body = m.group(1)
    assert "sectionsPicker.setData(data);" in body
    assert "schedSectionsPicker.setData(data);" in body


# ------------------------------------------------------------------ пресет «Mobile»

def test_mobile_preset_button_checks_mobile_checkbox():
    """Клик по «Mobile» включает #mobile-checkbox (если ещё не включён) — иначе
    выбранные им tests/ui/mobile/* гоняются в обычном десктопном viewport вместо
    вёрстки Pixel 7, что бессмысленно (см. data-preset="mobile" в project.html).
    Это page-level обработчик ряда «Как» формы запуска (sectionsKindsRow), отдельный
    от общего kindsRow.addEventListener внутри createSectionsPicker — он только
    выбирает файлы, про галочку «Мобильный» не знает."""
    m = re.search(
        r'sectionsKindsRow\.addEventListener\("click", \(ev\) => \{(.*?)\n  \}\);',
        PROJECT_SECTIONS_PICKER_JS, re.DOTALL,
    )
    assert m, "не найден обработчик клика по ряду «Как» вкладки «Запуск»"
    body = m.group(1)
    assert 'presetBtn.dataset.preset === "mobile"' in body
    assert "mobileCheckbox.checked = true;" in body
    assert 'mobileCheckbox.dispatchEvent(new Event("change"));' in body


# ------------------------------------------------------------------ подсказка «Эфир» для схлопнутых целей

def test_tests_count_by_target_covers_area_and_kind_targets_not_only_files():
    """SectionsTreeLogic.collectTargets схлопывает полностью отмеченный раздел/область
    в путь папки ("tests/api"/"tests/api/notifications") — любой пресет, выбирающий
    раздел/область целиком (API/UI/E2E/Всё/Regression/Mobile), может прислать такую
    цель в RunLiveLogic.countTargetTests. Без записи для неё в testsCountByTarget()
    схлопнутая цель считалась бы как «1 тест» (фоллбек countTargetTests), занижая
    подсказку «Эфир доступен для прогонов до N тестов, выбрано …» — баг, замеченный
    владельцем на пресете Regression 16.10.2026 (показывало 56 вместо реального числа)."""
    m = re.search(r"function testsCountByTarget\(\) \{(.*?)\n  \}", PROJECT_SECTIONS_PICKER_JS, re.DOTALL)
    assert m, "не найдена testsCountByTarget()"
    body = m.group(1)
    assert "map[f.target] = f.tests_count;" in body, "файловый уровень карты пропал"
    assert "if (a.target) map[a.target] = areaTotal;" in body, "уровень области (area.target) не считается"
    assert "if (k.target) map[k.target] = kindTotal;" in body, "уровень раздела (kind.target) не считается"
