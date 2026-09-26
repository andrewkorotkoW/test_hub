"""Telegram-бот (app/tg_bot.py): чистые функции парсинга/форматирования без
сети и без объектов telegram, плюс HubClient поверх реального ASGI-приложения
(тот же трюк, что и в tests/conftest.py::client — ASGITransport вместо сокета).

Ниже также интеграционные тесты кнопочного флоу и контроля доступа поверх
настоящего aiogram Dispatcher/Router из app/tg_bot.py, но с полностью
замоканным Telegram (см. FakeTelegramSession — подменяет transport-сессию
aiogram.Bot, никаких запросов к api.telegram.org) и замоканным HTTP test_hub
(httpx.MockTransport вместо реального сервера/сокета)."""

import json
import time

import httpx
import pytest
from httpx import ASGITransport
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, SendPhoto
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app import tg_bot
from app.config import _parse_allowed_ids, settings
from app.db import get_connection
from app.main import app, lifespan
from app.security import verify_password
from app.tg_bot import (
    ACCESS_DENIED_MESSAGE,
    MENU_TEXT,
    STAGE_USAGE,
    HubClient,
    AccessMiddleware,
    _is_allowed,
    _manual_confirm_text,
    build_callback,
    build_confirm_keyboard,
    build_manual_confirm_keyboard,
    build_marker_keyboard,
    build_preset_keyboard,
    build_run_args,
    build_run_keyboard,
    build_schedules_keyboard,
    build_stands_keyboard,
    format_flaky,
    format_projects,
    format_report,
    format_schedules,
    format_status,
    format_xfail,
    parse_callback,
    parse_optional_run_id,
    parse_project_name,
    parse_run_args,
    parse_run_command,
    parse_run_id,
    parse_stage_args,
    router,
)

from .conftest import poll_until, register_project


# ------------------------------------------------------------------ парсинг
def test_parse_run_args_happy_path():
    assert parse_run_args("bike_fit stage") == ("bike_fit", "stage", None)


def test_parse_run_args_with_marker():
    assert parse_run_args("bike_fit stage smoke") == ("bike_fit", "stage", "smoke")


def test_parse_run_args_marker_with_spaces():
    assert parse_run_args("bike_fit stage smoke and not slow") == (
        "bike_fit",
        "stage",
        "smoke and not slow",
    )


@pytest.mark.parametrize("text", ["", "bike_fit"])
def test_parse_run_args_missing_arguments_raises(text):
    with pytest.raises(ValueError, match="Использование"):
        parse_run_args(text)


def test_parse_run_id_ok():
    assert parse_run_id("42", "usage") == 42


@pytest.mark.parametrize("text", ["", "not-a-number"])
def test_parse_run_id_invalid_raises_usage(text):
    with pytest.raises(ValueError, match="usage"):
        parse_run_id(text, "usage")


def test_parse_optional_run_id_absent_is_none():
    assert parse_optional_run_id("") is None


def test_parse_optional_run_id_present():
    assert parse_optional_run_id("7") == 7


def test_parse_optional_run_id_invalid_raises():
    with pytest.raises(ValueError):
        parse_optional_run_id("abc")


def test_parse_project_name_ok():
    assert parse_project_name("bike_fit", "usage") == "bike_fit"


def test_parse_project_name_missing_raises():
    with pytest.raises(ValueError, match="usage"):
        parse_project_name("", "usage")


# ------------------------------------------------------------------ форматирование
def test_format_projects_lists_names_and_stands():
    text = format_projects(
        [
            {"name": "bike_fit", "stands": [{"name": "stage"}, {"name": "prod"}]},
            {"name": "Velo_bot", "stands": []},
        ]
    )
    assert "bike_fit (стенды: stage, prod)" in text
    assert "Velo_bot (стенды: —)" in text


def test_format_projects_empty():
    assert format_projects([]) == "Проектов пока нет."


def test_format_status_shows_status_and_counts():
    report = {
        "id": 5,
        "project": "bike_fit",
        "status": "running",
        "counts": {"passed": 1, "failed": 0, "broken": 0, "skipped": 0},
    }
    text = format_status(report)
    assert "Прогон #5 (bike_fit) — выполняется" in text
    assert "passed: 1, failed: 0, broken: 0, skipped: 0" in text


def test_format_report_includes_duration_and_link():
    report = {
        "id": 9,
        "project": "bike_fit",
        "status": "passed",
        "duration": 12.345,
        "counts": {"passed": 3, "failed": 0, "broken": 0, "skipped": 0},
        "tests": [],
    }
    text = format_report(report)
    assert "пройден" in text
    assert "Длительность: 12.3с" in text
    assert f"http://127.0.0.1:{settings.TH_PORT}/project.html?name=bike_fit&run=9" in text
    assert "Упавшие тесты" not in text


def test_format_report_lists_up_to_15_failed_tests_and_counts_rest():
    tests = [{"name": f"test_{i}", "status": "failed"} for i in range(18)]
    report = {
        "id": 1,
        "project": "p",
        "status": "failed",
        "duration": None,
        "counts": {"passed": 0, "failed": 18, "broken": 0, "skipped": 0},
        "tests": tests,
    }
    text = format_report(report)
    listed = [line for line in text.splitlines() if line.startswith("  - ")]
    assert len(listed) == 15
    assert "…и ещё 3" in text
    assert "Длительность: —" in text


# ------------------------------------------------------------------ доступ
def test_is_allowed_respects_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {1, 2, 3})
    assert _is_allowed(2) is True
    assert _is_allowed(99) is False
    assert _is_allowed(None) is False


