"""Вкладка «Запуск»: сворачивание формы «Тесты» в строку-сводку при открытом прогоне
(карточка прогона на всю ширину вместо двух колонок по 560px — замечание владельца
19.10.2026, макеты https://claude.ai/code/artifact/12387439-a1e3-4b80-9491-d03115eadb5d,
вариант 2) и предупреждение «маркер × цели» над кнопками запуска (прогон #89: пресет
Mobile + маркер e2e — FAILED с 0 собранных тестов, молча).

Чистая логика предупреждения (SectionsTreeLogic.markerConflict/targetCoversFile) —
в tests/js/test_sections_tree_logic.js. Здесь — то, что физически в разметке и
DOM-коде (project.html / style.css / project-run-window.js / project-sections-picker.js),
не исполняемое в node: проверяем статикой, по образцу tests/test_sections_tree_ui_smoke.py."""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()
STYLE_CSS = (REPO_ROOT / "ui" / "style.css").read_text()
RUN_WINDOW_JS = (REPO_ROOT / "ui" / "project-run-window.js").read_text()
SECTIONS_PICKER_JS = (REPO_ROOT / "ui" / "project-sections-picker.js").read_text()
SECTIONS_LOGIC_JS = (REPO_ROOT / "ui" / "sections-tree-logic.js").read_text()
PROJECT_SETUP_JS = (REPO_ROOT / "ui" / "project-setup.js").read_text()


# ------------------------------------------------------------------ разметка

async def test_project_html_has_run_form_summary_inside_tests_card(client):
    html = (await client.get("/project.html")).text
    tests_card = html.index('id="tests-card"')
    summary = html.index('id="run-form-summary"')
    queue_notice = html.index('id="run-queue-notice"')
    run_card = html.index('id="run-card"')
    # сводка — внутри карточки формы, до баннера очереди (оба видны в свёрнутом виде)
    assert tests_card < summary < queue_notice < run_card
    assert re.search(r'id="run-form-summary"[^>]*\bhidden\b', html)


async def test_project_html_has_marker_conflict_hint_above_run_buttons(client):
    html = (await client.get("/project.html")).text
    hint = html.index('id="marker-conflict-hint"')
    buttons = html.index('id="run-buttons-row"')
    assert hint < buttons
    assert re.search(r'id="marker-conflict-hint"[^>]*class="hint-box warn marker-conflict-hint"[^>]*\bhidden\b', html)


def test_project_html_loads_sections_picker_before_run_window():
    # collapseRunForm/renderRunFormSummary читают sectionsPicker.checkedFiles() и
    # sectionsDataCache — они объявлены в project-sections-picker.js
    assert PROJECT_HTML.index('src="project-sections-picker.js"') < PROJECT_HTML.index('src="project-run-window.js"')


# ------------------------------------------------------------------ стили

def test_style_css_single_column_layout_and_collapsed_rule():
    assert "grid-template-columns: 1.1fr 1.4fr" not in STYLE_CSS
    assert "minmax(0, 1.1fr) minmax(0, 1.4fr)" not in STYLE_CSS
    # лимит ширины формы в 720px убран 20.10.2026 — форма на всю ширину колонки
    assert "#tests-card:not(.collapsed) { max-width:" not in STYLE_CSS
    assert "#tests-card.collapsed > :not(#run-form-summary):not(#run-queue-notice) { display: none; }" in STYLE_CSS
    # баннер очереди в свёрнутом виде не упирается в кнопки сводки
    assert "#tests-card.collapsed #run-queue-notice { margin-top: 12px; margin-bottom: 0; }" in STYLE_CSS
    assert ".hint-box.warn" in STYLE_CSS


# ------------------------------------------------------------------ DOM-код: сворачивание

def test_run_window_js_collapses_form_on_open_run_and_restores_on_edit():
    assert "function collapseRunForm()" in RUN_WINDOW_JS
    assert "function expandRunForm()" in RUN_WINDOW_JS
    open_run = RUN_WINDOW_JS[RUN_WINDOW_JS.index("async function openRun(runId)"):]
    open_run = open_run[: open_run.index("await refreshReport(runId)")]
    assert "collapseRunForm();" in open_run
    assert 'testsCard.classList.add("collapsed")' in RUN_WINDOW_JS
    assert 'testsCard.classList.remove("collapsed")' in RUN_WINDOW_JS
    assert 'closest("#run-form-edit-btn")' in RUN_WINDOW_JS
    assert 'closest("#run-form-rerun-btn")' in RUN_WINDOW_JS
    # «Запустить ещё раз» — через те же кнопки, что и обычный запуск (их валидация/alert)
    assert '(lastSubmitKind === "all" ? runAllBtn : runSelectedBtn).click()' in RUN_WINDOW_JS


