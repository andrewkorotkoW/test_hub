"""Карточка прогона «Сплит» на вкладке «Запуск» (ui/project.html/project.js,
docs/missions/redesign/run_window): список тестов прогона слева, вкладки
Кадры/Консоль/Запросы справа, переключатель «Весь лог», деградация для старых
прогонов без разметки по nodeid.

По образцу tests/test_project_tabs_ui.py / tests/test_coverage_ui_routing.py /
tests/test_redesign_ui_smoke.py: без браузера — раздача статики, наличие нужных
id/data-атрибутов в разметке и (там, где поведение зависит от DOM-событий, не
исполняемых здесь) наличие соответствующей логики в исходнике project.js через
re.search/подстроки. Чистая логика без DOM (HTTP_LINE_RE/filterRequestLines,
normalizeTestStatus) реально прогоняется через node — см.
tests/js/test_run_window_split_logic.js и test_run_window_split_logic_js_suite_passes
ниже. Один сквозной API-тест (синтетические run_events в БД, как в
tests/test_run_tests_api.py) проверяет, что бэкенд отдаёт ровно те поля, которые
читает project.js.
"""
import hashlib
import pathlib
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from urllib.parse import quote

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

PROJECT_JS = (REPO_ROOT / "ui" / "project.js").read_text()
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()

JS_LOGIC_FILE = REPO_ROOT / "tests" / "js" / "test_run_window_split_logic.js"


# ------------------------------------------------------------------ 1. разметка сплит-карточки