def test_is_allowed_empty_allowlist_denies_everyone(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", set())
    assert _is_allowed(1) is False


# ------------------------------------------------------------------ config: парсинг CSV id
def test_parse_allowed_ids_from_csv():
    assert _parse_allowed_ids("1, 2 ,3") == {1, 2, 3}


def test_parse_allowed_ids_ignores_empty_tokens():
    assert _parse_allowed_ids(",1,,2,") == {1, 2}


def test_parse_allowed_ids_empty_string_is_empty_set():
    assert _parse_allowed_ids("") == set()


# ------------------------------------------------------------------ сид сервисной учётки
def test_tg_bot_service_user_seeded(db_path):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE login = ?", (settings.TH_TG_SERVICE_LOGIN,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["role"] == "customer"
    assert verify_password(settings.TH_TG_SERVICE_PASSWORD, row["password_hash"])


# ------------------------------------------------------------------ HubClient поверх реального приложения
def _hub_client() -> HubClient:
    client = HubClient()
    client._client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    return client


async def test_hub_client_logs_in_and_lists_seeded_projects(db_path):
    client = _hub_client()
    try:
        projects = await client.list_projects()
    finally:
        await client.aclose()
    names = {p["name"] for p in projects}
    assert {"bike_fit", "Velo_bot", "auto_tests_vshgu_cloude"} <= names


async def test_hub_client_relogs_in_after_session_lost(db_path):
    client = _hub_client()
    try:
        await client.list_projects()
        assert client._logged_in
        client._client.cookies.clear()  # имитирует протухшую/сброшенную сессию
        projects = await client.list_projects()  # первый запрос получит 401 и перелогинится сам
    finally:
        await client.aclose()
    assert {"bike_fit", "Velo_bot"} <= {p["name"] for p in projects}


async def test_hub_client_full_run_cycle_matches_report_format(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    # Регистрация проекта требует роль qa; сама сервисная учётка бота — customer
    # (см. _seed_tg_bot_user в app/db.py) и намеренно не может создавать проекты.
    await register_project(qa_client, "tg_bot_proj", runnable_project_dir)

    client = _hub_client()
    try:
        run = await client.submit_run("tg_bot_proj", None, None)
        run_id = run["id"]

        async def finished():
            report = await client.get_report(run_id)
            return report if report["status"] in {"passed", "failed"} else None

        report = await poll_until(finished, timeout=15)
        assert report is not None, "прогон не завершился вовремя"
        assert report["status"] == "failed"  # фикстурный проект содержит 2 падающих теста

        runs = await client.list_runs("tg_bot_proj")
        assert runs[0]["id"] == run_id

        text = format_report(report)
        assert "Прогон #" in text
        assert "Упавшие тесты" in text
        assert f"run={run_id}" in text
    finally:
        await client.aclose()


async def test_hub_client_create_share_link_matches_api_format(qa_client, isolated_allure_dir, runnable_project_dir):
    # POST /api/runs/{id}/share требует роль qa/manager (app/routers/share.py) — сервисная
    # учётка бота сидится с ролью customer (app/db.py::_seed_tg_bot_user), поэтому для этого
    # теста роль поднимается вручную, как это сделал бы администратор для реального бота.
    await register_project(qa_client, "tg_bot_share_proj", runnable_project_dir)
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET role = 'qa' WHERE login = ?", (settings.TH_TG_SERVICE_LOGIN,))
        conn.commit()
    finally:
        conn.close()

    run = await qa_client.post("/api/projects/tg_bot_share_proj/runs", json={"target": "tests/test_sample.py"})
    run_id = run.json()["id"]

    client = _hub_client()
    try:
        share = await client.create_share_link(run_id, expires="30d")
    finally:
        await client.aclose()

    assert share["token"]
    assert share["url"].endswith(f"/share/{share['token']}")
    assert share["revoked"] is False


# ------------------------------------------------------------------ парсинг /run без исключений
def test_parse_run_command_happy_path():
    assert parse_run_command("bike_fit stage smoke") == ("bike_fit", "stage", "smoke")


@pytest.mark.parametrize("text", ["", "bike_fit"])
def test_parse_run_command_invalid_returns_none(text):
    assert parse_run_command(text) is None


# ------------------------------------------------------------------ аргументы pytest (зеркалит runner._execute)
def test_build_run_args_env_flag_and_marker():
    assert build_run_args(True, "stage", "smoke") == ["--env", "stage", "-m", "smoke"]


def test_build_run_args_without_env_flag_skips_env():
    assert build_run_args(False, "stage", "smoke") == ["-m", "smoke"]


def test_build_run_args_no_stand_skips_env_even_if_flag_set():
    assert build_run_args(True, None, "smoke") == ["-m", "smoke"]


def test_build_run_args_no_marker_skips_dash_m():
    assert build_run_args(True, "stage", None) == ["--env", "stage"]


def test_build_run_args_all_none_is_empty():
    assert build_run_args(False, None, None) == []


# ------------------------------------------------------------------ callback_data кнопок
def test_build_callback_round_trips_through_parse_callback():
    data = build_callback("marker", project="bike_fit", stand="stage", marker="smoke")
    assert parse_callback(data) == {
        "action": "marker",
        "project": "bike_fit",
        "stand": "stage",
        "marker": "smoke",
    }


def test_build_callback_encodes_none_as_placeholder_and_decodes_back():
    data = build_callback("stand", project="bike_fit", stand=None)
    assert parse_callback(data) == {"action": "stand", "project": "bike_fit", "stand": None}


def test_parse_callback_menu():
    assert parse_callback("menu") == {"action": "menu"}


def test_parse_callback_project():
    assert parse_callback("project:bike_fit") == {"action": "project", "project": "bike_fit"}


def test_parse_callback_confirm_with_none_marker():
    assert parse_callback("confirm:bike_fit:stage:_") == {
        "action": "confirm",
        "project": "bike_fit",
        "stand": "stage",
        "marker": None,
    }


@pytest.mark.parametrize("action", ["run_status", "run_report", "run_cancel", "run_trend", "run_share"])
def test_parse_callback_run_actions(action):
    assert parse_callback(f"{action}:42") == {"action": action, "run_id": 42}


def test_parse_callback_preset():
    assert parse_callback("preset:bike_fit:stage:5") == {
        "action": "preset",
        "project": "bike_fit",
        "stand": "stage",
        "preset_id": 5,
    }


def test_parse_callback_preset_confirm():
    assert parse_callback("preset_confirm:bike_fit:stage:5") == {
        "action": "preset_confirm",
        "project": "bike_fit",
        "stand": "stage",
        "preset_id": 5,
    }


def test_parse_callback_preset_non_integer_id_is_invalid():
    assert parse_callback("preset:bike_fit:stage:abc") == {"action": "invalid", "raw": "preset:bike_fit:stage:abc"}


def test_parse_callback_tree_run_confirm_has_no_fields():
    assert parse_callback("tree_run_confirm") == {"action": "tree_run_confirm"}


@pytest.mark.parametrize(
    "data",
    ["", "unknown", "project", "project:a:b", "run_status:not-a-number", "marker:a:b"],
)
def test_parse_callback_invalid_returns_invalid_action(data):
    assert parse_callback(data) == {"action": "invalid", "raw": data}


# ------------------------------------------------------------------ /stage: разбор аргументов
def test_parse_stage_args_happy_path():
    assert parse_stage_args("bike_fit Smoke") == ("bike_fit", "Smoke")


def test_parse_stage_args_preset_name_with_spaces():
    assert parse_stage_args("bike_fit Custom preset name") == ("bike_fit", "Custom preset name")


@pytest.mark.parametrize("text", ["", "bike_fit"])
def test_parse_stage_args_missing_arguments_raises(text):
    with pytest.raises(ValueError, match="Использование"):
        parse_stage_args(text)


# ------------------------------------------------------------------ inline-клавиатуры
def test_build_stands_keyboard_lists_stand_buttons():
    markup = build_stands_keyboard("bike_fit", [{"name": "stage"}, {"name": "prod"}])
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "stand:bike_fit:stage" in data
    assert "stand:bike_fit:prod" in data


def test_build_stands_keyboard_no_stands_shows_no_stand_button():
    markup = build_stands_keyboard("bike_fit", [])
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "stand:bike_fit:_" in data


def test_build_stands_keyboard_manual_only_stand_shows_lock_label():
    markup = build_stands_keyboard("bike_fit", [{"name": "stage", "manual_only": True}, {"name": "develop", "manual_only": False}])
    buttons = {btn.text: btn.callback_data for row in markup.inline_keyboard for btn in row}
    assert buttons["🔒 stage (только вручную)"] == "stand:bike_fit:stage"
    assert buttons["develop"] == "stand:bike_fit:develop"


def test_build_marker_keyboard_covers_all_four_options():
    markup = build_marker_keyboard("bike_fit", "stage")
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "marker:bike_fit:stage:smoke" in data
    assert "marker:bike_fit:stage:api" in data
    assert "marker:bike_fit:stage:ui" in data
    assert "marker:bike_fit:stage:_" in data  # "Все" -> marker=None


def test_build_confirm_keyboard_has_yes_and_cancel():
    markup = build_confirm_keyboard("bike_fit", "stage", "smoke")
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "confirm:bike_fit:stage:smoke" in data
    assert "menu" in data


def test_build_preset_keyboard_lists_presets_and_tests_and_back_buttons():
    presets = [{"id": 1, "name": "Smoke"}, {"id": 2, "name": "БУК"}]
    markup = build_preset_keyboard("bike_fit", "stage", presets)
    buttons = {btn.text: btn.callback_data for row in markup.inline_keyboard for btn in row}
    assert buttons["Smoke"] == "preset:bike_fit:stage:1"
    assert buttons["БУК"] == "preset:bike_fit:stage:2"
    assert buttons["Выбрать тесты"] == "tests:bike_fit:stage"
    assert buttons["« К стендам"] == "project:bike_fit"


def test_build_manual_confirm_keyboard_has_yes_and_cancel():
    markup = build_manual_confirm_keyboard("preset_confirm:bike_fit:stage:1")
    buttons = {btn.text: btn.callback_data for row in markup.inline_keyboard for btn in row}
    assert buttons["Да, запустить"] == "preset_confirm:bike_fit:stage:1"
    assert buttons["Отмена"] == "menu"


def test_manual_confirm_text_matches_expected_wording():
    assert _manual_confirm_text("stage", "Smoke") == "⚠️ Запуск на stage: Smoke. Подтвердить?"


def test_build_run_keyboard_has_status_report_cancel_trend_share():
    markup = build_run_keyboard(7)
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert data == ["run_status:7", "run_report:7", "run_cancel:7", "run_trend:7", "run_share:7"]


# ------------------------------------------------------------------ lifespan: без токена бот не создаётся
async def test_lifespan_without_token_skips_bot(db_path, monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_BOT_TOKEN", "")
    async with lifespan(app):
        assert app.state.tg_bot is None


# ------------------------------------------------------------------ мок Telegram: Bot/Dispatcher без сети
class FakeTelegramSession:
    """Подменяет aiogram BaseSession (Bot.session): не делает запросов к
    api.telegram.org, только записывает переданные TelegramMethod (SendMessage/
    EditMessageText/AnswerCallbackQuery/...). aiogram вызывает её как
    `await self.session(self, method, timeout=...)` (см. Bot.__call__) и не
    проверяет тип возврата в коде app/tg_bot.py — везде используется только
    факт вызова метода."""

    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, bot, method, timeout=None):
        self.calls.append(method)
        return None

    async def close(self) -> None:
        return None


def _make_bot() -> tuple[Bot, FakeTelegramSession]:
    session = FakeTelegramSession()
    # Токен формально валиден (validate_token хочет "<цифры>:<непусто>"), но
    # никогда не используется для реального похода в сеть — вся отправка идёт
    # через FakeTelegramSession выше.
    bot = Bot(token="123456:FAKE-TEST-TOKEN", session=session)
    return bot, session


def _make_dispatcher(client) -> Dispatcher:
    # `router` — модульный синглтон app/tg_bot.py, использованный уже прошлым
    # тестом с его собственным (выброшенным) Dispatcher; include_router второй
    # раз на другом родителе иначе кидает RuntimeError ("already attached").
    router._parent_router = None
    dispatcher = Dispatcher(client=client, run_chats={}, last_run={})
    dispatcher.message.outer_middleware(AccessMiddleware())
    dispatcher.callback_query.outer_middleware(AccessMiddleware())
    dispatcher.include_router(router)
    return dispatcher


def _message(bot: Bot, *, chat_id: int = 555, user_id: int = 111, text: str = "/start") -> Message:
    return Message(
        message_id=1,
        date=int(time.time()),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="U"),
        text=text,
    ).as_(bot)


def _callback(bot: Bot, message: Message, data: str, *, user_id: int = 111, cb_id: str = "cb") -> CallbackQuery:
    return CallbackQuery(
        id=cb_id,
        from_user=User(id=user_id, is_bot=False, first_name="U"),
        chat_instance="1",
        data=data,
        message=message,
    ).as_(bot)


# ------------------------------------------------------------------ контроль доступа: не из allowlist не доходит до HubClient
async def test_access_middleware_denies_unknown_user_message(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    dispatcher = _make_dispatcher(client)

    message = _message(bot, user_id=999, text="/start")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    assert [type(c).__name__ for c in session.calls] == ["SendMessage"]
    assert session.calls[0].text == ACCESS_DENIED_MESSAGE
    client.list_projects.assert_not_called()


async def test_access_middleware_denies_unknown_user_callback(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    dispatcher = _make_dispatcher(client)

    msg = _message(bot, user_id=999)
    cb = _callback(bot, msg, "project:bike_fit", user_id=999)
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=cb))

    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery"]
    answer = session.calls[0]
    assert answer.text == ACCESS_DENIED_MESSAGE
    assert answer.show_alert is True
    client.list_stands.assert_not_called()


async def test_access_middleware_allows_listed_user(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_projects.return_value = []
    dispatcher = _make_dispatcher(client)

    message = _message(bot, user_id=111, text="/start")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_projects.assert_awaited_once()
    assert [type(c).__name__ for c in session.calls] == ["SendMessage"]
    assert session.calls[0].text != ACCESS_DENIED_MESSAGE


# ------------------------------------------------------------------ кнопочный флоу целиком: /start -> проект -> стенд -> маркер -> подтверждение
async def test_button_flow_edits_single_message_and_submits_expected_run(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    # Фоновый опрос прогона (_watch_run) не относится к этому сценарию — не
    # даём asyncio.create_task заспавнить реально спящую на 3с задачу, которая
    # переживёт тест и попытается сходить в замоканный HTTP уже после его конца.
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())

    bot, session = _make_bot()
    submitted_runs: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/projects":
            return httpx.Response(
                200,
                json=[{"name": "bike_fit", "stands": [{"name": "stage"}], "use_env_flag": True}],
            )
        if request.method == "GET" and request.url.path == "/api/projects/bike_fit/stands":
            return httpx.Response(200, json=[{"name": "stage"}])
        if request.method == "POST" and request.url.path == "/api/projects/bike_fit/runs":
            submitted_runs.append(json.loads(request.content))
            return httpx.Response(200, json={"id": 42, "status": "queued"})
        raise AssertionError(f"неожиданный запрос к test_hub: {request.method} {request.url}")

    client = HubClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client._logged_in = True  # логин сервисной учётки бота тестируется отдельно в test_hub_client_*

    dispatcher = _make_dispatcher(client)

    try:
        start_message = _message(bot, text="/start")
        await dispatcher.feed_update(bot, Update(update_id=1, message=start_message))

        # Дальше всё — редактирование одного и того же сообщения кнопками,
        # как в реальном боте (edit_text на query.message).
        flow_message = _message(bot, text="Выберите проект:")
        await dispatcher.feed_update(
            bot,
            Update(update_id=2, callback_query=_callback(bot, flow_message, "project:bike_fit", cb_id="c1")),
        )
        await dispatcher.feed_update(
            bot,
            Update(update_id=3, callback_query=_callback(bot, flow_message, "stand:bike_fit:stage", cb_id="c2")),
        )
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=4,
                callback_query=_callback(bot, flow_message, "marker:bike_fit:stage:smoke", cb_id="c3"),
            ),
        )
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=5,
                callback_query=_callback(bot, flow_message, "confirm:bike_fit:stage:smoke", cb_id="c4"),
            ),
        )
    finally:
        await client.aclose()

    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    answered = [c for c in session.calls if isinstance(c, AnswerCallbackQuery)]

    # Одно исходное меню отправлено send_message, всё остальное — правки того
    # же сообщения: новые сообщения на каждый шаг клавиатуры не плодятся.
    assert len(sent) == 1
    assert len(edited) == 4
    assert len(answered) == 4  # каждая callback_query отвечена (query.answer())

    assert "Выберите проект" in sent[0].text

    assert submitted_runs == [{"stand": "stage", "target": "all", "marker": "smoke"}]

    confirm_text = edited[2].text
    assert "Запустить bike_fit / stage / smoke?" in confirm_text
    assert "--env stage -m smoke" in confirm_text  # use_env_flag=True у проекта -> --env в подсказке

    final_message = edited[-1]
    assert "Прогон #42 поставлен в очередь." in final_message.text
    callback_datas = [btn.callback_data for row in final_message.reply_markup.inline_keyboard for btn in row]
    assert callback_datas == ["run_status:42", "run_report:42", "run_cancel:42", "run_trend:42", "run_share:42"]


