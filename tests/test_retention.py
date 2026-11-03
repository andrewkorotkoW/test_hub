"""Ретеншен файлов прогона на диске (app/core/retention.py, docs/missions/
2026-11-02_review_fixes.md п.5): purge_expired() удаляет каталоги video/frames/
allure-results/allure-reports у finished-прогонов старше TH_KEEP_*_DAYS, не трогая
строки runs/run_test_results/run_events (история и флаки от файлов не зависят —
см. tests/test_flaky.py::test_recalc_skips_run_purged_by_retention_without_crashing
для самого flaky.recalc); защищает прогоны с живой share-ссылкой; TH_KEEP_*_DAYS=0
означает "не удалять" для этой категории. Плюс disk_usage() и ручка суперадминки
POST /api/admin/retention/purge ("Очистить сейчас")."""
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.core import retention, runner
from app.db import get_connection

PROJECT = "ret_proj"


def _insert_run(conn, status="passed", finished_days_ago=None) -> int:
    now = datetime.now()
    finished = None
    if finished_days_ago is not None:
        finished = (now - timedelta(days=finished_days_ago)).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, finished, requested_by, counts) "
        "VALUES (?, NULL, 'all', ?, ?, ?, 'qa', '{}')",
        (PROJECT, status, now.isoformat(timespec="seconds"), finished),
    )
    conn.commit()
    return cur.lastrowid


def _insert_share_link(conn, run_id, token, revoked=0, expires_at=None):
    conn.execute(
        "INSERT INTO share_links (token, run_id, created_by, created_at, expires_at, revoked) "
        "VALUES (?, ?, 'qa', ?, ?, ?)",
        (token, run_id, datetime.now().isoformat(timespec="seconds"), expires_at, revoked),
    )
    conn.commit()


def _make_run_dirs(run_id):
    """Создаёт все 4 каталога прогона с файлом внутри — то, что purge_expired()
    должен(а) удалить/оставить."""
    video_dir = runner.video_dir(run_id)
    frames_dir = runner.frames_dir(run_id)
    results_dir = runner.allure_dir(run_id)
    report_dir = retention._report_dir(run_id)
    for d in (video_dir, frames_dir, results_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)
        (d / "file.bin").write_bytes(b"x" * 1024)
    return {"video": video_dir, "frames": frames_dir, "results": results_dir, "reports": report_dir}


@pytest.fixture()
def isolated_retention_dirs(isolated_allure_dir, isolated_frames_dir, isolated_video_dir):
    """Все 4 каталога ретеншена изолированы от боевого workspace/ одним фикстурным
    именем — покороче, чем перечислять три фикстуры conftest в каждом тесте."""


# ------------------------------------------------------------------ purge_expired: основной путь

def test_purge_removes_all_four_dirs_past_default_thresholds_keeps_db_rows(db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=100)  # старше всех 4 дефолтных порогов (14/30/90/30)
        conn.execute(
            "INSERT INTO run_test_results (run_id, nodeid, full_name, status) VALUES (?, 't.py::a', 't#a', 'passed')",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO run_events (run_id, ts, line, nodeid, kind) VALUES (?, '2024-01-01T00:00:00', 'x', NULL, 'line')",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 1, "frames": 1, "results": 1, "reports": 1}
    for path in dirs.values():
        assert not path.is_dir(), f"{path} должен быть удалён"

    conn = get_connection()
    try:
        run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert run_row is not None and run_row["status"] == "passed", "строка runs цела"
        test_result_row = conn.execute(
            "SELECT * FROM run_test_results WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert test_result_row is not None, "run_test_results цела и доступна как раньше"
        event_row = conn.execute("SELECT * FROM run_events WHERE run_id = ?", (run_id,)).fetchone()
        assert event_row is not None, "run_events цела и доступна как раньше"
    finally:
        conn.close()


def test_purge_leaves_recent_run_untouched(db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=1)  # моложе всех порогов
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 0, "frames": 0, "results": 0, "reports": 0}
    for path in dirs.values():
        assert path.is_dir(), f"{path} не должен быть тронут — прогон недостаточно старый"


def test_purge_ignores_run_without_finished_timestamp(db_path, isolated_retention_dirs):
    """running/queued-прогон (finished IS NULL) не кандидат на удаление вовсе,
    даже если бы каталоги были созданы очень давно."""
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "running", finished_days_ago=None)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 0, "frames": 0, "results": 0, "reports": 0}
    for path in dirs.values():
        assert path.is_dir()


