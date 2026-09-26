"""Дерево тестов кнопками (мультивыбор) и упавшие тесты с перезапуском
(app/tg_bot.py, задачи "Бот: дерево тестов и мультивыбор кнопками" и
"Бот: упавшие тесты кнопками в отчёте + перезапуск").

Три уровня:
- чистые функции (build_callback/parse_callback для tree_open/tree_page,
  build_tree_keyboard-пагинация, длина callback_data) — без aiogram вообще;
- toggle-логика мультивыбора и формирование target — прямой вызов хендлеров
  cb_tree_open/cb_tree_run с лёгкими фейковыми Message/CallbackQuery (без
  Dispatcher, по аналогии с tests/test_tg_bot_handlers.py);
- полный кнопочный флоу через настоящий Dispatcher.feed_update с
  FakeTelegramSession и AsyncMock(spec=HubClient) (техника из
  tests/test_tg_bot.py:391-448).
"""

from __future__ import annotations

import time

import pytest
from unittest.mock import AsyncMock

from aiogram import Dispatcher
from aiogram.methods import EditMessageText, SendMessage, SendPhoto
from aiogram.types import Update

from app import tg_bot
from app.config import settings
from app.tg_bot import (
    MAX_ERROR_TEXT_LEN,
    MENU_TEXT,
    TREE_PAGE_SIZE,
    AccessMiddleware,
    HubClient,
    _tree_item_label,
    build_callback,
    build_flat_tree,
    build_report_keyboard,
    build_tree_keyboard,
    parse_callback,
    router,
)

from .test_tg_bot import FakeTelegramSession, _callback, _make_bot, _message