async def test_button_flow_without_env_flag_omits_env_in_confirm_hint(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    bot, session = _make_bot()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/projects":
            return httpx.Response(
                200,
                json=[{"name": "bike_fit", "stands": [], "use_env_flag": False}],
            )
        raise AssertionError(f"неожиданный запрос к test_hub: {request.method} {request.url}")

    client = HubClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client._logged_in = True
    dispatcher = _make_dispatcher(client)

    try:
        flow_message = _message(bot, text="Выберите проект:")
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=1,
                callback_query=_callback(bot, flow_message, "marker:bike_fit:_:_", cb_id="c1"),
            ),
        )
    finally:
        await client.aclose()

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert len(edited) == 1
    assert "Аргументы pytest" not in edited[0].text  # use_env_flag=False и маркер "Все" -> build_run_args == []


async def test_button_flow_stand_step_does_not_call_hub_client(monkeypatch):
    """cb_stand строит клавиатуру маркеров из уже известных project/stand в
    callback_data (см. cb_project/cb_marker для сравнения) — но с задачи
    "пресеты и подтверждение запуска на stage" он всё же ходит в list_stands,
    чтобы узнать manual_only (это не приходит в callback_data, см.
    build_stands_keyboard/_stand_manual_only) и решить, показывать пресеты
    (manual_only-стенд) или обычную клавиатуру маркеров, как здесь."""
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "stage", "manual_only": False}]
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Выберите стенд:")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "stand:bike_fit:stage", cb_id="c1")),
    )

    client.list_projects.assert_not_called()
    client.list_stands.assert_awaited_once_with("bike_fit")
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert len(edited) == 1
    assert "Выберите набор тестов" in edited[0].text


