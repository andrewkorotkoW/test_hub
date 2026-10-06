"""Фронтенд «Мобильного» прогона (docs/missions/2026-10-06_mobile_frame.md, п.2-4):
галочка «Мобильный (Pixel 7)» рядом с «Эфир», рамка .phone-frame вокруг кадра эфира/
видео на странице прогона и на share-странице, пилюля «Pixel 7» в списке/таблице
прогонов и бейдж «Устройство: Pixel 7» в шапке.

По образцу tests/test_run_window_split_ui.py: без браузера — раздача статики и
наличие нужных id/классов в разметке, наличие соответствующей логики в исходниках
через re.search/подстроки. Чистая JS-логика рамки (phoneFrameEnabled/phoneFrameScale)
уже прогоняется через node в tests/test_run_live_logic_js.py (функции добавлены в
тот же tests/js/test_run_live_logic.js, не дублируем здесь).
"""
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()
PROJECT_JS = (REPO_ROOT / "ui" / "project.js").read_text()
SHARE_HTML = (REPO_ROOT / "ui" / "share.html").read_text()
SHARE_JS = (REPO_ROOT / "ui" / "share.js").read_text()
STYLE_CSS = (REPO_ROOT / "ui" / "style.css").read_text()
RUN_LIVE_LOGIC_JS = (REPO_ROOT / "ui" / "run-live-logic.js").read_text()


# ------------------------------------------------------------------ 1. форма запуска

async def test_project_html_has_mobile_checkbox_next_to_live(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="mobile-checkbox"' in html
    assert "Мобильный (Pixel 7)" in html
    assert "viewport 412" in html
    # галочка «Мобильный» идёт сразу после галочки «Эфир» (та же форма запуска)
    live_idx = html.index('id="live-checkbox-row"')
    mobile_idx = html.index('id="mobile-checkbox-row"')
    assert live_idx < mobile_idx


def test_project_js_mobile_checkbox_turns_on_live_but_does_not_block_manual_uncheck():
    assert 'document.getElementById("mobile-checkbox")' in PROJECT_JS
    m = PROJECT_JS.index('mobileCheckbox.addEventListener("change"')
    snippet = PROJECT_JS[m : m + 200]
    assert "liveCheckbox.checked = true" in snippet
    # никакого liveCheckbox.disabled = true здесь не выставляется — лимит эфира
    # продолжает решать submitRun сам через `liveCheckbox.checked && !liveCheckbox.disabled`
    assert "liveCheckbox.disabled" not in snippet


def test_project_js_submit_run_sends_mobile_flag():
    assert "mobile: mobileCheckbox.checked" in PROJECT_JS or "mobile," in PROJECT_JS
    assert "json: { stand: standSelect.value || null, target, marker: markerSelect.value || null, label, live, mobile }" in PROJECT_JS
    assert "mobileCheckbox.checked);" in PROJECT_JS


# ------------------------------------------------------------------ 2. чистые функции рамки

def test_run_live_logic_js_exports_phone_frame_helpers():
    assert "function phoneFrameEnabled(" in RUN_LIVE_LOGIC_JS
    assert "function phoneFrameScale(" in RUN_LIVE_LOGIC_JS
    assert "phoneFrameEnabled: phoneFrameEnabled" in RUN_LIVE_LOGIC_JS
    assert "phoneFrameScale: phoneFrameScale" in RUN_LIVE_LOGIC_JS
    # совместимость с node v12 (без optional chaining/nullish coalescing)
    assert "?." not in RUN_LIVE_LOGIC_JS
    assert "??" not in RUN_LIVE_LOGIC_JS


# ------------------------------------------------------------------ 3. CSS рамки

def test_style_css_has_phone_frame_class_sized_pixel7():
    assert ".phone-frame {" in STYLE_CSS
    assert "412 / 915" in STYLE_CSS
    assert "max-height" in STYLE_CSS.split(".phone-frame {", 1)[1].split("}", 1)[0]
    assert ".phone-frame-statusbar" in STYLE_CSS
    assert ".phone-frame-screen" in STYLE_CSS


# ------------------------------------------------------------------ 4. окно прогона: рамка + переключатель + бейджи

def test_project_js_wraps_live_and_video_tabs_in_phone_frame_when_run_mobile():
    assert "let currentRunMobile = false;" in PROJECT_JS
    assert "currentRunMobile = Boolean(payload.mobile);" in PROJECT_JS
    assert "function maybePhoneFrame(" in PROJECT_JS
    assert "if (!currentRunMobile) return innerHtml;" in PROJECT_JS
    # обе вкладки (Эфир/Видео) реально оборачиваются
    render_live = PROJECT_JS.index("function renderLiveTab()")
    render_video = PROJECT_JS.index("function renderVideoTab()")
    render_video_end = PROJECT_JS.index("function renderWindowBody()")
    assert "maybePhoneFrame(" in PROJECT_JS[render_live:render_video]
    assert "maybePhoneFrame(" in PROJECT_JS[render_video:render_video_end]


def test_project_js_has_no_frame_toggle_persisted_in_local_storage():
    assert 'th_phone_frame_off' in PROJECT_JS
    assert "localStorage.getItem(PHONE_FRAME_OFF_KEY)" in PROJECT_JS
    assert "localStorage.setItem(PHONE_FRAME_OFF_KEY" in PROJECT_JS
    assert "Без рамки" in PROJECT_JS


async def test_project_html_has_device_badge_hidden_by_default(client):
    resp = await client.get("/project.html")
    html = resp.text
    assert 'id="run-device-badge"' in html
    assert "Устройство: Pixel 7" in html
    badge_tag = html[html.index('id="run-device-badge"') - 60 : html.index('id="run-device-badge"') + 80]
    assert "hidden" in badge_tag


def test_project_js_toggles_device_badge_with_mobile_payload():
    assert "runDeviceBadge.hidden = !payload.mobile;" in PROJECT_JS
    assert "runDeviceBadge.hidden = true;" in PROJECT_JS


# ------------------------------------------------------------------ 5. пилюли «Pixel 7»

def test_project_js_renders_pixel7_pill_in_feed_and_table_next_to_live():
    assert 'r.mobile ? `<span class="badge-manual">Pixel 7</span>' in PROJECT_JS
    # ровно в тех же местах, где пилюля «эфир» — список прогонов и таблица истории
    assert PROJECT_JS.count('Pixel 7</span>') >= 2


# ------------------------------------------------------------------ 6. share-страница: та же рамка без логина

def test_share_html_includes_run_live_logic_for_phone_frame():
    assert '/run-live-logic.js' in SHARE_HTML
    assert 'id="live-frame-area"' in SHARE_HTML


def test_share_js_builds_phone_frame_from_run_mobile_without_touching_live_video_contract():
    assert "runMobile = Boolean(run.mobile);" in SHARE_JS
    assert "function maybePhoneFrame(" in SHARE_JS
    assert "RunLiveLogic.phoneFrameEnabled(" in SHARE_JS
    assert "th_phone_frame_off" in SHARE_JS
    # контракт /share/<token>/live.jpg и .../video не меняем — опрос остаётся по URL из data.json
    assert 'fetch(`${liveFrameUrl}' in SHARE_JS
    assert "video_url: `/share/" in SHARE_JS
