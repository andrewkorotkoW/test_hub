"""Smoke на разметку новой строки вида/плашек областей
(docs/missions/2026-11-03_area_chips.md, раздел 3) на РЕАЛЬНЫХ данных
проекта VSHGU, где один и тот же файл физически встречается в двух видах
(ui и e2e — см. раздел 2 миссии: `tests/ui/courses/.../test_user_scorm_
stream_flow.py` числится и в `ui/courses`, и в `e2e/None`).

Чистая логика дедупа (areaState/kindState/countCheckedByKind) уже покрыта
синтетическими node-тестами в tests/js/test_sections_tree_logic.js (задача
'logic-tests') — здесь задача другая: прогнать НАСТОЯЩИЕ функции разметки
(kindRowHtml/areaChipsHtml из ui/project-sections-picker.js, извлечены
регэкспом из реального файла, см. tests/js/test_sections_tree_render_dedup.js)
на данных из настоящего GET /api/projects/VSHGU/sections — чтобы ловить
расхождение чисел в разметке обеих форм, а не только в оторванной от
реализации логике."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_TEST_FILE = REPO_ROOT / "tests" / "js" / "test_sections_tree_render_dedup.js"


def _find_cross_kind_dup_target(data: dict) -> str:
    """Любой target файла, встречающийся в >1 виде (kindNode.kind) — на
    реальных данных VSHGU таких 21 (все из tests/ui/*, задублированные в
    tests/e2e, см. app.core.sections._e2e_virtual_files)."""
    seen = {}
    for kind_node in data["kinds"]:
        for area in kind_node["areas"]:
            for file_ in area["files"]:
                seen.setdefault(file_["target"], set()).add(kind_node["kind"])
    for target, kinds in seen.items():
        if len(kinds) > 1:
            return target
    return None


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
async def test_sections_tree_render_handles_real_cross_kind_duplicate(qa_client, tmp_path):
    resp = await qa_client.get("/api/projects/VSHGU/sections")
    if resp.status_code != 200:
        pytest.skip(f"проект VSHGU недоступен в этом окружении ({resp.status_code})")
    data = resp.json()

    dup_target = _find_cross_kind_dup_target(data)
    assert dup_target, (
        "на реальных данных VSHGU ожидался хотя бы один файл, задублированный "
        "между ui и e2e (docs/missions/2026-11-03_area_chips.md, раздел 2) — "
        "иначе сам кейс дедупа этим тестом не проверяется"
    )

    data_path = tmp_path / "sections.json"
    data_path.write_text(json.dumps(data))

    result = subprocess.run(
        ["node", str(JS_TEST_FILE), str(data_path), dup_target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"{JS_TEST_FILE.name} упал на target={dup_target}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "NOT OK" not in result.stdout