# ------------------------------------------------------------------ manual_only-стенд: пресеты + подтверждение запуска на stage
async def test_button_flow_manual_only_stand_shows_preset_keyboard_instead_of_markers(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "stage", "manual_only": True}]
    client.list_stand_presets.return_value = [{"id": 1, "name": "Smoke", "target": "all", "marker": "smoke"}]
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Выберите стенд:")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "stand:bike_fit:stage", cb_id="c1")),
    )

    client.list_stand_presets.assert_awaited_once_with("bike_fit", "stage")
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert len(edited) == 1
    assert "Выберите пресет" in edited[0].text
    assert "только вручную" in edited[0].text
    callback_datas = [btn.callback_data for row in edited[0].reply_markup.inline_keyboard for btn in row]
    assert "preset:bike_fit:stage:1" in callback_datas
    assert "tests:bike_fit:stage" in callback_datas


async def test_button_flow_preset_leads_to_confirmation_before_submit(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stand_presets.return_value = [{"id": 1, "name": "Smoke", "target": "all", "marker": "smoke"}]
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Выберите пресет:")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "preset:bike_fit:stage:1", cb_id="c1")),
    )

    client.submit_run.assert_not_called()
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert len(edited) == 1
    assert edited[0].text == "⚠️ Запуск на stage: Smoke. Подтвердить?"
    buttons = {btn.text: btn.callback_data for row in edited[0].reply_markup.inline_keyboard for btn in row}
    assert buttons["Да, запустить"] == "preset_confirm:bike_fit:stage:1"
    assert buttons["Отмена"] == "menu"