def _buttons(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def _callback_datas(markup):
    return [btn.callback_data for btn in _buttons(markup)]


# ------------------------------------------------------------------ кодирование/декодирование индекса узла дерева
def test_build_callback_tree_open_round_trips_node_index():
    data = build_callback("tree_open", node="12")
    assert parse_callback(data) == {"action": "tree_open", "node": 12}


def test_build_callback_tree_page_round_trips_page_index():
    data = build_callback("tree_page", page="3")
    assert parse_callback(data) == {"action": "tree_page", "page": 3}


def test_parse_callback_tree_open_non_integer_is_invalid():
    assert parse_callback("tree_open:abc") == {"action": "invalid", "raw": "tree_open:abc"}


def test_parse_callback_tree_page_non_integer_is_invalid():
    assert parse_callback("tree_page:xx") == {"action": "invalid", "raw": "tree_page:xx"}


@pytest.mark.parametrize("action", ["tree_up", "tree_refresh", "tree_select_file", "tree_clear", "tree_run"])
def test_parse_callback_tree_nav_actions_have_no_fields(action):
    assert parse_callback(action) == {"action": action}


# ------------------------------------------------------------------ пагинация списка узлов дерева
def _flat_files_tree(n: int) -> dict:
    """n файлов прямо в корне (без подпапок) -> у корневого узла ровно n
    детей-файлов, отсортированных по имени (см. build_flat_tree/_sorted_children)."""
    return {f"file_{i:02d}.py": {"": [f"test_{i}"]} for i in range(n)}


@pytest.mark.parametrize("n", [1, 7, 8])
def test_tree_keyboard_single_page_has_no_nav_buttons(n):
    nodes = build_flat_tree(_flat_files_tree(n))
    markup = build_tree_keyboard(nodes, "proj", None, 0, 0, set())
    datas = _callback_datas(markup)
    tree_open = [d for d in datas if d.startswith("tree_open:")]
    assert len(tree_open) == n
    assert not any(d.startswith("tree_page:") for d in datas)


@pytest.mark.parametrize("n", [9, 10, 16])
def test_tree_keyboard_first_page_shows_page_size_items_and_forward_nav(n):
    nodes = build_flat_tree(_flat_files_tree(n))
    markup = build_tree_keyboard(nodes, "proj", None, 0, 0, set())
    datas = _callback_datas(markup)
    tree_open = [d for d in datas if d.startswith("tree_open:")]
    assert len(tree_open) == TREE_PAGE_SIZE
    assert "tree_page:1" in datas
    assert not any(d.startswith("tree_page:-") for d in datas)  # первая страница -> нет "назад"


@pytest.mark.parametrize("n,expected_last_page_items", [(9, 1), (10, 2), (16, 8)])
def test_tree_keyboard_last_page_shows_remainder_and_back_nav_only(n, expected_last_page_items):
    nodes = build_flat_tree(_flat_files_tree(n))
    last_page = (n - 1) // TREE_PAGE_SIZE
    markup = build_tree_keyboard(nodes, "proj", None, 0, last_page, set())
    datas = _callback_datas(markup)
    tree_open = [d for d in datas if d.startswith("tree_open:")]
    assert len(tree_open) == expected_last_page_items
    assert f"tree_page:{last_page - 1}" in datas
    assert f"tree_page:{last_page + 1}" not in datas


def test_tree_keyboard_middle_page_has_both_nav_directions():
    nodes = build_flat_tree(_flat_files_tree(20))
    markup = build_tree_keyboard(nodes, "proj", None, 0, 1, set())
    datas = _callback_datas(markup)
    assert "tree_page:0" in datas
    assert "tree_page:2" in datas


# ------------------------------------------------------------------ отметка выбранных тестов в подписи кнопки
def test_tree_item_label_marks_selected_test_with_checkmark():
    node = {"kind": "test", "label": "test_one", "nodeid": "a.py::test_one"}
    assert _tree_item_label(node, set()) == "▫️ test_one"
    assert _tree_item_label(node, {"a.py::test_one"}) == "✅ test_one"


def test_tree_item_label_non_test_nodes_use_kind_icon():
    assert _tree_item_label({"kind": "dir", "label": "tests"}, set()) == "📁 tests"
    assert _tree_item_label({"kind": "file", "label": "test_a.py"}, set()) == "📄 test_a.py"
    assert _tree_item_label({"kind": "class", "label": "TestFoo"}, set()) == "🗂 TestFoo"


# ------------------------------------------------------------------ callback_data укладывается в лимит Telegram (64 байта)
def test_tree_open_callback_data_fits_64_bytes_for_long_realistic_paths():
    long_dir = "very_" * 15 + "nested"
    long_file = "test_" + "module_" * 15 + "name.py"
    long_test = "test_" + "case_with_a_very_descriptive_name_" * 5
    tree = {f"{long_dir}/{long_file}": {"": [long_test]}}
    nodes = build_flat_tree(tree)
    markup = build_tree_keyboard(nodes, "some_realistically_long_project_name", "stage", 0, 0, set())
    for data in _callback_datas(markup):
        assert len(data.encode("utf-8")) <= 64, data


def test_fail_open_callback_data_fits_64_bytes_for_long_test_names():
    long_name = "very.long.module.path." * 8 + "TestSomeReallyLongClassName#test_a_method_with_a_long_name"
    failed = [{"name": long_name, "status": "failed"}]
    markup = build_report_keyboard(999999999, failed)
    for data in _callback_datas(markup):
        assert len(data.encode("utf-8")) <= 64, data


# ------------------------------------------------------------------ toggle-логика мультивыбора и target (прямой вызов хендлеров, без Dispatcher)
class _FakeChat:
    def __init__(self, chat_id: int = 555) -> None:
        self.id = chat_id


class _FakeTreeMessage:
    def __init__(self, chat_id: int = 555) -> None:
        self.chat = _FakeChat(chat_id)
        self.edits: list[tuple[str, object]] = []

    async def edit_text(self, text, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))


