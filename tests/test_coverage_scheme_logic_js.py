"""Юнит-тесты чистой JS-логики схемы продукта на странице покрытия (ui/coverage.js —
роутинг ортогональных связей/слияние edges с target/переход в дерево тестов по клику,
без DOM). Сама логика и тесты на node.js лежат в tests/js/test_coverage_scheme_logic.js;
этот файл просто гоняет её через pytest, чтобы `pytest` в CI ловил регрессии и там
(по образцу tests/test_coverage_tree_logic_js.py)."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_TEST_FILE = REPO_ROOT / "tests" / "js" / "test_coverage_scheme_logic.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_coverage_scheme_logic_js_suite_passes():
    result = subprocess.run(
        ["node", str(JS_TEST_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"tests/js/test_coverage_scheme_logic.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "NOT OK" not in result.stdout