async def test_button_flow_preset_confirm_submits_with_confirm_manual_true(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stand_presets.return_value = [{"id": 1, "name": "Smoke", "target": "all", "marker": "smoke"}]
    client.submit_run.return_value = {"id": 99, "status": "queued"}
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="⚠️ Запуск на stage: Smoke. Подтвердить?")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "preset_confirm:bike_fit:stage:1", cb_id="c1")),
    )

    client.submit_run.assert_awaited_once_with("bike_fit", "stage", "smoke", target="all", confirm_manual=True)
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert len(edited) == 1
    assert "Прогон #99 поставлен в очередь." in edited[0].text
    callback_datas = [btn.callback_data for row in edited[0].reply_markup.inline_keyboard for btn in row]
    assert callback_datas == ["run_status:99", "run_report:99", "run_cancel:99", "run_trend:99", "run_share:99"]


@pytest.mark.parametrize(
    "preset,expected_marker",
    [
        pytest.param(
            {"id": 2, "name": "БУК", "target": "tests/api/buk\ntests/ui/buk", "marker": None},
            None,
            id="buk-two-path-target-no-marker",
        ),
        pytest.param(
            {"id": 3, "name": "API", "target": "tests/api", "marker": "api"},
            "api",
            id="api-target-with-marker",
        ),
    ],
)
async def test_button_flow_preset_confirm_submits_expected_target_and_marker(monkeypatch, preset, expected_marker):
    """Разные пресеты — разный target/marker в payload submit_run, но всегда
    confirm_manual=True (см. checklist "миссии": пресет БУК -> два пути через
    \\n и marker=None, пресет с явным маркером -> тот же путь)."""
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stand_presets.return_value = [preset]
    client.submit_run.return_value = {"id": 100, "status": "queued"}
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text=f"⚠️ Запуск на stage: {preset['name']}. Подтвердить?")
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=1,
            callback_query=_callback(
                bot, flow_message, f"preset_confirm:bike_fit:stage:{preset['id']}", cb_id="c1"
            ),
        ),
    )

    client.submit_run.assert_awaited_once_with(
        "bike_fit", "stage", expected_marker, target=preset["target"], confirm_manual=True
    )


async def test_button_flow_preset_confirm_unknown_preset_shows_error_and_does_not_submit(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stand_presets.return_value = []
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="⚠️ Запуск на stage: Smoke. Подтвердить?")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "preset_confirm:bike_fit:stage:1", cb_id="c1")),
    )

    client.submit_run.assert_not_called()
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[0].text == "Пресет не найден."


async def test_button_flow_preset_confirm_shows_generic_error_when_submit_fails(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stand_presets.return_value = [{"id": 1, "name": "Smoke", "target": "all", "marker": "smoke"}]
    client.submit_run.side_effect = httpx.HTTPStatusError(
        "409", request=httpx.Request("POST", "http://x"), response=httpx.Response(409, json={"detail": "manual only"})
    )
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="⚠️ Запуск на stage: Smoke. Подтвердить?")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "preset_confirm:bike_fit:stage:1", cb_id="c1")),
    )

    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[0].text == "Не удалось поставить прогон."


async def test_button_flow_preset_confirm_cancel_returns_to_menu_without_submitting(monkeypatch):
    """Полный флоу: стенд -> пресет -> экран подтверждения -> кнопка "Отмена"
    (callback_data "menu", см. build_manual_confirm_keyboard) — прогон не
    создаётся, submit_run не вызывается вовсе за весь флоу."""
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "stage", "manual_only": True}]
    client.list_stand_presets.return_value = [{"id": 1, "name": "Smoke", "target": "all", "marker": "smoke"}]
    client.list_projects.return_value = [{"name": "bike_fit", "stands": [], "use_env_flag": False}]
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Выберите стенд:")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "stand:bike_fit:stage", cb_id="c1")),
    )
    await dispatcher.feed_update(
        bot,
        Update(update_id=2, callback_query=_callback(bot, flow_message, "preset:bike_fit:stage:1", cb_id="c2")),
    )
    edited_before_cancel = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited_before_cancel[-1].text == "⚠️ Запуск на stage: Smoke. Подтвердить?"
    cancel_callback = {
        btn.text: btn.callback_data
        for row in edited_before_cancel[-1].reply_markup.inline_keyboard
        for btn in row
    }["Отмена"]

    await dispatcher.feed_update(
        bot,
        Update(update_id=3, callback_query=_callback(bot, flow_message, cancel_callback, cb_id="c3")),
    )

    client.submit_run.assert_not_called()
    client.list_projects.assert_awaited_once()
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[-1].text == MENU_TEXT


# ------------------------------------------------------------------ /stage <проект> <пресет>
async def test_cmd_stage_missing_arguments_shows_usage(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/stage bike_fit")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_stands.assert_not_called()
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert sent[0].text == STAGE_USAGE


async def test_cmd_stage_project_without_stage_stand(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "develop", "manual_only": False}]
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/stage bike_fit Smoke")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_stand_presets.assert_not_called()
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert "нет стенда «stage»" in sent[0].text