class _FakeTreeCallback:
    def __init__(self, data: str, message: _FakeTreeMessage) -> None:
        self.data = data
        self.message = message
        self.answers: list[tuple[tuple, dict]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answers.append((args, kwargs))


def _two_test_nodes():
    tree = {"tests/test_a.py": {"": ["test_one", "test_two"]}}
    nodes = build_flat_tree(tree)
    idx_one = next(i for i, n in enumerate(nodes) if n.get("nodeid") == "tests/test_a.py::test_one")
    idx_two = next(i for i, n in enumerate(nodes) if n.get("nodeid") == "tests/test_a.py::test_two")
    return nodes, idx_one, idx_two


async def test_cb_tree_open_toggles_test_into_and_out_of_selection():
    nodes, idx_one, _idx_two = _two_test_nodes()
    chat_id = 555
    tree_cache = {"proj": (time.monotonic(), nodes, None)}
    browse_state = {chat_id: {"project": "proj", "stand": None, "node": 0, "page": 0}}
    selections: dict[int, set[str]] = {}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)

    query = _FakeTreeCallback(f"tree_open:{idx_one}", message)
    await tg_bot.cb_tree_open(query, client, tree_cache, browse_state, selections)
    assert selections[chat_id] == {nodes[idx_one]["nodeid"]}

    query2 = _FakeTreeCallback(f"tree_open:{idx_one}", message)
    await tg_bot.cb_tree_open(query2, client, tree_cache, browse_state, selections)
    assert selections[chat_id] == set()
    client.get_tests.assert_not_called()  # дерево бралось из tree_cache, не из HTTP


async def test_cb_tree_open_selects_multiple_tests_independently():
    nodes, idx_one, idx_two = _two_test_nodes()
    chat_id = 555
    tree_cache = {"proj": (time.monotonic(), nodes, None)}
    browse_state = {chat_id: {"project": "proj", "stand": None, "node": 0, "page": 0}}
    selections: dict[int, set[str]] = {}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)

    await tg_bot.cb_tree_open(_FakeTreeCallback(f"tree_open:{idx_one}", message), client, tree_cache, browse_state, selections)
    await tg_bot.cb_tree_open(_FakeTreeCallback(f"tree_open:{idx_two}", message), client, tree_cache, browse_state, selections)

    assert selections[chat_id] == {nodes[idx_one]["nodeid"], nodes[idx_two]["nodeid"]}

    # снятие одного из двух не трогает второй
    await tg_bot.cb_tree_open(_FakeTreeCallback(f"tree_open:{idx_one}", message), client, tree_cache, browse_state, selections)
    assert selections[chat_id] == {nodes[idx_two]["nodeid"]}


async def test_cb_tree_open_on_dir_node_navigates_without_touching_selection():
    tree = {"a/test_x.py": {"": ["test_1"]}, "b/test_y.py": {"": ["test_2"]}}
    nodes = build_flat_tree(tree)
    dir_a_idx = next(i for i, n in enumerate(nodes) if n["kind"] == "dir" and n["label"] == "a")
    chat_id = 555
    tree_cache = {"proj": (time.monotonic(), nodes, None)}
    browse_state = {chat_id: {"project": "proj", "stand": None, "node": 0, "page": 0}}
    selections: dict[int, set[str]] = {}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)

    await tg_bot.cb_tree_open(_FakeTreeCallback(f"tree_open:{dir_a_idx}", message), client, tree_cache, browse_state, selections)

    assert browse_state[chat_id]["node"] == dir_a_idx
    assert selections.get(chat_id, set()) == set()


async def test_cb_tree_run_submits_target_joined_by_newline_in_sorted_order(monkeypatch):
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    nodes, idx_one, idx_two = _two_test_nodes()
    chat_id = 555
    browse_state = {chat_id: {"project": "proj", "stand": "stage"}}
    # выбираем в "обратном" порядке — target всё равно должен быть отсортирован
    selections = {chat_id: {nodes[idx_two]["nodeid"], nodes[idx_one]["nodeid"]}}
    run_chats: dict[int, int] = {}
    last_run: dict[int, int] = {}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)
    client.submit_run.return_value = {"id": 321, "status": "queued"}

    query = _FakeTreeCallback("tree_run", message)
    await tg_bot.cb_tree_run(query, client, browse_state, selections, run_chats, last_run, bot=None)

    client.submit_run.assert_awaited_once_with(
        "proj", "stage", None, target=f"{nodes[idx_one]['nodeid']}\n{nodes[idx_two]['nodeid']}"
    )
    assert selections[chat_id] == set()
    assert chat_id not in browse_state


