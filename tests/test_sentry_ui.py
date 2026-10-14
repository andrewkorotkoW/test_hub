"""UI-логика блока Sentry (ui/project.js + ui/project.html): карточка «Ошибки
продукта» на дашборде, вкладка Sentry в окне прогона — миссия
docs/missions/2026-09-29_sentry.md.

По образцу tests/test_project_tabs_ui.py / tests/test_run_window_split_ui.py:
без браузера — раздача статики + наличие нужных id в разметке + поведение,
которое зависит от DOM-событий, проверяется по исходнику через re.search (сам
project.js — не модуль, целиком в node не исполняется, см. мотивацию в
tests/js/test_run_window_split_logic.js). Чистая логика без DOM
(sentrySignalClass/sentryIssueRowHtml) вынесена в ui/sentry-logic.js
(window.SentryLogic) и реально прогоняется через node — см.
tests/js/test_sentry_logic.js и test_sentry_logic_js_suite_passes ниже.

Сценарий project.html разбит на несколько файлов, делящих один lexical scope
(см. шапку ui/project-setup.js): canSeeSentry объявлена и назначается в
ui/project-setup.js, карточка дашборда (renderSentryCard/loadSentryCard) —
в ui/project-dashboard.js, вкладка Sentry в окне прогона
(renderSentryTab/renderWindowTabs/openRun) — в ui/project-run-window.js.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

PROJECT_SETUP_JS = (REPO_ROOT / "ui" / "project-setup.js").read_text()
PROJECT_DASHBOARD_JS = (REPO_ROOT / "ui" / "project-dashboard.js").read_text()
PROJECT_RUN_WINDOW_JS = (REPO_ROOT / "ui" / "project-run-window.js").read_text()
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()

JS_LOGIC_FILE = REPO_ROOT / "tests" / "js" / "test_sentry_logic.js"


# ------------------------------------------------------------------ 1. разметка карточки дашборда

async def test_project_html_has_sentry_card_hidden_by_default(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="sentry-card" hidden' in html
    assert 'id="sentry-stand-select"' in html
    assert 'id="sentry-card-body"' in html


def test_project_html_sentry_card_wraps_stand_select_and_body():
    m = re.search(r'<div class="card" id="sentry-card"[^>]*>(.*?)\n    </div>', PROJECT_HTML, re.DOTALL)
    assert m, "не найдена карточка #sentry-card целиком"
    body = m.group(1)
    assert 'id="sentry-stand-select"' in body
    assert 'id="sentry-card-body"' in body


# ------------------------------------------------------------------ 2. видимость карточки только для qa/superadmin

def test_can_see_sentry_matches_qa_and_superadmin_only():
    """canSeeSentry — let в ui/project-setup.js (не const: назначается асинхронно
    внутри userReady.then(...), читается синхронно в файлах, подключённых позже
    — project-dashboard.js/project-run-window.js, см. их шапки)."""
    match = re.search(r'canSeeSentry = (.+);', PROJECT_SETUP_JS)
    assert match, "не найдено определение canSeeSentry в ui/project-setup.js"
    expr = match.group(1)
    assert 'user.role === "qa"' in expr
    assert 'user.role === "superadmin"' in expr
    # никакая другая роль явно не перечислена (manager/customer не должны видеть блок)
    assert '"manager"' not in expr
    assert '"customer"' not in expr


def test_sentry_card_hidden_flag_is_driven_by_can_see_sentry():
    assert "sentryCard.hidden = !canSeeSentry;" in PROJECT_SETUP_JS


# ------------------------------------------------------------------ 3. карточка дашборда: 5 строк, светофор, «не подключён»

def test_render_sentry_card_shows_disconnected_message_without_throwing():
    match = re.search(r"function renderSentryCard\(data, period\) \{(.*?)\n  \}", PROJECT_DASHBOARD_JS, re.DOTALL)
    assert match, "не найдена функция renderSentryCard() в ui/project-dashboard.js"
    body = match.group(1)
    assert "!data.connected" in body
    assert "Sentry не подключён" in body


def test_render_sentry_card_limits_to_five_rows_with_signal_dot():
    assert "const SENTRY_CARD_ROWS = 5;" in PROJECT_DASHBOARD_JS
    match = re.search(r"function renderSentryCard\(data, period\) \{(.*?)\n  \}", PROJECT_DASHBOARD_JS, re.DOTALL)
    body = match.group(1)
    assert "slice(0, SENTRY_CARD_ROWS)" in body
    assert "SentryLogic.sentrySignalClass(issues.length)" in body


def test_render_sentry_card_empty_issues_message():
    match = re.search(r"function renderSentryCard\(data, period\) \{(.*?)\n  \}", PROJECT_DASHBOARD_JS, re.DOTALL)
    body = match.group(1)
    assert "Issues за ${escapeHtml(p.label)} нет." in body


def test_load_sentry_card_requires_stand_selection_before_calling_api():
    match = re.search(r"async function loadSentryCard\(\) \{(.*?)\n  \}", PROJECT_DASHBOARD_JS, re.DOTALL)
    assert match, "не найдена функция loadSentryCard() в ui/project-dashboard.js"
    body = match.group(1)
    assert "if (!stand)" in body
    assert "Выберите стенд." in body
    # период карточки (1 ч / 4 ч / 24 ч / 14 д) — since и stats_period берутся из SENTRY_PERIODS
    assert "since=${encodeURIComponent(period.since)}" in body
    assert "stats_period=${period.stats}" in body
    assert '"24h": { since: "-24h"' in PROJECT_DASHBOARD_JS


# ------------------------------------------------------------------ 4. вкладка Sentry в окне прогона

def test_render_sentry_tab_shows_disconnected_and_empty_messages():
    match = re.search(r"function renderSentryTab\(\) \{(.*?)\n  \}", PROJECT_RUN_WINDOW_JS, re.DOTALL)
    assert match, "не найдена функция renderSentryTab() в ui/project-run-window.js"
    body = match.group(1)
    assert "!runSentryData || !runSentryData.connected" in body
    assert "Sentry не подключён" in body
    assert "Issues за окно прогона не найдено." in body


def test_render_sentry_tab_renders_rows_with_new_badge_enabled():
    match = re.search(r"function renderSentryTab\(\) \{(.*?)\n  \}", PROJECT_RUN_WINDOW_JS, re.DOTALL)
    body = match.group(1)
    # строка с раскрывающейся выжимкой события (sentryIssueItemHtml), бейдж «новое» включён
    assert "SentryLogic.sentryIssueItemHtml(i, { withNewBadge: true })" in body
    assert "SentryLogic.bindSentryDetails(runWindowBody" in PROJECT_RUN_WINDOW_JS


def test_window_tabs_include_sentry_only_when_can_see_sentry():
    """Sentry — последняя вкладка в RunLiveLogic.windowTabOrder(mediaTab, canSeeSentry)
    (docs/missions/2026-10-01_live_stream.md, п.4) — только видящим её роли."""
    match = re.search(r"function renderWindowTabs\(\)\s*\{(.*?)\n  \}", PROJECT_RUN_WINDOW_JS, re.DOTALL)
    assert match, "не найдена функция renderWindowTabs() в ui/project-run-window.js"
    body = match.group(1)
    assert "RunLiveLogic.windowTabOrder(currentMediaTab(), canSeeSentry)" in body
    assert 'sentry: `Sentry' in body


def test_render_window_body_dispatches_sentry_tab():
    assert 'runWindowBody.innerHTML = renderSentryTab();' in PROJECT_RUN_WINDOW_JS


def test_open_run_loads_run_sentry_data_for_qa_only():
    assert "if (canSeeSentry) {" in PROJECT_RUN_WINDOW_JS
    assert 'runSentryData = await api(`/api/runs/${runId}/sentry`);' in PROJECT_RUN_WINDOW_JS


# ------------------------------------------------------------------ чистая логика — реальный прогон через node

@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_sentry_logic_js_suite_passes():
    result = subprocess.run(
        ["node", str(JS_LOGIC_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"tests/js/test_sentry_logic.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "NOT OK" not in result.stdout
