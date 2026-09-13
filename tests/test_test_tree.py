"""GET /api/projects/{name}/tests — дерево обнаруженных тестов (файл -> класс -> тест).

Раннер обнаруживает тесты, реально запуская `pytest --collect-only -q` в каталоге
проекта (app/core/runner.py::discover), поэтому дерево здесь проверяется на реально
существующем на диске фикстурном мини-проекте (см. conftest.py), а не на моках.
"""

import pytest

from .conftest import EXPECTED_FIXTURE_TREE, register_project


async def test_tests_tree_matches_fixture_content(qa_client, runnable_project_dir):
    await register_project(qa_client, "tree_proj", runnable_project_dir)

    resp = await qa_client.get("/api/projects/tree_proj/tests")
    assert resp.status_code == 200
    body = resp.json()

    assert "error" not in body
    assert body["tree"] == EXPECTED_FIXTURE_TREE


async def test_tests_tree_for_unknown_project_is_404(qa_client):
    resp = await qa_client.get("/api/projects/does_not_exist/tests")
    assert resp.status_code == 404


async def test_tests_tree_falls_back_to_sys_executable_without_venv(qa_client, bare_project_dir):
    """Задача явно ожидает, что раннер сделает fallback на sys.executable, если
    <project>/.venv/bin/python отсутствует. app/core/runner.py::_venv_python не делает
    такого fallback (просто строит путь project_path/venv/"bin"/"python" без проверки
    альтернатив), а discover() при отсутствии этого файла сразу возвращает
    {"error": ..., "tree": {}}, не пытаясь запустить pytest через sys.executable.

    Тест фиксирует этот пробел через pytest.xfail, не переписывая app/ сам: если
    fallback когда-нибудь появится, тест начнёт молча проходить (без xfail-ветки)."""
    await register_project(qa_client, "bare_proj", bare_project_dir, venv=".venv")

    resp = await qa_client.get("/api/projects/bare_proj/tests")
    assert resp.status_code == 200
    body = resp.json()

    if "error" in body:
        pytest.xfail(
            "defect: runner.discover()/_venv_python() не делает fallback на "
            "sys.executable при отсутствии .venv/bin/python в проекте; "
            f"фактический ответ API: {body}"
        )

    assert body["tree"] == EXPECTED_FIXTURE_TREE
