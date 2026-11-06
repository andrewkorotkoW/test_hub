"""Автообновление ленты прогонов/истории/баннера очереди на странице проекта
(решение владельца 06.11.2026): прогон на медленном стенде может идти часами, а
карточка «RUNNING» в ленте/истории застывала до ручной перезагрузки страницы —
ни лента, ни история сами не опрашивались, в отличие от баннера очереди на
«Запуске» (refreshQueueNotice, уже опрашивается каждые 15 с).

По образцу tests/test_mobile_frame_ui.py: без браузера — наличие нужного кода в
ui/project-dashboard.js через подстроки/regex, без запуска самого JS."""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT_DASHBOARD_JS = (REPO_ROOT / "ui" / "project-dashboard.js").read_text()


def test_poll_runs_feed_is_scheduled_every_25_seconds():
    assert "setInterval(pollRunsFeed, 25000);" in PROJECT_DASHBOARD_JS


def test_poll_runs_feed_refetches_runs_and_rerenders_cheap_parts_without_network():
    match = re.search(
        r"async function pollRunsFeed\(\) \{(.*?)\n  \}\n  setInterval\(pollRunsFeed",
        PROJECT_DASHBOARD_JS, re.S,
    )
    assert match, "pollRunsFeed не найдена в ui/project-dashboard.js"
    body = match.group(1)
    # Лёгкий опрос: только список прогонов, без /flaky или /xfail на каждый тик
    # (они и так по несколько секунд каждый из-за runner.discover() без кэша).
    assert "api(`/api/projects/${encodeURIComponent(projectName)}/runs`)" in body
    assert "/flaky" not in body
    assert "/xfail" not in body
    # Чистый рендер без сети — три существующие функции, без похода за данными.
    assert "renderQueueNotice();" in body
    assert "renderHistoryTable();" in body
    assert "renderRunsFeed(runs);" in body


def test_poll_runs_feed_refreshes_heavy_dashboard_only_right_after_a_run_finishes():
    match = re.search(r"async function pollRunsFeed\(\) \{(.*?)\n  \}\n", PROJECT_DASHBOARD_JS, re.S)
    assert match
    body = match.group(1)
    # Число активных (running/queued) прогонов уменьшилось — кто-то только что
    # завершился; тяжёлые виджеты дашборда (KPI/флаки/xfail/топ долгих тестов)
    # пересчитываются ОДИН раз в этот момент, а не на каждом 25-секундном тике.
    assert "pollKnownActiveIds.size > 0 && activeIds.size < pollKnownActiveIds.size" in body
    assert "if (justFinished) await renderDashboard(runs);" in body


def test_load_history_seeds_known_active_ids_for_the_first_poll_comparison():
    # Иначе первый тик после загрузки страницы (если прогон уже шёл до открытия
    # вкладки) не с чем сравнивать, и "только что завершился" не сработает.
    assert (
        "pollKnownActiveIds = new Set(runs.filter((r) => r.status === \"running\" || r.status === \"queued\")"
        in PROJECT_DASHBOARD_JS
    )
