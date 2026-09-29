"""Встроенный демо-сервис test_hub: маленький FastAPI-магазин с намеренным
багом (см. demo/app/routers/orders.py) — на нём построены demo/tests/.

Поднимается самим test_hub (см. app/main.py::lifespan, флаг settings.TH_DEMO)
на порту settings.TH_DEMO_PORT, отдельным процессом uvicorn."""
from fastapi import FastAPI

from . import pages
from .routers import auth, catalog, orders, users

app = FastAPI(title="test_hub demo shop")

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(orders.router)
app.include_router(users.router)
app.include_router(pages.router)