async def test_project_html_run_card_has_split_container_and_view_toggle(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="run-split"' in html
    assert 'id="run-tests-rail"' in html
    assert 'id="run-tests-count"' in html
    assert 'id="run-window-tabs"' in html
    assert 'id="run-window-body"' in html
    # переключатель «Сплит»/«Весь лог»
    assert 'id="run-view-toggle"' in html
    assert 'data-view="split"' in html
    assert 'data-view="log"' in html
    assert 'id="run-log"' in html


def test_project_html_run_split_window_nested_inside_run_card():
    m = re.search(
        r'<div class="card" id="run-card"[^>]*>(.*?)\n      </div>\n    </div>',
        PROJECT_HTML,
        re.DOTALL,
    )
    assert m, "не найдена карточка #run-card целиком"
    body = m.group(1)
    for needle in ('id="run-split"', 'id="run-tests-rail"', 'id="run-window-tabs"', 'id="run-log"'):
        assert needle in body, f"{needle} не вложен в #run-card"


def test_project_js_renders_three_window_tabs_with_expected_data_attributes():
    """Вкладки Кадры/Консоль/Запросы рендерятся JS-ом (renderWindowTabs), а не
    статичной разметкой — проверяем сам шаблон в исходнике."""
    match = re.search(r"function renderWindowTabs\(\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена функция renderWindowTabs() в ui/project.js"
    body = match.group(1)
    assert 'data-tab="frame"' in body
    assert 'data-tab="console"' in body
    assert 'data-tab="req"' in body
    assert "Кадры" in body
    assert "Консоль" in body
    assert "Запросы" in body


def test_project_js_window_tabs_click_handler_switches_active_tab_and_rerenders():
    assert 'runWindowTabsBox.addEventListener("click"' in PROJECT_JS
    match = re.search(
        r'runWindowTabsBox\.addEventListener\("click", \(ev\) => \{(.*?)\n  \}\);',
        PROJECT_JS,
        re.DOTALL,
    )
    assert match, "не найден обработчик клика по вкладкам окна теста"
    body = match.group(1)
    assert "activeWindowTab = btn.dataset.tab" in body
    assert "renderWindowTabs()" in body
    assert "renderWindowBody()" in body


# ------------------------------------------------------------------ 2. WS test_start/test_end/step/frame

def test_project_js_ws_dispatch_covers_all_split_message_types():
    match = re.search(r'ws\.addEventListener\("message", \(ev\) => \{(.*?)\n    \}\);', PROJECT_JS, re.DOTALL)
    assert match, "не найден обработчик сообщений WS в openRun()"
    body = match.group(1)
    for msg_type, handler in [
        ("step", "handleSplitLineEvent(msg)"),
        ("test_start", "handleTestStart(msg)"),
        ("test_end", "handleTestEnd(msg)"),
        ("frame", "handleFrameEvent(msg)"),
    ]:
        assert f'msg.type === "{msg_type}"' in body, f"WS-сообщение типа {msg_type} не обрабатывается"
        assert handler in body


def test_project_js_handle_test_start_upserts_rail_row_and_sets_running():
    match = re.search(r"function handleTestStart\(msg\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена handleTestStart()"
    body = match.group(1)
    assert 'upsertSplitTest(msg.nodeid, { status: "running" })' in body
    assert "renderTestsRail()" in body
    assert "hasMarkup = true" in body


def test_project_js_handle_test_end_updates_status_from_th_end_line():
    match = re.search(r"function handleTestEnd\(msg\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена handleTestEnd()"
    body = match.group(1)
    assert "END_STATUS_RE" in body
    assert "upsertSplitTest(msg.nodeid" in body
    assert "renderTestsRail()" in body


def test_project_js_handle_split_line_event_appends_to_selected_test_log_only():
    match = re.search(r"function handleSplitLineEvent\(msg\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена handleSplitLineEvent()"
    body = match.group(1)
    # строка добавляется в окно только у выбранного в рельсе теста
    assert "if (selectedNodeid !== msg.nodeid) return;" in body
    assert "selectedTestLog = [...selectedTestLog, msg.line];" in body
    assert "renderWindowBody()" in body


def test_project_js_handle_frame_event_marks_has_frames_and_appends_filmstrip():
    match = re.search(r"function handleFrameEvent\(msg\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена handleFrameEvent()"
    body = match.group(1)
    assert "upsertSplitTest(msg.nodeid, { has_frames: true })" in body
    assert "selectedTestFrames = [...selectedTestFrames, { step: msg.step, url: msg.url }];" in body


def test_project_js_rail_click_selects_test_and_loads_its_window():
    assert 'runTestsRail.addEventListener("click"' in PROJECT_JS
    match = re.search(r"async function selectTest\(nodeid\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена selectTest()"
    body = match.group(1)
    assert "/tests/${encodeURIComponent(nodeid)}/log" in body
    assert "/tests/${encodeURIComponent(nodeid)}/frames" in body


# ------------------------------------------------------------------ 3. честная подпись «кадров нет»

def test_project_js_frames_tab_shows_explicit_caption_without_frames_not_just_spinner():
    match = re.search(r"function renderFramesTab\(\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена renderFramesTab()"
    body = match.group(1)
    empty_branch = re.search(r"if \(!selectedTestFrames\.length\) \{(.*?)\n    \}", body, re.DOTALL)
    assert empty_branch, "не найдена ветка пустых кадров в renderFramesTab()"
    branch_html = empty_branch.group(1)
    assert "Кадров нет" in branch_html
    # это не спиннер/заглушка загрузки, а объяснение причины
    assert "Загрузка" not in branch_html
    assert "API-тест" in branch_html or "плагин" in branch_html


# ------------------------------------------------------------------ 4. деградация для старых прогонов

def test_project_js_apply_view_mode_hides_split_and_toggle_without_markup():
    match = re.search(r"function applyViewMode\(\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена applyViewMode()"
    body = match.group(1)
    assert "const showSplit = hasMarkup && viewMode ===" in body
    assert "runSplit.hidden = !showSplit;" in body
    assert "runViewToggle.hidden = !hasMarkup;" in body
    # «Весь лог» доступен независимо от режима — противоположность showSplit
    assert "logBox.hidden = showSplit;" in body


def test_project_js_detect_markup_returns_false_for_empty_or_lineonly_run():
    match = re.search(r"async function detectMarkup\(runId\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена detectMarkup()"
    body = match.group(1)
    # GET /tests пуст (нет test_start/test_end) -> splitTests.length === 0 -> false сразу
    assert "if (!splitTests.length) return false;" in body


def test_project_js_reset_split_state_starts_with_markup_false():
    match = re.search(r"function resetSplitState\(\)\s*\{(.*?)\n  \}", PROJECT_JS, re.DOTALL)
    assert match, "не найдена resetSplitState()"
    body = match.group(1)
    assert "hasMarkup = false;" in body
    assert "applyViewMode();" in body


# ------------------------------------------------------------------ чистая логика — реальный прогон через node

@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_run_window_split_logic_js_suite_passes():
    result = subprocess.run(
        ["node", str(JS_LOGIC_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"tests/js/test_run_window_split_logic.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "NOT OK" not in result.stdout


# ------------------------------------------------------------------ 5. сквозной API-тест: бэкенд отдаёт то, что читает JS

def _insert_run(conn, project, status_, requested_by="qa"):
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, NULL, 'all', ?, ?, ?, '{}')",
        (project, status_, now, requested_by),
    )
    conn.commit()
    return cur.lastrowid


def _insert_event(conn, run_id, line, nodeid, kind):
    conn.execute(
        "INSERT INTO run_events (run_id, ts, line, nodeid, kind) VALUES (?, ?, ?, ?, ?)",
        (run_id, datetime.now().isoformat(timespec="seconds"), line, nodeid, kind),
    )
    conn.commit()


async def test_split_card_api_shape_matches_what_project_js_reads(qa_client, isolated_frames_dir, db_path):
    """project.js читает из /tests как минимум nodeid/status/has_frames (testRowHtml,
    normalizeTestStatus, upsertSplitTest), из /tests/{nodeid}/log — плоский массив
    строк (selectedTestLog передаётся прямо в filterRequestLines/renderConsoleBox),
    из /tests/{nodeid}/frames — список объектов с step и url (renderFramesTab
    читает f.step/f.url/cur.url). Синтетический run_events здесь имитирует то, что
    реально пишет test_hub_plugin: start -> step -> line -> frame -> end."""
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "running")
        nodeid = "tests/ui/test_x.py::test_foo"
        _insert_event(conn, run_id, f"[TH] start {nodeid}", nodeid, "test_start")
        step_line = f"[TH] step {nodeid} 1 открыть страницу"
        _insert_event(conn, run_id, step_line, nodeid, "step")
        _insert_event(conn, run_id, "GET /api/widget 200", nodeid, "line")
        _insert_event(conn, run_id, "не HTTP-строка вывода", nodeid, "line")
        h = hashlib.sha1(nodeid.encode()).hexdigest()[:16]
        _insert_event(conn, run_id, f"{h}/1.png", nodeid, "frame")
        _insert_event(conn, run_id, f"[TH] end {nodeid} passed", nodeid, "test_end")
    finally:
        conn.close()

    tests_resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert tests_resp.status_code == 200
    items = tests_resp.json()
    assert items == [
        {"nodeid": nodeid, "full_name": "tests.ui.test_x#test_foo", "status": "passed", "has_frames": True}
    ]
    # поля, которые реально читает project.js (testRowHtml/upsertSplitTest/normalizeTestStatus) —
    # full_name бэкенд отдаёт всегда (единый ключ — nodeid), но UI его пока не использует.
    assert {"nodeid", "status", "has_frames"} <= set(items[0].keys())

    log_resp = await qa_client.get(f"/api/runs/{run_id}/tests/{quote(nodeid, safe='')}/log")
    assert log_resp.status_code == 200
    log = log_resp.json()
    # selectedTestLog в project.js — плоский массив строк, без обёртки
    assert isinstance(log, list) and all(isinstance(line, str) for line in log)
    assert log == [step_line, "GET /api/widget 200", "не HTTP-строка вывода"]

    frames_resp = await qa_client.get(f"/api/runs/{run_id}/tests/{quote(nodeid, safe='')}/frames")
    assert frames_resp.status_code == 200
    frames = frames_resp.json()
    assert frames == [{"step": 1, "url": f"/api/runs/{run_id}/frames/{h}/1.png"}]
    # renderFramesTab использует ровно эти два поля у каждого элемента
    assert set(frames[0].keys()) == {"step", "url"}


async def test_split_card_api_old_run_without_markup_returns_empty_tests_list(qa_client, db_path):
    """Деградация: у старого прогона без [TH]-разметки (только kind='line') GET
    /tests возвращает пустой список -> detectMarkup()/refreshSplitTests() в
    project.js оставляют hasMarkup=false, сплит и переключатель скрыты."""
    conn = sqlite3.connect(db_path)
    try:
        run_id = _insert_run(conn, "any_proj", "passed")
        _insert_event(conn, run_id, "просто строка вывода pytest", None, "line")
        _insert_event(conn, run_id, "ещё одна строка без разметки", None, "line")
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert resp.status_code == 200
    assert resp.json() == []