# ------------------------------------------------------------------ живая share-ссылка защищает

def test_purge_skips_run_with_live_share_link_no_expiry(db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=100)
        _insert_share_link(conn, run_id, "tok-no-expiry", revoked=0, expires_at=None)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 0, "frames": 0, "results": 0, "reports": 0}
    for path in dirs.values():
        assert path.is_dir(), "живая ссылка без expires_at защищает прогон бессрочно"


def test_purge_skips_run_with_live_share_link_future_expiry(db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=100)
        future = (datetime.now() + timedelta(days=10)).isoformat(timespec="seconds")
        _insert_share_link(conn, run_id, "tok-future", revoked=0, expires_at=future)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 0, "frames": 0, "results": 0, "reports": 0}
    for path in dirs.values():
        assert path.is_dir(), "ссылка истекает в будущем — удаление откладывается до истечения"


def test_purge_does_not_skip_run_with_expired_share_link(db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=100)
        past = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        _insert_share_link(conn, run_id, "tok-past", revoked=0, expires_at=past)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 1, "frames": 1, "results": 1, "reports": 1}
    for path in dirs.values():
        assert not path.is_dir(), "ссылка уже истекла — не защищает"


def test_purge_does_not_skip_run_with_revoked_share_link(db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=100)
        _insert_share_link(conn, run_id, "tok-revoked", revoked=1, expires_at=None)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 1, "frames": 1, "results": 1, "reports": 1}
    for path in dirs.values():
        assert not path.is_dir(), "отозванная ссылка не защищает"


# ------------------------------------------------------------------ TH_KEEP_*_DAYS = 0 -> не удалять

@pytest.mark.parametrize(
    "zeroed_setting, protected_key",
    [
        ("TH_KEEP_VIDEO_DAYS", "video"),
        ("TH_KEEP_FRAMES_DAYS", "frames"),
        ("TH_KEEP_RESULTS_DAYS", "results"),
        ("TH_KEEP_REPORTS_DAYS", "reports"),
    ],
)
def test_zero_threshold_disables_deletion_only_for_that_category(
    db_path, isolated_retention_dirs, monkeypatch, zeroed_setting, protected_key
):
    monkeypatch.setattr(settings, zeroed_setting, 0)
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=1000)  # старше любых разумных порогов
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed[protected_key] == 0
    assert dirs[protected_key].is_dir(), f"{protected_key}: TH_KEEP_*_DAYS=0 — файлы не трогаются"
    for key, path in dirs.items():
        if key != protected_key:
            assert removed[key] == 1
            assert not path.is_dir(), f"{key}: должен быть удалён, порог не нулевой"


def test_all_zero_thresholds_is_a_noop(db_path, isolated_retention_dirs, monkeypatch):
    for name in ("TH_KEEP_VIDEO_DAYS", "TH_KEEP_FRAMES_DAYS", "TH_KEEP_RESULTS_DAYS", "TH_KEEP_REPORTS_DAYS"):
        monkeypatch.setattr(settings, name, 0)
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=1000)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    removed = retention.purge_expired()

    assert removed == {"video": 0, "frames": 0, "results": 0, "reports": 0}
    for path in dirs.values():
        assert path.is_dir()


# ------------------------------------------------------------------ disk_usage()

def test_disk_usage_sums_bytes_per_category(db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=1)
    finally:
        conn.close()
    video_dir = runner.video_dir(run_id)
    frames_dir = runner.frames_dir(run_id)
    results_dir = runner.allure_dir(run_id)
    report_dir = retention._report_dir(run_id)
    for d, size in ((video_dir, 500), (frames_dir, 700), (results_dir, 900), (report_dir, 1100)):
        d.mkdir(parents=True, exist_ok=True)
        (d / "f.bin").write_bytes(b"x" * size)

    usage = retention.disk_usage()

    assert usage == {"video": 500, "frames": 700, "results": 900, "reports": 1100}


def test_disk_usage_is_zero_for_missing_dirs(db_path, isolated_retention_dirs):
    assert retention.disk_usage() == {"video": 0, "frames": 0, "results": 0, "reports": 0}


# ------------------------------------------------------------------ суперадминка: обзор + «Очистить сейчас»

