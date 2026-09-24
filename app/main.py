import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .core import runner, schedule
from .db import init_db
from .routers import admin, auth, coverage, flaky, projects, runs, schedules, share, users, xfail

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

    yield

    scheduler_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await scheduler_task

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
app.include_router(runs.router)
app.include_router(runs.ws_router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(share.router)
app.include_router(share.public_router)
app.include_router(schedules.router)

# Статика фронтенда (ui/) монтируется последней, чтобы её catch-all "/" не
# перехватывал API-маршруты, зарегистрированные выше.
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.TH_PORT, reload=False)
