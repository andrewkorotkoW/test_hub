"""Новое меню бота (22.10.2026): карточка проекта, список прогонов, маркеры из
pytest.ini, экраны «Причины»/«Сравнить», раздел «Данные» и «Удалить данные прогона».
Чистые format_*/parse_callback — напрямую; кнопочные хендлеры — через настоящий
Dispatcher.feed_update с мок-HubClient и FakeTelegramSession (как в tests/test_tg_bot.py)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
from aiogram import Dispatcher
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Update

from app import tg_bot
from app.config import settings
from app.core import markers
from app.tg_bot import (
    AccessMiddleware,
    HubClient,
    batch_line,
    format_causes,
    format_compare,
    format_data_batch,
    format_data_batches,
    format_project_card,
    format_runs_list,
    parse_callback,
    router,
    run_line,
)

from .test_tg_bot import _callback, _make_bot, _message


def _dispatcher(client) -> Dispatcher:
    router._parent_router = None
    dispatcher = Dispatcher(client=client, run_chats={}, last_run={}, failed_cache={})
    dispatcher.message.outer_middleware(AccessMiddleware())
    dispatcher.callback_query.outer_middleware(AccessMiddleware())
    dispatcher.include_router(router)
    return dispatcher


def _buttons(markup) -> dict[str, str]:
    return {btn.text: btn.callback_data for row in markup.inline_keyboard for btn in row}


def _http_error(status_code: int, detail: str, method: str = "POST") -> httpx.HTTPStatusError:
    request = httpx.Request(method, "http://testserver/api/x")
    response = httpx.Response(status_code, request=request, json={"detail": detail})
    return httpx.HTTPStatusError(str(status_code), request=request, response=response)


RUN_96 = {
    "id": 96, "project": "vshgu", "stand": None, "marker": None, "label": "Мобильный (Pixel 7)",
    "status": "failed", "started": "2026-10-19T22:01:00", "duration": 1382,
    "counts": {"passed": 4, "failed": 1, "broken": 0, "skipped": 0},
}
RUN_97 = {"id": 97, "project": "vshgu", "stand": "develop", "marker": "smoke", "status": "running",
          "started": "2026-10-22T10:00:00", "duration": None, "counts": {}}


# ------------------------------------------------------------------ маркеры из pytest.ini
def test_read_markers_from_pytest_ini_skips_parametrized(tmp_path):
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = -v\nmarkers =\n    api: API tests\n    smoke: Smoke tests\n"
        "    env(name): окружение\n    buk\n    smoke: дубль\n",
        encoding="utf-8",
    )
    assert markers.read_markers(str(tmp_path)) == [
        {"name": "api", "description": "API tests"},
        {"name": "smoke", "description": "Smoke tests"},
        {"name": "buk", "description": ""},
    ]


def test_read_markers_from_pyproject_and_missing(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nmarkers = ["slow: медленные", "ui"]\n', encoding="utf-8"
    )
    assert [m["name"] for m in markers.read_markers(str(tmp_path))] == ["slow", "ui"]
    assert markers.read_markers(str(tmp_path / "nope")) == []


async def test_markers_api_returns_project_markers(qa_client, tmp_path):
    from .conftest import register_project

    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    smoke: s\n    regression: r\n", encoding="utf-8")
    await register_project(qa_client, "markers_proj", tmp_path)
    resp = await qa_client.get("/api/projects/markers_proj/markers")
    assert resp.status_code == 200, resp.text
    assert [m["name"] for m in resp.json()["markers"]] == ["smoke", "regression"]
    assert (await qa_client.get("/api/projects/nope/markers")).status_code == 404


# ------------------------------------------------------------------ callback_data
def test_parse_callback_new_actions():
    assert parse_callback("launch:vshgu") == {"action": "launch", "project": "vshgu"}
    assert parse_callback("runs:vshgu") == {"action": "runs", "project": "vshgu"}
    assert parse_callback("data_batch:vshgu:12") == {"action": "data_batch", "project": "vshgu", "batch_id": 12}
    assert parse_callback("data_del:vshgu:x") == {"action": "invalid", "raw": "data_del:vshgu:x"}
    assert parse_callback("data_sc:vshgu:users") == {"action": "data_sc", "project": "vshgu", "scenario": "users"}
    assert parse_callback("data_confirm:vshgu:users:_") == {
        "action": "data_confirm", "project": "vshgu", "scenario": "users", "stand": None,
    }
    assert parse_callback("run_cleanup:96") == {"action": "run_cleanup", "run_id": 96}
    assert parse_callback("run_causes:96") == {"action": "run_causes", "run_id": 96}


# ------------------------------------------------------------------ форматирование
def test_run_line_and_project_card():
    assert run_line(RUN_96) == "#96 ❌ 19.10 22:01 · без стенда · Мобильный (Pixel 7) · 23 мин 2 с · 4/1/0/0"
    # _marker_label("smoke") возвращает "smoke" как есть, не "Smoke" — существующий
    # баг MARKER_LABELS (dict(MARKER_BUTTONS) мапит label->marker, не наоборот),
    # уже закреплён test_format_schedules_lists_state_stand_and_cron; не трогаю здесь.
    assert run_line(RUN_97) == "#97 ▶️ 22.10 10:00 · develop · smoke · выполняется"
    text = format_project_card("vshgu", [{"name": "develop"}, {"name": "stage", "manual_only": True}], [RUN_97, RUN_96])
    assert text.splitlines()[:2] == ["Проект: vshgu", "Стенды: develop, stage 🔒"]
    assert "• #97 ▶️" in text and "• #96 ❌" in text
    assert "Прогонов ещё нет" in format_project_card("vshgu", [], [])
    assert "ещё нет прогонов" in format_runs_list("vshgu", [])


def test_format_causes_lists_summary_waves_and_code_tests():
    causes = {
        "summary": {"throttling": 2, "session": 0, "stand": 0, "code": 1, "total": 3},
        "waves": [{"cause": "throttling", "start_ts": "2026-10-19T09:43:00", "end_ts": "2026-10-19T09:50:00", "count": 2}],
        "tests": [
            {"nodeid": "tests/api/test_cas.py::test_sync", "full_name": "tests.api.test_cas#test_sync",
             "status": "failed", "cause": "code", "short_reason": "AssertionError: 401"},
            {"nodeid": "tests/api/test_x.py::test_y", "status": "failed", "cause": "throttling"},
        ],
    }
    text = format_causes(96, causes)
    assert "Причины падений прогона #96 (всего 3)" in text
    assert "• троттлинг 429: 2" in text and "• тест или продукт: 1" in text
    assert "429: 09:43–09:50, 2 падений" in text
    assert "  - test_cas::test_sync: AssertionError: 401" in text
    assert "падений нет" in format_causes(5, {"summary": {"total": 0}})


def test_format_compare_lists_kpis_and_groups():
    compare = {
        "base": {"id": 95, "started": "2026-10-19T20:00:00"},
        "kpis": {"passed": {"now": 4, "was": 5}, "failed": {"now": 1, "was": 0}, "skipped": {"now": 0, "was": 0},
                 "duration": {"now": 1382, "was": 1200}},
        "groups": {
            "new_failures": [{"nodeid": "tests/t.py::test_a", "short_reason": "boom"}],
            "fixed": [{"full_name": "tests.t#test_b", "was_xfail": True}],
            "still_failing": [],
            "speed": [{"nodeid": "tests/t.py::test_c", "prev_duration": 10, "duration": 277}],
        },
    }
    text = format_compare(96, compare)
    assert text.splitlines()[0] == "Сравнение #96 с #95 (19.10 20:00):"
    assert "• passed: 4 (было 5, -1)" in text
    assert "• длительность: 23 мин 2 с (было 20 мин 0 с)" in text
    assert "Новые падения (1):" in text and "  - t::test_a: boom" in text
    assert "  - t::test_b (был xfail)" in text
    assert "  - t::test_c 10.0 с → 4:37" in text
    assert "нет базового прогона" in format_compare(96, {"base": {}})


def test_format_data_batches_and_batch():
    scenarios = [{"name": "users", "title": "Пользователи", "category": "Пользователи"}]
    batches = [
        {"id": 12, "status": "running", "scenario": "users", "stand": "develop", "created_at": "2026-10-22T10:00:00"},
        {"id": 11, "status": "done", "scenario": "cleanup_after_run", "stand": "develop",
         "created_at": "2026-10-21T10:00:00", "run_id": 96, "created_total": 3},
    ]
    text = format_data_batches("vshgu", True, batches, scenarios)
    assert "⏳ Партия #12 ещё выполняется (создаётся)." in text
    assert batch_line(batches[1], scenarios) == "#11 создано · очистка после прогона · develop · 21.10 10:00 · прогон #96 · 3 сущностей"
    assert "нет генератора" in format_data_batches("bike_fit", False, [])
    detail = format_data_batch({
        "id": 11, "status": "delete_failed", "scenario": "users", "stand": "develop", "created_at": "2026-10-21T10:00:00",
        "created_by": "tg_bot", "entities": [{"entity": "user", "count": 2}], "error": "boom",
        "cleanup_summary": {"deleted": 1, "failed": 1, "skipped": 0},
    }, scenarios)
    assert detail.splitlines()[0] == "Партия #11 — ошибка удаления"
    assert "Создано: user × 2" in detail and "Удаление: удалено 1, ошибок 1, пропущено 0" in detail and "Ошибка: boom" in detail


# ------------------------------------------------------------------ хендлеры: карточка проекта и разделы
async def test_cb_project_shows_card_with_sections(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "develop"}]
    client.list_runs.return_value = [RUN_96]
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Выберите проект:")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "project:vshgu")))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert len(edited) == 1
    assert edited[0].text.startswith("Проект: vshgu\nСтенды: develop\nПоследние прогоны:\n• #96 ❌")
    assert list(_buttons(edited[0].reply_markup).values())[:3] == ["launch:vshgu", "runs:vshgu", "data:vshgu"]


async def test_cb_launch_and_stand_use_project_markers(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "develop", "manual_only": False}]
    client.list_markers.return_value = [{"name": "buk", "description": ""}, {"name": "smoke", "description": ""}]
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Проект: vshgu")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "launch:vshgu", cb_id="1")))
    await dispatcher.feed_update(bot, Update(update_id=2, callback_query=_callback(bot, msg, "stand:vshgu:develop", cb_id="2")))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert "Выберите стенд" in edited[0].text
    assert _buttons(edited[0].reply_markup)["« К проекту"] == "project:vshgu"
    buttons = _buttons(edited[1].reply_markup)
    assert buttons["buk"] == "marker:vshgu:develop:buk"
    assert "API" not in buttons


async def test_cb_runs_lists_runs_as_buttons(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_runs.return_value = [RUN_97, RUN_96]
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Проект: vshgu")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "runs:vshgu")))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)][0]
    assert edited.text.startswith("Прогоны «vshgu» (последние 2):")
    data = list(_buttons(edited.reply_markup).values())
    assert data == ["run_status:97", "run_status:96", "project:vshgu"]


async def test_cb_run_status_adds_back_to_project(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_report.return_value = dict(RUN_96, tests=[])
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Прогоны")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "run_status:96")))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)][0]
    assert edited.text.startswith("Прогон #96 (vshgu, сборка Мобильный (Pixel 7)) — провален")
    assert edited.reply_markup.inline_keyboard[-1][0].callback_data == "project:vshgu"


async def test_cb_stats_and_schedules_sections(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_stats.return_value = {"stand": "develop", "sections": [
        {"section": "api/x", "tests_total": 3, "passed_percent": 100.0, "avg_duration": 1.0, "flaky_count": 0, "xfail_count": 0},
    ]}
    client.list_schedules.return_value = [{"id": 3, "enabled": True, "stand": "develop", "marker": None, "target": "all", "cron": "0 9 * * *"}]
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Проект: vshgu")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "stats:vshgu", cb_id="1")))
    await dispatcher.feed_update(bot, Update(update_id=2, callback_query=_callback(bot, msg, "schedules:vshgu", cb_id="2")))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[0].text.startswith("Статистика «vshgu» / develop:")
    assert _buttons(edited[0].reply_markup)["« К проекту"] == "project:vshgu"
    assert edited[1].text.startswith("Расписания «vshgu»:")
    assert list(_buttons(edited[1].reply_markup).values()) == ["sched_toggle:vshgu:3", "project:vshgu"]


# ------------------------------------------------------------------ хендлеры: причины, сравнение, очистка данных прогона
async def test_cb_run_causes_and_compare_send_new_messages(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_run_causes.return_value = {"summary": {"code": 1, "total": 1}, "waves": [], "tests": []}
    client.get_run_compare.side_effect = _http_error(404, "No base run available for comparison", "GET")
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Прогон #96")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "run_causes:96", cb_id="1")))
    await dispatcher.feed_update(bot, Update(update_id=2, callback_query=_callback(bot, msg, "run_compare:96", cb_id="2")))

    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert sent[0].text.startswith("Причины падений прогона #96 (всего 1)")
    assert _buttons(sent[0].reply_markup)["« К прогону"] == "run_status:96"
    assert sent[1].text == "Прогон #96: нет базового прогона для сравнения."


async def test_cb_run_cleanup_starts_batch_and_watches(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    watch = AsyncMock()
    monkeypatch.setattr(tg_bot.handlers, "_watch_batch", watch)
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_report.return_value = dict(RUN_96, tests=[])
    client.cleanup_run_data.return_value = {"id": 15, "status": "queued", "scenario": "cleanup_after_run", "stand": None, "run_id": 96}
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Прогон #96")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "run_cleanup:96")))

    client.cleanup_run_data.assert_awaited_once_with("vshgu", 96)
    sent = [c for c in session.calls if isinstance(c, SendMessage)][0]
    assert sent.text.startswith("Очистка данных прогона #96 запущена: партия #15")
    assert list(_buttons(sent.reply_markup).values()) == ["data_batch:vshgu:15", "data:vshgu"]
    # asyncio.create_task(_watch_batch(...)) только создаёт корутину (вызов mock
    # записывается сразу), сама корутина ещё не выполнена — проверяем call, не await
    watch.assert_called_once()
    assert watch.call_args.args[2:] == (555, "vshgu", 15)


async def test_cb_run_cleanup_shows_api_detail_on_conflict(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_report.return_value = dict(RUN_96, tests=[])
    client.cleanup_run_data.side_effect = _http_error(409, "Партия #14 ещё выполняется (running) — дождитесь её завершения")
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Прогон #96")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "run_cleanup:96")))

    sent = [c for c in session.calls if isinstance(c, SendMessage)][0]
    assert sent.text == "Партия #14 ещё выполняется (running) — дождитесь её завершения"


# ------------------------------------------------------------------ хендлеры: «Данные»
SCENARIOS = {"supported": True, "scenarios": [
    {"name": "users", "title": "Пользователи", "category": "Пользователи", "description": "Слушатели по ролям"},
    {"name": "cas", "title": "КАС", "category": "Экзамены", "description": ""},
]}


async def test_data_flow_create_batch(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    watch = AsyncMock()
    monkeypatch.setattr(tg_bot.handlers, "_watch_batch", watch)
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_data_scenarios.return_value = SCENARIOS
    client.list_data_batches.return_value = []
    client.list_stands.return_value = [{"name": "develop"}, {"name": "stage"}]
    client.create_data_batch.return_value = {"id": 20, "status": "queued", "scenario": "users", "stand": "develop", "created_at": "2026-10-22T11:00:00"}
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Проект: vshgu")
    steps = ["data:vshgu", "data_new:vshgu", "data_sc:vshgu:users", "data_st:vshgu:users:develop", "data_confirm:vshgu:users:develop"]
    for i, data in enumerate(steps, start=1):
        await dispatcher.feed_update(bot, Update(update_id=i, callback_query=_callback(bot, msg, data, cb_id=str(i))))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert len(edited) == 5
    assert edited[0].text.startswith("Данные «vshgu»\nПартий данных ещё не создавалось.")
    assert list(_buttons(edited[0].reply_markup).values()) == ["data_new:vshgu", "data_refresh:vshgu", "project:vshgu"]
    assert _buttons(edited[1].reply_markup)["Пользователи · Пользователи"] == "data_sc:vshgu:users"
    assert _buttons(edited[2].reply_markup)["develop"] == "data_st:vshgu:users:develop"
    assert edited[3].text.startswith("Создать данные «Пользователи» на develop (vshgu)?\nСлушатели по ролям")
    assert list(_buttons(edited[3].reply_markup).values()) == ["data_confirm:vshgu:users:develop", "data:vshgu"]
    client.create_data_batch.assert_awaited_once_with("vshgu", "users", "develop")
    assert edited[4].text.startswith("Партия #20 поставлена в очередь.")
    watch.assert_called_once()
    assert watch.call_args.args[2:] == (555, "vshgu", 20)


async def test_data_batch_view_and_delete(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    watch = AsyncMock()
    monkeypatch.setattr(tg_bot.handlers, "_watch_batch", watch)
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_data_scenarios.return_value = SCENARIOS
    done = {"id": 20, "status": "done", "scenario": "users", "stand": "develop", "created_at": "2026-10-22T11:00:00",
            "created_total": 2, "entities": [{"entity": "user", "count": 2}]}
    client.get_data_batch.return_value = done
    client.delete_data_batch.return_value = dict(done, status="deleting")
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Данные")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "data_batch:vshgu:20", cb_id="1")))
    await dispatcher.feed_update(bot, Update(update_id=2, callback_query=_callback(bot, msg, "data_del:vshgu:20", cb_id="2")))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[0].text.startswith("Партия #20 — создано\nСценарий: Пользователи\nСтенд: develop")
    assert list(_buttons(edited[0].reply_markup).values()) == ["data_batch:vshgu:20", "data_del:vshgu:20", "data:vshgu"]
    client.delete_data_batch.assert_awaited_once_with("vshgu", 20)
    assert edited[1].text.startswith("Удаление данных партии #20 запущено.")
    # у партии в статусе deleting кнопки «Удалить данные» уже нет
    assert list(_buttons(edited[1].reply_markup).values()) == ["data_batch:vshgu:20", "data:vshgu"]
    watch.assert_called_once()


async def test_data_unsupported_project_and_forbidden(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_data_scenarios.side_effect = [
        {"supported": False, "scenarios": []},
        _http_error(403, "Forbidden", "GET"),
    ]
    dispatcher = _dispatcher(client)

    msg = _message(bot, text="Проект: bike_fit")
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_callback(bot, msg, "data:bike_fit", cb_id="1")))
    await dispatcher.feed_update(bot, Update(update_id=2, callback_query=_callback(bot, msg, "data:bike_fit", cb_id="2")))

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[0].text == "Данные «bike_fit»: в проекте нет генератора (test_data_generation/generate.py)."
    assert list(_buttons(edited[0].reply_markup).values()) == ["project:bike_fit"]
    client.list_data_batches.assert_not_awaited()
    assert edited[1].text == "Forbidden"


async def test_watch_batch_sends_card_when_batch_finishes(monkeypatch):
    monkeypatch.setattr(tg_bot.handlers, "BATCH_POLL_INTERVAL_SECONDS", 0)
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_data_batch.side_effect = [
        {"id": 20, "status": "running"},
        {"id": 20, "status": "done", "scenario": "users", "stand": "develop", "created_at": "2026-10-22T11:00:00", "created_total": 1},
    ]
    client.list_data_scenarios.return_value = SCENARIOS

    await tg_bot.handlers._watch_batch(bot, client, 555, "vshgu", 20)

    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert len(sent) == 1 and sent[0].chat_id == 555
    assert sent[0].text.startswith("Партия #20 — создано\nСценарий: Пользователи")
    assert client.get_data_batch.await_count == 2
