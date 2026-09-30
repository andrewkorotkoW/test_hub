"""Видео-заглушки для прогонов демо-проекта (docs/missions/2026-10-01_live_stream.md,
раздел «Демо-проект»): demo/tests не шлёт кадры/видео через плагин auto_tests_vshgu —
его для demo/ просто нет, реального видео теста неоткуда взять. После завершения
прогона Demo/local подставляем готовые заглушки (demo/assets/video/*.webm, см.
demo/gen_video_stub.py) первым 1-2 пройденным тестам этого прогона — только чтобы
вкладка «Видео» окна прогона была видна в туре.

Регистрируется как runner-хук (app/core/runner.register_finalize_hook, см.
app/main.py::lifespan), как app.core.schedule.on_run_finished — но фильтрует по
проекту Demo и no-op для всех остальных прогонов."""
from __future__ import annotations

import logging
from datetime import datetime
from hashlib import sha1
from pathlib import Path

from ..db import DEMO_PROJECT_NAME, get_connection
from . import allure_report, runner

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "demo" / "assets" / "video"
STUB_FILES = ("stub_1.webm", "stub_2.webm")
# Совпадает с DURATION_SECONDS в demo/gen_video_stub.py (там же генерируются сами файлы).
STUB_DURATION_MS = 2400


def _nodeid_hash(nodeid: str) -> str:
    # Своя копия app/routers/runs.py::_nodeid_hash — то же соглашение модулей,
    # что и у _nodeid_to_full_name ниже: не тянуть межмодульную зависимость ради
    # одной функции (см. flaky.py/xfail_registry.py).
    return sha1(nodeid.encode("utf-8")).hexdigest()[:16]


def _nodeid_to_full_name(nodeid: str) -> str:
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def _full_name_index(tree: dict) -> dict[str, str]:
    index: dict[str, str] = {}
    for file_path, classes in tree.items():
        for cls_name, tests in classes.items():
            for test_name in tests:
                nodeid = f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}"
                index.setdefault(_nodeid_to_full_name(nodeid), nodeid)
    return index


async def on_run_finished(run_id: int) -> None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT project, status FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["project"] != DEMO_PROJECT_NAME or row["status"] not in ("passed", "failed"):
            return
        # Идемпотентность: _finalize зовёт хуки один раз на прогон, но run_id уникален
        # для каждого нового прогона — эта проверка защищает только от повторного
        # ручного вызова хука (например, из теста), не от накопления по разным прогонам.
        if conn.execute("SELECT 1 FROM run_test_videos WHERE run_id = ?", (run_id,)).fetchone():
            return

        stub_paths = [p for name in STUB_FILES if (p := ASSETS_DIR / name).is_file()]
        if not stub_paths:
            logger.warning("demo_video: заглушки не найдены в %s, видео не подставлены", ASSETS_DIR)
            return

        project = conn.execute("SELECT path, venv FROM projects WHERE name = ?", (row["project"],)).fetchone()
        if project is None:
            return
        discovered = await runner.discover(project["path"], project["venv"])
        nodeid_by_full_name = _full_name_index(discovered.get("tree") or {})

        passed_nodeids: list[str] = []
        for test in allure_report.parse_results(runner.allure_dir(run_id)):
            if test["status"] != "passed":
                continue
            nodeid = nodeid_by_full_name.get(test["name"])
            if nodeid is None or nodeid in passed_nodeids:
                continue
            passed_nodeids.append(nodeid)
            if len(passed_nodeids) >= len(stub_paths):
                break

        if not passed_nodeids:
            return

        video_dir = runner.video_dir(run_id)
        video_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        for nodeid, stub_path in zip(passed_nodeids, stub_paths):
            raw = stub_path.read_bytes()
            dest = video_dir / f"{_nodeid_hash(nodeid)}.webm"
            dest.write_bytes(raw)
            conn.execute(
                "INSERT INTO run_test_videos (run_id, nodeid, path, duration_ms, size, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, nodeid, str(dest), STUB_DURATION_MS, len(raw), now),
            )
        conn.commit()
        logger.info("demo_video: подставлено %d видео-заглушек для прогона %s", len(passed_nodeids), run_id)
    finally:
        conn.close()