async def test_cb_tree_run_without_selection_shows_alert_and_does_not_submit():
    chat_id = 555
    browse_state = {chat_id: {"project": "proj", "stand": None}}
    selections: dict[int, set[str]] = {}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)

    query = _FakeTreeCallback("tree_run", message)
    await tg_bot.cb_tree_run(query, client, browse_state, selections, {}, {}, bot=None)

    client.submit_run.assert_not_called()
    assert query.answers  # предупреждение через query.answer(..., show_alert=True)
    assert query.answers[-1][1].get("show_alert") is True


# ------------------------------------------------------------------ manual_only-стенд: дерево ведёт на подтверждение, не сразу на submit_run
async def test_cb_tree_run_manual_only_stand_shows_confirmation_instead_of_submitting():
    nodes, idx_one, idx_two = _two_test_nodes()
    chat_id = 555
    browse_state = {chat_id: {"project": "proj", "stand": "stage"}}
    selections = {chat_id: {nodes[idx_one]["nodeid"], nodes[idx_two]["nodeid"]}}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)
    client.list_stands.return_value = [{"name": "stage", "manual_only": True}]

    query = _FakeTreeCallback("tree_run", message)
    await tg_bot.cb_tree_run(query, client, browse_state, selections, {}, {}, bot=None)

    client.submit_run.assert_not_called()
    assert message.edits, "должно быть показано подтверждение, а не мгновенный запуск"
    text, markup = message.edits[-1]
    assert text == "⚠️ Запуск на stage: 2 тест(ов). Подтвердить?"
    buttons = {btn.text: btn.callback_data for row in markup.inline_keyboard for btn in row}
    assert buttons["Да, запустить"] == "tree_run_confirm"
    # состояние (выбор/browse_state) не тронуто — юзер ещё может отменить
    assert selections[chat_id] == {nodes[idx_one]["nodeid"], nodes[idx_two]["nodeid"]}
    assert chat_id in browse_state


async def test_cb_tree_run_confirm_submits_with_confirm_manual_true(monkeypatch):
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    nodes, idx_one, idx_two = _two_test_nodes()
    chat_id = 555
    browse_state = {chat_id: {"project": "proj", "stand": "stage"}}
    selections = {chat_id: {nodes[idx_two]["nodeid"], nodes[idx_one]["nodeid"]}}
    run_chats: dict[int, int] = {}
    last_run: dict[int, int] = {}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)
    client.submit_run.return_value = {"id": 654, "status": "queued"}

    query = _FakeTreeCallback("tree_run_confirm", message)
    await tg_bot.cb_tree_run_confirm(query, client, browse_state, selections, run_chats, last_run, bot=None)

    client.submit_run.assert_awaited_once_with(
        "proj", "stage", None,
        target=f"{nodes[idx_one]['nodeid']}\n{nodes[idx_two]['nodeid']}",
        confirm_manual=True,
    )
    assert selections[chat_id] == set()
    assert chat_id not in browse_state


async def test_cb_tree_run_confirm_without_selection_shows_alert_and_does_not_submit():
    chat_id = 555
    browse_state = {chat_id: {"project": "proj", "stand": "stage"}}
    selections: dict[int, set[str]] = {}
    message = _FakeTreeMessage(chat_id)
    client = AsyncMock(spec=HubClient)

    query = _FakeTreeCallback("tree_run_confirm", message)
    await tg_bot.cb_tree_run_confirm(query, client, browse_state, selections, {}, {}, bot=None)

    client.submit_run.assert_not_called()
    assert query.answers[-1][1].get("show_alert") is True


