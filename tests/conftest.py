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

import asyncio
import sys
import time

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


@pytest_asyncio.fixture()
async def superadmin_client(db_path):
    # Собственный AsyncClient (не переиспользует фикстуру `client`): тестам этого
    # файла нужно одновременно держать сессию qa/manager/customer и superadmin —
    # при общем клиенте второй login() затирал бы cookie первого.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await login(ac, "admin", "admin")
        assert resp.status_code == 200
        yield ac


# ---------------------------------------------------------------- фикстурные проекты для тестов раннера
#
# _FIXTURE_TESTS содержит 3 проходящих и 2 падающих теста (один из них в классе), чтобы
# проверять и дерево обнаружения (файл -> класс -> тест), и allure-подсчёты passed/failed.
_FIXTURE_TESTS = '''\
def test_ok():
    assert 1 + 1 == 2


def test_ok_two():
    assert "a" in "abc"


def test_fail():
    assert 1 == 2, "one is definitely not two"


class TestGroup:
    def test_class_a(self):
        assert True

    def test_class_b(self):
        assert False, "boom in class"
'''

EXPECTED_FIXTURE_TREE = {
    "tests/test_sample.py": {
        "": ["test_ok", "test_ok_two", "test_fail"],
        "TestGroup": ["test_class_a", "test_class_b"],
    }
}

_SLOW_TEST = '''\
import time


def test_hangs():
    time.sleep(8)
'''


def _write_tests(tests_dir, content):
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_sample.py").write_text(content)


@pytest.fixture()
def bare_project_dir(tmp_path):
    """Мини-проект с тестами и БЕЗ .venv — для проверки, есть ли в раннере fallback
    на sys.executable, если <project>/.venv/bin/python отсутствует."""
    proj = tmp_path / "bare_proj"
    _write_tests(proj / "tests", _FIXTURE_TESTS)
    return proj


def _with_symlinked_venv(proj):
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


@pytest.fixture()
def runnable_project_dir(tmp_path):
    """Тот же мини-проект, но с .venv/bin/python, указывающим (симлинком) на
    sys.executable текущего процесса — т.к. app/core/runner.py не умеет падать
    назад на sys.executable при отсутствии реального .venv (см. bare_project_dir
    и test_test_tree.py), а тестам очереди/отмены/allure-отчёта нужен реально
    работающий pytest, а не полноценный venv."""
    proj = tmp_path / "runnable_proj"
    _write_tests(proj / "tests", _FIXTURE_TESTS)
    return _with_symlinked_venv(proj)


@pytest.fixture()
def slow_project_dir(tmp_path):
    """Проект с единственным тестом, зависающим на несколько секунд — для проверки
    отмены прогона (cancel должен убить subprocess до его естественного завершения)."""
    proj = tmp_path / "slow_proj"
    tests_dir = proj / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_slow.py").write_text(_SLOW_TEST)
    return _with_symlinked_venv(proj)


@pytest.fixture()
def isolated_allure_dir(tmp_path, monkeypatch):
    """settings.ALLURE_RESULTS_DIR/ALLURE_REPORTS_DIR по умолчанию — фиксированные пути
    внутри репозитория (BASE_DIR/workspace/allure-results и .../allure-reports, см.
    app/config.py), общие для всех прогонов и всех тестовых сессий. Без изоляции
    результаты прогонов с одинаковым (переиспользуемым между тестами, т.к. autoincrement
    сбрасывается вместе с db_path) run_id накапливались бы и просачивались между тестами
    и в рабочий workspace/ репозитория — включая закэшированный на диске статический
    allure-отчёт (app/core/allure_report.py::ensure_static_report короткоcircuit'ит на
    уже существующий report_dir/index.html независимо от allure_cli_available(), см.
    app/routers/share.py), поэтому изолируем оба пути, не только results."""
    monkeypatch.setattr(settings, "ALLURE_RESULTS_DIR", tmp_path / "allure-results")
    monkeypatch.setattr(settings, "ALLURE_REPORTS_DIR", tmp_path / "allure-reports")


async def register_project(client, name, path, venv=".venv"):
    resp = await client.post("/api/projects", json={"name": name, "path": str(path), "venv": venv})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def poll_until(check, timeout=10.0, interval=0.05):
    """Опрашивает async-callable `check` (без аргументов), пока он не вернёт truthy
    значение или не истечёт timeout секунд; возвращает последний результат (falsy,
    обычно None, если так и не дождались)."""
    deadline = time.monotonic() + timeout
    value = await check()
    while not value and time.monotonic() < deadline:
        await asyncio.sleep(interval)
        value = await check()
    return value
