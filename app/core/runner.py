"""Обнаружение тестов и исполнение прогонов pytest в целевом проекте.

Адаптация логики ~/PycharmProjects/agent_office/app/core/testlab.py под test_hub:
там прогоны хранились в JSON-файле на диск, здесь — в общей SQLite (таблицы runs и
run_events из app.db), поэтому раннер работает через короткоживущие sqlite3-соединения
(та же схема, что и в роутерах: открыть, сделать запрос, закрыть) и не хранит состояние
прогона в памяти, кроме двух карт ниже:

- `_active_procs`: run_id -> subprocess.Process, только для уже запущенных прогонов,
  чтобы POST /api/runs/{id}/cancel мог их убить;
- `_cancelled`: run_id-ы, отменённые до того, как subprocess успел завершиться сам —
  без этого убитый процесс выглядел бы как обычный provalившийся прогон.

Очередь («не больше одного running на проект») построена поверх самой таблицы runs:
запрос на прогон вставляет строку status='running', если для проекта нет ни одного
running/queued, иначе 'queued'; по завершении раннер сам подхватывает следующий queued
по этому проекту. Гонки между параллельными POST /runs и завершением прогона исключает
per-project asyncio.Lock (в одном процессе uvicorn этого достаточно)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import allure_report
from .ws import hub

_COLLECT_RE = re.compile(r"^(?P<file>[\w./-]+\.py)::(?P<rest>.+)$")

_project_locks: dict[str, asyncio.Lock] = {}
_active_procs: dict[int, "asyncio.subprocess.Process"] = {}
_cancelled: set[int] = set()


def _lock_for(project: str) -> asyncio.Lock:
    return _project_locks.setdefault(project, asyncio.Lock())


def _venv_python(project_path: str, venv: str) -> Path:
    return Path(project_path) / venv / "bin" / "python"


def allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


# ------------------------------------------------------------------ обнаружение
async def discover(project_path: str, venv: str) -> dict:
    """Дерево тестов файл -> класс -> [тест] через `pytest --collect-only -q`.
    Тесты без класса складываются под ключ "" (пустая строка), см. README задачи."""
    python = _venv_python(project_path, venv)
    if not python.exists():
        return {"error": f".venv/bin/python не найден: {python}", "tree": {}}
    proc = await asyncio.create_subprocess_exec(
        str(python), "-m", "pytest", "--collect-only", "-q",
        cwd=project_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", errors="replace")
    tree: dict[str, dict[str, list[str]]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        m = _COLLECT_RE.match(line)
        if not m:
            continue
        parts = m.group("rest").split("::")
        test = parts[-1]
        cls = "::".join(parts[:-1])
        tree.setdefault(m.group("file"), {}).setdefault(cls, []).append(test)
    if not tree and proc.returncode != 0:
        return {"error": text.strip()[-2000:] or f"pytest завершился с кодом {proc.returncode}", "tree": {}}
    return {"tree": tree}


# ------------------------------------------------------------------ запуск прогонов
def _get_project(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()


def _get_stand(conn: sqlite3.Connection, project: str, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM stands WHERE project = ? AND name = ?", (project, name)).fetchone()


async def submit_run(project_name: str, stand_name: str | None, target: str, requested_by: str) -> int:
    """Создаёт запись прогона (running, если для проекта нет активного, иначе queued)
    и, если она стартует сразу, запускает фоновую задачу исполнения."""
    async with _lock_for(project_name):
        conn = get_connection()
        try:
            active = conn.execute(
                "SELECT 1 FROM runs WHERE project = ? AND status IN ('running', 'queued') LIMIT 1",
                (project_name,),
            ).fetchone()
            start_now = active is None
            now = datetime.now().isoformat(timespec="seconds")
            cur = conn.execute(
                "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
                "VALUES (?, ?, ?, ?, ?, ?, '{}')",
                (project_name, stand_name, target, "running" if start_now else "queued",
                 now if start_now else None, requested_by),
            )
            conn.commit()
            run_id = cur.lastrowid
        finally:
            conn.close()

    if start_now:
        asyncio.create_task(_execute(run_id, project_name, stand_name, target))
    return run_id


async def cancel_run(run_id: int) -> str:
    """Смотрит текущий статус прогона сама (не доверяя снимку статуса, сделанному
    вызывающим кодом чуть раньше — между чтением и вызовом раннер мог продвинуть
    очередь). Возвращает 'cancelled', 'not_found' или 'not_cancellable'.

    running: убивает subprocess, статус=cancelled выставит сам _execute, когда
    процесс завершится (иначе он посчитал бы себя обычным provalившимся прогоном).
    queued: переводит в cancelled сразу же, под тем же project-lock, что и
    submit_run/_advance_queue, чтобы не столкнуться с автостартом из очереди."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT project, status FROM runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return "not_found"

    if row["status"] == "running":
        proc = _active_procs.get(run_id)
        if proc is None:
            return "not_cancellable"
        _cancelled.add(run_id)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return "cancelled"

    if row["status"] == "queued":
        async with _lock_for(row["project"]):
            conn = get_connection()
            try:
                cur = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
                if not cur or cur["status"] != "queued":
                    return "not_cancellable"
                conn.execute(
                    "UPDATE runs SET status = 'cancelled', finished = ? WHERE id = ?",
                    (datetime.now().isoformat(timespec="seconds"), run_id),
                )
                conn.commit()
                return "cancelled"
            finally:
                conn.close()

    return "not_cancellable"


