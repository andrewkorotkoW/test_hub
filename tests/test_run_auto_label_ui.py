"""Автометка сборки (docs/missions/2026-11-03_product_presets.md, план раздел 2):
если владелец не задаёт свою метку (режим «Сборка», isBuildMode) и не отмечена
галочка «Мобильный», submitRun подставляет "<Продукт>"/"<Продукт> · <Вид>" по
текущей паре продукт/вид пикера (SectionsTreeLogic.buildAutoLabel, чистая логика
уже прогоняется через node — tests/js/test_sections_tree_logic.js, кейсы
"buildAutoLabel: ..."). Мобильный прогон автометку не получает вовсе (label:
null) — дефолт "Мобильный (Pixel 7)" подставляет бэкенд
(app/core/runner.py::submit_run, уже покрыт tests/test_runs_mobile_flag.py::
test_create_run_mobile_without_label_defaults_to_pixel7_label), иначе он бы
конфликтовал с "<Продукт> · Mobile" из buildAutoLabel.

По образцу tests/test_sections_tree_ui_smoke.py / tests/test_mobile_frame_ui.py:
без браузера — статика исходника ui/project-run-window.js через re.search/
подстроки (computeRunLabel/autoBuildLabel — DOM-код верхнеуровневого IIFE,
не исполняемый в node, см. их же шапки про тот же приём).
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT_RUN_WINDOW_JS = (REPO_ROOT / "ui" / "project-run-window.js").read_text()


def test_auto_build_label_reads_product_kind_from_picker_via_build_auto_label():
    m = re.search(r"function autoBuildLabel\(\) \{(.*?)\n  \}", PROJECT_RUN_WINDOW_JS, re.DOTALL)
    assert m, "не найдена autoBuildLabel()"
    body = m.group(1)
    assert "sectionsPicker.getProductKind()" in body
    assert "SectionsTreeLogic.buildAutoLabel(product, kind)" in body


def test_compute_run_label_prefers_build_mode_label_over_auto_label():
    m = re.search(r"function computeRunLabel\(\) \{(.*?)\n  \}", PROJECT_RUN_WINDOW_JS, re.DOTALL)
    assert m, "не найдена computeRunLabel()"
    body = m.group(1)
    assert "if (isBuildMode) return buildLabel;" in body


def test_compute_run_label_returns_null_for_mobile_run_not_product_kind_label():
    """helpdesk + api без галочки «Мобильный» -> автометка "Helpdesk · API"
    (computeRunLabel уходит в autoBuildLabel), но lms + Mobile (пресет "Mobile"
    сам включает #mobile-checkbox, см. test_mobile_preset_button_checks_mobile_checkbox
    в tests/test_sections_tree_ui_smoke.py) -> null, а не "LMS · Mobile": иначе
    submitRun отправил бы собственную метку, и бэкенд не подставил бы дефолт
    "Мобильный (Pixel 7)" (app/core/runner.py: `if label is None and mobile: ...`)."""
    m = re.search(r"function computeRunLabel\(\) \{(.*?)\n  \}", PROJECT_RUN_WINDOW_JS, re.DOTALL)
    assert m, "не найдена computeRunLabel()"
    body = m.group(1)
    assert "if (mobileCheckbox.checked) return null;" in body
    assert "return autoBuildLabel();" in body
    # null возвращается строго раньше вызова autoBuildLabel() — проверка по порядку строк
    mobile_line = body.index("if (mobileCheckbox.checked) return null;")
    auto_line = body.index("return autoBuildLabel();")
    assert mobile_line < auto_line


def test_update_build_chip_shows_pixel7_for_mobile_without_calling_auto_label_text():
    m = re.search(r"function updateBuildChip\(\) \{(.*?)\n  \}", PROJECT_RUN_WINDOW_JS, re.DOTALL)
    assert m, "не найдена updateBuildChip()"
    body = m.group(1)
    assert 'const label = isBuildMode ? buildLabel : (mobileCheckbox.checked ? "Мобильный (Pixel 7)" : autoBuildLabel());' in body
    assert 'runBuildChip.textContent = `Сборка: ${label || "—"}`;' in body
