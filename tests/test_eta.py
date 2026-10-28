"""ETA очереди прогонов (app/core/eta.py + GET .../runs[].eta, GET /runs/{id}/eta,
POST .../eta): медианы wall-time из run_events, overhead, раскрытие цели, оценка
прогона (история той же цели / по тестам / по типу), остаток выполняющегося с темпом,
позиции и старты в очереди. События и прогоны вставляются прямо в БД — реальный
pytest не гоняется; кэш пишется в tmp_path (monkeypatch settings.WORKSPACE_DIR)."""
import json
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.core import eta
from app.db import get_connection

PROJECT = "eta_proj"
STAND = "2420"
T0 = datetime(2026, 10, 28, 12, 0, 0)

TREE = {
    "tests/ui/lrs/test_a.py": {"TestA": ["test_one", "test_two"]},
    "tests/ui/lrs/test_b.py": {"": ["test_three"]},
    "tests/api/x/test_c.py": {"TestC": ["test_four"]},
}
NODEIDS = eta.flatten_tree(TREE)
A1, A2, B3, C4 = NODEIDS


@pytest.fixture()
def eta_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKSPACE_DIR", tmp_path / "workspace")
    return tmp_path / "workspace" / "eta"


def _seed_project(conn, workers=0):
    conn.execute("INSERT OR IGNORE INTO projects (name, path, venv, stands) VALUES (?, '/tmp/nope', '.venv', '[]')", (PROJECT,))
    conn.execute("INSERT OR IGNORE INTO stands (project, name, url, login, workers) VALUES (?, ?, '', NULL, ?)", (PROJECT, STAND, workers))
    conn.commit()


def _insert_run(conn, status="passed", started=T0, duration=None, target="tests/ui/lrs", marker=None, stand=STAND, repeat=1, live=0):
    finished = (started + timedelta(seconds=duration)).isoformat(timespec="seconds") if duration is not None else None
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, marker, status, started, finished, duration, requested_by, counts, repeat, live) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'qa', '{}', ?, ?)",
        (PROJECT, stand, target, marker, status, started.isoformat(timespec="seconds"), finished, duration, repeat, live),
    )
    conn.commit()
    return cur.lastrowid


def _events(conn, run_id, timeline, started=T0):
    """timeline: [(offset_s, kind, nodeid, status|None)] → run_events."""
    for offset, kind, nodeid, st in timeline:
        ts = (started + timedelta(seconds=offset)).isoformat(timespec="seconds")
        line = f"[TH] start {nodeid}" if kind == "start" else f"[TH] end {nodeid} {st}"
        conn.execute(
            "INSERT INTO run_events (run_id, ts, line, nodeid, kind) VALUES (?, ?, ?, ?, ?)",
            (run_id, ts, line, nodeid, "test_start" if kind == "start" else "test_end"),  # kind как у runner._parse_th_line
        )
    conn.commit()


def _finished_run(conn, started, durations, statuses=None, duration=None, **kw):
    """Прогон с тестами durations {nodeid: wall} подряд; duration прогона = сумма + overhead."""
    statuses = statuses or {}
    run_id = _insert_run(conn, started=started, duration=duration if duration is not None else sum(durations.values()) + 40, **kw)
    t = 5
    timeline = []
    for nodeid, wall in durations.items():
        timeline.append((t, "start", nodeid, None))
        t += wall
        timeline.append((t, "end", nodeid, statuses.get(nodeid, "passed")))
    _events(conn, run_id, timeline, started)
    return run_id


def _seed_history(conn):
    """Три прогона на стенде (длительность = тесты + 40 с overhead): A1 10/12/14 с, A2 20 с, B3 30/30/60 с,
    в последнем B3 упал; первые два — цель tests/ui/lrs (100 и 102 с), третий — два файла (134 с)."""
    _finished_run(conn, T0 - timedelta(hours=3), {A1: 10, A2: 20, B3: 30})
    _finished_run(conn, T0 - timedelta(hours=2), {A1: 12, A2: 20, B3: 30})
    _finished_run(conn, T0 - timedelta(hours=1), {A1: 14, A2: 20, B3: 60}, statuses={B3: "failed"}, target="tests/ui/lrs/test_a.py\ntests/ui/lrs/test_b.py")


