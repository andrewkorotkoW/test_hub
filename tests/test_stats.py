"""Юнит-тесты app/core/stats.py — статистика по разделам проекта и её динамика
за 30 дней (см. миссию docs/missions/2026-09-26_clear_design_stats_sections.md,
часть 2).

По образцу tests/test_flaky.py: allure-results пишутся напрямую в изолированный
ALLURE_RESULTS_DIR (isolated_allure_dir, tests/conftest.py), runs/flaky_stats/
xfail_registry — напрямую в БД, без реального venv/pytest фикстурного проекта —
так тесты проверяют именно арифметику recalc(), а не раннер."""
import json
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.core import coverage, stats
from app.db import get_connection

PROJECT = "stats_proj"
STAND = "stage"


@pytest.fixture(autouse=True)
def isolated_stats_dir(tmp_path, monkeypatch):
    """stats.STATS_DIR — фиксированный путь внутри репозитория (см. app/core/stats.py),
    как и coverage.COVERAGE_DIR (tests/test_coverage_api.py::isolated_coverage_dir) —
    без изоляции recalc()/load_cached() писали бы и читали кэш из реального
    workspace/stats/ репозитория, приводя к утечкам между тестовыми сессиями."""
    monkeypatch.setattr(stats, "STATS_DIR", tmp_path / "stats_cache")


def _insert_project_and_stand(conn, project=PROJECT, stand=STAND):
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/does-not-matter', '.venv', '[]')",
        (project,),
    )
    if stand is not None:
        conn.execute(
            "INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (project, stand)
        )
    conn.commit()


def _insert_run(conn, *, project=PROJECT, stand=STAND, status="passed", target="all", started=None) -> int:
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
        "VALUES (?, ?, ?, ?, ?, 'qa', '{}')",
        (project, stand, target, status, started or "2024-01-01T00:00:00"),
    )
    conn.commit()
    return cur.lastrowid


def _write_result(run_id, prefix, full_name, status, *, start=0, stop=1000, message=None):
    """parse_results (app.core.allure_report) только *-result.json — суффикс обязателен."""
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fullName": full_name, "status": status, "start": start, "stop": stop}
    if message:
        payload["statusDetails"] = {"message": message}
    (results_dir / f"{prefix}-result.json").write_text(json.dumps(payload), encoding="utf-8")


# ------------------------------------------------------------------ чистые функции

@pytest.mark.parametrize(
    "full_name, expected",
    [
        ("tests.api.notifications.test_x#test_y", "api/notifications"),
        ("tests.ui.buk.test_x#test_y", "ui/buk"),
        ("tests.e2e.test_checkout#test_full_flow", "e2e"),
        ("tests.e2e.sub.test_checkout#test_full_flow", "e2e"),
        ("tests.api#test_top_level", "api"),
        ("tests.test_root#test_x", None),
        ("other.api.notifications.test_x#test_y", None),
        ("standalone#test_x", None),
    ],
)
def test_section_of_full_name(full_name, expected):
    assert stats._section_of_full_name(full_name) == expected


def test_discover_section_dirs_scans_api_ui_e2e_and_skips_dunder(tmp_path):
    root = tmp_path / "proj"
    (root / "tests" / "api" / "notifications").mkdir(parents=True)
    (root / "tests" / "api" / "__pycache__").mkdir(parents=True)
    (root / "tests" / "ui" / "buk").mkdir(parents=True)
    (root / "tests" / "e2e").mkdir(parents=True)

    sections = stats.discover_section_dirs(str(root))

    assert sections == ["api/notifications", "ui/buk", "e2e"]


def test_discover_section_dirs_missing_tests_dir_returns_empty(tmp_path):
    assert stats.discover_section_dirs(str(tmp_path / "no_such_project")) == []


# ------------------------------------------------------------------ recalc(): срез по разделам

