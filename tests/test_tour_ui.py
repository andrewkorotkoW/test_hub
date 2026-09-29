"""Онбординг-тур (ui/tour.js) — часть, проверяемая без браузера.

TOUR_STEPS/tourStepsForRole (чистые данные+функция без DOM) покрыты через node —
см. tests/test_tour_data.py/tests/js/test_tour_data.js. Остальная логика tour.js
(tourShowStep/tourRender/tourAdvance/tourFinish/...) перемешана с DOM: создаёт
элементы через document.createElement, читает getBoundingClientRect, дёргает
window.location/requestAnimationFrame — исполнить это в node без jsdom нельзя, а
jsdom в зависимостях репозитория нет. Поэтому по образцу
tests/test_project_tabs_ui.py/tests/test_redesign_ui_smoke.py проверяем то, что
доступно без исполнения JS: наличие нужного кода в исходнике через re.search
(тексты кнопок на русском, ключ localStorage, вызов /api/me/onboarded), разметку
меню в ui/common.js и раздачу tour.js статикой на нужных страницах. Полноценный
визуальный прогон тура (подсветка/позиционирование/переходы между страницами)
проверялся только вручную в браузере.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui"

TOUR_JS = (UI_DIR / "tour.js").read_text()
COMMON_JS = (UI_DIR / "common.js").read_text()

PAGES_WITH_SHELL = [
    "projects.html",
    "project.html",
    "coverage.html",
    "xfail.html",
    "admin_all.html",
    "admin.html",
    "stats.html",
]


# ------------------------------------------------------------------ старая статичная модалка удалена

def test_old_onboarding_modal_fully_removed():
    """t3 заменила ONBOARDING_STEPS/maybeShowOnboarding (ui/common.js) и разметку
    #onb-... на ui/tour.js — старое не должно остаться ни в одном ui/-файле рядом
    с новым туром (иначе на странице будут одновременно два онбординга)."""
    for path in UI_DIR.glob("*.js"):
        text = path.read_text()
        assert "ONBOARDING_STEPS" not in text, f"{path.name}: осталась старая ONBOARDING_STEPS"
        assert "maybeShowOnboarding" not in text, f"{path.name}: осталась старая maybeShowOnboarding"
    for path in UI_DIR.glob("*.html"):
        text = path.read_text()
        assert 'id="onb-' not in text, f"{path.name}: осталась разметка старой модалки #onb-..."


# ------------------------------------------------------------------ тексты/поведение — через исходник tour.js

def test_tour_js_storage_key_is_namespaced():
    match = re.search(r'TOUR_STORAGE_KEY\s*=\s*"([^"]+)"', TOUR_JS)
    assert match, "не найден TOUR_STORAGE_KEY в ui/tour.js"
    assert match.group(1) == "testhub-tour-state"


def test_tour_js_buttons_are_russian_next_and_skip():
    match = re.search(r"function tourShowStep\(state, steps\)\s*\{(.*?)\n\}", TOUR_JS, re.DOTALL)
    assert match, "не найдена функция tourShowStep() в ui/tour.js"
    body = match.group(1)
    assert 'id="tour-skip-btn"' in body
    assert "Пропустить" in body
    assert 'id="tour-next-btn"' in body
    assert "Дальше" in body
    assert "Готово" in body, "на последнем шаге кнопка «Дальше» должна становиться «Готово»"


def test_tour_js_finish_calls_onboarded_endpoint_and_clears_state():
    match = re.search(r"async function tourFinish\(\)\s*\{(.*?)\n\}", TOUR_JS, re.DOTALL)
    assert match, "не найдена функция tourFinish() в ui/tour.js"
    body = match.group(1)
    assert "tourClearState()" in body
    assert re.search(r'api\(\s*"/api/me/onboarded"\s*,\s*\{\s*method:\s*"POST"\s*\}\s*\)', body), (
        "tourFinish() должна дёргать POST /api/me/onboarded (app/routers/auth.py::set_onboarded)"
    )


def test_tour_js_skip_button_finishes_tour_without_advancing():
    """«Пропустить» должен вызывать tourFinish() напрямую, а не tourAdvance() — иначе
    это было бы «Дальше», а не полноценный пропуск тура."""
    match = re.search(r"tooltip\.querySelector\(\"#tour-skip-btn\"\)\.addEventListener\(\"click\", \(\) => (\w+)\(\)\);", TOUR_JS)
    assert match, "не найден обработчик клика на #tour-skip-btn в ui/tour.js"
    assert match.group(1) == "tourFinish"


def test_tour_js_next_button_advances_current_state_and_steps():
    match = re.search(
        r'tooltip\.querySelector\("#tour-next-btn"\)\.addEventListener\("click", \(\) => (\w+)\(([^)]*)\)\);',
        TOUR_JS,
    )
    assert match, "не найден обработчик клика на #tour-next-btn в ui/tour.js"
    assert match.group(1) == "tourAdvance"
    assert "state" in match.group(2) and "steps" in match.group(2)


def test_tour_js_exposes_continue_and_restart_entry_points():
    assert "window.TestHubTour = { continueIfActive: tourContinueIfActive, restart: tourRestart };" in TOUR_JS


def test_tour_js_continue_if_active_skips_when_already_onboarded_without_saved_state():
    match = re.search(r"function tourContinueIfActive\(user\)\s*\{(.*?)\n\}", TOUR_JS, re.DOTALL)
    assert match, "не найдена функция tourContinueIfActive() в ui/tour.js"
    body = match.group(1)
    assert "user.onboarded" in body
    assert "return;" in body


# ------------------------------------------------------------------ пункт меню «Показать тур» — ui/common.js

def test_common_js_has_show_tour_menu_item_wired_to_restart():
    assert 'id="tour-restart-btn"' in COMMON_JS
    assert "Показать тур" in COMMON_JS
    match = re.search(
        r'getElementById\("tour-restart-btn"\)\.addEventListener\("click", \(\) => \{(.*?)\n  \}\);',
        COMMON_JS,
        re.DOTALL,
    )
    assert match, "не найден обработчик клика на #tour-restart-btn в ui/common.js"
    body = match.group(1)
    assert "window.TestHubTour" in body
    assert "TestHubTour.restart(user)" in body


def test_common_js_init_page_continues_tour_after_auth():
    match = re.search(r"async function initPage\(\)\s*\{(.*?)\n\}", COMMON_JS, re.DOTALL)
    assert match, "не найдена функция initPage() в ui/common.js"
    body = match.group(1)
    assert "requireAuth()" in body
    assert "renderHeader(user)" in body
    assert "TestHubTour.continueIfActive(user)" in body


# ------------------------------------------------------------------ раздача статики + подключение на страницах

async def test_tour_js_served_as_javascript(client):
    resp = await client.get("/tour.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "TestHubTour" in resp.text


async def test_tour_script_tag_present_on_all_shell_pages(client):
    for page in PAGES_WITH_SHELL:
        resp = await client.get(f"/{page}")
        assert resp.status_code == 200, page
        assert 'src="tour.js"' in resp.text, f"{page}: не подключён <script src=\"tour.js\">"
