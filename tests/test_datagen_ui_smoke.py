"""Вкладка «Данные» проекта (project.html#data, 21.10.2026): генерация тестовых данных
на стенде через CLI проекта тестов и кнопка «Удалить данные». Чистая логика —
ui/datagen-logic.js (tests/js/test_datagen_logic.js), здесь статикой — разметка,
DOM-код ui/project-data.js, гейт роли в ui/project-setup.js, стили."""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui"
PROJECT_HTML = (UI_DIR / "project.html").read_text()
PROJECT_SETUP_JS = (UI_DIR / "project-setup.js").read_text()
PROJECT_DATA_JS = (UI_DIR / "project-data.js").read_text()
STYLE_CSS = (UI_DIR / "style.css").read_text()


def _data_panel():
    # Панель должна лежать внутри <main class="page"> вместе с остальными вкладками —
    # снаружи (после </main>) карточка рендерилась под сайдбаром на всю ширину (21.10.2026).
    m = re.search(r'<div class="tab-panel" data-tab-panel="data"[^>]*>(.*?)</main>', PROJECT_HTML, re.DOTALL)
    assert m, "панель вкладки «Данные» не найдена внутри <main>"
    assert '<div class="tab-panel" data-tab-panel="testcases"' in PROJECT_HTML[:m.start()]
    assert 'id="manual-run-modal-overlay"' not in m.group(1)
    return m.group(1)


def test_tab_link_is_hidden_by_default_and_panel_has_form_and_table():
    assert '<a href="#data" data-tab="data" hidden>Данные</a>' in PROJECT_HTML
    panel = _data_panel()
    assert 'id="data-card" hidden' in panel
    for needle in ('id="data-scenario-select"', 'id="data-stand-select"', 'id="data-count-input"',
                   'id="data-prefix-input"', 'id="data-create-btn"', 'id="data-rows"', 'id="data-show-deleted"',
                   'id="data-unsupported"', 'id="data-error"'):
        assert needle in panel, needle
    assert 'class="table-wrap table-sticky-head"' in panel
    assert "Удалить данные" in PROJECT_DATA_JS


def test_scripts_are_included_in_order():
    assert '<script src="datagen-logic.js"></script>' in PROJECT_HTML
    assert '<script src="project-data.js"></script>' in PROJECT_HTML
    assert PROJECT_HTML.index('<script src="datagen-logic.js">') < PROJECT_HTML.index('<script src="project-setup.js">')
    assert PROJECT_HTML.index('<script src="project-data.js">') < PROJECT_HTML.index('<script src="project.js">')


def test_role_gate_in_setup_js():
    assert 'canManageData = ["qa", "superadmin"].includes(user.role);' in PROJECT_SETUP_JS
    assert """projectTabsNav.querySelector('a[data-tab="data"]').hidden = !canManageData;""" in PROJECT_SETUP_JS
    assert "let canShare, canSeeSentry, canManageSchedules, canManageData;" in PROJECT_SETUP_JS


def test_data_js_uses_logic_and_api_contract():
    assert "const DgLogic = window.DatagenLogic;" in PROJECT_DATA_JS
    for needle in (
        "DgLogic.validateForm(form)",
        "DgLogic.groupScenarios(dgScenarios)",
        '<optgroup label="${escapeHtml(group.category)}">',
        "${escapeHtml(s.title || s.name)}</option>",
        "DgLogic.summaryText(batch.entities, 3)",
        "RunsHistoryLogic.fmtStarted(batch.created_at, now)",
        'class="dg-summary-text" title="${escapeHtml(summaryFull)}"',
        "DgLogic.statusPill(batch.status)",
        "DgLogic.statusLabel(batch.status)",
        "DgLogic.canDelete(batch)",
        "DgLogic.anyActive(dgBatches)",
        "DgLogic.visibleBatches(dgBatches, dataShowDeleted.checked)",
        "DgLogic.cleanupStatusFor(detail.cleanup, entry)",
        "`${dgApiBase()}/scenarios`",
        'method: "POST", json: form',
        'method: "DELETE"',
        "window.confirm(",
        "userReady.then(async () => {",
        "if (!canManageData) return;",
    ):
        assert needle in PROJECT_DATA_JS, needle


def test_open_log_spoilers_survive_rerender():
    """Пока партия активна, таблица перерисовывается раз в 3 с — раскрытый «Лог создания»
    не должен схлопываться (замечание владельца 21.10.2026): состояние спойлеров
    хранится в dgOpenLogs, рендер ставит open, toggle ловится на фазе захвата."""
    assert "const dgOpenLogs = new Set();" in PROJECT_DATA_JS
    assert 'dgOpenLogs.has(`${batchId}:${key}`) ? " open" : ""' in PROJECT_DATA_JS
    assert 'data-id="${batchId}" data-log="${key}"${open}' in PROJECT_DATA_JS
    assert 'dataRows.addEventListener("toggle", (event) => {' in PROJECT_DATA_JS
    assert "}, true);" in PROJECT_DATA_JS
    assert "dgScrollOpenLogs();" in PROJECT_DATA_JS


def test_style_css_rules():
    for needle in (".project-tabs a[hidden] { display: none; }", ".datagen-form {", ".datagen-form-row {",
                   ".dg-delete-btn {", ".dg-detail-row td {", ".dg-log {", ".dg-manifest {",
                   ".datagen-table { font-size: 12.5px; }", ".dg-summary-text { display: block; overflow: hidden; text-overflow: ellipsis;",
                   ".dg-actions button { padding: 3px 9px; font-size: 12px;"):
        assert needle in STYLE_CSS, needle