@pytest.fixture()
def stats_project(db_path, isolated_allure_dir, tmp_path):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn)
    finally:
        conn.close()
    project_dir = tmp_path / "stats_proj_src"
    (project_dir / "tests" / "api" / "notifications").mkdir(parents=True)
    (project_dir / "tests" / "api" / "empty_area").mkdir(parents=True)
    (project_dir / "tests" / "ui" / "buk").mkdir(parents=True)
    conn = get_connection()
    try:
        conn.execute("UPDATE projects SET path = ? WHERE name = ?", (str(project_dir), PROJECT))
        conn.commit()
    finally:
        conn.close()
    return project_dir


def test_recalc_computes_section_summary_counts_and_percent(stats_project):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, target="all", status="failed")
    finally:
        conn.close()

    _write_result(run_id, "00", "tests.api.notifications#test_a", "passed")
    _write_result(run_id, "01", "tests.api.notifications#test_b", "passed")
    _write_result(run_id, "02", "tests.api.notifications#test_c", "failed")
    _write_result(run_id, "03", "tests.api.notifications#test_d", "broken")
    _write_result(run_id, "04", "tests.api.notifications#test_e", "skipped", message="xfail: known bug")
    _write_result(run_id, "05", "tests.api.notifications#test_f", "skipped")
    _write_result(run_id, "06", "tests.ui.buk#test_g", "passed", start=0, stop=2000)

    result = stats.recalc(PROJECT, STAND)

    sections = {s["section"]: s for s in result["sections"]}
    notif = sections["api/notifications"]
    assert notif["tests_total"] == 6
    assert notif["passed"] == 2
    # broken схлопывается в failed
    assert notif["failed"] == 2
    assert notif["xfail"] == 1
    assert notif["skipped"] == 1
    assert notif["passed_percent"] == pytest.approx(2 / 6 * 100, abs=0.05)

    buk = sections["ui/buk"]
    assert buk["tests_total"] == 1
    assert buk["avg_duration"] == pytest.approx(2.0)

    # раздел без единого теста в прогоне, но существующий на диске -> empty_sections
    assert "api/empty_area" in result["empty_sections"]
    assert sections["api/empty_area"]["tests_total"] == 0
    assert sections["api/empty_area"]["passed_percent"] is None
    assert sections["api/empty_area"]["avg_duration"] is None

    assert result["run_id"] == run_id
    assert result["cache_key_run_id"] == run_id


def test_recalc_avg_duration_only_counts_entries_with_duration(stats_project):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, target="all")
    finally:
        conn.close()
    _write_result(run_id, "00", "tests.api.notifications#test_a", "passed", start=0, stop=1000)
    _write_result(run_id, "01", "tests.api.notifications#test_b", "passed", start=0, stop=3000)

    result = stats.recalc(PROJECT, STAND)
    section = next(s for s in result["sections"] if s["section"] == "api/notifications")
    assert section["avg_duration"] == pytest.approx(2.0)


def test_recalc_top_slowest_sorted_descending_and_limited_to_ten(stats_project):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, target="all")
    finally:
        conn.close()
    for i in range(12):
        _write_result(
            run_id, f"{i:02d}", f"tests.api.notifications#test_{i}", "passed", start=0, stop=i * 1000
        )

    result = stats.recalc(PROJECT, STAND)
    durations = [t["duration"] for t in result["top_slowest"]]
    assert len(result["top_slowest"]) == 10
    assert durations == sorted(durations, reverse=True)
    assert durations[0] == 11.0
    assert result["top_slowest"][0]["section"] == "api/notifications"


def test_recalc_no_full_run_leaves_sections_empty_but_keeps_discovered_dirs(stats_project):
    result = stats.recalc(PROJECT, STAND)
    assert result["run_id"] is None
    sections = {s["section"] for s in result["sections"]}
    assert sections == {"api/notifications", "api/empty_area", "ui/buk"}
    assert set(result["empty_sections"]) == sections
    assert result["top_slowest"] == []


# ------------------------------------------------------------------ флаки/xfail по разделу

