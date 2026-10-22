"""app/core/fmt.py (форматы длительностей/имён для бота и PNG, как в вебе) и
allure_report.final_attempts (одна финальная попытка на тест при реранах) — 22.10.2026."""
from app.core import allure_report, charts
from app.core.fmt import fmt_dt, fmt_run_duration, fmt_test_duration, pass_rate, short_test_name


def test_fmt_run_duration_matches_run_window():
    assert fmt_run_duration(1382) == "23 мин 2 с"
    assert fmt_run_duration(45.4) == "45 с"
    assert fmt_run_duration(3 * 3600 + 2 * 60 + 5) == "3 ч 02 мин"
    assert fmt_run_duration(None) == "—"
    assert fmt_run_duration("x") == "—"


def test_fmt_test_duration_matches_common_js():
    assert fmt_test_duration(0.84) == "840 мс"
    assert fmt_test_duration(53.49) == "53.5 с"
    assert fmt_test_duration(277) == "4:37"
    assert fmt_test_duration(3612) == "1:00:12"
    assert fmt_test_duration(None) == "—"


def test_fmt_dt_and_pass_rate():
    assert fmt_dt("2026-10-19T22:01:33") == "19.10 22:01"
    assert fmt_dt(None) == "—"
    assert pass_rate({"passed": 4, "failed": 1, "broken": 0, "skipped": 7}) == 80
    assert pass_rate({"skipped": 3}) is None
    assert pass_rate(None) is None


def test_short_test_name_from_full_name_and_nodeid():
    assert short_test_name("tests.api.test_cas#test_sync") == "test_cas::test_sync"
    assert short_test_name("tests.api.test_cas.TestCas#test_sync") == "test_cas::test_sync"
    assert short_test_name("tests/api/test_cas.py::TestCas::test_sync[blacklist]") == "test_cas::test_sync[blacklist]"
    assert short_test_name("tests/ui/test_login.py::test_ok") == "test_login::test_ok"
    assert short_test_name("") == "—"


def test_final_attempts_keeps_latest_by_stop_ts_and_counts_attempts():
    tests = [
        {"name": "a#t1", "params": None, "status": "failed", "stop_ts": "2026-10-19T22:01:00"},
        {"name": "a#t2", "params": None, "status": "passed", "stop_ts": "2026-10-19T22:01:30"},
        {"name": "a#t1", "params": None, "status": "passed", "stop_ts": "2026-10-19T22:05:00"},
        {"name": "a#t3", "params": "x", "status": "failed", "stop_ts": None},
        {"name": "a#t3", "params": "y", "status": "passed", "stop_ts": None},
    ]
    final = allure_report.final_attempts(tests)
    assert [(t["name"], t.get("params"), t["status"], t["attempts"]) for t in final] == [
        ("a#t1", None, "passed", 2),
        ("a#t2", None, "passed", 1),
        ("a#t3", "x", "failed", 1),
        ("a#t3", "y", "passed", 1),
    ]
    # counts — по финальным попыткам: 3 passed, 1 failed, а не 7 строк с 57 %
    assert allure_report.counts_from_tests(tests) == {"passed": 3, "failed": 1, "broken": 0, "skipped": 0}


def test_final_attempts_without_stop_ts_takes_last_in_order():
    tests = [{"name": "a#t", "status": "passed"}, {"name": "a#t", "status": "failed"}]
    assert [t["status"] for t in allure_report.final_attempts(tests)] == ["failed"]


def test_init_db_recounts_finished_runs_once(db_path, isolated_allure_dir):
    """Однократный пересчёт runs.counts по финальным попыткам при старте
    (app.db._recount_run_counts_once, маркер — PRAGMA user_version)."""
    import json
    import sqlite3

    from app.config import settings
    from app.db import RECOUNT_FINAL_ATTEMPTS_VERSION, get_connection, init_db

    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO projects (name, path, venv) VALUES ('rc_proj', '/tmp/rc', '/tmp/rc/.venv')")
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts, repeat) "
            "VALUES ('rc_proj', NULL, 'all', 'failed', '2026-10-19T22:01:00', 'qa', ?, 1)",
            (json.dumps({"passed": 1, "failed": 1, "broken": 0, "skipped": 0}),),
        )
        run_id = cur.lastrowid
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
    finally:
        conn.close()
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "00-result.json").write_text(
        json.dumps({"status": "failed", "fullName": "a#t", "start": 0, "stop": 1000}), encoding="utf-8"
    )
    (results_dir / "01-result.json").write_text(
        json.dumps({"status": "passed", "fullName": "a#t", "start": 2000, "stop": 3000}), encoding="utf-8"
    )

    init_db()

    conn = sqlite3.connect(db_path)
    try:
        counts = json.loads(conn.execute("SELECT counts FROM runs WHERE id = ?", (run_id,)).fetchone()[0])
        assert counts == {"passed": 1, "failed": 0, "broken": 0, "skipped": 0}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == RECOUNT_FINAL_ATTEMPTS_VERSION
        # повторный init_db пересчёт не трогает (маркер уже выставлен)
        conn.execute("UPDATE runs SET counts = '{\"passed\": 9}' WHERE id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()
    init_db()
    conn = sqlite3.connect(db_path)
    try:
        assert json.loads(conn.execute("SELECT counts FROM runs WHERE id = ?", (run_id,)).fetchone()[0]) == {"passed": 9}
    finally:
        conn.close()


def test_trend_label_like_run_report_logic():
    assert charts.trend_label({"id": 96, "started": "2026-10-19T22:01:00"}) == "#96 · 19.10"
    assert charts.trend_label({"id": 7, "started": None}) == "#7"
    assert charts.trend_label({"started": "2026-10-19T22:01:00"}) == "19.10"
