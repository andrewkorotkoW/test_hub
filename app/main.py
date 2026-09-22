import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import admin, auth, coverage, projects, runs, users

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

    yield

    if tg_application is not None:
        try:
            await stop_application(tg_application)
        except Exception:
            logger.exception("tg_bot: ошибка при остановке Telegram-бота")


app = FastAPI(title="test_hub", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(coverage.router)
app.include_router(runs.router)
app.include_router(runs.ws_router)
app.include_router(users.router)
app.include_router(admin.router)

# Статика фронтенда (ui/) монтируется последней, чтобы её catch-all "/" не
# перехватывал API-маршруты, зарегистрированные выше.
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.TH_PORT, reload=False)
