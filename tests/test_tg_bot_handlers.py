"""Обработчики текстовых команд бота (app/tg_bot.py::cmd_*) вызываются напрямую
с фейковыми aiogram Message/CommandObject и мок-HubClient — без Dispatcher,
без объектов python-telegram-bot и без сети.

tests/test_tg_bot.py уже покрывает чистые parse_*/format_* функции, полный
кнопочный флоу и контроль доступа (AccessMiddleware) через настоящий
Dispatcher.feed_update; здесь — то, что он не покрывает: сама «проводка»
текстовых команд (разбор аргументов -> HubClient -> ответ), включая обработку
HTTP-ошибок 404 и прочих, и то, что при ошибке разбора аргументов HubClient
вообще не вызывается. aiogram передаёт хендлерам именно те параметры, что
объявлены в их сигнатуре (client/run_chats/last_run/bot берутся из данных
Dispatcher, command — из CommandObject) — здесь они собраны вручную, без
диспетчеризации.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app import tg_bot
from app.tg_bot import (
    HubClient,
    cmd_last,
    cmd_projects,
    cmd_report,
    cmd_run,
    cmd_status,
)


# ------------------------------------------------------------------ фейковые объекты aiogram
class FakeChat:
    def __init__(self, chat_id: int = 555) -> None:
        self.id = chat_id


class FakeMessage:
    def __init__(self, chat_id: int = 555) -> None:
        self.chat = FakeChat(chat_id)
        self.answers: list[str] = []
        self.photos: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)

    async def answer_photo(self, photo, **kwargs) -> None:
        self.photos.append({"photo": photo, **kwargs})


class FakeCommand:
    def __init__(self, args: str | None) -> None:
        self.args = args


def make_client() -> AsyncMock:
    return AsyncMock(spec=HubClient)


@pytest.fixture(autouse=True)
def _no_background_watch(monkeypatch):
    """cmd_run ставит фоновую задачу опроса прогона через asyncio.create_task —
    подменяем саму _watch_run (как в tests/test_tg_bot.py), чтобы не плодить
    реальную задачу, спящую POLL_INTERVAL_SECONDS и переживающую тест."""
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())


PROJECTS = [
    {"name": "bike_fit", "stands": [{"name": "stage"}, {"name": "prod"}]},
    {"name": "Velo_bot", "stands": []},
]


def _not_found(method: str = "GET") -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "not found", request=httpx.Request(method, "http://x"), response=httpx.Response(404)
    )


# ------------------------------------------------------------------ /projects
async def test_cmd_projects_lists_projects_and_stands():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    message = FakeMessage()

    await cmd_projects(message, client)

    client.list_projects.assert_awaited_once()
    assert message.answers == ["Проекты:\n• bike_fit (стенды: stage, prod)\n• Velo_bot (стенды: —)"]


async def test_cmd_projects_empty_list():
    client = make_client()
    client.list_projects.return_value = []
    message = FakeMessage()

    await cmd_projects(message, client)

    assert message.answers == ["Проектов пока нет."]


async def test_cmd_projects_http_error():
    client = make_client()
    client.list_projects.side_effect = httpx.ConnectError("boom")
    message = FakeMessage()

    await cmd_projects(message, client)

    assert message.answers == ["Не удалось получить список проектов."]


# ------------------------------------------------------------------ /run
async def test_cmd_run_missing_arguments_does_not_call_client():
    client = make_client()
    message = FakeMessage()
    command = FakeCommand("bike_fit")  # нет стенда

    await cmd_run(message, command, client, run_chats={}, last_run={}, bot=None)

    assert message.answers == ["Использование: /run <проект> <стенд> [маркер]"]
    client.list_projects.assert_not_called()
    client.submit_run.assert_not_called()


async def test_cmd_run_unknown_project_reports_error_and_skips_submit():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    message = FakeMessage()
    command = FakeCommand("no_such_project stage")

    await cmd_run(message, command, client, run_chats={}, last_run={}, bot=None)

    assert message.answers == ["Проект «no_such_project» не найден. См. /projects."]
    client.submit_run.assert_not_called()


async def test_cmd_run_unknown_stand_reports_error_and_skips_submit():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    message = FakeMessage()
    command = FakeCommand("bike_fit no_such_stand")

    await cmd_run(message, command, client, run_chats={}, last_run={}, bot=None)

    assert message.answers == ["Стенд «no_such_stand» не найден в проекте «bike_fit». См. /projects."]
    client.submit_run.assert_not_called()


async def test_cmd_run_valid_args_submits_and_tracks_run_chats_and_last_run():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    client.submit_run.return_value = {"id": 42}
    message = FakeMessage(chat_id=555)
    command = FakeCommand("bike_fit stage smoke")
    run_chats: dict[int, int] = {}
    last_run: dict[int, int] = {}

    await cmd_run(message, command, client, run_chats=run_chats, last_run=last_run, bot=None)

    client.submit_run.assert_awaited_once_with("bike_fit", "stage", "smoke")
    assert message.answers == ["Прогон #42 поставлен в очередь."]
    assert run_chats[42] == 555
    assert last_run[555] == 42


async def test_cmd_run_list_projects_http_error_skips_submit():
    client = make_client()
    client.list_projects.side_effect = httpx.ConnectError("boom")
    message = FakeMessage()
    command = FakeCommand("bike_fit stage")

    await cmd_run(message, command, client, run_chats={}, last_run={}, bot=None)

    assert message.answers == ["Не удалось получить список проектов."]
    client.submit_run.assert_not_called()


async def test_cmd_run_submit_http_error():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    client.submit_run.side_effect = httpx.ConnectError("boom")
    message = FakeMessage()
    command = FakeCommand("bike_fit stage")
    run_chats: dict[int, int] = {}
    last_run: dict[int, int] = {}

    await cmd_run(message, command, client, run_chats=run_chats, last_run=last_run, bot=None)

    assert message.answers == ["Не удалось поставить прогон."]
    assert run_chats == {}
    assert last_run == {}


# ------------------------------------------------------------------ /status
async def test_cmd_status_without_id_and_without_prior_run_asks_for_id():
    client = make_client()
    message = FakeMessage()
    command = FakeCommand("")

    await cmd_status(message, command, client, last_run={})

    assert message.answers == ["Нет последнего прогона в этом чате. Укажите id: /status <id>"]
    client.get_report.assert_not_called()


async def test_cmd_status_with_explicit_id():
    client = make_client()
    client.get_report.return_value = {
        "id": 7,
        "project": "bike_fit",
        "status": "passed",
        "counts": {"passed": 3, "failed": 0, "broken": 0, "skipped": 0},
    }
    message = FakeMessage()
    command = FakeCommand("7")

    await cmd_status(message, command, client, last_run={})

    client.get_report.assert_awaited_once_with(7)
    assert message.answers == ["Прогон #7 (bike_fit) — пройден\npassed: 3, failed: 0, broken: 0, skipped: 0"]


async def test_cmd_status_reuses_last_run_from_same_chat():
    client = make_client()
    client.get_report.return_value = {"id": 42, "project": "bike_fit", "status": "running", "counts": {}}
    message = FakeMessage(chat_id=555)
    command = FakeCommand("")
    last_run = {555: 42}

    await cmd_status(message, command, client, last_run=last_run)

    client.get_report.assert_awaited_once_with(42)


async def test_cmd_status_last_run_is_per_chat():
    """last_run из чужого чата не должен использоваться для другого чата."""
    client = make_client()
    message = FakeMessage(chat_id=555)
    command = FakeCommand("")
    last_run = {999: 42}  # другой чат

    await cmd_status(message, command, client, last_run=last_run)

    assert message.answers == ["Нет последнего прогона в этом чате. Укажите id: /status <id>"]
    client.get_report.assert_not_called()


async def test_cmd_status_non_numeric_id_reports_usage():
    client = make_client()
    message = FakeMessage()
    command = FakeCommand("abc")

    await cmd_status(message, command, client, last_run={})

    assert message.answers == ["id прогона должен быть числом: /status [id]"]
    client.get_report.assert_not_called()


async def test_cmd_status_not_found_run():
    client = make_client()
    client.get_report.side_effect = _not_found()
    message = FakeMessage()
    command = FakeCommand("999")

    await cmd_status(message, command, client, last_run={})

    assert message.answers == ["Прогон #999 не найден."]


# ------------------------------------------------------------------ /report
async def test_cmd_report_missing_argument_reports_usage():
    client = make_client()
    message = FakeMessage()
    command = FakeCommand("")

    await cmd_report(message, command, client)

    assert message.answers == ["Использование: /report <id>"]
    client.get_report.assert_not_called()


async def test_cmd_report_non_numeric_argument_reports_usage():
    client = make_client()
    message = FakeMessage()
    command = FakeCommand("abc")

    await cmd_report(message, command, client)

    assert message.answers == ["Использование: /report <id>"]
    client.get_report.assert_not_called()


async def test_cmd_report_not_found():
    client = make_client()
    client.get_report.side_effect = _not_found()
    message = FakeMessage()
    command = FakeCommand("5")

    await cmd_report(message, command, client)

    client.get_report.assert_awaited_once_with(5)
    assert message.answers == ["Прогон #5 не найден."]


async def test_cmd_report_formats_full_report():
    client = make_client()
    client.get_report.return_value = {
        "id": 9,
        "project": "bike_fit",
        "status": "failed",
        "duration": 3.5,
        "counts": {"passed": 1, "failed": 1, "broken": 0, "skipped": 0},
        "tests": [{"name": "test_x", "status": "failed", "message": "boom"}],
    }
    client.get_report_png.return_value = b"\x89PNGfakebytes"
    message = FakeMessage()
    command = FakeCommand("9")

    await cmd_report(message, command, client)

    # Отчёт короче лимита подписи -> уходит фото с подписью, без отдельного текста.
    assert message.answers == []
    assert len(message.photos) == 1
    caption = message.photos[0]["caption"]
    assert "Прогон #9 (bike_fit) — провален" in caption
    assert "test_x" in caption


async def test_cmd_report_png_error_falls_back_to_text():
    client = make_client()
    client.get_report.return_value = {
        "id": 9,
        "project": "bike_fit",
        "status": "failed",
        "duration": 3.5,
        "counts": {"passed": 1, "failed": 1, "broken": 0, "skipped": 0},
        "tests": [{"name": "test_x", "status": "failed", "message": "boom"}],
    }
    client.get_report_png.side_effect = httpx.ConnectError("boom")
    message = FakeMessage()
    command = FakeCommand("9")

    await cmd_report(message, command, client)

    assert message.photos == []
    assert "Прогон #9 (bike_fit) — провален" in message.answers[0]


# ------------------------------------------------------------------ /last
async def test_cmd_last_missing_project_argument():
    client = make_client()
    message = FakeMessage()
    command = FakeCommand("")

    await cmd_last(message, command, client)

    assert message.answers == ["Использование: /last <проект>"]
    client.list_runs.assert_not_called()


async def test_cmd_last_no_runs_yet():
    client = make_client()
    client.list_runs.return_value = []
    message = FakeMessage()
    command = FakeCommand("bike_fit")

    await cmd_last(message, command, client)

    client.list_runs.assert_awaited_once_with("bike_fit")
    assert message.answers == ["У проекта «bike_fit» ещё нет прогонов."]
    client.get_report.assert_not_called()


async def test_cmd_last_reports_most_recent_run():
    client = make_client()
    client.list_runs.return_value = [{"id": 9}, {"id": 3}]
    client.get_report.return_value = {
        "id": 9,
        "project": "bike_fit",
        "status": "passed",
        "duration": 1.0,
        "counts": {"passed": 1, "failed": 0, "broken": 0, "skipped": 0},
        "tests": [],
    }
    client.get_report_png.return_value = b"\x89PNGfakebytes"
    message = FakeMessage()
    command = FakeCommand("bike_fit")

    await cmd_last(message, command, client)

    client.get_report.assert_awaited_once_with(9)
    assert message.answers == []
    assert len(message.photos) == 1
    assert "Прогон #9 (bike_fit) — пройден" in message.photos[0]["caption"]


async def test_cmd_last_unknown_project():
    client = make_client()
    client.list_runs.side_effect = _not_found()
    message = FakeMessage()
    command = FakeCommand("no_such_project")

    await cmd_last(message, command, client)

    assert message.answers == ["Проект «no_such_project» не найден."]
    client.get_report.assert_not_called()


async def test_cmd_last_report_http_error_after_list_runs():
    client = make_client()
    client.list_runs.return_value = [{"id": 9}]
    client.get_report.side_effect = httpx.ConnectError("boom")
    message = FakeMessage()
    command = FakeCommand("bike_fit")

    await cmd_last(message, command, client)

    assert message.answers == ["Не удалось получить отчёт."]