async def test_cmd_stage_unknown_preset_lists_available_names(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "stage", "manual_only": True}]
    client.list_stand_presets.return_value = [{"id": 1, "name": "Smoke", "target": "all", "marker": "smoke"}]
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/stage bike_fit Unknown")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert "Пресет «Unknown» не найден" in sent[0].text
    assert "Smoke" in sent[0].text


async def test_cmd_stage_known_preset_shows_confirmation_keyboard(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "stage", "manual_only": True}]
    client.list_stand_presets.return_value = [{"id": 7, "name": "Smoke", "target": "all", "marker": "smoke"}]
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/stage bike_fit Smoke")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.submit_run.assert_not_called()
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert sent[0].text == "⚠️ Запуск на stage: Smoke. Подтвердить?"
    buttons = {btn.text: btn.callback_data for row in sent[0].reply_markup.inline_keyboard for btn in row}
    assert buttons["Да, запустить"] == "preset_confirm:bike_fit:stage:7"


async def test_cmd_stage_denied_for_user_outside_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    dispatcher = _make_dispatcher(client)

    message = _message(bot, user_id=999, text="/stage bike_fit Smoke")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_stands.assert_not_called()
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert sent[0].text == ACCESS_DENIED_MESSAGE


# ------------------------------------------------------------------ HubClient: confirm_manual в payload, список пресетов
async def test_hub_client_submit_run_omits_confirm_manual_when_false():
    submitted: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        submitted.append(json.loads(request.content))
        return httpx.Response(200, json={"id": 1, "status": "queued"})

    client = HubClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client._logged_in = True
    try:
        await client.submit_run("p", "stage", "smoke")
    finally:
        await client.aclose()

    assert submitted == [{"stand": "stage", "target": "all", "marker": "smoke"}]


async def test_hub_client_submit_run_includes_confirm_manual_when_true():
    submitted: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        submitted.append(json.loads(request.content))
        return httpx.Response(200, json={"id": 1, "status": "queued"})

    client = HubClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client._logged_in = True
    try:
        await client.submit_run("p", "stage", "smoke", target="tests/test_a.py", confirm_manual=True)
    finally:
        await client.aclose()

    assert submitted == [
        {"stand": "stage", "target": "tests/test_a.py", "marker": "smoke", "confirm_manual": True}
    ]


async def test_hub_client_list_stand_presets_matches_api_format():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/projects/p/stands/stage/presets"
        return httpx.Response(200, json=[{"id": 1, "project": "p", "stand": "stage", "name": "Smoke", "target": "all", "marker": "smoke"}])

    client = HubClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client._logged_in = True
    try:
        presets = await client.list_stand_presets("p", "stage")
    finally:
        await client.aclose()

    assert presets == [{"id": 1, "project": "p", "stand": "stage", "name": "Smoke", "target": "all", "marker": "smoke"}]


# ------------------------------------------------------------------ реальный сервер: сервисная учётка бота всё равно не может запустить manual_only-стенд
async def test_bot_service_account_still_gets_409_on_manual_only_stand_even_via_new_flow(
    qa_client, isolated_allure_dir, runnable_project_dir
):
    """Задача добавляет боту UX подтверждения (confirm_manual=True), но не должна
    ослаблять существующую защиту (см. app/core/runner.py::ManualRunNotConfirmed) —
    сервисная учётка бота (settings.TH_TG_SERVICE_LOGIN) остаётся заблокированной
    даже когда сама «подтверждает» запуск, ровно как и раньше (см.
    tests/test_run_manual_stage.py::test_run_on_manual_only_stand_confirm_but_service_login_still_409)."""
    await register_project(qa_client, "stage_guard_proj", runnable_project_dir)
    stand_resp = await qa_client.post("/api/projects/stage_guard_proj/stands", json={"name": "stage", "url": ""})
    stand_id = stand_resp.json()["id"]
    await qa_client.patch(f"/api/projects/stage_guard_proj/stands/{stand_id}", json={"manual_only": True})

    client = _hub_client()
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.submit_run(
                "stage_guard_proj", "stage", None, target="tests/test_sample.py", confirm_manual=True
            )
    finally:
        await client.aclose()
    assert exc_info.value.response.status_code == 409

    rows = (await qa_client.get("/api/projects/stage_guard_proj/runs")).json()
    assert rows == []


# ------------------------------------------------------------------ фото-отчёт: кнопка «Отчёт»/«Тренд»
_SHORT_REPORT = {
    "id": 42,
    "project": "bike_fit",
    "status": "failed",
    "duration": 3.5,
    "counts": {"passed": 1, "failed": 1, "broken": 0, "skipped": 0},
    "tests": [{"name": "test_x", "status": "failed", "message": "boom"}],
}


def _long_report(n_failed: int = 40) -> dict:
    """Отчёт, чей format_report() заведомо длиннее TELEGRAM_CAPTION_LIMIT (1024) —
    длинные имена и сообщения на каждый из n_failed упавших тестов."""
    tests = [
        {
            "name": f"test_case_number_{i:03d}_with_a_fairly_long_and_descriptive_name",
            "status": "failed",
            "message": "AssertionError: " + "x" * 130,
        }
        for i in range(n_failed)
    ]
    return {
        "id": 43,
        "project": "bike_fit",
        "status": "failed",
        "duration": 12.0,
        "counts": {"passed": 0, "failed": n_failed, "broken": 0, "skipped": 0},
        "tests": tests,
    }


async def test_cb_run_report_sends_photo_with_caption(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_report.return_value = _SHORT_REPORT
    client.get_report_png.return_value = b"\x89PNGfakereportbytes"
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Прогон #42 поставлен в очередь.")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "run_report:42", cb_id="c1")),
    )

    client.get_report.assert_awaited_once_with(42)
    client.get_report_png.assert_awaited_once_with(42)
    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery", "SendPhoto"]
    sent = session.calls[1]
    assert isinstance(sent, SendPhoto)
    assert sent.photo.data == b"\x89PNGfakereportbytes"
    assert "Прогон #42 (bike_fit) — провален" in sent.caption
    assert "passed: 1, failed: 1" in sent.caption


