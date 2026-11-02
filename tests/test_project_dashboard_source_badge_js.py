"""Подпись источника «по прогону #N · стенд · дата» и бейдж «· N стенд» у «% passed»
на дашборде (docs/missions/2026-11-02_review_fixes.md, п.1). Чистая логика
(kpiSourceHtml/standBadgeText/runMetrics) прогоняется через node
(tests/js/test_project_dashboard_source_badge.js), здесь — подключение в разметке
и то, что рендер действительно вызывает эти функции, а не рисует плитки без
источника."""
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JS_LOGIC_FILE = REPO_ROOT / "tests" / "js" / "test_project_dashboard_source_badge.js"
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text(encoding="utf-8")
DASHBOARD_JS = (REPO_ROOT / "ui" / "project-dashboard.js").read_text(encoding="utf-8")


def test_project_html_has_kpi_and_donut_source_boxes():
    assert 'id="kpi-source"' in PROJECT_HTML
    assert 'id="status-donut-source"' in PROJECT_HTML


def test_dashboard_renders_kpi_source_and_stand_badge_for_the_same_source_run():
    # обе подписи (плитки KPI и кольцо «Статусы последнего прогона») рисуются по
    # тому же sourceRun, что и сами плитки — не runs[0]
    assert "renderKpiSource(sourceRun);" in DASHBOARD_JS
    assert "standBadgeText(sourceRun)" in DASHBOARD_JS
    assert "sourceRun ? runMetrics(sourceRun) : null, standBadgeText(sourceRun));" in DASHBOARD_JS


def test_stand_badge_title_explains_infra_cause_threshold():
    # title бейджа объясняет происхождение (app/core/failure_causes.py), не просто «· N стенд»
    assert "доля падений с инфраструктурной причиной" in DASHBOARD_JS
    assert "app/core/failure_causes.py" in DASHBOARD_JS


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_project_dashboard_source_badge_js_suite_passes():
    result = subprocess.run(["node", str(JS_LOGIC_FILE)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"tests/js/test_project_dashboard_source_badge.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.stdout.strip().splitlines()[-1].endswith("passed")
