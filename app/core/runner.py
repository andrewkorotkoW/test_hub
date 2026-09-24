"""Обнаружение тестов и исполнение прогонов pytest в целевом проекте.

Адаптация логики ~/PycharmProjects/cyber_office/app/core/testlab.py под test_hub:
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
from . import allure_report, flaky, xfail_registry
from .ws import hub

_COLLECT_RE = re.compile(r"^(?P<file>[\w./-]+\.py)::(?P<rest>.+)$")

# Маскирование секретов в строках вывода pytest перед записью в run_events/трансляцией
# по WebSocket (см. задачу шаринга отчёта — публичная ссылка на прогон не должна
# раскрывать заголовки авторизации/куки, даже если их напечатал сам тест или
# HTTP-клиент в verbose-режиме).
_SECRET_HEADER_RE = re.compile(r"(?im)^(.*\b(?:authorization|cookie|set-cookie)\b[\"']?\s*:\s*).+$")
_SECRET_TOKEN_PARAM_RE = re.compile(r"(?i)\btoken=[^\s&\"']+")


def mask_secrets(line: str) -> str:
    line = _SECRET_HEADER_RE.sub(r"\1***", line)
    line = _SECRET_TOKEN_PARAM_RE.sub("token=***", line)
    return line

_project_locks: dict[str, asyncio.Lock] = {}
_active_procs: dict[int, "asyncio.subprocess.Process"] = {}
_cancelled: set[int] = set()

# Хуки, вызываемые после завершения каждого прогона (см. _finalize) — раннер не
# знает про app.core.schedule (тот сам импортирует runner, обратный импорт создал
# бы цикл), поэтому подписка делается снаружи, в app/main.py::lifespan, где обе
# стороны уже видны.
_finalize_hooks: list = []


def register_finalize_hook(hook) -> None:
    # idempotent: app/main.py::lifespan может быть запущен повторно в одном процессе
    # (см. tests/test_tg_bot.py::test_lifespan_without_token_skips_bot, вызывающий
    # lifespan(app) напрямую) — без этой проверки каждый повторный запуск добавлял
    # бы в общий список ещё одну копию того же хука.
    if hook not in _finalize_hooks:
        _finalize_hooks.append(hook)


def unregister_finalize_hook(hook) -> None:
    """Для тестов: убрать хук, добавленный вручную (без lifespan), чтобы не влиять
    на остальные тесты в той же pytest-сессии (_finalize_hooks — модульное состояние)."""
    if hook in _finalize_hooks:
        _finalize_hooks.remove(hook)


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
    # -o addopts= : у проекта в pytest.ini может стоять -v (как у auto_tests_vshgu_cloude) —
    # он гасит наш -q, и pytest печатает <Module …> вместо nodeid'ов, дерево выходит пустым
    proc = await asyncio.create_subprocess_exec(
        str(python), "-m", "pytest", "--collect-only", "-o", "addopts=", "-q", "-p", "no:cacheprovider",
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


async def submit_run(
    project_name: str,
    stand_name: str | None,
    target: str,
    requested_by: str,
    marker: str | None = None,
    repeat: int = 1,
) -> int:
    """Создаёт запись прогона (running, если для проекта нет активного, иначе queued)
    и, если она стартует сразу, запускает фоновую задачу исполнения. `repeat` > 1
    прогоняет одну и ту же цель несколько раз подряд в одном прогоне (см. _execute) —
    используется флаки-детектором (app/core/flaky.py) для накопления истории на
    одном и том же снимке кода/стенда."""
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
                "INSERT INTO runs (project, stand, target, status, started, requested_by, counts, marker, repeat) "
                "VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)",
                (project_name, stand_name, target, "running" if start_now else "queued",
                 now if start_now else None, requested_by, marker, repeat),
            )
            conn.commit()
            run_id = cur.lastrowid
        finally:
            conn.close()

    if start_now:
        asyncio.create_task(_execute(run_id, project_name, stand_name, target, marker, repeat))
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
    line = mask_secrets(line)
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
        row = conn.execute("SELECT project, stand FROM runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    await hub.broadcast(run_id, {"type": "status", "run_id": run_id, "status": status, "counts": counts})

    if row is not None and row["stand"]:
        # Флаки-детектор и реестр известных дефектов: оба пересчёта синхронные (читают
        # allure-results с диска и пишут в SQLite) и не должны блокировать завершение
        # прогона, поэтому уходят в отдельные потоки фоновыми задачами, а не await'ятся
        # здесь. Независимы друг от друга — ни один не знает про другой.
        asyncio.create_task(asyncio.to_thread(flaky.recalc, row["project"], row["stand"]))
        asyncio.create_task(asyncio.to_thread(xfail_registry.recalc, row["project"], row["stand"], run_id))

    # Уведомление о расписании (app.core.schedule.on_run_finished) само решает, был ли
    # этот run_id вообще запущен планировщиком — не блокирует завершение прогона.
    # Вне if выше: у расписания может не быть стенда (stand допускает NULL).
    for hook in _finalize_hooks:
        asyncio.create_task(hook(run_id))


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
        asyncio.create_task(
            _execute(nxt["id"], project_name, nxt["stand"], nxt["target"], nxt["marker"], nxt["repeat"])
        )


async def _execute(
    run_id: int,
    project_name: str,
    stand_name: str | None,
    target: str,
    marker: str | None = None,
    repeat: int = 1,
) -> None:
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
        if project["use_env_flag"]:
            args.extend(["--env", stand_name])
            env["HEADLESS"] = "1"
    if marker:
        args.extend(["-m", marker])

    # repeat > 1 (флаки-детектор, см. app/core/flaky.py) гоняет ту же цель несколько
    # раз подряд в один и тот же results_dir: pytest-repeat не в requirements.txt,
    # поэтому вместо --count используется просто N последовательных subprocess-запусков
    # — allure-pytest сам называет файлы результатов случайным uuid на каждый запуск,
    # так что коллизий имён между повторами не бывает и без ручных префиксов.
    total_returncode = 0
    for attempt in range(max(1, repeat)):
        if repeat > 1:
            await _log_line(run_id, f"=== повтор {attempt + 1}/{repeat} ===")
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
            break
        if proc.returncode != 0:
            total_returncode = proc.returncode

    if run_id in _cancelled:
        _cancelled.discard(run_id)
        status = "cancelled"
    else:
        status = "passed" if total_returncode == 0 else "failed"

    tests = allure_report.parse_results(results_dir)
    counts = allure_report.counts_from_tests(tests)
    await _finalize(run_id, status, started_at, counts)
    await _advance_queue(project_name)