async def test_cb_run_report_long_caption_sends_photo_and_separate_text(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    long_report = _long_report()
    full_caption = format_report(long_report)
    assert len(full_caption) > 1024, "фикстура должна гарантированно превышать лимит подписи"
    client.get_report.return_value = long_report
    client.get_report_png.return_value = b"\x89PNGfakereportbytes"
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Прогон #43 поставлен в очередь.")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "run_report:43", cb_id="c1")),
    )

    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery", "SendPhoto", "SendMessage"]
    photo_call, text_call = session.calls[1], session.calls[2]
    assert isinstance(photo_call, SendPhoto)
    assert photo_call.caption is None  # подпись не влезла -> фото без подписи
    assert isinstance(text_call, SendMessage)
    assert text_call.text == full_caption


async def test_cb_run_trend_sends_photo(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.get_trend_png.return_value = b"\x89PNGfaketrendbytes"
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Прогон #42 поставлен в очередь.")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "run_trend:42", cb_id="c1")),
    )

    client.get_trend_png.assert_awaited_once_with(42)
    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery", "SendPhoto"]
    sent = session.calls[1]
    assert sent.photo.data == b"\x89PNGfaketrendbytes"
    assert sent.caption == "Тренд последних прогонов"


async def test_cb_run_share_sends_link_message(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.create_share_link.return_value = {
        "token": "tok123", "url": "http://127.0.0.1:8700/share/tok123",
        "created_by": "tg_bot", "created_at": "2026-01-01T00:00:00", "expires_at": None, "revoked": False,
    }
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Прогон #42 поставлен в очередь.")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "run_share:42", cb_id="c1")),
    )

    client.create_share_link.assert_awaited_once_with(42, expires="30d")
    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery", "SendMessage"]
    sent = session.calls[1]
    assert "http://127.0.0.1:8700/share/tok123" in sent.text


async def test_cb_run_share_reports_error_on_forbidden(monkeypatch):
    """Сервисная учётка бота сидится с ролью customer (app/db.py::_seed_tg_bot_user),
    у которой по умолчанию нет прав на POST /api/runs/{id}/share (qa/manager, см.
    app/routers/share.py) — бот не должен падать, а должен сообщить об ошибке."""
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    request = httpx.Request("POST", "http://testserver/api/runs/42/share")
    response = httpx.Response(403, request=request, json={"detail": "Forbidden"})
    client.create_share_link.side_effect = httpx.HTTPStatusError("403", request=request, response=response)
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Прогон #42 поставлен в очередь.")
    await dispatcher.feed_update(
        bot,
        Update(update_id=1, callback_query=_callback(bot, flow_message, "run_share:42", cb_id="c1")),
    )

    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery", "SendMessage"]
    assert "Не удалось создать ссылку" in session.calls[1].text


async def test_access_middleware_denies_run_report_callback_without_hitting_client_or_photo(monkeypatch):
    """Тот же сценарий, что test_access_middleware_denies_unknown_user_callback, но на
    callback_data кнопки «Отчёт» — убеждаемся, что новая ветка с фото тоже не достижима
    для пользователя не из allowlist: ни SendPhoto, ни обращений к HubClient."""
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    dispatcher = _make_dispatcher(client)

    msg = _message(bot, user_id=999)
    cb = _callback(bot, msg, "run_report:42", user_id=999)
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=cb))

    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery"]
    answer = session.calls[0]
    assert answer.text == ACCESS_DENIED_MESSAGE
    assert answer.show_alert is True
    client.get_report.assert_not_called()
    client.get_report_png.assert_not_called()
    client.get_trend_png.assert_not_called()


# ------------------------------------------------------------------ форматирование: флаки/дефекты/расписания
def test_format_flaky_lists_top_items_with_percent_and_counts():
    items = [
        {"test": "tests.test_a#test_one", "stand": "stage", "score": 0.75, "fails": 3, "runs": 4},
        {"test": "tests.test_b#test_two", "stand": "stage", "score": 0.5, "fails": 2, "runs": 4},
    ]
    text = format_flaky("bike_fit", "stage", items)
    assert text.splitlines()[0] == "Нестабильные тесты «bike_fit» / stage:"
    assert "• test_one: 75% (3/4 упал)" in text
    assert "• test_two: 50% (2/4 упал)" in text
    # stand явно задан -> суффикс со стендом в строках не дублируется
    assert "стенд stage" not in text


def test_format_flaky_without_stand_shows_stand_per_item():
    items = [{"test": "tests.test_a#test_one", "stand": "stage", "score": 0.5, "fails": 1, "runs": 2}]
    text = format_flaky("bike_fit", None, items)
    assert text.splitlines()[0] == "Нестабильные тесты «bike_fit»:"
    assert "стенд stage" in text


def test_format_flaky_empty_items_shows_placeholder():
    text = format_flaky("bike_fit", "stage", [])
    assert "Пока нет данных" in text


def test_format_xfail_marks_xpass_and_lists_stand():
    items = [
        {"test": "tests.test_a#test_bug", "stand": "stage", "state": "xfail"},
        {"test": "tests.test_b#test_fixed", "stand": "prod", "state": "xpass"},
    ]
    text = format_xfail("bike_fit", items)
    assert text.splitlines()[0] == "Известные дефекты «bike_fit»:"
    assert "• test_bug [stage]: xfail" in text
    assert "• test_fixed [prod]: можно снять xfail (xpass)" in text


def test_format_xfail_empty_items_shows_placeholder():
    assert "Дефектов не найдено" in format_xfail("bike_fit", [])


def test_format_schedules_lists_state_stand_and_cron():
    items = [
        {"id": 5, "stand": "stage", "target": "all", "marker": None, "cron": "0 3 * * 1-5", "enabled": True, "last_run_id": 42},
        {"id": 6, "stand": None, "target": "custom", "marker": "smoke", "cron": "0 4 * * 1-5", "enabled": False, "last_run_id": None},
    ]
    text = format_schedules("bike_fit", items)
    lines = text.splitlines()
    assert lines[0] == "Расписания «bike_fit»:"
    assert lines[1] == "• #5 stage / Все / все тесты — 0 3 * * 1-5 (включено), последний прогон #42"
    assert lines[2] == "• #6 без стенда / smoke / выборочно — 0 4 * * 1-5 (выключено)"


def test_format_schedules_empty_shows_placeholder():
    assert "Расписаний нет" in format_schedules("bike_fit", [])