# ------------------------------------------------------------------ сбор
def test_wall_times_sums_reruns_and_tracks_in_progress(db_path):
    conn = get_connection()
    _seed_project(conn)
    run_id = _insert_run(conn, status="running", duration=None)
    _events(conn, run_id, [
        (0, "start", A1, None), (10, "end", A1, "failed"),
        (10, "start", A1, None), (18, "end", A1, "passed"),   # повтор (--reruns) — суммируется
        (18, "start", A2, None),                               # ещё идёт
    ])
    total, status, in_progress = eta.wall_times(conn, run_id)
    assert total == {A1: 18.0}
    assert status == {A1: "passed"}
    assert list(in_progress) == [A2]


def test_build_cache_medians_overhead_failed_last_and_signatures(db_path, eta_dir):
    conn = get_connection()
    _seed_project(conn)
    _seed_history(conn)
    cache = eta.build_cache(conn, PROJECT, TREE)
    tests = cache["stands"][STAND]["tests"]
    assert tests[A1]["median"] == 12 and tests[A1]["n"] == 3
    assert tests[B3]["median"] == 30 and tests[B3]["failed_last"] is True
    assert tests[A2]["failed_last"] is False
    assert cache["stands"][STAND]["overhead"] == 40
    assert cache["any"]["tests"][A1]["median"] == 12
    assert cache["kind_defaults"]["ui"] == eta.KIND_DEFAULTS["ui"]  # < KIND_MIN_SAMPLES разных тестов
    assert cache["signatures"][eta.signature(STAND, "tests/ui/lrs", None)] == [102.0, 100.0]  # новые первыми
    assert cache["nodeids"] == NODEIDS
    written = eta.recalc(PROJECT, TREE)
    assert json.loads(eta.cache_path(PROJECT).read_text())["nodeids"] == NODEIDS
    assert written["project"] == PROJECT


# ------------------------------------------------------------------ раскрытие цели
def test_select_nodeids_dir_file_class_nodeid_options_all():
    assert eta.select_nodeids(NODEIDS, "all") == NODEIDS
    assert eta.select_nodeids(NODEIDS, "") == NODEIDS
    assert eta.select_nodeids(NODEIDS, "tests/ui/lrs") == [A1, A2, B3]
    assert eta.select_nodeids(NODEIDS, "tests/ui/lrs/") == [A1, A2, B3]
    assert eta.select_nodeids(NODEIDS, "tests/ui/lrs/test_a.py") == [A1, A2]
    assert eta.select_nodeids(NODEIDS, "tests/ui/lrs/test_a.py::TestA") == [A1, A2]
    assert eta.select_nodeids(NODEIDS, f"{A2}\n{C4}") == [A2, C4]
    assert eta.select_nodeids(NODEIDS, "--ignore=tests/api\ntests/ui/lrs/test_b.py") == [B3]
    assert eta.select_nodeids(NODEIDS, "--ignore=tests/api") == NODEIDS


# ------------------------------------------------------------------ оценка
def _cache(conn):
    return eta.build_cache(conn, PROJECT, TREE)


def test_estimate_run_prefers_same_target_history(db_path):
    conn = get_connection()
    _seed_project(conn)
    _seed_history(conn)
    est = eta.estimate_run(_cache(conn), STAND, "tests/ui/lrs")
    assert est["source"] == "same_runs" and est["rough"] is False
    assert (est["seconds"], est["low"], est["high"]) == (101, 100, 102)  # медиана/min/max двух прогонов той же цели


