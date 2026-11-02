"""Ретеншен файлов прогона (docs/missions/2026-11-02_review_fixes.md, п.5):
видео/кадры/allure-results/allure-отчёты накапливаются на диске (+1 ГБ за две
недели), а удаление до этой задачи было только вручную в суперадминке. purge_expired()
удаляет каталоги прогонов старше TH_KEEP_*_DAYS (app/config.py, 0 = не удалять) —
строки в БД (runs, run_test_results, run_events, counts) не трогает: история,
графики и флаки от файлов на диске не зависят (flaky.recalc читает allure через
allure_report.parse_results, которая сама отдаёт [] для отсутствующего каталога).

Фоновая задача retention_loop — asyncio-задача, запускаемая/отменяемая в
app/main.py::lifespan, по образцу schedule.scheduler_loop, только раз в сутки.
Кнопка «Очистить сейчас» в суперадминке (app/routers/admin.py) вызывает тот же
purge_expired() синхронно."""
from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import runner

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 24 * 3600.0


def _cutoff(days: int) -> str | None:
    if not days:
        return None
    return (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")


def _has_live_share(conn, run_id: int, now_iso: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM share_links WHERE run_id = ? AND revoked = 0 "
        "AND (expires_at IS NULL OR expires_at > ?) LIMIT 1",
        (run_id, now_iso),
    ).fetchone()
    return row is not None


def _report_dir(run_id: int) -> Path:
    return settings.ALLURE_REPORTS_DIR / str(run_id)


def _rmtree(path: Path) -> bool:
    if not path.is_dir():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def purge_expired() -> dict[str, int]:
    """Удаляет каталоги video/frames/allure-results/allure-отчётов у finished-прогонов
    старше соответствующего TH_KEEP_*_DAYS, кроме прогонов с живой share-ссылкой
    (им удаление откладывается до истечения ссылки). Возвращает число прогонов, у
    которых реально что-то удалено, по каждой из четырёх категорий."""
    removed = {"video": 0, "frames": 0, "results": 0, "reports": 0}
    cutoffs = {
        "video": _cutoff(settings.TH_KEEP_VIDEO_DAYS),
        "frames": _cutoff(settings.TH_KEEP_FRAMES_DAYS),
        "results": _cutoff(settings.TH_KEEP_RESULTS_DAYS),
        "reports": _cutoff(settings.TH_KEEP_REPORTS_DAYS),
    }
    active = {k: v for k, v in cutoffs.items() if v is not None}
    if not active:
        return removed

    now_iso = datetime.now().isoformat(timespec="seconds")
    # Самый "свежий" порог (наименьшее число дней хранения) задаёт верхнюю границу
    # выборки прогонов-кандидатов — остальные категории с более строгими порогами
    # проверяются по своему cutoff уже внутри цикла.
    candidates_cutoff = max(active.values())

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, finished FROM runs WHERE finished IS NOT NULL AND finished <= ?",
            (candidates_cutoff,),
        ).fetchall()
        for row in rows:
            run_id, finished = row["id"], row["finished"]
            if _has_live_share(conn, run_id, now_iso):
                continue
            if cutoffs["video"] is not None and finished <= cutoffs["video"]:
                if _rmtree(runner.video_dir(run_id)):
                    removed["video"] += 1
            if cutoffs["frames"] is not None and finished <= cutoffs["frames"]:
                if _rmtree(runner.frames_dir(run_id)):
                    removed["frames"] += 1
            if cutoffs["results"] is not None and finished <= cutoffs["results"]:
                if _rmtree(runner.allure_dir(run_id)):
                    removed["results"] += 1
            if cutoffs["reports"] is not None and finished <= cutoffs["reports"]:
                if _rmtree(_report_dir(run_id)):
                    removed["reports"] += 1
    finally:
        conn.close()

    if any(removed.values()):
        logger.info(
            "retention: удалено каталогов — видео %d, кадры %d, результаты %d, отчёты %d",
            removed["video"], removed["frames"], removed["results"], removed["reports"],
        )
    return removed


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def disk_usage() -> dict[str, int]:
    """Размер в байтах по каждой из четырёх категорий — для строки «Диск: видео X ГБ…»
    в суперадминке. workspace/runs/<id>/video — видео, остальные три совпадают с
    настройками ALLURE_RESULTS_DIR/ALLURE_REPORTS_DIR/FRAMES_DIR."""
    video = sum(_dir_size(p) for p in settings.VIDEO_DIR.glob("*/video")) if settings.VIDEO_DIR.is_dir() else 0
    return {
        "video": video,
        "results": _dir_size(settings.ALLURE_RESULTS_DIR),
        "reports": _dir_size(settings.ALLURE_REPORTS_DIR),
        "frames": _dir_size(settings.FRAMES_DIR),
    }


async def retention_loop(poll_interval: float = POLL_INTERVAL_SECONDS) -> None:
    """Запускается/отменяется в app/main.py::lifespan (по аналогии со
    schedule.scheduler_loop, только раз в сутки, а не раз в минуту)."""
    while True:
        try:
            purge_expired()
        except Exception:
            logger.exception("retention: ошибка цикла очистки по сроку хранения")
        await asyncio.sleep(poll_interval)
