"""Оценка времени ожидания в очереди прогонов (ETA) — макет и формулы согласованы с
владельцем 28.10.2026 (артефакт «Очередь test_hub: ETA»).

Откуда время одного теста: события раннера "[TH] start/end <nodeid>" в run_events
пишутся с меткой времени (app.core.runner._log_line) — разница даёт wall-time теста
ВМЕСТЕ с фикстурами (создание пользователей/курсов по API, логин). allure `duration`
для этого не годится: там только тело теста (на прогоне #100 — 3 482 с из 7 803).
Повторы (--reruns) того же nodeid в одном прогоне суммируются — так в медиану
попадает реальная цена падающего теста.

Кэш workspace/eta/<проект>/eta.json пересчитывается по завершении каждого прогона
(хук runner.register_finalize_hook → on_run_finished) и содержит:
  stands[stand].tests[nodeid] = {median, p25, p75, n, failed_last} по последним
      HISTORY_RUNS завершённым прогонам стенда;
  stands[stand].overhead — медиана (duration прогона − Σ wall-time его тестов): старт
      сессии pytest, сбор тестов, allure;
  any — то же по всем стендам проекта (fallback для теста без истории на стенде);
  kind_defaults — медиана по типу тестов (tests/ui → "ui", tests/api → "api"), последний
      fallback (тест вообще без истории → пометка rough);
  signatures["<stand>|<target>|<marker>"] — длительности последних SAME_RUNS прогонов
      с той же целью: если их ≥ 2, оценка берётся прямо из них (в ней уже и повторы,
      и маркер, который по nodeid'ам применить нельзя);
  nodeids — плоский список дерева тестов (runner.discover) для раскрытия цели прогона
      (каталог/файл/класс/nodeid построчно, как в runner.count_target_tests).

Оценка прогона: overhead + Σ медиан тестов цели + ещё по медиане на каждый тест,
упавший в последнем прогоне стенда (reruns=1) — ÷ workers стенда (xdist, не при
live/repeat) × repeat. Диапазон low/high — ×RANGE_LOW/×RANGE_HIGH от тестовой части:
коэффициент вариации wall-time одного теста между прогонами ≈ 0.9 (таймауты, повторы,
нагрузка стенда), поэтому точной цифры нет и не будет — только «≈» с вилкой.

Остаток выполняющегося прогона: Σ оценок ещё не завершённых тестов цели × темп,
где темп = факт завершённых / их оценка (в границах PACE_MIN…PACE_MAX) — так цифра
сдвигается, когда стенд тормозит, а не висит. Старт прогона в очереди = сейчас +
остаток выполняющегося + Σ оценок прогонов перед ним (очередь в test_hub общая на
проект, не на стенд — app.core.runner.submit_run)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from ..config import settings
from ..db import get_connection

logger = logging.getLogger(__name__)


def eta_dir() -> Path:
    """Каталог кэша — от settings.WORKSPACE_DIR в момент вызова (не на импорте), чтобы
    тесты с monkeypatch WORKSPACE_DIR не писали в рабочий workspace."""
    return settings.WORKSPACE_DIR / "eta"

HISTORY_RUNS = 5
ANY_HISTORY_RUNS = 10
SAME_RUNS = 3
KIND_DEFAULTS = {"ui": 15.0, "api": 1.0, "e2e": 30.0, "": 5.0}
KIND_MIN_SAMPLES = 5
OVERHEAD_DEFAULT = 45.0
PACE_MIN, PACE_MAX = 0.5, 3.0
RANGE_LOW, RANGE_HIGH = 0.7, 1.5
FINISHED_STATUSES = ("passed", "failed")
FAILED_TEST_STATUSES = {"failed", "broken", "error"}

_END_RE = re.compile(r"^\[TH\] end (?P<nodeid>.+) (?P<st>\S+)$")


def cache_path(project_name: str) -> Path:
    return eta_dir() / project_name / "eta.json"


def load_cached(project_name: str) -> dict | None:
    path = cache_path(project_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ сбор истории
def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def wall_times(conn: sqlite3.Connection, run_id: int) -> tuple[dict[str, float], dict[str, str], dict[str, datetime]]:
    """По событиям прогона (run_events.kind = test_start/test_end, см. runner._parse_th_line):
    {nodeid: wall-time с, суммарно по повторам}, {nodeid: статус последнего завершения},
    {nodeid: ts старта незавершённого теста}."""
    rows = conn.execute(
        "SELECT ts, line, nodeid, kind FROM run_events WHERE run_id = ? AND kind IN ('test_start', 'test_end') ORDER BY id",
        (run_id,),
    ).fetchall()
    started: dict[str, datetime] = {}
    total: dict[str, float] = {}
    status: dict[str, str] = {}
    for row in rows:
        nodeid = row["nodeid"]
        if not nodeid:
            continue
        if row["kind"] == "test_start":
            started[nodeid] = _parse_ts(row["ts"])
        elif row["kind"] == "test_end" and nodeid in started:
            delta = (_parse_ts(row["ts"]) - started.pop(nodeid)).total_seconds()
            total[nodeid] = total.get(nodeid, 0.0) + max(delta, 0.0)
            m = _END_RE.match(row["line"] or "")
            status[nodeid] = m.group("st") if m else "unknown"
    return total, status, started


def _quantiles(values: list[float]) -> dict:
    ordered = sorted(values)
    n = len(ordered)
    q = lambda p: ordered[min(n - 1, max(0, round((n - 1) * p)))]  # noqa: E731
    return {"median": round(statistics.median(ordered), 1), "p25": round(q(0.25), 1), "p75": round(q(0.75), 1), "n": n}


def _runs_for(conn: sqlite3.Connection, project: str, stand: str | None, limit: int) -> list[sqlite3.Row]:
    sql = (
        "SELECT id, stand, target, marker, duration, repeat FROM runs WHERE project = ? AND status IN ('passed', 'failed') "
        "AND duration IS NOT NULL"
    )
    params: list = [project]
    if stand is not None:
        sql += " AND stand = ?"
        params.append(stand)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _bucket(conn: sqlite3.Connection, runs: list[sqlite3.Row]) -> dict:
    """Медианы по тестам и overhead по списку прогонов (новые — первыми)."""
    samples: dict[str, list[float]] = {}
    failed_last: dict[str, bool] = {}
    overheads: list[float] = []
    for run in runs:
        total, status, _ = wall_times(conn, run["id"])
        if not total:
            continue
        for nodeid, seconds in total.items():
            samples.setdefault(nodeid, []).append(seconds)
            if nodeid not in failed_last:
                failed_last[nodeid] = status.get(nodeid) in FAILED_TEST_STATUSES
        if run["duration"] and (run["repeat"] or 1) <= 1:
            overheads.append(max(0.0, run["duration"] - sum(total.values())))
    tests = {nodeid: {**_quantiles(v), "failed_last": failed_last.get(nodeid, False)} for nodeid, v in samples.items()}
    overhead = round(statistics.median(overheads), 1) if overheads else None
    return {"tests": tests, "overhead": overhead, "runs": [r["id"] for r in runs]}


def test_kind(nodeid: str) -> str:
    parts = nodeid.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "tests" else ""


def flatten_tree(tree: dict) -> list[str]:
    """Дерево runner.discover() {file: {class: [tests]}} → список nodeid."""
    out: list[str] = []
    for file_path, classes in (tree or {}).items():
        for cls_name, tests in classes.items():
            for test_name in tests:
                out.append(f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}")
    return out


def signature(stand: str | None, target: str, marker: str | None) -> str:
    return f"{stand or ''}|{(target or 'all').strip()}|{marker or ''}"


def build_cache(conn: sqlite3.Connection, project: str, tree: dict | None) -> dict:
    stands = [
        r["stand"] for r in conn.execute(
            "SELECT DISTINCT stand FROM runs WHERE project = ? AND stand IS NOT NULL AND status IN ('passed', 'failed')",
            (project,),
        ).fetchall()
    ]
    cache: dict = {
        "project": project,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stands": {stand: _bucket(conn, _runs_for(conn, project, stand, HISTORY_RUNS)) for stand in stands},
        "any": _bucket(conn, _runs_for(conn, project, None, ANY_HISTORY_RUNS)),
        "signatures": {},
        "nodeids": flatten_tree(tree) if tree else [],
    }
    by_kind: dict[str, list[float]] = {}
    for nodeid, entry in cache["any"]["tests"].items():
        by_kind.setdefault(test_kind(nodeid), []).append(entry["median"])
    cache["kind_defaults"] = {
        kind: (round(statistics.median(v), 1) if len(v) >= KIND_MIN_SAMPLES else KIND_DEFAULTS.get(kind, KIND_DEFAULTS[""]))
        for kind, v in by_kind.items()
    }
    for kind, default in KIND_DEFAULTS.items():
        cache["kind_defaults"].setdefault(kind, default)
    for run in _runs_for(conn, project, None, 200):
        if (run["repeat"] or 1) > 1:
            continue
        key = signature(run["stand"], run["target"], run["marker"])
        bucket = cache["signatures"].setdefault(key, [])
        if len(bucket) < SAME_RUNS:
            bucket.append(round(run["duration"], 1))
    return cache


def recalc(project: str, tree: dict | None) -> dict:
    conn = get_connection()
    try:
        cache = build_cache(conn, project, tree)
    finally:
        conn.close()
    path = cache_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


# ------------------------------------------------------------------ оценка
def select_nodeids(nodeids: list[str], target: str | None) -> list[str]:
    """Какие nodeid выберет pytest для цели (построчно: каталог, файл, класс, nodeid —
    как runner.count_target_tests, плюс каталоги). Строки-опции (`--ignore=…`) не
    фильтруют — для них цель считается «всё»."""
    lines = [line.strip() for line in (target or "").splitlines() if line.strip() and not line.strip().startswith("-")]
    if not lines or target == "all":
        return list(nodeids)
    selected: list[str] = []
    for nodeid in nodeids:
        file_path = nodeid.split("::", 1)[0]
        for line in lines:
            if nodeid == line or nodeid.startswith(line + "::") or file_path == line or file_path.startswith(line.rstrip("/") + "/"):
                selected.append(nodeid)
                break
    return selected


def _lookup(cache: dict, stand: str | None, nodeid: str) -> tuple[float, bool, bool]:
    """(медиана, известен ли тест, упал ли в последнем прогоне стенда)."""
    stand_tests = (cache.get("stands", {}).get(stand) or {}).get("tests", {}) if stand else {}
    entry = stand_tests.get(nodeid)
    if entry:
        return entry["median"], True, bool(entry.get("failed_last"))
    entry = cache.get("any", {}).get("tests", {}).get(nodeid)
    if entry:
        return entry["median"], True, False
    defaults = cache.get("kind_defaults", KIND_DEFAULTS)
    return defaults.get(test_kind(nodeid), defaults.get("", KIND_DEFAULTS[""])), False, False


def _overhead(cache: dict, stand: str | None) -> float:
    for bucket in ((cache.get("stands", {}).get(stand) if stand else None), cache.get("any")):
        if bucket and bucket.get("overhead") is not None:
            return float(bucket["overhead"])
    return OVERHEAD_DEFAULT


def estimate_run(
    cache: dict,
    stand: str | None,
    target: str | None,
    marker: str | None = None,
    workers: int = 0,
    repeat: int = 1,
    live: bool = False,
) -> dict:
    """{seconds, low, high, rough, source, tests_total, tests_known}."""
    repeat = max(1, repeat or 1)
    same = cache.get("signatures", {}).get(signature(stand, target or "all", marker)) or []
    if len(same) >= 2:
        seconds = statistics.median(same) * repeat
        return {
            "seconds": round(seconds), "low": round(min(same) * repeat), "high": round(max(same) * repeat),
            "rough": False, "source": "same_runs", "tests_total": None, "tests_known": None,
        }
    nodeids = select_nodeids(cache.get("nodeids", []), target)
    overhead = _overhead(cache, stand)
    tests_seconds = 0.0
    known = 0
    for nodeid in nodeids:
        median, is_known, failed_last = _lookup(cache, stand, nodeid)
        tests_seconds += median * (2 if failed_last else 1)
        known += int(is_known)
    if workers and workers > 1 and not live and repeat <= 1:
        tests_seconds /= workers
    seconds = (overhead + tests_seconds) * repeat
    rough = not nodeids or known < len(nodeids) / 2 or bool(marker)
    return {
        "seconds": round(seconds),
        "low": round((overhead + tests_seconds * RANGE_LOW) * repeat),
        "high": round((overhead + tests_seconds * RANGE_HIGH) * repeat),
        "rough": rough,
        "source": "tests",
        "tests_total": len(nodeids),
        "tests_known": known,
    }


def remaining_running(conn: sqlite3.Connection, cache: dict, run: sqlite3.Row, workers: int = 0, now: datetime | None = None) -> dict:
    """Остаток выполняющегося прогона: {seconds, done, total, elapsed, pace, rough}."""
    now = now or datetime.now()
    elapsed = max(0.0, (now - _parse_ts(run["started"])).total_seconds()) if run["started"] else 0.0
    stand = run["stand"]
    done_wall, _, in_progress = wall_times(conn, run["id"])
    planned = select_nodeids(cache.get("nodeids", []), run["target"]) if not run["marker"] else []
    estimate = estimate_run(cache, stand, run["target"], run["marker"], workers, run["repeat"] or 1, bool(run["live"]))
    if planned and (run["repeat"] or 1) <= 1:
        est_done = sum(_lookup(cache, stand, n)[0] for n in done_wall)
        pace = 1.0
        if est_done > 0 and done_wall:
            pace = min(PACE_MAX, max(PACE_MIN, sum(done_wall.values()) / est_done))
        left = [n for n in planned if n not in done_wall]
        remaining = 0.0
        overdue = False
        for nodeid in left:
            median, _, _ = _lookup(cache, stand, nodeid)
            if nodeid in in_progress:
                running_for = (now - in_progress[nodeid]).total_seconds()
                # Текущий тест уже дольше своей медианы: сколько ещё — неизвестно (таймаут,
                # повтор, зависший стенд); остаток по нему 0, но прогон помечаем overdue.
                overdue = running_for > median * pace
                median = max(0.0, median - running_for)
            remaining += median
        remaining *= pace
        if workers and workers > 1 and not run["live"]:
            remaining /= workers
        if not done_wall:
            remaining = max(remaining, estimate["seconds"] - elapsed)
        return {
            "seconds": round(remaining), "done": len(done_wall), "total": len(planned), "elapsed": round(elapsed),
            "pace": round(pace, 2), "rough": estimate["rough"] and not done_wall,
            # overdue: текущий тест дольше медианы × темп, либо прогон в целом уже дольше своей
            # полной оценки, а работа ещё есть — остаток показывать нечестно, старт очереди сдвинется
            "overdue": overdue or (not left and bool(in_progress)) or (elapsed > estimate["seconds"] and bool(left)),
        }
    remaining = max(0.0, estimate["seconds"] - elapsed)
    return {
        "seconds": round(remaining), "done": len(done_wall), "total": None,
        "elapsed": round(elapsed), "pace": None, "rough": estimate["rough"], "overdue": elapsed > estimate["seconds"],
    }


def _workers_by_stand(conn: sqlite3.Connection, project: str) -> dict[str, int]:
    return {
        r["name"]: int(r["workers"] or 0)
        for r in conn.execute("SELECT name, workers FROM stands WHERE project = ?", (project,)).fetchall()
    }


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def queue_eta(conn: sqlite3.Connection, project: str, now: datetime | None = None, cache: dict | None = None) -> dict[int, dict]:
    """ETA по активным прогонам проекта: {run_id: {...}} — для running: remaining/done/
    total, для queued: position/start_in/start_at/duration/finish_at. Пусто без кэша."""
    return _queue_plan(conn, project, now, cache)[0]


def _queue_plan(conn: sqlite3.Connection, project: str, now: datetime | None, cache: dict | None) -> tuple[dict[int, dict], float]:
    """(ETA по активным прогонам, через сколько секунд очередь освободится)."""
    cache = cache if cache is not None else load_cached(project)
    if cache is None:
        return {}, 0.0
    now = now or datetime.now()
    workers = _workers_by_stand(conn, project)
    active = conn.execute(
        "SELECT * FROM runs WHERE project = ? AND status IN ('running', 'queued') ORDER BY id", (project,)
    ).fetchall()
    result: dict[int, dict] = {}
    cursor = 0.0
    position = 0
    overdue_ahead = False
    for run in active:
        if run["status"] == "running":
            rem = remaining_running(conn, cache, run, workers.get(run["stand"] or "", 0), now)
            cursor += rem["seconds"]
            overdue_ahead = overdue_ahead or rem["overdue"]
            result[run["id"]] = {"kind": "running", "finish_at": _iso(now + timedelta(seconds=cursor)), **rem}
        else:
            position += 1
            est = estimate_run(cache, run["stand"], run["target"], run["marker"], workers.get(run["stand"] or "", 0), run["repeat"] or 1, bool(run["live"]))
            start_in = cursor
            cursor += est["seconds"]
            result[run["id"]] = {
                "kind": "queued", "position": position, "start_in": round(start_in),
                "start_at": _iso(now + timedelta(seconds=start_in)), "finish_at": _iso(now + timedelta(seconds=cursor)),
                "duration": est["seconds"], "low": est["low"], "high": est["high"], "source": est["source"],
                # старт сдвинется на неизвестное время, если выполняющийся прогон уже вышел за оценку
                "rough": est["rough"] or overdue_ahead,
            }
    return result, cursor


def estimate_for_form(
    conn: sqlite3.Connection, project: str, stand: str | None, target: str | None, marker: str | None = None,
    live: bool = False, repeat: int = 1, now: datetime | None = None,
) -> dict | None:
    """«Ваш запуск» на вкладке «Запуск»: когда стартует и сколько займёт прогон с такими
    параметрами, если нажать «Запустить» сейчас. None без кэша."""
    cache = load_cached(project)
    if cache is None:
        return None
    now = now or datetime.now()
    queue, start_seconds = _queue_plan(conn, project, now, cache)
    est = estimate_run(cache, stand, target, marker, _workers_by_stand(conn, project).get(stand or "", 0), repeat, live)
    return {
        "queue_len": len(queue), "start_in": round(start_seconds), "start_at": _iso(now + timedelta(seconds=start_seconds)),
        "finish_at": _iso(now + timedelta(seconds=start_seconds + est["seconds"])), **est,
    }


# ------------------------------------------------------------------ пересчёт
async def recalc_async(project: str) -> dict | None:
    """Дерево тестов — через runner.discover (pytest --collect-only, секунды), сам
    расчёт — в потоке: читает run_events за несколько прогонов."""
    from . import runner  # локально: runner не зависит от eta, цикла нет

    conn = get_connection()
    try:
        row = conn.execute("SELECT path, venv FROM projects WHERE name = ?", (project,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    if not runner._venv_python(row["path"], row["venv"]).exists():
        # Проект без окружения (тестовые проекты с выдуманным path, снятый с диска
        # репозиторий) — считать нечего, и в workspace ничего не пишем.
        return None
    tree = None
    try:
        discovered = await runner.discover(row["path"], row["venv"])
        tree = discovered.get("tree") or None
    except Exception:
        logger.exception("eta: discover упал для проекта %s", project)
    if tree is None:
        cached = load_cached(project)
        if not (cached and cached.get("nodeids")):
            return None
        # без свежего дерева оставляем прошлый список nodeid
        cache = await asyncio.to_thread(recalc, project, None)
        cache["nodeids"] = cached["nodeids"]
        cache_path(project).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        return cache
    return await asyncio.to_thread(recalc, project, tree)


async def on_run_finished(run_id: int) -> None:
    """Хук runner.register_finalize_hook: медианы и overhead меняются с каждым
    завершённым прогоном. Выключается settings.TH_ETA_HOOK (в тестах — всегда)."""
    if not settings.TH_ETA_HOOK:
        return
    conn = get_connection()
    try:
        row = conn.execute("SELECT project FROM runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return
    try:
        await recalc_async(row["project"])
    except Exception:
        logger.exception("eta: пересчёт после прогона #%s не удался", run_id)
