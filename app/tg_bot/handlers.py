"""Кнопочный флоу и текстовые команды бота — router, middleware доступа, все
cb_*/cmd_* хендлеры и их приватные async-хелперы, плюс запуск/остановка
aiogram-приложения (TgApplication/build_application/start_application/
stop_application). Самый большой модуль пакета: вся эта часть завязана на общий
Router и на состояние, которое прокидывает Dispatcher (tree_cache, browse_state,
selections, failed_cache, last_run, run_chats — см. build_application), поэтому
дробить её дальше рискованно — see app/tg_bot/__init__.py про monkeypatch
tg_bot.handlers._watch_run в тестах."""
from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
import time
from dataclasses import dataclass, field

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import settings
from .callbacks import build_callback, parse_callback
from .client import HubClient
from .formatting import (
    DATA_ACTIVE_STATUSES,
    STATUS_RU,
    _bad_tests,
    _confirm_text,
    _error_text,
    _manual_confirm_text,
    _stand_label,
    format_causes,
    format_compare,
    format_data_batch,
    format_data_batches,
    format_data_confirm,
    format_flaky,
    format_project_card,
    format_projects,
    format_report,
    format_runs_list,
    format_schedules,
    format_stats,
    format_status,
    format_xfail,
)
from .keyboards import (
    build_back_keyboard,
    build_batch_keyboard,
    build_confirm_keyboard,
    build_data_confirm_keyboard,
    build_data_keyboard,
    build_data_stand_keyboard,
    build_fail_detail_keyboard,
    build_manual_confirm_keyboard,
    build_marker_keyboard,
    build_preset_keyboard,
    build_project_keyboard,
    build_projects_keyboard,
    build_report_keyboard,
    build_run_keyboard,
    build_runs_keyboard,
    build_scenarios_keyboard,
    build_schedules_keyboard,
    build_stands_keyboard,
    build_tree_keyboard,
    build_tree_text,
)
from .parsing import (
    RUN_USAGE,
    parse_flaky_args,
    parse_optional_run_id,
    parse_project_name,
    parse_run_command,
    parse_run_id,
    parse_stage_args,
    parse_stats_args,
    parse_xfail_args,
)
from .tree import _collect_test_nodeids, build_flat_tree, build_full_name_index, build_run_args

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3.0
TERMINAL_STATUSES = {"passed", "failed", "cancelled"}
TELEGRAM_CAPTION_LIMIT = 1024

TREE_CACHE_TTL_SECONDS = 300

REPORT_USAGE = "Использование: /report <id>"
LAST_USAGE = "Использование: /last <проект>"
SCHEDULE_USAGE = "Использование: /schedules <проект>"
STAGE_STAND_NAME = "stage"

# Второй аргумент /run — либо имя стенда (старое поведение, см. RUN_USAGE), либо
# раздел вида "api/<область>"/"ui/<область>"/"e2e" (часть 3 миссии про статистику
# по разделам, дерево разделов в ui/project.js). Раздел проверяется вторым, после
# сверки со списком реальных стендов проекта — так старые тексты вида "/run X prod"
# продолжают работать один в один. Раздел не привязан к стенду (запуск без стенда,
# как flaky-run-btn в ui/project.js), поэтому manual_only-проверка тут ни при чём —
# см. app/core/runner.py::ManualRunNotConfirmed — у стенда stage свой отдельный
# путь через /stage и пресеты, этот код его не затрагивает и не ослабляет.
_SECTION_ARG_RE = re.compile(r"^(?:api|ui)/[\w-]+$|^e2e$")

ACCESS_DENIED_MESSAGE = "Извините, у вас нет доступа к этому боту."
MENU_TEXT = "Выберите проект:"