async def test_admin_overview_includes_disk_usage(superadmin_client, db_path, isolated_retention_dirs):
    resp = await superadmin_client.get("/api/admin/overview")
    assert resp.status_code == 200
    disk = resp.json()["disk"]
    assert set(disk.keys()) == {"video", "results", "reports", "frames"}
    assert all(isinstance(v, int) for v in disk.values())


async def test_admin_purge_now_deletes_expired_dirs_immediately(superadmin_client, db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=100)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    resp = await superadmin_client.post("/api/admin/retention/purge")

    assert resp.status_code == 200
    body = resp.json()
    assert body["removed"] == {"video": 1, "frames": 1, "results": 1, "reports": 1}
    assert body["disk"] == {"video": 0, "results": 0, "reports": 0, "frames": 0}
    for path in dirs.values():
        assert not path.is_dir()


async def test_admin_purge_now_respects_live_share_link(superadmin_client, db_path, isolated_retention_dirs):
    conn = get_connection()
    try:
        run_id = _insert_run(conn, "passed", finished_days_ago=100)
        _insert_share_link(conn, run_id, "tok-admin-live", revoked=0, expires_at=None)
    finally:
        conn.close()
    dirs = _make_run_dirs(run_id)

    resp = await superadmin_client.post("/api/admin/retention/purge")

    assert resp.status_code == 200
    assert resp.json()["removed"] == {"video": 0, "frames": 0, "results": 0, "reports": 0}
    for path in dirs.values():
        assert path.is_dir()


# ------------------------------------------------------------------ окно прогона: video_purged/frames_purged в API

async def test_list_run_tests_marks_video_purged_when_video_dir_is_gone_but_results_remain(
    qa_client, db_path, isolated_retention_dirs, runnable_project_dir
):
    """Видео (TH_KEEP_VIDEO_DAYS=14 по умолчанию) истекает раньше результатов
    (TH_KEEP_RESULTS_DAYS=90) — типичный случай: allure_dir ещё жив, per-test список
    строится как обычно, но video_dir уже удалён ретеншеном. video_purged=True и
    video_retention_days=14 — то, что ui/project-run-window.js использует, чтобы
    показать "Видео удалено по сроку хранения (14 дней)." вместо "Плагин не записал
    видео". Проект регистрируется (как и в test_run_tests_api.py), чтобы nodeid из
    run_test_videos (pytest-форма) совпал с nodeid, в который list_run_tests
    приводит allure fullName через статическое дерево — иначе has_video уйдёт в
    False просто из-за несовпадения форматов nodeid, и проверка ничего не скажет
    про video_purged."""
    import json

    from .conftest import register_project

    await register_project(qa_client, "ret_tree_proj", runnable_project_dir)
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, finished, requested_by, counts) "
            "VALUES ('ret_tree_proj', NULL, 'all', 'passed', ?, ?, 'qa', '{}')",
            (
                (datetime.now() - timedelta(days=20)).isoformat(timespec="seconds"),
                (datetime.now() - timedelta(days=20)).isoformat(timespec="seconds"),
            ),
        )
        run_id = cur.lastrowid
        nodeid = "tests/test_sample.py::test_ok"
        conn.execute(
            "INSERT INTO run_test_videos (run_id, nodeid, path, duration_ms, size, created_at) "
            "VALUES (?, ?, 'was-here.webm', 1500, 100, '2024-01-01T00:00:00')",
            (run_id, nodeid),
        )
        conn.commit()
    finally:
        conn.close()

    results_dir = runner.allure_dir(run_id)
    results_dir.mkdir(parents=True)
    (results_dir / "abc-result.json").write_text(
        json.dumps({"fullName": "tests.test_sample#test_ok", "name": "test_ok", "status": "passed", "start": 0, "stop": 1000})
    )
    assert not runner.video_dir(run_id).is_dir()  # видео никогда не писалось на этот диск (только строка в БД)

    resp = await qa_client.get(f"/api/runs/{run_id}/tests")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["nodeid"] == nodeid
    assert items[0]["has_video"] is True
    assert items[0]["video_purged"] is True
    assert items[0]["video_retention_days"] == settings.TH_KEEP_VIDEO_DAYS
    assert items[0]["frames_purged"] is False, "кадров у этого теста не было (frame_nodeids пуст) — purged не относится"
