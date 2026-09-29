import json
from pathlib import Path

import allure
import pytest

pytestmark = [pytest.mark.api]

# Счётчик вызовов в файле (не в памяти процесса — pytest перезапускается заново
# на каждый прогон), сознательно не сбрасывается между прогонами: именно поэтому
# test_catalog_is_eventually_consistent ниже время от времени падает — раз в
# несколько прогонов, а не всегда одинаково (демонстрация флаки-теста).
_FLAKY_STATE_FILE = Path(__file__).resolve().parents[3] / ".state" / "flaky_calls.json"


def _next_flaky_call_count() -> int:
    try:
        count = json.loads(_FLAKY_STATE_FILE.read_text())["count"]
    except (OSError, ValueError, KeyError):
        count = 0
    count += 1
    _FLAKY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FLAKY_STATE_FILE.write_text(json.dumps({"count": count}))
    return count


@allure.title("Список каталога возвращает все товары")
def test_list_returns_items(catalog_api):
    resp = catalog_api.list()
    assert resp.status_code == 200
    titles = {item["title"] for item in resp.json()}
    assert "Кружка Demo" in titles
    assert "Футболка Demo" in titles


@allure.title("Поиск по каталогу нечувствителен к регистру")
def test_list_filter_by_query_case_insensitive(catalog_api):
    resp = catalog_api.list(query="кружка")
    assert resp.status_code == 200
    titles = [item["title"] for item in resp.json()]
    assert titles == ["Кружка Demo"]


@allure.title("Карточка товара по id")
def test_get_item_by_id(catalog_api):
    resp = catalog_api.get(1)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Кружка Demo"


@allure.title("Несуществующий товар — 404")
def test_get_item_not_found(catalog_api):
    resp = catalog_api.get(9999)
    assert resp.status_code == 404


@allure.title("В каждом товаре каталога есть цена, скидка и остаток")
def test_list_item_fields_present(catalog_api):
    resp = catalog_api.list()
    for item in resp.json():
        assert {"id", "title", "price", "discount", "stock"} <= item.keys()


@pytest.mark.skip(reason="пагинация каталога не реализована в демо-сервисе (см. demo/app/routers/catalog.py)")
def test_list_supports_pagination(catalog_api):
    resp = catalog_api.list()
    assert "next_page" in resp.json()


@allure.title("Поиск с опечаткой — известное ограничение")
@pytest.mark.xfail(reason="demo/app/routers/catalog.py: поиск ищет точную подстроку, опечатки не терпит")
def test_search_supports_typos(catalog_api):
    resp = catalog_api.list(query="кружко")
    titles = [item["title"] for item in resp.json()]
    assert titles == ["Кружка Demo"]


@allure.title("Каталог остаётся стабильным между повторными запросами (флаки)")
def test_catalog_is_eventually_consistent(catalog_api):
    # Флаки-тест: падает на каждый третий вызов (счётчик в файле, см.
    # conftest.py::next_flaky_call_count) — демонстрирует, как test_hub считает
    # flips между прогонами (app/core/flaky.py), а не баг демо-сервиса.
    resp = catalog_api.list()
    assert resp.status_code == 200
    assert _next_flaky_call_count() % 3 != 0, "каждый третий прогон намеренно флакует"
