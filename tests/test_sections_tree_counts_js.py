"""Счётчики тестов (fileTestCounts/uniqueTestCount/productTestCounts/countCheckedByKind)
при файле в двух видах с разным tests_count — node-тесты tests/js/test_sections_tree_counts.js."""
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JS_TEST_FILE = REPO_ROOT / "tests" / "js" / "test_sections_tree_counts.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_sections_tree_counts_js_suite_passes():
    result = subprocess.run(["node", str(JS_TEST_FILE)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"{JS_TEST_FILE.name} упал:\n{result.stdout}\n{result.stderr}"
    assert result.stdout.strip().splitlines()[-1].endswith("passed")
