"""Графики дашборда (ui/dashboard-charts-logic.js): бары самых долгих тестов, события
Sentry по часам, выбор «последнего прогона» с результатами. Чистая логика прогоняется
через node (tests/js/test_dashboard_charts_logic.js), здесь же — проверка подключения
в project.html и использования в ui/project-dashboard.js."""
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JS_LOGIC_FILE = REPO_ROOT / "tests" / "js" / "test_dashboard_charts_logic.js"
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text(encoding="utf-8")
DASHBOARD_JS = (REPO_ROOT / "ui" / "project-dashboard.js").read_text(encoding="utf-8")


def test_project_html_includes_charts_logic_before_dashboard_script():
    logic = PROJECT_HTML.index('<script src="dashboard-charts-logic.js"></script>')
    dashboard = PROJECT_HTML.index('<script src="project-dashboard.js"></script>')
    assert logic < dashboard
    assert 'id="longest-tests-chart"' in PROJECT_HTML
    assert 'id="longest-tests-run"' in PROJECT_HTML


def test_dashboard_uses_run_with_results_and_charts():
    assert "DashboardChartsLogic.pickRunWithResults(runs, 20)" in DASHBOARD_JS
    assert "DashboardChartsLogic.longestTestsBarsHtml(withDuration, { top: 10 })" in DASHBOARD_JS
    assert "DashboardChartsLogic.sentryHourlyBarsHtml(issues, { windowSeconds: p.windowSeconds" in DASHBOARD_JS
    assert 'id="sentry-period"' in PROJECT_HTML
    for period in ("1h", "4h", "24h", "14d"):
        assert f'"{period}": {{ since: "-{period}"' in DASHBOARD_JS
    assert "api(`/api/runs/${runs[0].id}/report`)" not in DASHBOARD_JS, "отчёт берётся у выбранного прогона, не у runs[0]"


@pytest.mark.skipif(shutil.which("node") is None, reason="node.js не установлен в окружении")
def test_dashboard_charts_logic_js_suite_passes():
    result = subprocess.run(["node", str(JS_LOGIC_FILE)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"tests/js/test_dashboard_charts_logic.js упал:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.stdout.strip().splitlines()[-1].endswith("passed")