def _is_allowed(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.TH_TG_ALLOWED_IDS


class AccessMiddleware:
    """outer-middleware на Message и CallbackQuery: без токена/пароля никуда не
    ходит, только сверяет from_user.id со settings.TH_TG_ALLOWED_IDS и либо
    пропускает апдейт дальше, либо коротко отказывает — до любых данных."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if _is_allowed(user.id if user else None):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer(ACCESS_DENIED_MESSAGE, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(ACCESS_DENIED_MESSAGE)
        return None


async def _safe_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def _reply_http_error(message: Message, exc: httpx.HTTPError, action: str, not_found: str | None = None) -> None:
    if not_found is not None and isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        await message.answer(not_found)
        return
    logger.warning("tg_bot: %s: %s", action, exc)
    await message.answer(f"Не удалось {action}.")


def _http_detail(exc: httpx.HTTPError) -> str | None:
    """detail из JSON-ответа test_hub (409 «партия ещё выполняется», 422 «нет
    генератора», 403 по роли) — он уже на русском и понятен пользователю бота."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    try:
        detail = exc.response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return str(detail) if detail else None


async def _send_report_png(
    send_photo,
    send_text,
    run_id: int,
    png: bytes,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """send_photo/send_text — уже связанные с получателем (chat_id/message) корутины
    вида send_photo(photo, caption=..., reply_markup=...) и send_text(text, reply_markup=...).
    Подпись к фото в Telegram ограничена TELEGRAM_CAPTION_LIMIT символами — если отчёт
    длиннее, фото уходит без подписи, а полный текст следом отдельным сообщением."""
    photo = BufferedInputFile(png, filename=f"report_{run_id}.png")
    if len(caption) <= TELEGRAM_CAPTION_LIMIT:
        await send_photo(photo, caption=caption, reply_markup=reply_markup)
    else:
        await send_photo(photo)
        await send_text(caption, reply_markup=reply_markup)


async def _project_use_env_flag(client: HubClient, project: str) -> bool:
    try:
        projects = await client.list_projects()
    except httpx.HTTPError:
        return False
    row = next((p for p in projects if p["name"] == project), None)
    return bool(row and row.get("use_env_flag"))


async def _stand_manual_only(client: HubClient, project: str, stand: str | None) -> bool:
    """manual_only приходит только из /api/projects/{name}/stands, не из
    callback_data (см. build_stands_keyboard) — cb_stand и cb_tree_run
    перезапрашивают его тем же способом, что и _project_use_env_flag."""
    if stand is None:
        return False
    try:
        stands = await client.list_stands(project)
    except httpx.HTTPError:
        return False
    row = next((s for s in stands if s.get("name") == stand), None)
    return bool(row and row.get("manual_only"))


async def _project_markers(client: HubClient, project: str) -> list[dict] | None:
    """Маркеры из pytest.ini проекта (GET /api/projects/{name}/markers); пустой
    список или ошибка API → None, и build_marker_keyboard берёт вшитые Smoke/API/UI."""
    try:
        markers = await client.list_markers(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить маркеры проекта %s: %s", project, exc)
        return None
    return markers or None


async def _data_scenarios(client: HubClient, project: str) -> tuple[bool, list[dict]]:
    """(supported, scenarios) из GET /api/projects/{name}/data/scenarios; при ошибке —
    (False, []) — вызывающий код сам решает, что показать (см. cb_data)."""
    data = await client.list_data_scenarios(project)
    return bool(data.get("supported")), list(data.get("scenarios") or [])


async def _scenarios_or_empty(client: HubClient, project: str) -> list[dict]:
    try:
        _supported, scenarios = await _data_scenarios(client, project)
    except httpx.HTTPError:
        return []
    return scenarios


BATCH_POLL_INTERVAL_SECONDS = 3.0


async def _watch_batch(bot: Bot, client: HubClient, chat_id: int, project: str, batch_id: int) -> None:
    """Фоновый опрос партии данных (создание/удаление/очистка после прогона) — как
    _watch_run для прогонов: по завершении присылает карточку партии в чат."""
    while True:
        await asyncio.sleep(BATCH_POLL_INTERVAL_SECONDS)
        try:
            batch = await client.get_data_batch(project, batch_id)
        except httpx.HTTPError as exc:
            logger.warning("tg_bot: не удалось опросить партию данных #%s: %s", batch_id, exc)
            continue
        if batch.get("status") in DATA_ACTIVE_STATUSES:
            continue
        scenarios = await _scenarios_or_empty(client, project)
        await bot.send_message(chat_id, format_data_batch(batch, scenarios), reply_markup=build_batch_keyboard(project, batch))
        return


async def _load_tree(
    client: HubClient, tree_cache: dict[str, tuple[float, list[dict], str | None]], project: str, force: bool = False
) -> tuple[list[dict] | None, str | None]:
    cached = tree_cache.get(project)
    now = time.monotonic()
    if not force and cached is not None and now - cached[0] < TREE_CACHE_TTL_SECONDS:
        return cached[1], cached[2]
    try:
        data = await client.get_tests(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить дерево тестов проекта %s: %s", project, exc)
        return None, "Не удалось получить дерево тестов."
    error = data.get("error")
    nodes = build_flat_tree(data.get("tree") or {})
    tree_cache[project] = (now, nodes, error)
    return nodes, error


async def _resolve_nodeid(client: HubClient, tree_cache: dict, project: str, test: dict) -> str | None:
    nodes, _error = await _load_tree(client, tree_cache, project)
    if nodes is None:
        return None
    return build_full_name_index(nodes).get(test.get("name") or "")


async def _render_tree(
    message: Message, nodes: list[dict], project: str, stand: str | None, node: int, page: int, selected: set[str], error: str | None
) -> None:
    text = build_tree_text(nodes, project, stand, node, selected, error)
    keyboard = build_tree_keyboard(nodes, project, stand, node, page, selected)
    await _safe_edit(message, text, keyboard)


async def _report_extras(client: HubClient, run_id: int) -> tuple[dict | None, dict | None]:
    """Причины падений и сравнение с предыдущим прогоном — для строк, которые
    format_report добавляет после _counts_line (см. docs/missions/2026-10-13_run_compare_and_causes.md,
    п.5). Best-effort: сбой любого из двух запросов (например, 404 от /compare,
    если на стенде это первый прогон) не должен мешать показать сам отчёт — так же,
    как report.png ниже не блокирует подпись. isinstance-проверка — на случай
    неожиданного (не словарь) ответа клиента, не только HTTPError."""
    causes: dict | None = None
    compare: dict | None = None
    try:
        result = await client.get_run_causes(run_id)
        causes = result if isinstance(result, dict) else None
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить причины падений прогона #%s: %s", run_id, exc)
    try:
        result = await client.get_run_compare(run_id)
        compare = result if isinstance(result, dict) else None
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить сравнение прогона #%s: %s", run_id, exc)
    return causes, compare


async def _watch_run(
    bot: Bot, client: HubClient, run_chats: dict[int, int], run_id: int, failed_cache: dict[int, list[dict]]
) -> None:
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            report = await client.get_report(run_id)
        except httpx.HTTPError as exc:
            logger.warning("tg_bot: не удалось опросить прогон #%s: %s", run_id, exc)
            continue
        if report["status"] in TERMINAL_STATUSES:
            chat_id = run_chats.pop(run_id, None)
            if chat_id is not None:
                causes, compare = await _report_extras(client, run_id)
                caption = format_report(report, causes, compare)
                failed = _bad_tests(report, causes)
                failed_cache[run_id] = failed
                keyboard = build_report_keyboard(run_id, failed)
                try:
                    png = await client.get_report_png(run_id)
                except httpx.HTTPError as exc:
                    logger.warning("tg_bot: не удалось получить report.png для прогона #%s: %s", run_id, exc)
                    await bot.send_message(chat_id, caption, reply_markup=keyboard)
                else:
                    await _send_report_png(
                        functools.partial(bot.send_photo, chat_id),
                        functools.partial(bot.send_message, chat_id),
                        run_id,
                        png,
                        caption,
                        keyboard,
                    )
            return


router = Router(name="tg_bot")


async def _show_menu(message: Message, client: HubClient) -> None:
    try:
        projects = await client.list_projects()
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить список проектов: %s", exc)
        await message.answer("Не удалось получить список проектов.")
        return
    if not projects:
        await message.answer("Проектов пока нет.")
        return
    await message.answer(MENU_TEXT, reply_markup=build_projects_keyboard(projects))


async def _edit_menu(message: Message, client: HubClient) -> None:
    try:
        projects = await client.list_projects()
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить список проектов: %s", exc)
        await _safe_edit(message, "Не удалось получить список проектов.")
        return
    if not projects:
        await _safe_edit(message, "Проектов пока нет.")
        return
    await _safe_edit(message, MENU_TEXT, build_projects_keyboard(projects))


@router.message(CommandStart())
async def on_start(message: Message, client: HubClient) -> None:
    await _show_menu(message, client)


@router.message(F.text == "Меню")
async def on_menu_text(message: Message, client: HubClient) -> None:
    await _show_menu(message, client)


@router.callback_query(F.data == "menu")
async def cb_menu(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is not None:
        await _edit_menu(query.message, client)


@router.callback_query(F.data.startswith("project:"))
async def cb_project(query: CallbackQuery, client: HubClient) -> None:
    """Карточка проекта: стенды, три последних прогона и кнопки разделов
    (build_project_keyboard). Запуск — отдельной кнопкой «Запуск» (cb_launch)."""
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        stands = await client.list_stands(project)
        runs = await client.list_runs(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить данные проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить данные проекта «{project}».", build_back_keyboard("menu", "« К проектам"))
        return
    await _safe_edit(query.message, format_project_card(project, stands, runs), build_project_keyboard(project))


@router.callback_query(F.data.startswith("launch:"))
async def cb_launch(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        stands = await client.list_stands(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить стенды проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить стенды проекта «{project}».")
        return
    text = f"Проект: {project}\nВыберите стенд:"
    await _safe_edit(query.message, text, build_stands_keyboard(project, stands))


@router.callback_query(F.data.startswith("runs:"))
async def cb_runs(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        runs = await client.list_runs(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить прогоны проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить прогоны проекта «{project}».", build_project_keyboard(project))
        return
    await _safe_edit(query.message, format_runs_list(project, runs), build_runs_keyboard(project, runs))


@router.callback_query(F.data.startswith("stats:"))
async def cb_stats(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        data = await client.get_stats(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить статистику проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить статистику проекта «{project}».", build_project_keyboard(project))
        return
    text = format_stats(project, data.get("stand"), data)
    await _safe_edit(query.message, text, build_back_keyboard(build_callback("project", project=project), "« К проекту"))


@router.callback_query(F.data.startswith("schedules:"))
async def cb_schedules(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        items = await client.list_schedules(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить расписания проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить расписания проекта «{project}».", build_project_keyboard(project))
        return
    await _safe_edit(query.message, format_schedules(project, items), build_schedules_keyboard(project, items))


# ------------------------------------------------------------------ «Данные»
async def _show_data(message: Message, client: HubClient, project: str) -> None:
    try:
        supported, scenarios = await _data_scenarios(client, project)
        batches = await client.list_data_batches(project) if supported else []
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить данные проекта %s: %s", project, exc)
        detail = _http_detail(exc) or f"Не удалось получить раздел «Данные» проекта «{project}»."
        await _safe_edit(message, detail, build_project_keyboard(project))
        return
    await _safe_edit(
        message,
        format_data_batches(project, supported, batches, scenarios),
        build_data_keyboard(project, supported, batches, scenarios),
    )


@router.callback_query(F.data.startswith("data:"))
async def cb_data(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    await _show_data(query.message, client, parse_callback(query.data)["project"])


@router.callback_query(F.data.startswith("data_refresh:"))
async def cb_data_refresh(query: CallbackQuery, client: HubClient) -> None:
    await query.answer("Обновлено")
    if query.message is None:
        return
    await _show_data(query.message, client, parse_callback(query.data)["project"])


@router.callback_query(F.data.startswith("data_new:"))
async def cb_data_new(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        supported, scenarios = await _data_scenarios(client, project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить сценарии проекта %s: %s", project, exc)
        await _safe_edit(query.message, _http_detail(exc) or "Не удалось получить список сценариев.", build_project_keyboard(project))
        return
    if not supported or not scenarios:
        await _safe_edit(query.message, format_data_batches(project, False, []), build_project_keyboard(project))
        return
    await _safe_edit(query.message, f"Данные «{project}»\nВыберите, что создать:", build_scenarios_keyboard(project, scenarios))


@router.callback_query(F.data.startswith("data_sc:"))
async def cb_data_scenario(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, scenario = parsed["project"], parsed["scenario"]
    try:
        stands = await client.list_stands(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить стенды проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить стенды проекта «{project}».", build_project_keyboard(project))
        return
    scenarios = await _scenarios_or_empty(client, project)
    title = next((s.get("title") or s["name"] for s in scenarios if s.get("name") == scenario), scenario)
    text = f"Данные «{project}» · {title}\nНа каком стенде создать?"
    await _safe_edit(query.message, text, build_data_stand_keyboard(project, scenario, stands))


@router.callback_query(F.data.startswith("data_st:"))
async def cb_data_stand(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, scenario, stand = parsed["project"], parsed["scenario"], parsed["stand"]
    scenarios = await _scenarios_or_empty(client, project)
    info = next((s for s in scenarios if s.get("name") == scenario), scenario)
    await _safe_edit(query.message, format_data_confirm(project, info, stand), build_data_confirm_keyboard(project, scenario, stand))


@router.callback_query(F.data.startswith("data_confirm:"))
async def cb_data_confirm(query: CallbackQuery, client: HubClient, bot: Bot) -> None:
    if query.message is None:
        await query.answer()
        return
    parsed = parse_callback(query.data)
    project, scenario, stand = parsed["project"], parsed["scenario"], parsed["stand"]
    try:
        batch = await client.create_data_batch(project, scenario, stand)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось создать партию данных %s/%s: %s", project, scenario, exc)
        await query.answer()
        await _safe_edit(query.message, _http_detail(exc) or "Не удалось запустить создание данных.", build_project_keyboard(project))
        return
    await query.answer()
    scenarios = await _scenarios_or_empty(client, project)
    text = f"Партия #{batch['id']} поставлена в очередь. Сообщу, когда данные будут созданы.\n\n{format_data_batch(batch, scenarios)}"
    await _safe_edit(query.message, text, build_batch_keyboard(project, batch))
    asyncio.create_task(_watch_batch(bot, client, query.message.chat.id, project, batch["id"]))


@router.callback_query(F.data.startswith("data_batch:"))
async def cb_data_batch(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, batch_id = parsed["project"], parsed["batch_id"]
    try:
        batch = await client.get_data_batch(project, batch_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить партию данных #%s: %s", batch_id, exc)
        await _safe_edit(query.message, f"Не удалось получить партию #{batch_id}.", build_back_keyboard(build_callback("data", project=project), "« К данным"))
        return
    scenarios = await _scenarios_or_empty(client, project)
    await _safe_edit(query.message, format_data_batch(batch, scenarios), build_batch_keyboard(project, batch))


@router.callback_query(F.data.startswith("data_del:"))
async def cb_data_delete(query: CallbackQuery, client: HubClient, bot: Bot) -> None:
    if query.message is None:
        await query.answer()
        return
    parsed = parse_callback(query.data)
    project, batch_id = parsed["project"], parsed["batch_id"]
    try:
        batch = await client.delete_data_batch(project, batch_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось удалить данные партии #%s: %s", batch_id, exc)
        await query.answer(_http_detail(exc) or f"Не удалось удалить данные партии #{batch_id}.", show_alert=True)
        return
    await query.answer()
    scenarios = await _scenarios_or_empty(client, project)
    text = f"Удаление данных партии #{batch_id} запущено. Сообщу, когда закончится.\n\n{format_data_batch(batch, scenarios)}"
    await _safe_edit(query.message, text, build_batch_keyboard(project, batch))
    asyncio.create_task(_watch_batch(bot, client, query.message.chat.id, project, batch_id))


@router.callback_query(F.data.startswith("flaky:"))
async def cb_flaky(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        items = await client.list_flaky(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить флаки-статистику проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить флаки-статистику проекта «{project}».")
        return
    text = format_flaky(project, None, items)
    await _safe_edit(query.message, text, build_back_keyboard(build_callback("project", project=project)))


@router.callback_query(F.data.startswith("xfail:"))
async def cb_xfail(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        items = await client.list_xfail(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить известные дефекты проекта %s: %s", project, exc)
        await _safe_edit(query.message, f"Не удалось получить известные дефекты проекта «{project}».")
        return
    text = format_xfail(project, items)
    builder = InlineKeyboardBuilder()
    if items:
        builder.row(InlineKeyboardButton(text="Проверить", callback_data=build_callback("xfail_check", project=project)))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=build_callback("project", project=project)))
    await _safe_edit(query.message, text, builder.as_markup())


@router.callback_query(F.data.startswith("xfail_check:"))
async def cb_xfail_check(
    query: CallbackQuery,
    client: HubClient,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    failed_cache: dict[int, list[dict]],
    bot: Bot,
) -> None:
    if query.message is None:
        return
    project = parse_callback(query.data)["project"]
    try:
        items = await client.list_xfail(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить известные дефекты проекта %s: %s", project, exc)
        await query.answer("Не удалось получить известные дефекты.", show_alert=True)
        return

    by_stand: dict[str | None, list[str]] = {}
    for item in items:
        nodeid = item.get("nodeid")
        if nodeid:
            by_stand.setdefault(item.get("stand"), []).append(nodeid)
    if not by_stand:
        await query.answer("Не удалось найти эти тесты в текущем дереве проекта.", show_alert=True)
        return

    await query.answer()
    for stand, nodeids in by_stand.items():
        await _restart_tests(query.message, client, run_chats, last_run, failed_cache, bot, project, stand, nodeids)


@router.callback_query(F.data.startswith("stand:"))
async def cb_stand(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, stand = parsed["project"], parsed["stand"]
    if await _stand_manual_only(client, project, stand):
        try:
            presets = await client.list_stand_presets(project, stand)
        except httpx.HTTPError as exc:
            logger.warning("tg_bot: не удалось получить пресеты стенда %s/%s: %s", project, stand, exc)
            await _safe_edit(query.message, f"Не удалось получить пресеты стенда «{stand}».")
            return
        text = f"Проект: {project}\nСтенд: {_stand_label(stand)} 🔒 (только вручную)\nВыберите пресет:"
        await _safe_edit(query.message, text, build_preset_keyboard(project, stand, presets))
        return
    text = f"Проект: {project}\nСтенд: {_stand_label(stand)}\nВыберите набор тестов:"
    markers = await _project_markers(client, project)
    await _safe_edit(query.message, text, build_marker_keyboard(project, stand, markers))


@router.callback_query(F.data.startswith("marker:"))
async def cb_marker(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, stand, marker = parsed["project"], parsed["stand"], parsed["marker"]
    env_flag = await _project_use_env_flag(client, project)
    args = build_run_args(env_flag, stand, marker)
    text = _confirm_text(project, stand, marker, args)
    await _safe_edit(query.message, text, build_confirm_keyboard(project, stand, marker))


async def _get_preset_or_notify(query: CallbackQuery, client: HubClient, project: str, stand: str, preset_id: int) -> dict | None:
    try:
        presets = await client.list_stand_presets(project, stand)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить пресеты стенда %s/%s: %s", project, stand, exc)
        await _safe_edit(query.message, "Не удалось получить пресеты.")
        return None
    preset = next((p for p in presets if p["id"] == preset_id), None)
    if preset is None:
        await _safe_edit(query.message, "Пресет не найден.")
        return None
    return preset


@router.callback_query(F.data.startswith("preset:"))
async def cb_preset(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "preset":
        return
    project, stand, preset_id = parsed["project"], parsed["stand"], parsed["preset_id"]
    preset = await _get_preset_or_notify(query, client, project, stand, preset_id)
    if preset is None:
        return
    text = _manual_confirm_text(stand, preset["name"])
    yes_callback = build_callback("preset_confirm", project=project, stand=stand, id=str(preset_id))
    await _safe_edit(query.message, text, build_manual_confirm_keyboard(yes_callback))


@router.callback_query(F.data.startswith("preset_confirm:"))
async def cb_preset_confirm(
    query: CallbackQuery,
    client: HubClient,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
    failed_cache: dict[int, list[dict]] | None = None,
) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "preset_confirm":
        return
    project, stand, preset_id = parsed["project"], parsed["stand"], parsed["preset_id"]
    preset = await _get_preset_or_notify(query, client, project, stand, preset_id)
    if preset is None:
        return
    try:
        run = await client.submit_run(
            project, stand, preset.get("marker"), target=preset["target"], confirm_manual=True
        )
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось поставить прогон по пресету %s: %s", preset.get("name"), exc)
        await _safe_edit(query.message, "Не удалось поставить прогон.")
        return

    run_id = run["id"]
    chat_id = query.message.chat.id
    run_chats[run_id] = chat_id
    last_run[chat_id] = run_id
    await _safe_edit(query.message, f"Прогон #{run_id} поставлен в очередь.", build_run_keyboard(run_id))
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id, failed_cache if failed_cache is not None else {}))


@router.callback_query(F.data.startswith("run_section_confirm:"))
async def cb_run_section_confirm(
    query: CallbackQuery,
    client: HubClient,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
    failed_cache: dict[int, list[dict]] | None = None,
) -> None:
    """Подтверждение из /run <проект> <раздел> (см. cmd_run) — запуск без стенда,
    target — путь папки раздела ("tests/api/notifications"), который одинаково
    понимает и runner._execute (директория как аргумент pytest), и дерево
    разделов в ui/project.js (тот же target у корневого чекбокса области)."""
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "run_section_confirm":
        return
    project, section = parsed["project"], parsed["section"]
    try:
        run = await client.submit_run(project, None, None, target=f"tests/{section}")
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось поставить прогон раздела %s/%s: %s", project, section, exc)
        await _safe_edit(query.message, "Не удалось поставить прогон.")
        return

    run_id = run["id"]
    chat_id = query.message.chat.id
    run_chats[run_id] = chat_id
    last_run[chat_id] = run_id
    await _safe_edit(query.message, f"Прогон #{run_id} поставлен в очередь.", build_run_keyboard(run_id))
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id, failed_cache if failed_cache is not None else {}))


@router.callback_query(F.data.startswith("tests:"))
async def cb_tests(
    query: CallbackQuery,
    client: HubClient,
    tree_cache: dict,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, stand = parsed["project"], parsed["stand"]
    nodes, error = await _load_tree(client, tree_cache, project)
    if nodes is None:
        await _safe_edit(query.message, error or "Не удалось получить дерево тестов.")
        return
    chat_id = query.message.chat.id
    browse_state[chat_id] = {"project": project, "stand": stand}
    selected = selections.setdefault(chat_id, set())
    await _render_tree(query.message, nodes, project, stand, 0, 0, selected, error)


def _tree_nav_state(browse_state: dict[int, dict], chat_id: int) -> dict | None:
    return browse_state.get(chat_id)


@router.callback_query(F.data.startswith("tree_open:"))
async def cb_tree_open(
    query: CallbackQuery,
    client: HubClient,
    tree_cache: dict,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
) -> None:
    await query.answer()
    if query.message is None:
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    if state is None:
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "tree_open":
        return
    nodes, error = await _load_tree(client, tree_cache, state["project"])
    if nodes is None:
        await _safe_edit(query.message, error or "Не удалось получить дерево тестов.")
        return
    node_index = parsed["node"]
    if node_index < 0 or node_index >= len(nodes):
        return
    selected = selections.setdefault(chat_id, set())
    node = nodes[node_index]
    if node["kind"] == "test":
        selected.symmetric_difference_update({node["nodeid"]})
    else:
        state["node"] = node_index
        state["page"] = 0
    await _render_tree(
        query.message, nodes, state["project"], state["stand"], state.get("node", 0), state.get("page", 0), selected, error
    )


@router.callback_query(F.data.startswith("tree_page:"))
async def cb_tree_page(
    query: CallbackQuery,
    client: HubClient,
    tree_cache: dict,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
) -> None:
    await query.answer()
    if query.message is None:
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    if state is None:
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "tree_page":
        return
    nodes, error = await _load_tree(client, tree_cache, state["project"])
    if nodes is None:
        await _safe_edit(query.message, error or "Не удалось получить дерево тестов.")
        return
    state["page"] = parsed["page"]
    selected = selections.setdefault(chat_id, set())
    await _render_tree(
        query.message, nodes, state["project"], state["stand"], state.get("node", 0), state["page"], selected, error
    )


@router.callback_query(F.data == "tree_up")
async def cb_tree_up(
    query: CallbackQuery,
    client: HubClient,
    tree_cache: dict,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
) -> None:
    await query.answer()
    if query.message is None:
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    if state is None:
        return
    nodes, error = await _load_tree(client, tree_cache, state["project"])
    if nodes is None:
        await _safe_edit(query.message, error or "Не удалось получить дерево тестов.")
        return
    parent = nodes[state.get("node", 0)]["parent"]
    if parent is not None:
        state["node"] = parent
        state["page"] = 0
    selected = selections.setdefault(chat_id, set())
    await _render_tree(
        query.message, nodes, state["project"], state["stand"], state.get("node", 0), state.get("page", 0), selected, error
    )


@router.callback_query(F.data == "tree_refresh")
async def cb_tree_refresh(
    query: CallbackQuery,
    client: HubClient,
    tree_cache: dict,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
) -> None:
    await query.answer("Дерево обновлено")
    if query.message is None:
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    if state is None:
        return
    nodes, error = await _load_tree(client, tree_cache, state["project"], force=True)
    if nodes is None:
        await _safe_edit(query.message, error or "Не удалось получить дерево тестов.")
        return
    state["node"] = 0
    state["page"] = 0
    selected = selections.setdefault(chat_id, set())
    await _render_tree(query.message, nodes, state["project"], state["stand"], 0, 0, selected, error)


@router.callback_query(F.data == "tree_select_file")
async def cb_tree_select_file(
    query: CallbackQuery,
    client: HubClient,
    tree_cache: dict,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
) -> None:
    await query.answer()
    if query.message is None:
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    if state is None:
        return
    nodes, error = await _load_tree(client, tree_cache, state["project"])
    if nodes is None:
        await _safe_edit(query.message, error or "Не удалось получить дерево тестов.")
        return
    selected = selections.setdefault(chat_id, set())
    node_index = state.get("node", 0)
    if nodes[node_index]["kind"] == "file":
        selected.update(_collect_test_nodeids(nodes, node_index))
    await _render_tree(
        query.message, nodes, state["project"], state["stand"], node_index, state.get("page", 0), selected, error
    )


@router.callback_query(F.data == "tree_clear")
async def cb_tree_clear(
    query: CallbackQuery,
    client: HubClient,
    tree_cache: dict,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
) -> None:
    await query.answer("Выбор сброшен")
    if query.message is None:
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    if state is None:
        return
    nodes, error = await _load_tree(client, tree_cache, state["project"])
    if nodes is None:
        await _safe_edit(query.message, error or "Не удалось получить дерево тестов.")
        return
    selections[chat_id] = set()
    await _render_tree(
        query.message,
        nodes,
        state["project"],
        state["stand"],
        state.get("node", 0),
        state.get("page", 0),
        selections[chat_id],
        error,
    )


async def _submit_selected_tests(
    query: CallbackQuery,
    client: HubClient,
    state: dict,
    selected: set[str],
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
    failed_cache: dict[int, list[dict]] | None,
    confirm_manual: bool,
) -> None:
    chat_id = query.message.chat.id
    target = "\n".join(sorted(selected))
    kwargs = {"confirm_manual": True} if confirm_manual else {}
    try:
        run = await client.submit_run(state["project"], state["stand"], None, target=target, **kwargs)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось поставить прогон по выбранным тестам: %s", exc)
        await _safe_edit(query.message, "Не удалось поставить прогон.")
        return

    run_id = run["id"]
    run_chats[run_id] = chat_id
    last_run[chat_id] = run_id
    selections[chat_id] = set()
    browse_state.pop(chat_id, None)
    await _safe_edit(
        query.message, f"Прогон #{run_id} поставлен в очередь ({len(selected)} тест(ов)).", build_run_keyboard(run_id)
    )
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id, failed_cache if failed_cache is not None else {}))


@router.callback_query(F.data == "tree_run")
async def cb_tree_run(
    query: CallbackQuery,
    client: HubClient,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
    failed_cache: dict[int, list[dict]] | None = None,
) -> None:
    if query.message is None:
        await query.answer()
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    selected = selections.get(chat_id) or set()
    if state is None or not selected:
        await query.answer("Сначала выберите хотя бы один тест.", show_alert=True)
        return

    if await _stand_manual_only(client, state["project"], state["stand"]):
        await query.answer()
        text = _manual_confirm_text(state["stand"], f"{len(selected)} тест(ов)")
        await _safe_edit(query.message, text, build_manual_confirm_keyboard("tree_run_confirm"))
        return

    await query.answer()
    await _submit_selected_tests(
        query, client, state, selected, browse_state, selections, run_chats, last_run, bot, failed_cache,
        confirm_manual=False,
    )


@router.callback_query(F.data == "tree_run_confirm")
async def cb_tree_run_confirm(
    query: CallbackQuery,
    client: HubClient,
    browse_state: dict[int, dict],
    selections: dict[int, set[str]],
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
    failed_cache: dict[int, list[dict]] | None = None,
) -> None:
    if query.message is None:
        await query.answer()
        return
    chat_id = query.message.chat.id
    state = _tree_nav_state(browse_state, chat_id)
    selected = selections.get(chat_id) or set()
    if state is None or not selected:
        await query.answer("Информация устарела, выберите тесты заново.", show_alert=True)
        return

    await query.answer()
    await _submit_selected_tests(
        query, client, state, selected, browse_state, selections, run_chats, last_run, bot, failed_cache,
        confirm_manual=True,
    )


@router.callback_query(F.data.startswith("confirm:"))
async def cb_confirm(
    query: CallbackQuery,
    client: HubClient,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
    failed_cache: dict[int, list[dict]] | None = None,
) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, stand, marker = parsed["project"], parsed["stand"], parsed["marker"]
    try:
        run = await client.submit_run(project, stand, marker)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось поставить прогон: %s", exc)
        await _safe_edit(query.message, "Не удалось поставить прогон.")
        return

    run_id = run["id"]
    chat_id = query.message.chat.id
    run_chats[run_id] = chat_id
    last_run[chat_id] = run_id
    await _safe_edit(query.message, f"Прогон #{run_id} поставлен в очередь.", build_run_keyboard(run_id))
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id, failed_cache if failed_cache is not None else {}))


@router.callback_query(F.data.startswith("run_status:"))
async def cb_run_status(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить статус прогона #%s: %s", run_id, exc)
        await _safe_edit(query.message, f"Не удалось получить статус прогона #{run_id}.", build_run_keyboard(run_id))
        return
    await _safe_edit(query.message, format_status(report), build_run_keyboard(run_id, report.get("project")))


@router.callback_query(F.data.startswith("run_report:"))
async def cb_run_report(
    query: CallbackQuery, client: HubClient, failed_cache: dict[int, list[dict]] | None = None
) -> None:
    await query.answer()
    if query.message is None:
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить отчёт прогона #%s: %s", run_id, exc)
        await _safe_edit(query.message, f"Не удалось получить отчёт прогона #{run_id}.", build_run_keyboard(run_id))
        return
    causes, compare = await _report_extras(client, run_id) if report["status"] in TERMINAL_STATUSES else (None, None)
    caption = format_report(report, causes, compare)
    failed = _bad_tests(report, causes)
    if failed_cache is not None:
        failed_cache[run_id] = failed
    keyboard = build_report_keyboard(run_id, failed)
    try:
        png = await client.get_report_png(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить report.png для прогона #%s: %s", run_id, exc)
        await _safe_edit(query.message, caption, keyboard)
        return
    # edit_text не умеет заменять сообщение на фото — вместо редактирования шлём
    # новое сообщение с фото, а кнопки навешиваем прямо на него.
    await _send_report_png(
        query.message.answer_photo,
        query.message.answer,
        run_id,
        png,
        caption,
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("run_trend:"))
async def cb_run_trend(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        png = await client.get_trend_png(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить trend.png для прогона #%s: %s", run_id, exc)
        await _reply_http_error(query.message, exc, "получить тренд", not_found=f"Прогон #{run_id} не найден.")
        return
    await query.message.answer_photo(
        BufferedInputFile(png, filename=f"trend_{run_id}.png"),
        caption="Тренд последних прогонов",
    )


@router.callback_query(F.data.startswith("run_cancel:"))
async def cb_run_cancel(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        run = await client.cancel_run(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось отменить прогон #%s: %s", run_id, exc)
        await _safe_edit(query.message, f"Не удалось отменить прогон #{run_id}.", build_run_keyboard(run_id))
        return
    status_ru = STATUS_RU.get(run["status"], run["status"])
    await _safe_edit(query.message, f"Прогон #{run_id}: {status_ru}.", build_run_keyboard(run_id))


@router.callback_query(F.data.startswith("run_share:"))
async def cb_run_share(query: CallbackQuery, client: HubClient) -> None:
    """Ссылка на 30 дней по умолчанию (см. задачу шаринга отчёта) — публичная
    страница без логина, доступна по client.create_share_link (POST /api/runs/{id}/share)."""
    await query.answer()
    if query.message is None:
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        share = await client.create_share_link(run_id, expires="30d")
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось создать публичную ссылку для прогона #%s: %s", run_id, exc)
        await _reply_http_error(query.message, exc, "создать ссылку", not_found=f"Прогон #{run_id} не найден.")
        return
    await query.message.answer(f"Ссылка на отчёт прогона #{run_id} (30 дней): {share['url']}")


@router.callback_query(F.data.startswith("run_causes:"))
async def cb_run_causes(query: CallbackQuery, client: HubClient) -> None:
    """Экран «Причины» — отдельным сообщением: исходное может быть фото отчёта,
    которое edit_text не правит."""
    await query.answer()
    if query.message is None:
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        causes = await client.get_run_causes(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить причины падений прогона #%s: %s", run_id, exc)
        await _reply_http_error(query.message, exc, "получить причины падений", not_found=f"Прогон #{run_id} не найден.")
        return
    await query.message.answer(
        format_causes(run_id, causes),
        reply_markup=build_back_keyboard(build_callback("run_status", run_id=str(run_id)), "« К прогону"),
    )


@router.callback_query(F.data.startswith("run_compare:"))
async def cb_run_compare(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        compare = await client.get_run_compare(run_id)
    except httpx.HTTPError as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
            await query.message.answer(f"Прогон #{run_id}: нет базового прогона для сравнения.")
            return
        logger.warning("tg_bot: не удалось получить сравнение прогона #%s: %s", run_id, exc)
        await _reply_http_error(query.message, exc, "получить сравнение")
        return
    await query.message.answer(
        format_compare(run_id, compare),
        reply_markup=build_back_keyboard(build_callback("run_status", run_id=str(run_id)), "« К прогону"),
    )


@router.callback_query(F.data.startswith("run_cleanup:"))
async def cb_run_cleanup(query: CallbackQuery, client: HubClient, bot: Bot) -> None:
    """«Удалить данные прогона» — POST /api/projects/{name}/runs/{id}/cleanup-data
    (партия cleanup_after_run), проект берём из отчёта прогона."""
    if query.message is None:
        await query.answer()
        return
    run_id = parse_callback(query.data)["run_id"]
    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        await query.answer()
        await _reply_http_error(query.message, exc, "получить прогон", not_found=f"Прогон #{run_id} не найден.")
        return
    project = report.get("project")
    try:
        batch = await client.cleanup_run_data(project, run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось запустить очистку данных прогона #%s: %s", run_id, exc)
        await query.answer()
        await query.message.answer(_http_detail(exc) or f"Не удалось запустить очистку данных прогона #{run_id}.")
        return
    await query.answer()
    await query.message.answer(
        f"Очистка данных прогона #{run_id} запущена: партия #{batch['id']} на {_stand_label(batch.get('stand'))}. "
        "Сообщу, когда закончится.",
        reply_markup=build_batch_keyboard(project, batch),
    )
    asyncio.create_task(_watch_batch(bot, client, query.message.chat.id, project, batch["id"]))


async def _restart_tests(
    message: Message,
    client: HubClient,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    failed_cache: dict[int, list[dict]],
    bot: Bot,
    project: str,
    stand: str | None,
    nodeids: list[str],
) -> None:
    target = "\n".join(nodeids)
    try:
        run = await client.submit_run(project, stand, None, target=target)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось перезапустить тесты проекта %s: %s", project, exc)
        await message.answer("Не удалось поставить прогон.")
        return

    run_id = run["id"]
    chat_id = message.chat.id
    run_chats[run_id] = chat_id
    last_run[chat_id] = run_id
    await message.answer(
        f"Прогон #{run_id} поставлен в очередь ({len(nodeids)} тест(ов)).", reply_markup=build_run_keyboard(run_id)
    )
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id, failed_cache))


@router.callback_query(F.data.startswith("fail_open:"))
async def cb_fail_open(query: CallbackQuery, failed_cache: dict[int, list[dict]]) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "fail_open":
        return
    run_id, index = parsed["run_id"], parsed["index"]
    failed = failed_cache.get(run_id)
    if failed is None or not (0 <= index < len(failed)):
        await query.message.answer("Информация об этом тесте устарела, откройте отчёт заново.")
        return
    test = failed[index]
    text = f"❌ {test.get('name') or '?'}\n\n{_error_text(test)}"
    await query.message.answer(text, reply_markup=build_fail_detail_keyboard(run_id, index))


@router.callback_query(F.data.startswith("fail_restart_one:"))
async def cb_fail_restart_one(
    query: CallbackQuery,
    client: HubClient,
    failed_cache: dict[int, list[dict]],
    tree_cache: dict,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
) -> None:
    if query.message is None:
        await query.answer()
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "fail_restart_one":
        await query.answer()
        return
    run_id, index = parsed["run_id"], parsed["index"]
    failed = failed_cache.get(run_id)
    if failed is None or not (0 <= index < len(failed)):
        await query.answer("Информация об этом тесте устарела, откройте отчёт заново.", show_alert=True)
        return
    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить прогон #%s для перезапуска: %s", run_id, exc)
        await query.answer("Не удалось получить данные прогона.", show_alert=True)
        return
    nodeid = await _resolve_nodeid(client, tree_cache, report["project"], failed[index])
    if nodeid is None:
        await query.answer("Не удалось найти этот тест в дереве проекта.", show_alert=True)
        return
    await query.answer()
    await _restart_tests(
        query.message, client, run_chats, last_run, failed_cache, bot, report["project"], report.get("stand"), [nodeid]
    )


@router.callback_query(F.data.startswith("fail_restart_all:"))
async def cb_fail_restart_all(
    query: CallbackQuery,
    client: HubClient,
    failed_cache: dict[int, list[dict]],
    tree_cache: dict,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
) -> None:
    if query.message is None:
        await query.answer()
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "fail_restart_all":
        await query.answer()
        return
    run_id = parsed["run_id"]
    failed = failed_cache.get(run_id)
    if not failed:
        await query.answer("Информация об упавших тестах устарела, откройте отчёт заново.", show_alert=True)
        return
    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить прогон #%s для перезапуска: %s", run_id, exc)
        await query.answer("Не удалось получить данные прогона.", show_alert=True)
        return
    nodeids: list[str] = []
    for test in failed:
        nodeid = await _resolve_nodeid(client, tree_cache, report["project"], test)
        if nodeid and nodeid not in nodeids:
            nodeids.append(nodeid)
    if not nodeids:
        await query.answer("Не удалось найти эти тесты в дереве проекта.", show_alert=True)
        return
    await query.answer()
    await _restart_tests(
        query.message, client, run_chats, last_run, failed_cache, bot, report["project"], report.get("stand"), nodeids
    )


@router.message(Command("projects"))
async def cmd_projects(message: Message, client: HubClient) -> None:
    try:
        projects = await client.list_projects()
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить список проектов")
        return
    await message.answer(format_projects(projects))


@router.message(Command("run"))
async def cmd_run(
    message: Message,
    command: CommandObject,
    client: HubClient,
    run_chats: dict[int, int],
    last_run: dict[int, int],
    bot: Bot,
    failed_cache: dict[int, list[dict]] | None = None,
) -> None:
    parsed = parse_run_command(command.args or "")
    if parsed is None:
        await message.answer(RUN_USAGE)
        return
    project, stand, marker = parsed

    try:
        projects = await client.list_projects()
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить список проектов")
        return

    project_row = next((p for p in projects if p["name"] == project), None)
    if project_row is None:
        await message.answer(f"Проект «{project}» не найден. См. /projects.")
        return
    stand_names = {s["name"] for s in project_row.get("stands", [])}
    if stand not in stand_names:
        # Второй аргумент похож на раздел ("api/notifications", "e2e"), а не на
        # стенд — предлагаем подтверждение и запуск без стенда по тому же пути,
        # что и кнопка «Прогнать ×3» флаки-теста в ui/project.js (submit_run без
        # stand). Маркер здесь не поддержан — раздел уже сам сужает выборку.
        if marker is None and _SECTION_ARG_RE.match(stand):
            section = stand
            text = f"Запустить тесты раздела «{section}» в проекте «{project}»?"
            yes_callback = build_callback("run_section_confirm", project=project, section=section)
            await message.answer(text, reply_markup=build_manual_confirm_keyboard(yes_callback))
            return
        await message.answer(f"Стенд «{stand}» не найден в проекте «{project}». См. /projects.")
        return

    try:
        run = await client.submit_run(project, stand, marker)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "поставить прогон")
        return

    run_id = run["id"]
    chat_id = message.chat.id
    run_chats[run_id] = chat_id
    last_run[chat_id] = run_id
    await message.answer(f"Прогон #{run_id} поставлен в очередь.")
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id, failed_cache if failed_cache is not None else {}))


@router.message(Command("stage"))
async def cmd_stage(message: Message, command: CommandObject, client: HubClient) -> None:
    """/stage <проект> <пресет> — тот же путь подтверждения, что и у кнопки
    пресета (cb_preset/cb_preset_confirm): "Да, запустить" здесь шлёт то же
    callback_data "preset_confirm:...", обработанное тем же хендлером."""
    try:
        project, preset_name = parse_stage_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        stands = await client.list_stands(project)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить стенды", not_found=f"Проект «{project}» не найден.")
        return
    if not any(s.get("name") == STAGE_STAND_NAME for s in stands):
        await message.answer(f"У проекта «{project}» нет стенда «{STAGE_STAND_NAME}».")
        return

    try:
        presets = await client.list_stand_presets(project, STAGE_STAND_NAME)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить пресеты")
        return
    preset = next((p for p in presets if p["name"] == preset_name), None)
    if preset is None:
        names = ", ".join(p["name"] for p in presets) or "—"
        await message.answer(f"Пресет «{preset_name}» не найден. Доступные: {names}")
        return

    text = _manual_confirm_text(STAGE_STAND_NAME, preset["name"])
    yes_callback = build_callback("preset_confirm", project=project, stand=STAGE_STAND_NAME, id=str(preset["id"]))
    await message.answer(text, reply_markup=build_manual_confirm_keyboard(yes_callback))


@router.message(Command("status"))
async def cmd_status(message: Message, command: CommandObject, client: HubClient, last_run: dict[int, int]) -> None:
    try:
        run_id = parse_optional_run_id(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    chat_id = message.chat.id
    if run_id is None:
        run_id = last_run.get(chat_id)
        if run_id is None:
            await message.answer("Нет последнего прогона в этом чате. Укажите id: /status <id>")
            return

    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить статус", not_found=f"Прогон #{run_id} не найден.")
        return
    await message.answer(format_status(report))


@router.message(Command("report"))
async def cmd_report(
    message: Message, command: CommandObject, client: HubClient, failed_cache: dict[int, list[dict]] | None = None
) -> None:
    try:
        run_id = parse_run_id(command.args or "", REPORT_USAGE)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить отчёт", not_found=f"Прогон #{run_id} не найден.")
        return
    causes, compare = await _report_extras(client, run_id) if report["status"] in TERMINAL_STATUSES else (None, None)
    caption = format_report(report, causes, compare)
    failed = _bad_tests(report, causes)
    if failed_cache is not None:
        failed_cache[run_id] = failed
    keyboard = build_report_keyboard(run_id, failed)
    try:
        png = await client.get_report_png(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить report.png для прогона #%s: %s", run_id, exc)
        await message.answer(caption, reply_markup=keyboard)
        return
    await _send_report_png(message.answer_photo, message.answer, run_id, png, caption, keyboard)


@router.message(Command("flaky"))
async def cmd_flaky(message: Message, command: CommandObject, client: HubClient) -> None:
    try:
        project, stand = parse_flaky_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        items = await client.list_flaky(project, stand)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить флаки-статистику", not_found=f"Проект «{project}» не найден.")
        return
    await message.answer(format_flaky(project, stand, items))


@router.message(Command("xfail"))
async def cmd_xfail(message: Message, command: CommandObject, client: HubClient) -> None:
    try:
        project, stand = parse_xfail_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        items = await client.list_xfail(project, stand)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить известные дефекты", not_found=f"Проект «{project}» не найден.")
        return
    await message.answer(format_xfail(project, items))


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject, client: HubClient) -> None:
    try:
        project, stand = parse_stats_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        data = await client.get_stats(project, stand)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить статистику", not_found=f"Проект «{project}» не найден.")
        return
    await message.answer(format_stats(project, data.get("stand"), data))


@router.message(Command("schedules"))
async def cmd_schedules(message: Message, command: CommandObject, client: HubClient) -> None:
    try:
        project = parse_project_name(command.args or "", SCHEDULE_USAGE)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        items = await client.list_schedules(project)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить расписания", not_found=f"Проект «{project}» не найден.")
        return
    await message.answer(format_schedules(project, items), reply_markup=build_schedules_keyboard(project, items))


@router.callback_query(F.data.startswith("sched_toggle:"))
async def cb_sched_toggle(query: CallbackQuery, client: HubClient) -> None:
    if query.message is None:
        await query.answer()
        return
    parsed = parse_callback(query.data)
    if parsed["action"] != "sched_toggle":
        await query.answer()
        return
    project, schedule_id = parsed["project"], parsed["schedule_id"]

    try:
        items = await client.list_schedules(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить расписания проекта %s: %s", project, exc)
        await query.answer("Не удалось получить расписания.", show_alert=True)
        return
    current = next((i for i in items if i["id"] == schedule_id), None)
    if current is None:
        await query.answer("Расписание не найдено.", show_alert=True)
        return

    try:
        await client.set_schedule_enabled(project, schedule_id, not current["enabled"])
        items = await client.list_schedules(project)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось переключить расписание #%s проекта %s: %s", schedule_id, project, exc)
        await query.answer("Не удалось изменить расписание.", show_alert=True)
        return

    await query.answer()
    await _safe_edit(query.message, format_schedules(project, items), build_schedules_keyboard(project, items))


@router.message(Command("last"))
async def cmd_last(
    message: Message, command: CommandObject, client: HubClient, failed_cache: dict[int, list[dict]] | None = None
) -> None:
    try:
        project = parse_project_name(command.args or "", LAST_USAGE)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        runs = await client.list_runs(project)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить прогоны", not_found=f"Проект «{project}» не найден.")
        return

    if not runs:
        await message.answer(f"У проекта «{project}» ещё нет прогонов.")
        return

    run_id = runs[0]["id"]
    try:
        report = await client.get_report(run_id)
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить отчёт")
        return
    causes, compare = await _report_extras(client, run_id) if report["status"] in TERMINAL_STATUSES else (None, None)
    caption = format_report(report, causes, compare)
    failed = _bad_tests(report, causes)
    if failed_cache is not None:
        failed_cache[run_id] = failed
    keyboard = build_report_keyboard(run_id, failed)
    try:
        png = await client.get_report_png(run_id)
    except httpx.HTTPError as exc:
        logger.warning("tg_bot: не удалось получить report.png для прогона #%s: %s", run_id, exc)
        await message.answer(caption, reply_markup=keyboard)
        return
    await _send_report_png(message.answer_photo, message.answer, run_id, png, caption, keyboard)


@dataclass
class TgApplication:
    bot: Bot
    dispatcher: Dispatcher
    client: HubClient
    polling_task: "asyncio.Task | None" = field(default=None)


def build_application() -> TgApplication:
    bot = Bot(token=settings.TH_TG_BOT_TOKEN)
    client = HubClient()
    dispatcher = Dispatcher(
        client=client, run_chats={}, last_run={}, tree_cache={}, browse_state={}, selections={}, failed_cache={}
    )
    dispatcher.message.outer_middleware(AccessMiddleware())
    dispatcher.callback_query.outer_middleware(AccessMiddleware())
    dispatcher.include_router(router)
    return TgApplication(bot=bot, dispatcher=dispatcher, client=client)


def _log_polling_failure(task: "asyncio.Task") -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        # Например, невалидный/фиктивный токен — сервер при этом продолжает работать
        # без Telegram-бота, см. lifespan в app/main.py.
        logger.warning("tg_bot: polling завершился с ошибкой: %s", exc)


async def start_application(application: TgApplication) -> None:
    application.polling_task = asyncio.create_task(
        application.dispatcher.start_polling(application.bot, handle_signals=False)
    )
    application.polling_task.add_done_callback(_log_polling_failure)


async def stop_application(application: TgApplication) -> None:
    try:
        if application.polling_task is not None:
            application.polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await application.polling_task
    finally:
        await application.bot.session.close()
        await application.client.aclose()