# ------------------------------------------------------------------ интеграция: полный Dispatcher + FakeTelegramSession
def _make_full_dispatcher(client, tree_cache=None, browse_state=None, selections=None, failed_cache=None) -> Dispatcher:
    router._parent_router = None
    dispatcher = Dispatcher(
        client=client,
        run_chats={},
        last_run={},
        tree_cache=tree_cache if tree_cache is not None else {},
        browse_state=browse_state if browse_state is not None else {},
        selections=selections if selections is not None else {},
        failed_cache=failed_cache if failed_cache is not None else {},
    )
    dispatcher.message.outer_middleware(AccessMiddleware())
    dispatcher.callback_query.outer_middleware(AccessMiddleware())
    dispatcher.include_router(router)
    return dispatcher


async def test_tree_flow_selects_two_tests_and_runs_them_and_clears_selection(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    bot, session = _make_bot()

    tree = {"tests/test_a.py": {"": ["test_one", "test_two"]}}
    nodes = build_flat_tree(tree)
    idx_one = next(i for i, n in enumerate(nodes) if n.get("nodeid") == "tests/test_a.py::test_one")
    idx_two = next(i for i, n in enumerate(nodes) if n.get("nodeid") == "tests/test_a.py::test_two")

    client = AsyncMock(spec=HubClient)
    client.get_tests.return_value = {"tree": tree}
    client.submit_run.return_value = {"id": 77, "status": "queued"}

    tree_cache: dict = {}
    browse_state: dict = {}
    selections: dict = {}
    failed_cache: dict = {}
    dispatcher = _make_full_dispatcher(client, tree_cache, browse_state, selections, failed_cache)

    flow_message = _message(bot, text="Выберите набор тестов:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "tests:bike_fit:_", cb_id="c1"))
    )
    await dispatcher.feed_update(
        bot, Update(update_id=2, callback_query=_callback(bot, flow_message, f"tree_open:{idx_one}", cb_id="c2"))
    )
    await dispatcher.feed_update(
        bot, Update(update_id=3, callback_query=_callback(bot, flow_message, f"tree_open:{idx_two}", cb_id="c3"))
    )
    await dispatcher.feed_update(
        bot, Update(update_id=4, callback_query=_callback(bot, flow_message, "tree_run", cb_id="c4"))
    )

    client.submit_run.assert_awaited_once_with(
        "bike_fit", None, None, target="tests/test_a.py::test_one\ntests/test_a.py::test_two"
    )
    chat_id = flow_message.chat.id
    assert selections.get(chat_id, set()) == set()
    assert chat_id not in browse_state


async def test_tree_flow_manual_only_stand_requires_confirmation_step_before_submit(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    bot, session = _make_bot()

    tree = {"tests/test_a.py": {"": ["test_one"]}}
    nodes = build_flat_tree(tree)
    idx_one = next(i for i, n in enumerate(nodes) if n.get("nodeid") == "tests/test_a.py::test_one")

    client = AsyncMock(spec=HubClient)
    client.get_tests.return_value = {"tree": tree}
    client.list_stands.return_value = [{"name": "stage", "manual_only": True}]
    client.submit_run.return_value = {"id": 88, "status": "queued"}

    dispatcher = _make_full_dispatcher(client)

    flow_message = _message(bot, text="Выберите набор тестов:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "tests:bike_fit:stage", cb_id="c1"))
    )
    await dispatcher.feed_update(
        bot, Update(update_id=2, callback_query=_callback(bot, flow_message, f"tree_open:{idx_one}", cb_id="c2"))
    )
    await dispatcher.feed_update(
        bot, Update(update_id=3, callback_query=_callback(bot, flow_message, "tree_run", cb_id="c3"))
    )

    client.submit_run.assert_not_called()  # первый клик — только подтверждение
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[-1].text == "⚠️ Запуск на stage: 1 тест(ов). Подтвердить?"

    await dispatcher.feed_update(
        bot, Update(update_id=4, callback_query=_callback(bot, flow_message, "tree_run_confirm", cb_id="c4"))
    )

    client.submit_run.assert_awaited_once_with(
        "bike_fit", "stage", None, target="tests/test_a.py::test_one", confirm_manual=True
    )
    final = [c for c in session.calls if isinstance(c, EditMessageText)][-1]
    assert "Прогон #88 поставлен в очередь" in final.text


async def test_tree_flow_manual_only_stand_cancel_returns_to_menu_without_submitting(monkeypatch):
    """Кнопка "Отмена" на экране подтверждения дерева (callback_data "menu")
    — submit_run не вызывается, бот возвращается в меню проектов."""
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    bot, session = _make_bot()

    tree = {"tests/test_a.py": {"": ["test_one"]}}
    nodes = build_flat_tree(tree)
    idx_one = next(i for i, n in enumerate(nodes) if n.get("nodeid") == "tests/test_a.py::test_one")

    client = AsyncMock(spec=HubClient)
    client.get_tests.return_value = {"tree": tree}
    client.list_stands.return_value = [{"name": "stage", "manual_only": True}]
    client.list_projects.return_value = [{"name": "bike_fit", "stands": [], "use_env_flag": False}]

    dispatcher = _make_full_dispatcher(client)

    flow_message = _message(bot, text="Выберите набор тестов:")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "tests:bike_fit:stage", cb_id="c1"))
    )
    await dispatcher.feed_update(
        bot, Update(update_id=2, callback_query=_callback(bot, flow_message, f"tree_open:{idx_one}", cb_id="c2"))
    )
    await dispatcher.feed_update(
        bot, Update(update_id=3, callback_query=_callback(bot, flow_message, "tree_run", cb_id="c3"))
    )
    edited_before_cancel = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited_before_cancel[-1].text == "⚠️ Запуск на stage: 1 тест(ов). Подтвердить?"
    cancel_callback = {
        btn.text: btn.callback_data
        for row in edited_before_cancel[-1].reply_markup.inline_keyboard
        for btn in row
    }["Отмена"]

    await dispatcher.feed_update(
        bot, Update(update_id=4, callback_query=_callback(bot, flow_message, cancel_callback, cb_id="c4"))
    )

    client.submit_run.assert_not_called()
    client.list_projects.assert_awaited_once()
    edited = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edited[-1].text == MENU_TEXT


