"""Общие фикстуры демо-проекта (в стиле auto_tests_vshgu): клиент к встроенному
демо-сервису (см. demo/app/) для API-тестов и обёртки над Playwright `page` для
UI-тестов. Адрес сервиса — STAND_URL, который выставляет app/core/runner.py при
прогоне через test_hub (стенд `local` проекта Demo); без test_hub (ручной pytest
из demo/) используется адрес по умолчанию — тот же порт, что и
app/config.py::Settings.TH_DEMO_PORT."""
import os

import pytest

from api.client import HttpClient
from api.endpoints.auth_endpoint import AuthEndpoint
from api.endpoints.catalog_endpoint import CatalogEndpoint
from api.endpoints.orders_endpoint import OrdersEndpoint
from api.endpoints.users_endpoint import UsersEndpoint

DEFAULT_BASE_URL = "http://127.0.0.1:8710"


def pytest_addoption(parser):
    # Единственный стенд demo-проекта — local. Опция зарегистрирована в стиле
    # auto_tests_vshgu (там --env выбирает между несколькими стендами) — если
    # project.use_env_flag у Demo когда-нибудь включат, раннер (app/core/runner.py)
    # передаст --env local, и сборка не упадёт на "unrecognized arguments".
    parser.addoption("--env", action="store", default="local", help="стенд демо-проекта")


@pytest.fixture(scope="session")
def base_url():
    # Переопределяет одноимённую фикстуру pytest-playwright (см.
    # browser_context_args в самом плагине) — так относительные page.goto("/login")
    # в demo/ui/pages/*.py резолвятся в адрес поднятого test_hub демо-сервиса.
    return os.environ.get("STAND_URL") or DEFAULT_BASE_URL


@pytest.fixture()
def http_client(base_url):
    return HttpClient(base_url)


@pytest.fixture()
def auth_api(http_client):
    return AuthEndpoint(http_client)


@pytest.fixture()
def catalog_api(http_client):
    return CatalogEndpoint(http_client)


@pytest.fixture()
def orders_api(http_client):
    return OrdersEndpoint(http_client)


@pytest.fixture()
def users_api(http_client):
    return UsersEndpoint(http_client)


# Страничные объекты (demo/ui/pages/*.py) сознательно НЕ фикстуры, как API-эндпоинты
# выше, а создаются прямо в теле теста (`LoginPage(page)`): app/core/coverage.py
# (карта покрытия) умеет распознавать и то, и другое для api/endpoints, но для
# ui/pages — только прямое создание в теле теста/фикстуры (см.
# discover_page_routes + _local_class_vars), не транзитивные фикстуры-обёртки.