def test_estimate_run_by_tests_with_failed_double_fallbacks_and_workers(db_path):
    conn = get_connection()
    _seed_project(conn)
    _seed_history(conn)
    cache = _cache(conn)
    # test_b.py один раз шёл с другой целью → по тестам: overhead 40 + B3 30×2 (упал в последний раз)
    est = eta.estimate_run(cache, STAND, "tests/ui/lrs/test_b.py")
    assert est == {"seconds": 100, "low": 82, "high": 130, "rough": False, "source": "tests", "tests_total": 1, "tests_known": 1}
    # C4 без истории → KIND_DEFAULTS["api"] = 1 с, rough (0 известных из 1)
    est = eta.estimate_run(cache, STAND, "tests/api")
    assert est["seconds"] == 41 and est["rough"] is True and est["tests_known"] == 0
    # другой стенд: медианы из any (A1 12 + A2 20 + B3 30, без удвоения — failed_last только по стенду), overhead из any
    est = eta.estimate_run(cache, "develop", "tests/ui/lrs/test_a.py")
    assert est["seconds"] == 72 and est["rough"] is False
    # workers делят тестовую часть, не overhead; маркер делает оценку грубой
    est = eta.estimate_run(cache, STAND, "tests/ui/lrs/test_a.py", workers=2)
    assert est["seconds"] == 56
    assert eta.estimate_run(cache, STAND, "tests/ui/lrs/test_a.py", marker="smoke")["rough"] is True
    # repeat умножает всё
    assert eta.estimate_run(cache, STAND, "tests/ui/lrs/test_a.py", repeat=3)["seconds"] == 216
    # пустой кэш — по умолчанию
    assert eta.estimate_run({}, None, "tests/ui/lrs")["seconds"] == round(eta.OVERHEAD_DEFAULT)


def test_remaining_running_uses_pace_of_finished_tests(db_path):
    conn = get_connection()
    _seed_project(conn)
    _seed_history(conn)
    cache = _cache(conn)
    now = T0 + timedelta(seconds=100)
    run_id = _insert_run(conn, status="running", target="tests/ui/lrs", duration=None)
    # A1 (оценка 12) прошёл за 24 с → темп ×2; A2 идёт уже 40 с из оценки 20 → остаток 0; B3 30×2 (failed_last)
    _events(conn, run_id, [(0, "start", A1, None), (24, "end", A1, "passed"), (60, "start", A2, None)])
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    rem = eta.remaining_running(conn, cache, run, now=now)
    assert rem["done"] == 1 and rem["total"] == 3 and rem["elapsed"] == 100
    assert rem["pace"] == 2.0
    assert rem["seconds"] == 60  # (0 + 30) × 2
    assert rem["overdue"] is False  # A2 идёт 40 с при медиане 20 × темп 2 — ещё в пределах
    rem_late = eta.remaining_running(conn, cache, run, now=now + timedelta(seconds=30))
    assert rem_late["overdue"] is True  # A2 идёт 70 с > 20 × 2 — дольше оценки
    # ничего не завершено → не меньше, чем оценка − прошедшее
    run2 = _insert_run(conn, status="running", target="tests/ui/lrs", duration=None, started=T0 + timedelta(seconds=90))
    row2 = conn.execute("SELECT * FROM runs WHERE id = ?", (run2,)).fetchone()
    rem2 = eta.remaining_running(conn, cache, row2, now=now)
    assert rem2["done"] == 0 and rem2["seconds"] >= 101 - 10


def test_queue_eta_positions_and_cumulative_starts(db_path, eta_dir):
    conn = get_connection()
    _seed_project(conn)
    _seed_history(conn)
    eta.recalc(PROJECT, TREE)
    now = T0 + timedelta(seconds=100)
    running = _insert_run(conn, status="running", target="tests/ui/lrs", duration=None)
    _events(conn, running, [(0, "start", A1, None), (12, "end", A1, "passed")])
    q1 = _insert_run(conn, status="queued", target="tests/ui/lrs", duration=None, started=None if False else now)
    q2 = _insert_run(conn, status="queued", target="tests/api", duration=None, started=now)
    result = eta.queue_eta(conn, PROJECT, now)
    assert result[running]["kind"] == "running" and result[running]["done"] == 1
    remaining = result[running]["seconds"]
    assert result[q1] == {
        "kind": "queued", "position": 1, "start_in": remaining,
        "start_at": (now + timedelta(seconds=remaining)).isoformat(timespec="seconds"),
        "finish_at": (now + timedelta(seconds=remaining + 101)).isoformat(timespec="seconds"),
        "duration": 101, "low": 100, "high": 102, "rough": False, "source": "same_runs",
    }
    assert result[q2]["position"] == 2 and result[q2]["start_in"] == remaining + 101 and result[q2]["rough"] is True
    assert result[running]["overdue"] is False and result[q1]["rough"] is False
    # выполняющийся вышел за оценку → очередь за ним помечена как грубая (старт сдвинется)
    late = eta.queue_eta(conn, PROJECT, now + timedelta(hours=1))
    assert late[running]["overdue"] is True and late[q1]["rough"] is True
    assert set(result) == {running, q1, q2}


