"""Сквозная приёмка миссии docs/missions/2026-09-29_demo_project.md (раздел
«Приёмка») — прогоняет то, что из этого чек-листа можно автоматизировать без
ручного живого сервера/браузера: сид Demo на пустой БД, доступность встроенного
демо-сервиса, реальный прогон через runner.submit_run на СИДИРОВАННОМ проекте
Demo/стенде local (а не на отдельно зарегистрированном demo_run_* проекте, как в
tests/test_demo_run.py — там уже проверена сама механика раннера/флаки-флипов),
ненулевые числа отчёта и появление строк во «Флаки»/«Известных дефектах».

Остальная часть чек-листа («Запустить всё» из браузера, кнопка «Отчёт» открывает
Allure, тур на живом qa/qa) проверена вручную (Playwright, headless Chromium) —
см. отчёт по задаче и docs/screenshots/demo_tour_*.png; здесь автоматизирован
только эквивалент через HTTP API/allure-results на диске.
"""
import asyncio
import shutil
import socket
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.config import BASE_DIR
from app.db import DEMO_PROJECT_NAME, DEMO_PROJECT_PATH, DEMO_STAND_NAME

from .conftest import poll_until

_FLAKY_STATE_FILE = Path(DEMO_PROJECT_PATH) / ".state" / "flaky_calls.json"


