"""Общие фикстуры для тестов test_hub.

test_hub (см. app/config.py) не предоставляет ни переменной окружения, ни
параметра конфигурации для инъекции пути к БД — settings.DB_PATH жёстко
вычисляется как BASE_DIR / "workspace" / "test_hub.db" при импорте модуля.
TH_PORT и TH_SECRET читаются из окружения, а DB_PATH — нет. Это отмечено в
финальном отчёте задачи как найденный (небокирующий) пробел: минимальный
безопасный обходной путь для тестируемости — monkeypatch.setattr(settings,
"DB_PATH", ...) до вызова init_db(); он не требует правок app/, поэтому тесты
ниже используют именно его для полной изоляции от боевого workspace/test_hub.db.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import init_db
from app.main import app


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test_hub.db"
    monkeypatch.setattr(settings, "DB_PATH", path)
    init_db()
    return path


@pytest_asyncio.fixture()
async def client(db_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def login(client: AsyncClient, login_: str, password: str):
    return await client.post("/api/login", json={"login": login_, "password": password})


@pytest_asyncio.fixture()
async def qa_client(client):
    resp = await login(client, "qa", "qa")
    assert resp.status_code == 200
    return client


@pytest_asyncio.fixture()
async def manager_client(client):
    resp = await login(client, "manager", "manager")
    assert resp.status_code == 200
    return client


@pytest_asyncio.fixture()
async def customer_client(client):
    resp = await login(client, "customer", "customer")
    assert resp.status_code == 200
    return client
