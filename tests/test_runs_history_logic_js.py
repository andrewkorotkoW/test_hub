"""Юнит-тесты чистой JS-логики вкладки «Прогоны» проекта (ui/runs-history-logic.js —
фильтры, варианты селектов, результат прогона, форматы даты/цели/тегов; без DOM).
Сама логика и тесты на node.js — tests/js/test_runs_history_logic.js; этот файл
гоняет их через pytest."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_TEST_FILE = REPO_ROOT / "tests" / "js" / "test_runs_history_logic.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_runs_history_logic_js_suite_passes():
    result = subprocess.run(["node", str(JS_TEST_FILE)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"tests/js/test_runs_history_logic.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "NOT OK" not in result.stdout