@pytest.fixture(autouse=True)
def _reset_flaky_state():
    # Как и в tests/test_demo_run.py: счётчик в файле переживает процессы pytest,
    # без сброса "какой по счёту вызов" зависел бы от прогонов demo/tests, уже
    # выполнявшихся на этой машине раньше (в т.ч. вручную при живой проверке).
    shutil.rmtree(_FLAKY_STATE_FILE.parent, ignore_errors=True)
    yield
    shutil.rmtree(_FLAKY_STATE_FILE.parent, ignore_errors=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture()
async def demo_service_url():
    # Тот же способ запуска, что app/main.py::lifespan использует для demo_proc —
    # но на отдельном свободном порту, не на settings.TH_DEMO_PORT (там может уже
    # слушать боевой test_hub).
    port = _free_port()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "demo.app.main:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        cwd=str(BASE_DIR),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                if proc.returncode is not None:
                    raise RuntimeError("демо-сервис упал ещё до готовности")
                try:
                    resp = await client.get(f"{base_url}/api/catalog", timeout=1)
                    if resp.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("демо-сервис не поднялся вовремя")
        yield base_url
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


async def _point_demo_stand_to(qa_client, base_url: str) -> None:
    """Сидированный стенд local указывает на settings.TH_DEMO_PORT (см.
    app/db.py::_seed_demo_project) — переключаем его на порт demo_service_url,
    поднятый этим тестом изолированно, не трогая settings.TH_DEMO_PORT глобально."""
    stands = (await qa_client.get(f"/api/projects/{DEMO_PROJECT_NAME}/stands")).json()
    stand = next(s for s in stands if s["name"] == DEMO_STAND_NAME)
    resp = await qa_client.put(
        f"/api/projects/{DEMO_PROJECT_NAME}/stands/{stand['id']}", json={"url": base_url}
    )
    assert resp.status_code == 200, resp.text


async def _run_and_wait(qa_client, target: str, repeat: int = 1):
    resp = await qa_client.post(
        f"/api/projects/{DEMO_PROJECT_NAME}/runs",
        json={"stand": DEMO_STAND_NAME, "target": target, "repeat": repeat},
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await qa_client.get(f"/api/projects/{DEMO_PROJECT_NAME}/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed", "cancelled"} else None

    final = await poll_until(finished, timeout=60)
    assert final is not None, f"прогон Demo/{target} не завершился вовремя"
    return final


# ------------------------------------------------------------------ п.1 приёмки: Demo на пустой БД, "Запустить всё", числа в отчёте


async def test_demo_seeded_project_run_all_finishes_with_nonzero_counts(
    qa_client, isolated_allure_dir, demo_service_url
):
    # db_path (через qa_client) вызывает init_db() на пустой БД — Demo/local уже
    # сидированы (см. tests/test_demo_seed.py), здесь проверяется дальнейший шаг
    # приёмки: реальный прогон и ненулевые итоговые числа.
    stands_resp = await qa_client.get(f"/api/projects/{DEMO_PROJECT_NAME}/stands")
    assert DEMO_STAND_NAME in {s["name"] for s in stands_resp.json()}

    await _point_demo_stand_to(qa_client, demo_service_url)
    final = await _run_and_wait(qa_client, target="all")
    # намеренный баг demo/app/routers/orders.py делает прогон Demo/all failed по
    # сценарию — это ожидаемое поведение демо-проекта, не ошибка окружения (см.
    # tests/test_demo_run.py::test_demo_api_suite_has_passed_failed_skipped_and_xfail).
    assert final["status"] == "failed"

    counts = final["counts"]
    assert sum(counts.values()) > 0, "прогон не дал результатов — дашборд проекта был бы пустым"
    assert counts.get("passed", 0) > 0
    assert counts.get("failed", 0) > 0

    report_resp = await qa_client.get(f"/api/runs/{final['id']}/report")
    assert report_resp.status_code == 200
    assert report_resp.json()["tests"], "у прогона нет ни одного теста в отчёте"


# ------------------------------------------------------------------ п.1 приёмки: строки во «Флаки» и «Известных дефектах»


async def test_demo_seeded_project_flaky_and_xfail_have_rows_after_runs(
    qa_client, isolated_allure_dir, demo_service_url
):
    # /api/projects/{name}/flaky по умолчанию фильтрует min_runs=3 (см.
    # app/routers/flaky.py) — 3 прогона "Запустить всё" дают историю нужной длины,
    # а флаки-тест намеренно падает на 3-й вызов счётчика (см.
    # demo/tests/api/catalog/test_catalog.py::test_catalog_is_eventually_consistent),
    # так что после 3 прогонов у него будет флип passed->failed.
    await _point_demo_stand_to(qa_client, demo_service_url)
    for _ in range(3):
        await _run_and_wait(qa_client, target="all")

    # flaky.recalc/xfail_registry.recalc уходят в фоновые asyncio.to_thread-задачи
    # из _finalize (см. app/core/runner.py) и не await'ятся раннером — статус
    # прогона может стать passed/failed раньше, чем эти таблицы пересчитаны,
    # поэтому опрашиваем API, а не читаем его один раз сразу после последнего прогона.
    async def flaky_items():
        resp = await qa_client.get(f"/api/projects/{DEMO_PROJECT_NAME}/flaky")
        items = resp.json()["items"]
        return items or None

    flaky_rows = await poll_until(flaky_items, timeout=10)
    assert flaky_rows, "страница «Флаки» пуста после 3 прогонов Demo"
    flaky_test_row = next(
        (r for r in flaky_rows if r["test"].endswith("test_catalog_is_eventually_consistent")), None
    )
    assert flaky_test_row is not None, "намеренно флаки-тест demo/tests не попал в flaky_stats"
    assert flaky_test_row["flips"] >= 1

    async def xfail_items():
        resp = await qa_client.get(f"/api/projects/{DEMO_PROJECT_NAME}/xfail")
        items = resp.json()["items"]
        return items or None

    xfail_rows = await poll_until(xfail_items, timeout=10)
    assert xfail_rows, "страница «Известные дефекты» пуста после прогона Demo"
    assert any(r["state"] == "xfail" for r in xfail_rows)


# ------------------------------------------------------------------ п.2 приёмки: противоречие в текущей реализации


def test_qa_seed_onboarded_flag_contradicts_mission_auto_tour_requirement(db_path):
    """НЕ баг раннера/демо, а несостыковка между кодом и текстом приёмки миссии
    (см. отчёт по задаче): SEED_USERS в app/db.py сидирует qa с onboarded=1 —
    наследие поля из старой статичной модалки (до ui/tour.js). ui/tour.js::
    tourContinueIfActive запускает тур только когда user.onboarded falsy
    (`if (user.onboarded) return;`), поэтому на чистой БД первый вход qa/qa САМ
    тур не запускает — вопреки формулировке приёмки "Первый вход qa/qa запускает
    тур". Тур всё равно доступен через пункт меню «Показать тур» (проверено живым
    Playwright, см. docs/screenshots/demo_tour_*.png) — просто не автоматически.
    Этот тест фиксирует факт (а не чинит db.py — не в роли QA по этой задаче):
    если он упадёт, значит SEED_USERS поменяли и это расхождение больше не
    актуально."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT onboarded FROM users WHERE login = 'qa'").fetchone()
    finally:
        conn.close()
    assert row["onboarded"] == 1
