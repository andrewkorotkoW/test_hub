import asyncio
import contextlib
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .core import runner, schedule
from .db import init_db
from .routers import (
    admin, auth, coverage, flaky, projects, runs, schedules, sections, sentry, share, stats, test_cases, users, xfail,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    tg_application = None
    if settings.TH_TG_BOT_TOKEN:
        # Импорт внутри if: без токена бот полностью не поднимается — ни сети,
        # ни фоновых задач python-telegram-bot.
        from .tg_bot import build_application, start_application, stop_application

        try:
            tg_application = build_application()
            await start_application(tg_application)
        except Exception:
            # Ошибка запуска бота (например, невалидный токен) не должна ронять
            # весь сервер — test_hub работает и без Telegram-бота.
            logger.exception("tg_bot: не удалось запустить Telegram-бота")
            tg_application = None
    app.state.tg_bot = tg_application
    # Уведомления о прогонах по расписанию шлются через того же бота (см.
    # app.core.schedule.on_run_finished) — без токена schedule.set_bot(None)
    # просто отключает отправку, сами прогоны по расписанию всё равно выполняются.
    schedule.set_bot(tg_application.bot if tg_application is not None else None)

    runner.register_finalize_hook(schedule.on_run_finished)
    scheduler_task = asyncio.create_task(schedule.scheduler_loop())
    app.state.schedule_task = scheduler_task

    # Демо-сервис (demo/app/) — отдельный процесс uvicorn на TH_DEMO_PORT, не
    # asyncio-задача в нашем процессе: это самостоятельное FastAPI-приложение со
    # своими роутами, и запуск его как второго uvicorn.Server в том же event loop
    # столкнул бы оба сервера на установке обработчиков SIGINT/SIGTERM
    # (uvicorn.Server.serve() всегда их переустанавливает, см. capture_signals) —
    # Ctrl+C перестал бы штатно останавливать сам test_hub. Подпроцесс этого
    # риска лишён, как и раннер pytest в app/core/runner.py.
    demo_proc: asyncio.subprocess.Process | None = None
    if settings.TH_DEMO:
        try:
            demo_proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "uvicorn", "demo.app.main:app",
                "--host", "127.0.0.1", "--port", str(settings.TH_DEMO_PORT),
                "--log-level", "warning",
                cwd=str(BASE_DIR),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            logger.exception("demo: не удалось запустить встроенный демо-сервис")
            demo_proc = None
    app.state.demo_proc = demo_proc

    yield

    scheduler_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await scheduler_task

    if demo_proc is not None and demo_proc.returncode is None:
        demo_proc.terminate()
        try:
            await asyncio.wait_for(demo_proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            demo_proc.kill()
            await demo_proc.wait()

    if tg_application is not None:
        try:
            await stop_application(tg_application)
        except Exception:
            logger.exception("tg_bot: ошибка при остановке Telegram-бота")


app = FastAPI(title="test_hub", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(coverage.router)
app.include_router(flaky.router)
app.include_router(xfail.router)
app.include_router(stats.router)
app.include_router(sections.router)
app.include_router(runs.router)
app.include_router(runs.ws_router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(share.router)
app.include_router(share.public_router)
app.include_router(schedules.router)
app.include_router(test_cases.router)
app.include_router(sentry.router)

# Статика фронтенда (ui/) монтируется последней, чтобы её catch-all "/" не
# перехватывал API-маршруты, зарегистрированные выше.
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.TH_PORT, reload=False)