def test_recalc_flaky_and_xfail_counts_by_section(stats_project):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, target="all")
        conn.execute(
            "INSERT INTO flaky_stats (project, stand, test, runs, fails, flips, score, last_statuses, updated_at) "
            "VALUES (?, ?, ?, 5, 2, 3, 0.8, '[]', '2024-01-01')",
            (PROJECT, STAND, "tests.api.notifications#test_flaky"),
        )
        # ниже порога FLAKY_MIN_RUNS/FLAKY_THRESHOLD -> не должен попасть в счётчик
        conn.execute(
            "INSERT INTO flaky_stats (project, stand, test, runs, fails, flips, score, last_statuses, updated_at) "
            "VALUES (?, ?, ?, 5, 1, 1, 0.1, '[]', '2024-01-01')",
            (PROJECT, STAND, "tests.api.notifications#test_barely_flaky"),
        )
        conn.execute(
            "INSERT INTO xfail_registry (project, stand, test, reason, first_seen, state) "
            "VALUES (?, ?, ?, 'known bug', '2024-01-01', 'xfail')",
            (PROJECT, STAND, "tests.ui.buk#test_xfail"),
        )
        conn.commit()
    finally:
        conn.close()
    _write_result(run_id, "00", "tests.api.notifications#test_flaky", "passed")

    result = stats.recalc(PROJECT, STAND)
    sections = {s["section"]: s for s in result["sections"]}
    assert sections["api/notifications"]["flaky_count"] == 1
    assert sections["ui/buk"]["xfail_count"] == 1

    # top_flaky фильтрует только по FLAKY_MIN_RUNS (сортировка по score DESC) —
    # в отличие от flaky_count по разделу выше, порог FLAKY_THRESHOLD здесь не
    # применяется, поэтому test_barely_flaky тоже попадает в топ, но после test_flaky.
    top_flaky_tests = [t["test"] for t in result["top_flaky"]]
    assert top_flaky_tests == [
        "tests.api.notifications#test_flaky",
        "tests.api.notifications#test_barely_flaky",
    ]
    assert result["top_flaky"][0]["section"] == "api/notifications"


def test_recalc_without_stand_flaky_and_xfail_counts_are_zero(db_path, isolated_allure_dir, tmp_path):
    """flaky_stats.stand/xfail_registry.stand NOT NULL — без стенда данных нет."""
    project_dir = tmp_path / "no_stand_proj"
    (project_dir / "tests" / "api" / "notifications").mkdir(parents=True)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')",
            ("no_stand_proj", str(project_dir)),
        )
        run_id = _insert_run(conn, project="no_stand_proj", stand=None, target="all")
        conn.commit()
    finally:
        conn.close()
    _write_result(run_id, "00", "tests.api.notifications#test_a", "passed")

    result = stats.recalc("no_stand_proj", None)
    section = next(s for s in result["sections"] if s["section"] == "api/notifications")
    assert section["flaky_count"] == 0
    assert section["xfail_count"] == 0
    assert result["top_flaky"] == []


# ------------------------------------------------------------------ покрытие маршрутов по разделу

def test_recalc_routes_coverage_by_area(stats_project, monkeypatch, tmp_path):
    coverage_dir = tmp_path / "coverage_cache"
    monkeypatch.setattr(coverage, "COVERAGE_DIR", coverage_dir)
    cache = {
        "routes": [
            {"name": "notifications.index", "covered": True},
            {"name": "notifications.show", "covered": False},
            {"name": "buk.index", "covered": True},
        ]
    }
    path = coverage.cache_path(PROJECT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache), encoding="utf-8")

    conn = get_connection()
    try:
        run_id = _insert_run(conn, target="all")
    finally:
        conn.close()
    _write_result(run_id, "00", "tests.api.notifications#test_a", "passed")

    result = stats.recalc(PROJECT, STAND)
    sections = {s["section"]: s for s in result["sections"]}
    notif = sections["api/notifications"]
    assert notif["routes_total"] == 2
    assert notif["routes_covered"] == 1
    assert notif["routes_percent"] == 50.0

    buk = sections["ui/buk"]
    assert buk["routes_total"] == 1
    assert buk["routes_covered"] == 1
    assert buk["routes_percent"] == 100.0


