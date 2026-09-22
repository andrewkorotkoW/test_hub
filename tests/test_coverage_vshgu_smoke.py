"""Smoke-тест покрытия на РЕАЛЬНОМ проекте auto_tests_vshgu_cloude — только чтение:
app/core/coverage.analyze_project() исполняет исключительно ast.parse по файлам
проекта (api/endpoints/*.py, tests/**/test_*.py, conftest.py) и ничего в них не
пишет, поэтому recalc() безопасен для реального чек-аута на диске.

По аналогии с runnable_project_dir (tests/conftest.py) тест пропускается, если
в этой среде нет реального чек-аута auto_tests_vshgu_cloude с .venv — тогда
пропуск логичнее xfail, т.к. сам факт отсутствия проекта на диске не является
дефектом test_hub.

routes.tsv для auto_tests_vshgu_cloude уже скопирован в репозиторий test_hub
(workspace/coverage/auto_tests_vshgu_cloude/routes.tsv, см. задачу t1) — тест
копирует его в изолированный COVERAGE_DIR, не трогая ни реальный кэш test_hub,
ни сам проект auto_tests_vshgu_cloude.
"""

import shutil
from pathlib import Path

import pytest

from app.core import coverage
from app.db import VSHGU_PROJECT_NAME, VSHGU_PROJECT_PATH, VSHGU_PROJECT_VENV

REAL_ROUTES_TSV = (
    Path(__file__).resolve().parent.parent / "workspace" / "coverage" / VSHGU_PROJECT_NAME / "routes.tsv"
)
VSHGU_VENV_PYTHON = Path(VSHGU_PROJECT_PATH) / VSHGU_PROJECT_VENV / "bin" / "python"

pytestmark = pytest.mark.skipif(
    not VSHGU_VENV_PYTHON.is_file(),
    reason=f"нет реального чек-аута {VSHGU_PROJECT_PATH} с .venv в этой среде",
)


@pytest.fixture()
def isolated_coverage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "COVERAGE_DIR", tmp_path / "coverage")


async def test_vshgu_smoke_recalc_covers_routes_and_links_create_stream_test(qa_client, isolated_coverage_dir):
    assert REAL_ROUTES_TSV.is_file(), f"{REAL_ROUTES_TSV} отсутствует — см. задачу t1"
    dest = coverage.routes_tsv_path(VSHGU_PROJECT_NAME)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_ROUTES_TSV, dest)

    resp = await qa_client.post(f"/api/projects/{VSHGU_PROJECT_NAME}/coverage/recalc")
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["routes_total"] > 0
    assert summary["routes_covered"] > 0

    detail_resp = await qa_client.get(
        f"/api/projects/{VSHGU_PROJECT_NAME}/coverage/route",
        params={"method": "POST", "path": "/api/v1/programs/{program}/streams"},
    )
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["name"] == "programs.streams.store"

    nodeids = {t["nodeid"] for t in detail["tests"]}
    assert any(
        nodeid.startswith("tests/api/programs/test_create_stream_api.py::") for nodeid in nodeids
    ), f"нет связи маршрут<->тест с test_create_stream_api.py среди {sorted(nodeids)}"