def test_run_selected_with_empty_selection_hints_mobile_preset():
    # галочка «Мобильный» ≠ пресет «Mobile»: при пустом выборе подсказываем пресет
    handler = RUN_WINDOW_JS[RUN_WINDOW_JS.index('runSelectedBtn.addEventListener("click"'):]
    handler = handler[: handler.index("// ---------------- шаринг отчёта")]
    assert "alert(mobileCheckbox.checked" in handler
    assert "нажмите пресет «Mobile»" in handler
    assert "Отметьте хотя бы один раздел/файл или заполните ручное поле." in handler


def test_style_css_set_target_summary_respects_hidden():
    assert ".set-target-summary[hidden] { display: none; }" in STYLE_CSS


def test_run_all_button_passes_live_and_mobile_flags():
    # прогон #92 (19.10.2026): «Запустить всё» с отмеченным «Мобильный» уходил без
    # mobile/live — флаги передавались только из «Запустить выбранное»
    handler = RUN_WINDOW_JS[RUN_WINDOW_JS.index('runAllBtn.addEventListener("click"'):]
    handler = handler[: handler.index('runSelectedBtn.addEventListener("click"')]
    assert 'submitRun("all", isBuildMode ? buildLabel : null, liveCheckbox.checked && !liveCheckbox.disabled, mobileCheckbox.checked)' in handler
    assert 'submitRun("all");' not in handler


def test_run_window_js_summary_counts_use_leaf_files_not_collapsed_targets():
    # targets() схлопывает полностью отмеченный раздел в папку ("tests/ui") —
    # countCheckedByKind по такому набору дал бы 0 файлов для пресетов UI/Всё
    assert "sectionsPicker.checkedFiles()" in RUN_WINDOW_JS
    assert "checkedFiles() {" in SECTIONS_PICKER_JS
    summary_fn = RUN_WINDOW_JS[RUN_WINDOW_JS.index("function runFormTargetsText()"):]
    summary_fn = summary_fn[: summary_fn.index("function renderRunFormSummary()")]
    assert "countCheckedByKind(sectionsDataCache, new Set(checkedFiles))" in summary_fn
    assert "new Set(sectionsPicker.targets())" not in summary_fn


def test_project_setup_js_declares_new_dom_refs():
    for needle in (
        'const testsCard = document.getElementById("tests-card");',
        'const runFormSummary = document.getElementById("run-form-summary");',
        'const markerConflictHint = document.getElementById("marker-conflict-hint");',
    ):
        assert needle in PROJECT_SETUP_JS


# ------------------------------------------------------------------ DOM-код: предупреждение о маркере

def test_sections_picker_js_marker_conflict_hint_recomputed_on_every_selection_change():
    assert "function updateMarkerConflictHint()" in SECTIONS_PICKER_JS
    assert "SectionsTreeLogic.markerConflict(sectionsDataCache, marker, currentTargetLines())" in SECTIONS_PICKER_JS
    # вместе с подсказкой «Эфир» — она уже пересчитывается на дерево/пресеты/ручной ввод
    live_fn = SECTIONS_PICKER_JS[SECTIONS_PICKER_JS.index("function updateLiveCheckboxState()"):]
    live_fn = live_fn[: live_fn.index("function updateMarkerConflictHint()")]
    assert "updateMarkerConflictHint();" in live_fn
    assert 'markerSelect.addEventListener("change", updateMarkerConflictHint)' in SECTIONS_PICKER_JS
    # «Снять маркер» сбрасывает селект штатным change — пикер снимает подсветку пресета
    assert 'closest("#marker-conflict-clear-btn")' in SECTIONS_PICKER_JS
    assert 'markerSelect.dispatchEvent(new Event("change"))' in SECTIONS_PICKER_JS


def test_sections_tree_logic_exports_marker_conflict():
    assert "markerConflict: markerConflict," in SECTIONS_LOGIC_JS
    assert "targetCoversFile: targetCoversFile," in SECTIONS_LOGIC_JS