# ------------------------------------------------------------------ интеграция: упавшие тесты, детали ошибки и перезапуск
def _failing_tree_and_report():
    tree = {"tests/test_mod.py": {"": ["test_alpha"], "TestFoo": ["test_beta"]}}
    report = {
        "id": 55,
        "project": "bike_fit",
        "stand": None,
        "status": "failed",
        "duration": 5.0,
        "counts": {"passed": 0, "failed": 2, "broken": 0, "skipped": 0},
        "tests": [
            {
                "name": "tests.test_mod#test_alpha",
                "status": "failed",
                "message": "AssertionError: boom",
                "trace": "x" * 2000,
            },
            {
                "name": "tests.test_mod.TestFoo#test_beta",
                "status": "failed",
                "message": "assert 1 == 2",
            },
        ],
    }
    return tree, report


def _last_sent_of_type(session, sent_type):
    sent = [c for c in session.calls if isinstance(c, sent_type)]
    assert sent, f"{sent_type.__name__} не найдено среди {[type(c).__name__ for c in session.calls]}"
    return sent[-1]


async def test_fail_open_shows_trimmed_error_then_restart_one_submits_its_nodeid(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    bot, session = _make_bot()

    tree, report = _failing_tree_and_report()
    client = AsyncMock(spec=HubClient)
    client.get_report.return_value = report
    client.get_report_png.return_value = b"\x89PNGfakebytes"
    client.get_tests.return_value = {"tree": tree}
    client.submit_run.return_value = {"id": 100, "status": "queued"}

    dispatcher = _make_full_dispatcher(client)

    flow_message = _message(bot, text="Прогон #55 поставлен в очередь.")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "run_report:55", cb_id="c1"))
    )

    report_media = _last_sent_of_type(session, SendPhoto)
    fail_open_data = next(
        btn.callback_data
        for row in report_media.reply_markup.inline_keyboard
        for btn in row
        if btn.callback_data.startswith("fail_open:55:")
    )
    assert fail_open_data == "fail_open:55:0"  # test_alpha — первый упавший в report["tests"]

    detail_message = _message(bot, text="report")
    await dispatcher.feed_update(
        bot, Update(update_id=2, callback_query=_callback(bot, detail_message, fail_open_data, cb_id="c2"))
    )

    detail_sent = _last_sent_of_type(session, SendMessage)
    assert "❌ tests.test_mod#test_alpha" in detail_sent.text
    assert "AssertionError: boom" in detail_sent.text
    assert "x" * 100 in detail_sent.text
    # message (21) + "\n\n" + trace (2000) обрезаны до MAX_ERROR_TEXT_LEN + многоточие
    error_part = detail_sent.text.split("\n\n", 1)[1]
    assert len(error_part) == MAX_ERROR_TEXT_LEN + 1
    assert error_part.endswith("…")

    restart_data = next(
        btn.callback_data
        for row in detail_sent.reply_markup.inline_keyboard
        for btn in row
        if btn.callback_data.startswith("fail_restart_one:")
    )
    assert restart_data == "fail_restart_one:55:0"

    restart_message = _message(bot, text="detail")
    await dispatcher.feed_update(
        bot, Update(update_id=3, callback_query=_callback(bot, restart_message, restart_data, cb_id="c3"))
    )

    client.submit_run.assert_awaited_once_with("bike_fit", None, None, target="tests/test_mod.py::test_alpha")


