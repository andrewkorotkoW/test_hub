"""Юнит-тесты чистой JS-логики вкладки «Данные» проекта (ui/datagen-logic.js —
подписи статусов/сущностей, сводка манифеста, проверка формы, фильтр удалённых; без DOM).
Сама логика и тесты на node.js — tests/js/test_datagen_logic.js; этот файл гоняет их
через pytest."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_TEST_FILE = REPO_ROOT / "tests" / "js" / "test_datagen_logic.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_datagen_logic_js_suite_passes():
    result = subprocess.run(["node", str(JS_TEST_FILE)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"tests/js/test_datagen_logic.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "NOT OK" not in result.stdout