def test_build_schedules_keyboard_toggle_buttons_encode_project_and_id():
    items = [{"id": 5, "enabled": True}, {"id": 6, "enabled": False}]
    markup = build_schedules_keyboard("bike_fit", items)
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert data == ["sched_toggle:bike_fit:5", "sched_toggle:bike_fit:6", "menu"]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert labels[0].startswith("✅")
    assert labels[1].startswith("▫️")


# ------------------------------------------------------------------ команды /flaky, /xfail, /schedules и кнопка вкл/выкл
async def test_cmd_flaky_sends_formatted_list_with_stand(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_flaky.return_value = [
        {"test": "tests.test_a#test_one", "stand": "stage", "score": 1.0, "fails": 2, "runs": 2}
    ]
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/flaky bike_fit stage")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_flaky.assert_awaited_once_with("bike_fit", "stage")
    assert [type(c).__name__ for c in session.calls] == ["SendMessage"]
    assert session.calls[0].text == format_flaky(
        "bike_fit", "stage", [{"test": "tests.test_a#test_one", "stand": "stage", "score": 1.0, "fails": 2, "runs": 2}]
    )


async def test_cmd_flaky_missing_project_shows_usage(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/flaky")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_flaky.assert_not_called()
    assert session.calls[0].text == "Использование: /flaky <проект> [стенд]"


async def test_cmd_flaky_unknown_project_shows_not_found(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    request = httpx.Request("GET", "http://testserver/api/projects/nope/flaky")
    response = httpx.Response(404, request=request, json={"detail": "Not found"})
    client.list_flaky.side_effect = httpx.HTTPStatusError("404", request=request, response=response)
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/flaky nope")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    assert session.calls[0].text == "Проект «nope» не найден."


async def test_cmd_xfail_sends_formatted_list(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_xfail.return_value = [{"test": "tests.test_a#test_bug", "stand": "stage", "state": "xfail"}]
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/xfail bike_fit")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_xfail.assert_awaited_once_with("bike_fit", None)
    assert session.calls[0].text == format_xfail(
        "bike_fit", [{"test": "tests.test_a#test_bug", "stand": "stage", "state": "xfail"}]
    )


async def test_cmd_schedules_sends_list_with_toggle_keyboard(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_schedules.return_value = [
        {"id": 5, "stand": "stage", "target": "all", "marker": None, "cron": "0 3 * * 1-5", "enabled": True, "last_run_id": None}
    ]
    dispatcher = _make_dispatcher(client)

    message = _message(bot, text="/schedules bike_fit")
    await dispatcher.feed_update(bot, Update(update_id=1, message=message))

    client.list_schedules.assert_awaited_once_with("bike_fit")
    sent = session.calls[0]
    assert "Расписания «bike_fit»" in sent.text
    assert [btn.callback_data for row in sent.reply_markup.inline_keyboard for btn in row] == [
        "sched_toggle:bike_fit:5",
        "menu",
    ]


async def test_cb_sched_toggle_flips_enabled_state_and_edits_keyboard(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    before = {"id": 5, "stand": "stage", "target": "all", "marker": None, "cron": "0 3 * * 1-5", "enabled": True, "last_run_id": None}
    after = {**before, "enabled": False}
    client.list_schedules.side_effect = [[before], [after]]
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Расписания «bike_fit»:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "sched_toggle:bike_fit:5", cb_id="c1"))
    )

    client.set_schedule_enabled.assert_awaited_once_with("bike_fit", 5, False)
    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery", "EditMessageText"]
    edited = session.calls[1]
    assert "выключено" in edited.text
    assert [btn.callback_data for row in edited.reply_markup.inline_keyboard for btn in row] == [
        "sched_toggle:bike_fit:5",
        "menu",
    ]


async def test_cb_sched_toggle_unknown_id_shows_alert_and_does_not_call_set(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_schedules.return_value = []
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Расписания «bike_fit»:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "sched_toggle:bike_fit:999", cb_id="c1"))
    )

    client.set_schedule_enabled.assert_not_called()
    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery"]
    answer = session.calls[0]
    assert answer.text == "Расписание не найдено."
    assert answer.show_alert is True


async def test_cb_flaky_button_from_stands_keyboard_edits_message(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_flaky.return_value = [{"test": "tests.test_a#test_one", "stand": "stage", "score": 1.0, "fails": 1, "runs": 1}]
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Проект: bike_fit\nВыберите стенд:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "flaky:bike_fit", cb_id="c1"))
    )

    client.list_flaky.assert_awaited_once_with("bike_fit")
    assert [type(c).__name__ for c in session.calls] == ["AnswerCallbackQuery", "EditMessageText"]
    assert "Нестабильные тесты «bike_fit»" in session.calls[1].text


async def test_cb_xfail_button_shows_check_button_only_when_items_present(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_xfail.return_value = [{"test": "tests.test_a#test_bug", "stand": "stage", "state": "xfail"}]
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Проект: bike_fit\nВыберите стенд:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "xfail:bike_fit", cb_id="c1"))
    )

    client.list_xfail.assert_awaited_once_with("bike_fit")
    edited = session.calls[1]
    callback_datas = [btn.callback_data for row in edited.reply_markup.inline_keyboard for btn in row]
    assert callback_datas == ["xfail_check:bike_fit", "project:bike_fit"]


async def test_cb_xfail_button_no_items_hides_check_button(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    client.list_xfail.return_value = []
    dispatcher = _make_dispatcher(client)

    flow_message = _message(bot, text="Проект: bike_fit\nВыберите стенд:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "xfail:bike_fit", cb_id="c1"))
    )

    edited = session.calls[1]
    callback_datas = [btn.callback_data for row in edited.reply_markup.inline_keyboard for btn in row]
    assert callback_datas == ["project:bike_fit"]


async def test_access_middleware_denies_flaky_and_schedules_commands(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()
    client = AsyncMock(spec=HubClient)
    dispatcher = _make_dispatcher(client)

    for text in ("/flaky bike_fit", "/xfail bike_fit", "/schedules bike_fit"):
        session.calls.clear()
        message = _message(bot, user_id=999, text=text)
        await dispatcher.feed_update(bot, Update(update_id=1, message=message))
        assert [type(c).__name__ for c in session.calls] == ["SendMessage"]
        assert session.calls[0].text == ACCESS_DENIED_MESSAGE

    client.list_flaky.assert_not_called()
    client.list_xfail.assert_not_called()
    client.list_schedules.assert_not_called()