async def test_fail_restart_all_submits_every_failing_nodeid_joined_by_newline(monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_ALLOWED_IDS", {111})
    monkeypatch.setattr(tg_bot, "_watch_run", AsyncMock())
    bot, session = _make_bot()

    tree, report = _failing_tree_and_report()
    client = AsyncMock(spec=HubClient)
    client.get_report.return_value = report
    client.get_report_png.return_value = b"\x89PNGfakebytes"
    client.get_tests.return_value = {"tree": tree}
    client.submit_run.return_value = {"id": 101, "status": "queued"}

    dispatcher = _make_full_dispatcher(client)

    flow_message = _message(bot, text="Прогон #55 поставлен в очередь.")
    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_callback(bot, flow_message, "run_report:55", cb_id="c1"))
    )
    report_media = _last_sent_of_type(session, SendPhoto)
    fail_open_data = next(
        btn.callback_data
        for row in report_media.reply_markup.inline_keyboard
        for btn in row
        if btn.callback_data.startswith("fail_open:55:")
    )

    detail_message = _message(bot, text="report")
    await dispatcher.feed_update(
        bot, Update(update_id=2, callback_query=_callback(bot, detail_message, fail_open_data, cb_id="c2"))
    )

    detail_sent = _last_sent_of_type(session, SendMessage)
    restart_all_data = next(
        btn.callback_data
        for row in detail_sent.reply_markup.inline_keyboard
        for btn in row
        if btn.callback_data.startswith("fail_restart_all:")
    )
    assert restart_all_data == "fail_restart_all:55"

    restart_message = _message(bot, text="detail")
    await dispatcher.feed_update(
        bot, Update(update_id=3, callback_query=_callback(bot, restart_message, restart_all_data, cb_id="c3"))
    )

    client.submit_run.assert_awaited_once_with(
        "bike_fit",
        None,
        None,
        target="tests/test_mod.py::test_alpha\ntests/test_mod.py::TestFoo::test_beta",
    )