def test_recalc_routes_coverage_absent_when_no_cache(stats_project):
    conn = get_connection()
    try:
        _insert_run(conn, target="all")
    finally:
        conn.close()
    result = stats.recalc(PROJECT, STAND)
    for section in result["sections"]:
        assert section["routes_total"] is None
        assert section["routes_covered"] is None
        assert section["routes_percent"] is None


# ------------------------------------------------------------------ динамика за 30 дней

def test_recalc_dynamics_excludes_runs_older_than_30_days(stats_project):
    now = datetime.now()
    old = (now - timedelta(days=45)).isoformat(timespec="seconds")
    recent = (now - timedelta(days=5)).isoformat(timespec="seconds")

    conn = get_connection()
    try:
        old_run = _insert_run(conn, target="all", started=old)
        recent_run = _insert_run(conn, target="all", started=recent)
    finally:
        conn.close()
    _write_result(old_run, "00", "tests.api.notifications#test_a", "passed")
    _write_result(recent_run, "00", "tests.api.notifications#test_a", "passed")

    result = stats.recalc(PROJECT, STAND)
    run_ids = {p["run_id"] for p in result["dynamics_project"]}
    assert run_ids == {recent_run}
    section_run_ids = {p["run_id"] for p in result["dynamics_by_section"]["api/notifications"]}
    assert section_run_ids == {recent_run}


def test_recalc_dynamics_project_passed_percent_and_duration(stats_project):
    recent = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        run_id = _insert_run(conn, target="all", status="passed", started=recent)
        conn.execute(
            "UPDATE runs SET counts = ?, duration = ? WHERE id = ?",
            (json.dumps({"passed": 3, "failed": 1, "skipped": 1}), 12.5, run_id),
        )
        conn.commit()
    finally:
        conn.close()

    result = stats.recalc(PROJECT, STAND)
    point = next(p for p in result["dynamics_project"] if p["run_id"] == run_id)
    assert point["passed_percent"] == 60.0
    assert point["duration"] == 12.5


# ------------------------------------------------------------------ кэш: cache_path/load_cached/latest_finished_run_id

def test_recalc_writes_cache_and_load_cached_reads_it_back(stats_project):
    result = stats.recalc(PROJECT, STAND)
    cached = stats.load_cached(PROJECT, STAND)
    assert cached == result
    assert stats.cache_path(PROJECT, STAND).is_file()


def test_load_cached_missing_file_returns_none(stats_project):
    assert stats.load_cached("no_such_project_at_all", STAND) is None


def test_load_cached_corrupt_json_returns_none(stats_project):
    path = stats.cache_path(PROJECT, STAND)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert stats.load_cached(PROJECT, STAND) is None


def test_latest_finished_run_id_ignores_queued_and_running(stats_project):
    conn = get_connection()
    try:
        assert stats.latest_finished_run_id(conn, PROJECT, STAND) is None
        _insert_run(conn, target="all", status="passed")
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, counts) VALUES (?, ?, 'all', 'running', '{}')",
            (PROJECT, STAND),
        )
        conn.commit()
        running_id = cur.lastrowid
        latest = stats.latest_finished_run_id(conn, PROJECT, STAND)
        assert latest is not None
        assert latest != running_id
    finally:
        conn.close()


def test_default_stand_returns_alphabetically_first(db_path):
    conn = get_connection()
    try:
        _insert_project_and_stand(conn, project="multi_stand_proj", stand=None)
        conn.execute(
            "INSERT INTO stands (project, name, url, login) VALUES (?, 'stage', '', NULL)",
            ("multi_stand_proj",),
        )
        conn.execute(
            "INSERT INTO stands (project, name, url, login) VALUES (?, 'develop', '', NULL)",
            ("multi_stand_proj",),
        )
        conn.commit()
        assert stats.default_stand(conn, "multi_stand_proj") == "develop"
        assert stats.default_stand(conn, "no_such_project") is None
    finally:
        conn.close()
