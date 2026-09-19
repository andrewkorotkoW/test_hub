"""Обработчики команд бота (app/tg_bot.py::cmd_*) с фейковыми Update/Context и
мок-HubClient — без объектов python-telegram-bot и без сети.

tests/test_tg_bot.py уже покрывает чистые parse_*/format_* функции и HubClient
поверх реального ASGI-приложения; здесь — то, что он не покрывает: сами
обработчики команд (маршрутизация access-check -> HubClient -> ответ), включая
то, что при отказе доступа HubClient не дёргается вообще.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.tg_bot import (
    ACCESS_DENIED_MESSAGE,
    HubClient,
    cmd_last,
    cmd_projects,
    cmd_report,
    cmd_run,
    cmd_status,
)


# ------------------------------------------------------------------ фейковые объекты telegram
class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeChat:
    def __init__(self, chat_id: int = 100) -> None:
        self.id = chat_id
        self.messages: list[str] = []

    async def send_message(self, text: str) -> None:
        self.messages.append(text)


class FakeUpdate:
    def __init__(self, user_id: int | None, chat: FakeChat | None = None) -> None:
        self.effective_user = FakeUser(user_id) if user_id is not None else None
        self.effective_chat = chat if chat is not None else FakeChat()


class FakeApplication:
    """Достаточно bot_data + create_task, чтобы удовлетворить cmd_run/_client_of.

    Фоновая задача наблюдения за прогоном (_watch_run) намеренно не выполняется —
    она опрашивает HubClient каждые POLL_INTERVAL_SECONDS и не относится к тому,
    что проверяют эти тесты (немедленный ответ на команду); .close() у корутины
    предотвращает предупреждение "coroutine was never awaited".
    """

    def __init__(self, client: HubClient) -> None:
        self.bot_data: dict = {"client": client, "last_run": {}}
        self.created_tasks: list = []

    def create_task(self, coro, update=None):
        self.created_tasks.append(coro)
        coro.close()


class FakeContext:
    def __init__(self, args: list[str], client: HubClient) -> None:
        self.args = args
        self.application = FakeApplication(client)


def make_client() -> AsyncMock:
    return AsyncMock(spec=HubClient)


@pytest.fixture(autouse=True)
def _allowed_ids(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {42})


PROJECTS = [
    {"name": "bike_fit", "stands": [{"name": "stage"}, {"name": "prod"}]},
    {"name": "Velo_bot", "stands": []},
]


# ------------------------------------------------------------------ доступ
@pytest.mark.parametrize(
    "handler, args",
    [
        (cmd_projects, []),
        (cmd_run, ["bike_fit", "stage"]),
        (cmd_status, []),
        (cmd_report, ["1"]),
        (cmd_last, ["bike_fit"]),
    ],
)
async def test_denied_user_gets_access_denied_and_client_untouched(handler, args):
    client = make_client()
    chat = FakeChat()
    update = FakeUpdate(user_id=999, chat=chat)
    context = FakeContext(args, client)

    await handler(update, context)

    assert chat.messages == [ACCESS_DENIED_MESSAGE]
    for method_name in ("list_projects", "submit_run", "get_report", "list_runs"):
        getattr(client, method_name).assert_not_called()


async def test_allowed_user_passes_access_check():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext([], client)

    await cmd_projects(update, context)

    client.list_projects.assert_awaited_once()
    assert chat.messages == ["Проекты:\n• bike_fit (стенды: stage, prod)\n• Velo_bot (стенды: —)"]


async def test_user_without_effective_user_is_denied():
    client = make_client()
    chat = FakeChat()
    update = FakeUpdate(user_id=None, chat=chat)
    context = FakeContext([], client)

    await cmd_projects(update, context)

    assert chat.messages == [ACCESS_DENIED_MESSAGE]
    client.list_projects.assert_not_called()


# ------------------------------------------------------------------ /projects
async def test_cmd_projects_empty_list():
    client = make_client()
    client.list_projects.return_value = []
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext([], client)

    await cmd_projects(update, context)

    assert chat.messages == ["Проектов пока нет."]


# ------------------------------------------------------------------ /run
async def test_cmd_run_missing_arguments_does_not_call_client():
    client = make_client()
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["bike_fit"], client)  # нет стенда

    await cmd_run(update, context)

    assert chat.messages == ["Использование: /run <проект> <стенд> [маркер]"]
    client.list_projects.assert_not_called()
    client.submit_run.assert_not_called()


async def test_cmd_run_unknown_project_reports_error_and_skips_submit():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["no_such_project", "stage"], client)

    await cmd_run(update, context)

    assert chat.messages == ["Проект «no_such_project» не найден. См. /projects."]
    client.submit_run.assert_not_called()


async def test_cmd_run_unknown_stand_reports_error_and_skips_submit():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["bike_fit", "no_such_stand"], client)

    await cmd_run(update, context)

    assert chat.messages == ["Стенд «no_such_stand» не найден в проекте «bike_fit». См. /projects."]
    client.submit_run.assert_not_called()


async def test_cmd_run_valid_args_submits_and_replies_with_run_id():
    client = make_client()
    client.list_projects.return_value = PROJECTS
    client.submit_run.return_value = {"id": 42}
    chat = FakeChat(chat_id=555)
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["bike_fit", "stage", "smoke"], client)

    await cmd_run(update, context)

    client.submit_run.assert_awaited_once_with("bike_fit", "stage", "smoke")
    assert chat.messages == ["Прогон #42 поставлен в очередь."]
    assert context.application.bot_data["last_run"][555] == 42
    assert len(context.application.created_tasks) == 1  # фоновое наблюдение поставлено в очередь


async def test_cmd_run_list_projects_http_error_skips_submit():
    client = make_client()
    client.list_projects.side_effect = httpx.ConnectError("boom")
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["bike_fit", "stage"], client)

    await cmd_run(update, context)

    assert chat.messages == ["Не удалось получить список проектов."]
    client.submit_run.assert_not_called()


# ------------------------------------------------------------------ /status
async def test_cmd_status_without_id_and_without_prior_run_asks_for_id():
    client = make_client()
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext([], client)

    await cmd_status(update, context)

    assert chat.messages == ["Нет последнего прогона в этом чате. Укажите id: /status <id>"]
    client.get_report.assert_not_called()


async def test_cmd_status_with_explicit_id():
    client = make_client()
    client.get_report.return_value = {
        "id": 7,
        "project": "bike_fit",
        "status": "passed",
        "counts": {"passed": 3, "failed": 0, "broken": 0, "skipped": 0},
    }
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["7"], client)

    await cmd_status(update, context)

    client.get_report.assert_awaited_once_with(7)
    assert chat.messages == ["Прогон #7 (bike_fit) — пройден\npassed: 3, failed: 0, broken: 0, skipped: 0"]


async def test_cmd_status_reuses_last_run_from_same_chat():
    client = make_client()
    client.get_report.return_value = {
        "id": 42,
        "project": "bike_fit",
        "status": "running",
        "counts": {},
    }
    chat = FakeChat(chat_id=555)
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext([], client)
    context.application.bot_data["last_run"][555] = 42

    await cmd_status(update, context)

    client.get_report.assert_awaited_once_with(42)


async def test_cmd_status_last_run_is_per_chat():
    """last_run из чужого чата не должен использоваться для другого чата."""
    client = make_client()
    chat = FakeChat(chat_id=555)
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext([], client)
    context.application.bot_data["last_run"][999] = 42  # другой чат

    await cmd_status(update, context)

    assert chat.messages == ["Нет последнего прогона в этом чате. Укажите id: /status <id>"]
    client.get_report.assert_not_called()


async def test_cmd_status_not_found_run():
    client = make_client()
    client.get_report.side_effect = httpx.HTTPStatusError(
        "not found", request=httpx.Request("GET", "http://x"), response=httpx.Response(404)
    )
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["999"], client)

    await cmd_status(update, context)

    assert chat.messages == ["Прогон #999 не найден."]


# ------------------------------------------------------------------ /last
async def test_cmd_last_missing_project_argument():
    client = make_client()
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext([], client)

    await cmd_last(update, context)

    assert chat.messages == ["Использование: /last <проект>"]
    client.list_runs.assert_not_called()


async def test_cmd_last_no_runs_yet():
    client = make_client()
    client.list_runs.return_value = []
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["bike_fit"], client)

    await cmd_last(update, context)

    client.list_runs.assert_awaited_once_with("bike_fit")
    assert chat.messages == ["У проекта «bike_fit» ещё нет прогонов."]
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
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["bike_fit"], client)

    await cmd_last(update, context)

    client.get_report.assert_awaited_once_with(9)
    assert "Прогон #9 (bike_fit) — пройден" in chat.messages[0]


async def test_cmd_last_unknown_project():
    client = make_client()
    client.list_runs.side_effect = httpx.HTTPStatusError(
        "not found", request=httpx.Request("GET", "http://x"), response=httpx.Response(404)
    )
    chat = FakeChat()
    update = FakeUpdate(user_id=42, chat=chat)
    context = FakeContext(["no_such_project"], client)

    await cmd_last(update, context)

    assert chat.messages == ["Проект «no_such_project» не найден."]
    client.get_report.assert_not_called()
