from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import admin, auth, projects, runs, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="test_hub", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(projects.router)
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
