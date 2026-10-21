"""Генерация тестовых данных на стенде (вкладка «Данные» проекта, app/routers/datagen.py).

test_hub сам ничего на стенде не создаёт: он запускает CLI проекта тестов
`test_data_generation/generate.py` (auto_tests_vshgu) как subprocess в venv проекта —
ровно так же, как app/core/runner.py запускает pytest (тот же _venv_python, те же
переменные STAND_URL/STAND_LOGIN и флаг --env <стенд> при use_env_flag). CLI в режиме
--json печатает последней строкой «__TH_DATAGEN_RESULT__ {json}» с манифестом созданного;
манифест хранится в data_batches.manifest и в workspace/datagen/batch_<id>.json, по нему
та же CLI удаляет партию (--cleanup) по кнопке «Удалить данные».

Статусы партии: queued → running → done | failed (частичный манифест сохраняется —
удалить можно и после сбоя) → deleting → deleted | delete_failed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..db import get_connection
from .runner import _venv_python, mask_secrets

logger = logging.getLogger(__name__)

GENERATOR_REL_PATH = Path("test_data_generation") / "generate.py"
RESULT_MARKER = "__TH_DATAGEN_RESULT__"
ACTIVE_STATUSES = ("queued", "running", "deleting")
DELETABLE_STATUSES = ("done", "failed", "delete_failed")
LIST_TIMEOUT_SEC = 90
MAX_COUNT = 50

_scenarios_cache: dict[str, tuple[tuple, list[dict]]] = {}
_tasks: set[asyncio.Task] = set()


class DatagenError(RuntimeError):
    """CLI генератора недоступна или ответила не по контракту (--list --json)."""


# ---------------------------------------------------------------- CLI проекта

def generator_path(project_path: str) -> Path:
    return Path(project_path) / GENERATOR_REL_PATH


def supports(project_path: str) -> bool:
    return generator_path(project_path).is_file()


def manifest_path(batch_id: int) -> Path:
    return settings.WORKSPACE_DIR / "datagen" / f"batch_{batch_id}.json"


def _signature(project_path: str) -> tuple:
    """Ключ кэша списка сценариев: mtime generate.py и всех scenarios/*.py — новый сценарий
    в репозитории проекта появляется в форме без перезапуска test_hub."""
    gen = generator_path(project_path)
    parts = [gen.stat().st_mtime_ns]
    scenarios_dir = gen.parent / "scenarios"
    if scenarios_dir.is_dir():
        parts.extend(sorted(p.stat().st_mtime_ns for p in scenarios_dir.glob("*.py")))
    return tuple(parts)


def _parse_scenarios(text: str) -> list[dict]:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        return [
            {
                "name": str(item["name"]),
                "title": str(item.get("title") or item["name"]),
                "category": str(item.get("category") or ""),
                "description": str(item.get("description") or ""),
                "count_help": str(item.get("count_help") or ""),
            }
            for item in data
            if isinstance(item, dict) and item.get("name")
        ]
    raise DatagenError("generate.py --list --json не вернул JSON-список сценариев")


async def list_scenarios(project: sqlite3.Row) -> list[dict]:
    path = project["path"]
    if not supports(path):
        return []
    signature = _signature(path)
    cached = _scenarios_cache.get(path)
    if cached is not None and cached[0] == signature:
        return cached[1]

    python = _venv_python(path, project["venv"])
    try:
        proc = await asyncio.create_subprocess_exec(
            str(python), str(generator_path(path)), "--list", "--json",
            cwd=path, env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=LIST_TIMEOUT_SEC)
    except (OSError, asyncio.TimeoutError) as exc:
        raise DatagenError(f"не удалось получить список сценариев: {exc}") from exc
    if proc.returncode != 0:
        tail = mask_secrets(err.decode("utf-8", errors="replace")[-600:])
        raise DatagenError(f"generate.py --list завершился с кодом {proc.returncode}: {tail}")
    scenarios = _parse_scenarios(out.decode("utf-8", errors="replace"))
    _scenarios_cache[path] = (signature, scenarios)
    return scenarios


# ---------------------------------------------------------------- строки data_batches

def _parse_json(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def entity_counts(manifest: dict | None) -> list[dict]:
    """[{entity, count}] в порядке первого появления в манифесте — для сводки партии в таблице."""
    order: list[str] = []
    counts: dict[str, int] = {}
    for entry in (manifest or {}).get("created", []) or []:
        entity = str(entry.get("entity", "?")) if isinstance(entry, dict) else "?"
        if entity not in counts:
            order.append(entity)
            counts[entity] = 0
        counts[entity] += 1
    return [{"entity": entity, "count": counts[entity]} for entity in order]


def row_to_dict(row: sqlite3.Row, details: bool = False) -> dict:
    manifest = _parse_json(row["manifest"])
    cleanup = _parse_json(row["cleanup_result"])
    created = (manifest or {}).get("created", []) or []
    skipped = (manifest or {}).get("skipped", []) or []
    data = {
        "id": row["id"],
        "project": row["project"],
        "stand": row["stand"],
        "scenario": row["scenario"],
        "count": row["count"],
        "prefix": row["prefix"],
        "status": row["status"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "finished_at": row["finished_at"],
        "deleted_at": row["deleted_at"],
        "error": row["error"],
        "created_total": len(created),
        "skipped_total": len(skipped),
        "entities": entity_counts(manifest),
        "cleanup_summary": (
            {"deleted": int(cleanup.get("deleted", 0)), "failed": int(cleanup.get("failed", 0)),
             "skipped": int(cleanup.get("skipped", 0))}
            if isinstance(cleanup, dict) else None
        ),
    }
    if details:
        data["manifest"] = manifest
        data["cleanup"] = cleanup
        data["log"] = row["log"] or ""
        data["delete_log"] = row["delete_log"] or ""
    return data


def list_batches(conn: sqlite3.Connection, project: str, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM data_batches WHERE project = ? ORDER BY id DESC LIMIT ?", (project, limit)
    ).fetchall()


def get_batch(conn: sqlite3.Connection, project: str, batch_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM data_batches WHERE project = ? AND id = ?", (project, batch_id)
    ).fetchone()


def active_batch(conn: sqlite3.Connection, project: str) -> sqlite3.Row | None:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    return conn.execute(
        f"SELECT * FROM data_batches WHERE project = ? AND status IN ({placeholders}) ORDER BY id LIMIT 1",
        (project, *ACTIVE_STATUSES),
    ).fetchone()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def insert_batch(
    conn: sqlite3.Connection, project: str, stand: str | None, scenario: str, count: int,
    prefix: str | None, created_by: str | None,
) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO data_batches (project, stand, scenario, count, prefix, status, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)",
        (project, stand, scenario, count, prefix, _now(), created_by),
    )
    conn.commit()
    return get_batch(conn, project, cur.lastrowid)


def _update(batch_id: int, **fields) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn = get_connection()
    try:
        conn.execute(f"UPDATE data_batches SET {assignments} WHERE id = ?", (*fields.values(), batch_id))
        conn.commit()
    finally:
        conn.close()


def _append_log(batch_id: int, column: str, line: str) -> None:
    if column not in ("log", "delete_log"):
        raise ValueError(column)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE data_batches SET {column} = {column} || ? WHERE id = ?",
            (mask_secrets(line) + "\n", batch_id),
        )
        conn.commit()
    finally:
        conn.close()


def recover_stale() -> int:
    """При старте test_hub партии, оставшиеся в queued/running/deleting от предыдущего
    процесса, завершить уже некому — помечаем как сбой (манифест, если он успел
    сохраниться в файл, подхватывается, чтобы данные можно было удалить)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, status, manifest FROM data_batches WHERE status IN ('queued', 'running', 'deleting')"
        ).fetchall()
        for row in rows:
            manifest = row["manifest"]
            path = manifest_path(row["id"])
            if not manifest and path.exists():
                manifest = path.read_text(encoding="utf-8")
            status = "delete_failed" if row["status"] == "deleting" else "failed"
            conn.execute(
                "UPDATE data_batches SET status = ?, error = ?, finished_at = COALESCE(finished_at, ?), manifest = ? "
                "WHERE id = ?",
                (status, "test_hub был перезапущен до завершения", _now(), manifest, row["id"]),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


# ---------------------------------------------------------------- запуск CLI

def _base_command(project: sqlite3.Row, stand: sqlite3.Row | None, stand_name: str | None) -> tuple[list[str], dict]:
    python = _venv_python(project["path"], project["venv"])
    args = [str(python), str(generator_path(project["path"]))]
    env = os.environ.copy()
    if stand is not None:
        env["STAND_URL"] = stand["url"] or ""
        env["STAND_LOGIN"] = stand["login"] or ""
        if project["use_env_flag"]:
            args.extend(["--env", stand_name])
    return args, env


def _load(batch_id: int) -> tuple[sqlite3.Row | None, sqlite3.Row | None, sqlite3.Row | None]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM data_batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            return None, None, None
        project = conn.execute("SELECT * FROM projects WHERE name = ?", (row["project"],)).fetchone()
        stand = None
        if row["stand"]:
            stand = conn.execute(
                "SELECT * FROM stands WHERE project = ? AND name = ?", (row["project"], row["stand"])
            ).fetchone()
        return row, project, stand
    finally:
        conn.close()


async def _run_cli(batch_id: int, args: list[str], cwd: str, env: dict, log_column: str) -> tuple[int | None, dict | None]:
    """Запускает CLI, построчно пишет её вывод в колонку лога партии, вырезая строку с
    RESULT_MARKER — её JSON возвращается отдельно. (None, None) — процесс не запустился."""
    shown = " ".join(args[1:])
    await asyncio.to_thread(_append_log, batch_id, log_column, f"$ python {shown}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        await asyncio.to_thread(_append_log, batch_id, log_column, f"не удалось запустить generate.py: {exc}")
        return None, None
    result: dict | None = None
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if line.startswith(RESULT_MARKER):
            try:
                parsed = json.loads(line[len(RESULT_MARKER):].strip())
                result = parsed if isinstance(parsed, dict) else None
            except ValueError:
                result = None
            continue
        await asyncio.to_thread(_append_log, batch_id, log_column, line)
    await proc.wait()
    return proc.returncode, result


async def execute_create(batch_id: int) -> None:
    row, project, stand = _load(batch_id)
    if row is None:
        return
    if project is None:
        _update(batch_id, status="failed", error="проект больше не существует", finished_at=_now())
        return
    _update(batch_id, status="running")

    path = manifest_path(batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    args, env = _base_command(project, stand, row["stand"])
    args.extend(["--scenario", row["scenario"], "--count", str(row["count"]), "--json", "--manifest-out", str(path)])
    if row["prefix"]:
        args.extend(["--prefix", row["prefix"]])

    returncode, result = await _run_cli(batch_id, args, project["path"], env, "log")

    manifest = result.get("manifest") if isinstance(result, dict) else None
    if not isinstance(manifest, dict) and path.exists():
        manifest = _parse_json(path.read_text(encoding="utf-8"))
    ok = returncode == 0 and bool(result and result.get("ok"))
    error = None
    if not ok:
        error = (result or {}).get("error") if isinstance(result, dict) else None
        error = error or (
            "generate.py не запустился" if returncode is None else f"generate.py завершился с кодом {returncode}"
        )
    _update(
        batch_id,
        status="done" if ok else "failed",
        finished_at=_now(),
        manifest=json.dumps(manifest, ensure_ascii=False) if isinstance(manifest, dict) else None,
        error=error,
    )


async def execute_delete(batch_id: int) -> None:
    row, project, stand = _load(batch_id)
    if row is None:
        return
    if project is None:
        _update(batch_id, status="delete_failed", error="проект больше не существует")
        return
    manifest = _parse_json(row["manifest"])
    path = manifest_path(batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(manifest, dict):
        # Файл манифеста переписывается из БД: workspace могли почистить, а --cleanup
        # читает именно файл.
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    elif not path.exists():
        _update(batch_id, status="delete_failed", error="у партии нет манифеста — удалять нечего")
        return

    args, env = _base_command(project, stand, row["stand"])
    args.extend(["--cleanup", str(path), "--json"])
    returncode, result = await _run_cli(batch_id, args, project["path"], env, "delete_log")

    ok = returncode == 0 and bool(result and result.get("ok"))
    error = None
    if not ok:
        error = (result or {}).get("error") if isinstance(result, dict) else None
        if not error and isinstance(result, dict) and result.get("failed"):
            error = f"не удалено сущностей: {result.get('failed')}"
        error = error or (
            "generate.py не запустился" if returncode is None else f"cleanup завершился с кодом {returncode}"
        )
    _update(
        batch_id,
        status="deleted" if ok else "delete_failed",
        deleted_at=_now() if ok else None,
        cleanup_result=json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else None,
        error=error,
    )


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def schedule_create(batch_id: int) -> asyncio.Task:
    return _spawn(execute_create(batch_id))


def schedule_delete(batch_id: int) -> asyncio.Task:
    return _spawn(execute_delete(batch_id))
