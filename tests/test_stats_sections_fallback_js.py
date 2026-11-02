"""Состояние «частичный прогон» и подпись источника на странице «Статистика»
(docs/missions/2026-11-02_review_fixes.md, п.2). Чистая логика
(targetLabel/fallbackStateHtml/sectionsSourceHtml) прогоняется через node
(tests/js/test_stats_sections_source_fallback.js), здесь — подключение в разметке
и то, что рендер действительно вызывает эти функции при отсутствии full_run."""
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JS_LOGIC_FILE = REPO_ROOT / "tests" / "js" / "test_stats_sections_source_fallback.js"
STATS_HTML = (REPO_ROOT / "ui" / "stats.html").read_text(encoding="utf-8")
STATS_JS = (REPO_ROOT / "ui" / "stats.js").read_text(encoding="utf-8")


def test_stats_html_has_source_caption_and_fallback_box():
    assert 'id="sections-source-caption"' in STATS_HTML
    assert 'id="sections-fallback-box"' in STATS_HTML
    assert 'id="sections-partial-note"' in STATS_HTML


def test_render_sections_shows_fallback_box_only_without_full_run():
    # !data.full_run && data.fallback_run -> показываем состояние "данных нет",
    # а не таблицу разделов в нулях (см. миссию, п.2)
    assert "if (!data.full_run && data.fallback_run) {" in STATS_JS
    assert "sectionsFallbackBox.innerHTML = fallbackStateHtml(data.fallback_run, standLabel);" in STATS_JS
    assert "sectionsTableWrap.hidden = true;" in STATS_JS


def test_fallback_button_marks_result_as_partial_and_skips_empty_sections():
    # кнопка "Показать по последнему прогону" считает по fallback_run, но
    # "Разделы без единого теста" не показывает (раздел не из цели != "без тестов")
    assert "sectionsPartialNote.textContent = `Частичный прогон, " in STATS_JS
    assert "sectionsEmptyBox.hidden = true;" in STATS_JS


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_stats_sections_source_fallback_js_suite_passes():
    result = subprocess.run(["node", str(JS_LOGIC_FILE)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"tests/js/test_stats_sections_source_fallback.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.stdout.strip().splitlines()[-1].endswith("passed")