def test_queue_eta_without_cache_is_empty_and_form_estimate(db_path, eta_dir):
    conn = get_connection()
    _seed_project(conn)
    _seed_history(conn)
    assert eta.queue_eta(conn, PROJECT) == {}
    assert eta.estimate_for_form(conn, PROJECT, STAND, "tests/ui/lrs") is None
    eta.recalc(PROJECT, TREE)
    now = T0 + timedelta(seconds=100)
    assert eta.queue_eta(conn, PROJECT, now) == {}  # активных прогонов нет
    est = eta.estimate_for_form(conn, PROJECT, STAND, "tests/ui/lrs", now=now)
    assert est["queue_len"] == 0 and est["start_in"] == 0 and est["seconds"] == 101
    assert est["finish_at"] == (now + timedelta(seconds=101)).isoformat(timespec="seconds")
    _insert_run(conn, status="queued", target="tests/api", duration=None, started=now)
    est = eta.estimate_for_form(conn, PROJECT, STAND, "tests/ui/lrs", now=now)
    assert est["queue_len"] == 1 and est["start_in"] == 41 and est["start_at"] == (now + timedelta(seconds=41)).isoformat(timespec="seconds")


@pytest.mark.asyncio
async def test_hook_skips_project_without_venv_and_writes_nothing(db_path, eta_dir, monkeypatch):
    """Хук по завершении прогона у проекта без окружения (тестовые проекты с выдуманным
    path) ничего не считает и не пишет в workspace — иначе каждый тест раннера оставлял
    бы каталог в workspace/eta/."""
    conn = get_connection()
    _seed_project(conn)
    run_id = _insert_run(conn, duration=10)
    monkeypatch.setattr(settings, "TH_ETA_HOOK", True)
    await eta.on_run_finished(run_id)
    assert not eta_dir.exists()
    assert await eta.recalc_async("no_such_project") is None
    monkeypatch.setattr(settings, "TH_ETA_HOOK", False)
    await eta.on_run_finished(run_id)  # выключенный хук — тоже ничего не пишет
    assert not eta_dir.exists()


# ------------------------------------------------------------------ API
@pytest.mark.asyncio
async def test_runs_list_and_run_eta_endpoints(qa_client, eta_dir):
    conn = get_connection()
    _seed_project(conn)
    _seed_history(conn)
    queued = _insert_run(conn, status="queued", target="tests/ui/lrs", duration=None, started=T0)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/runs")
    assert resp.status_code == 200
    by_id = {r["id"]: r for r in resp.json()}
    assert by_id[queued]["eta"] is None  # кэша ещё нет
    assert all(r["eta"] is None for r in by_id.values())

    eta.recalc(PROJECT, TREE)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/runs")
    by_id = {r["id"]: r for r in resp.json()}
    assert by_id[queued]["eta"]["kind"] == "queued" and by_id[queued]["eta"]["position"] == 1
    assert by_id[queued]["eta"]["duration"] == 101
    finished_ids = [i for i in by_id if i != queued]
    assert all(by_id[i]["eta"] is None for i in finished_ids)

    resp = await qa_client.get(f"/api/runs/{queued}/eta")
    assert resp.status_code == 200 and resp.json()["position"] == 1
    resp = await qa_client.get(f"/api/runs/{finished_ids[0]}/eta")
    assert resp.status_code == 200 and resp.json() is None

    resp = await qa_client.post(f"/api/projects/{PROJECT}/eta", json={"stand": STAND, "target": "tests/ui/lrs/test_b.py"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue_len"] == 1 and body["start_in"] == 101 and body["seconds"] == 100 and body["rough"] is False

    resp = await qa_client.post("/api/projects/nope/eta", json={"target": "all"})
    assert resp.status_code == 404
