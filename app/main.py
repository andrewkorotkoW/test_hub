from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import init_db
from .routers import auth, projects, runs, users


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.TH_PORT, reload=False)
