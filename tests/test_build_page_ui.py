"""«Сборка тестов» (project.html?name=&set=<area>#run, этап 2 миссии
2026-10-01_coverage_k_and_test_sets.md) — DOM/разметка уровня, не покрытая чистой
логикой ui/build-page-logic.js (см. tests/test_build_page_logic_js.py и
tests/js/test_build_page_logic.js — там уже разобраны matchedBuildAreas/
totalTestsCount/leafTargetsFromAreas/latestRunByStand). Сценарий project.html —
несколько классических <script> (project-setup.js/project-*.js/project.js, делят
один lexical scope, см. шапку ui/project-setup.js), с `document`/`initPage()` на
верхнем уровне — исполнить в node нельзя (см. tests/test_run_window_split_ui.py
о том же приёме) — здесь, как и в test_project_tabs_ui.py, проверяем статикой
HTML/исходника JS без браузера.
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Сценарий project.html разбит на несколько файлов, делящих один lexical scope
# (см. шапку ui/project-setup.js): режим «Сборка тестов» — в ui/project-build.js,
# скрытие кнопок запуска для customer — в ui/project-setup.js (userReady.then(...)).
PROJECT_BUILD_JS = (REPO_ROOT / "ui" / "project-build.js").read_text()
PROJECT_SETUP_JS = (REPO_ROOT / "ui" / "project-setup.js").read_text()
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()


# ------------------------------------------------------------------ разметка режима сборки

def test_project_html_has_build_mode_elements():
    for needle in (
        'id="set-card"', 'id="set-title"', 'id="set-count"', 'id="set-composition-body"',
        'id="set-stand-status"', 'id="set-runs-feed"', 'id="set-target-summary"',
        'id="set-target-text"', 'id="set-edit-targets-btn"', 'id="tests-tree-block"',
    ):
        assert needle in PROJECT_HTML, f"{needle!r} не найден в project.html"


def test_set_card_hidden_by_default_js_shows_it_only_in_build_mode():
    # Статический hidden в разметке — initBuildMode() в project.js снимает его только
    # когда isBuildMode (?set= в URL), см. project.js:780-793.
    m = re.search(r'<div class="card set-card" id="set-card"([^>]*)>', PROJECT_HTML)
    assert m and "hidden" in m.group(1)
    assert "if (!isBuildMode) { setCard.hidden = true; return; }" in PROJECT_BUILD_JS
    assert "setCard.hidden = false;" in PROJECT_BUILD_JS


def test_target_field_hidden_until_edit_composition_clicked():
    # ?set=... должен скрывать поле целей (testsTreeBlock) до клика «Изменить состав»
    # и открывать сводку (setTargetSummary) — пункт 1 этапа 2 миссии.
    assert "testsTreeBlock.hidden = true;" in PROJECT_BUILD_JS
    assert "setTargetSummary.hidden = false;" in PROJECT_BUILD_JS
    m = re.search(
        r'setEditTargetsBtn\.addEventListener\("click", \(\) => \{([^}]*)\}\);',
        PROJECT_BUILD_JS,
    )
    assert m, "не найден обработчик клика «Изменить состав»"
    assert "testsTreeBlock.hidden = false;" in m.group(1)
    assert "setTargetSummary.hidden = true;" in m.group(1)


def test_build_runs_history_limited_to_10():
    # Пункт 4 этапа 2 миссии: «последние 10 прогонов».
    m = re.search(r"function renderSetRunsFeed\(buildRuns\) \{\s*const items = buildRuns\.slice\((\d+), (\d+)\);", PROJECT_BUILD_JS)
    assert m, "не найден срез истории прогонов сборки"
    assert m.group(1) == "0" and m.group(2) == "10"


def test_build_mode_uses_label_filter_on_runs_endpoint():
    assert re.search(
        r"/api/projects/\$\{encodeURIComponent\(projectName\)\}/runs\?label=\$\{encodeURIComponent\(buildLabel\)\}",
        PROJECT_BUILD_JS,
    ), "loadBuildRuns должен запрашивать GET .../runs?label=<area> (пункт 4 этапа 2 миссии)"


# ------------------------------------------------------------------ режим «только просмотр»

def test_customer_run_buttons_are_hidden_in_build_mode():
    assert 'if (user.role === "customer") {' in PROJECT_SETUP_JS
    assert 'document.getElementById("run-buttons-row").hidden = true;' in PROJECT_SETUP_JS


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Найденный дефект (не мой код, t3 уже в main): пункт 5 этапа 2 миссии "
        "docs/missions/2026-10-01_coverage_k_and_test_sets.md прямо требует, чтобы ссылка на "
        "сборку у customer И manager открывалась в режиме «только просмотр» (без кнопки "
        "запуска). В ui/project.js:143-145 кнопки run-buttons-row скрываются только для "
        "customer: `if (user.role === \"customer\") { ...hidden = true; }` — роль manager "
        "не проверяется вообще, кнопки «Запустить всё»/«Запустить выбранное» остаются "
        "видимыми и рабочими. Совпадает с тем, что POST /api/projects/{name}/runs "
        "(app/routers/runs.py) тоже разрешает manager запуск — т.е. баг именно в UI-гейте, "
        "не подстрахован бэкендом.\n"
        "Повтор: залогиниться как manager/manager, открыть "
        "project.html?name=<project>&set=<area>#run — «Запустить всё» видна и активна.\n"
        "Если это когда-нибудь починят (добавят manager в условие), тест XPASS-нет из-за "
        "strict=True — уберите маркер."
    ),
)
def test_manager_run_buttons_should_also_be_hidden_in_build_mode_per_mission_item_5():
    m = re.search(r'if \(user\.role === "customer"\) \{\s*document\.getElementById\("run-buttons-row"\)\.hidden = true;\s*\}', PROJECT_SETUP_JS)
    assert m, "не найден блок скрытия кнопок запуска для customer"
    assert "manager" in m.group(0), (
        "условие скрытия run-buttons-row должно включать и customer, и manager "
        "(пункт 5 этапа 2 миссии), но проверяет только customer"
    )
