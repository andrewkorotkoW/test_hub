"""Юнит-тесты чистой JS-логики вкладки «Эфир»/«Видео» и слежения за прогоном
(ui/run-live-logic.js — выбор медиа-вкладки, "нет сигнала", авто-выбор теста по
test_start, порядок вкладок). Сама логика и тесты на node.js лежат в
tests/js/test_run_live_logic.js; этот файл гоняет её через pytest, по образцу
tests/test_testcases_logic_js.py."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_TEST_FILE = REPO_ROOT / "tests" / "js" / "test_run_live_logic.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_run_live_logic_js_suite_passes():
    result = subprocess.run(
        ["node", str(JS_TEST_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"tests/js/test_run_live_logic.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "NOT OK" not in result.stdout