async def _log_line(run_id: int, line: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO run_events (run_id, ts, line) VALUES (?, ?, ?)",
            (run_id, datetime.now().isoformat(timespec="seconds"), line),
        )
        conn.commit()
    finally:
        conn.close()
    await hub.broadcast(run_id, {"type": "line", "run_id": run_id, "line": line})


async def _finalize(run_id: int, status: str, started_at: float, counts: dict[str, int]) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE runs SET status = ?, finished = ?, duration = ?, counts = ? WHERE id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), time.monotonic() - started_at,
             json.dumps(counts), run_id),
        )
        conn.commit()
    finally:
        conn.close()
    await hub.broadcast(run_id, {"type": "status", "run_id": run_id, "status": status, "counts": counts})


async def _advance_queue(project_name: str) -> None:
    async with _lock_for(project_name):
        conn = get_connection()
        try:
            nxt = conn.execute(
                "SELECT * FROM runs WHERE project = ? AND status = 'queued' ORDER BY id LIMIT 1",
                (project_name,),
            ).fetchone()
            if nxt is not None:
                conn.execute(
                    "UPDATE runs SET status = 'running', started = ? WHERE id = ?",
                    (datetime.now().isoformat(timespec="seconds"), nxt["id"]),
                )
                conn.commit()
        finally:
            conn.close()
    if nxt is not None:
        asyncio.create_task(_execute(nxt["id"], project_name, nxt["stand"], nxt["target"]))


async def _execute(run_id: int, project_name: str, stand_name: str | None, target: str) -> None:
    conn = get_connection()
    try:
        project = _get_project(conn, project_name)
        stand = _get_stand(conn, project_name, stand_name) if stand_name else None
    finally:
        conn.close()

    started_at = time.monotonic()
    if project is None:
        await _log_line(run_id, f"проект {project_name} больше не существует")
        await _finalize(run_id, "failed", started_at, {})
        await _advance_queue(project_name)
        return

    python = _venv_python(project["path"], project["venv"])
    results_dir = allure_dir(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    args = [str(python), "-m", "pytest"]
    if target and target != "all":
        # UI посылает несколько выбранных nodeid, разделённых переводом строки
        # (не пробелом — параметризованные тесты содержат пробелы в имени).
        args.extend(line for line in target.splitlines() if line.strip())
    args.append(f"--alluredir={results_dir}")

    env = os.environ.copy()
    if stand is not None:
        env["STAND_URL"] = stand["url"] or ""
        env["STAND_LOGIN"] = stand["login"] or ""

    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=project["path"], env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        await _log_line(run_id, f"не удалось запустить pytest: {exc}")
        await _finalize(run_id, "failed", started_at, {})
        await _advance_queue(project_name)
        return

    _active_procs[run_id] = proc
    try:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            await _log_line(run_id, raw.decode("utf-8", errors="replace").rstrip("\n"))
        await proc.wait()
    finally:
        _active_procs.pop(run_id, None)

    if run_id in _cancelled:
        _cancelled.discard(run_id)
        status = "cancelled"
    else:
        status = "passed" if proc.returncode == 0 else "failed"

    tests = allure_report.parse_results(results_dir)
    counts = allure_report.counts_from_tests(tests)
    await _finalize(run_id, status, started_at, counts)
    await _advance_queue(project_name)
