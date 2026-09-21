"""Telegram-бот test_hub на inline-кнопках (aiogram 3).

Главный сценарий — кнопочный: /start или текст «Меню» открывает список проектов,
дальше выбор стенда → набора тестов (Smoke/API/UI/Все) → подтверждение → запуск,
и всё это редактирует одно и то же сообщение (edit_text), не плодя новые. Текстовые
команды (/projects, /run, /status, /report, /last) дублируют тот же функционал через
HTTP API test_hub — обе ветки используют один и тот же HubClient.

Бот работает поверх REST API самого test_hub (app/routers/projects.py, app/routers/runs.py)
под сервисной учёткой settings.TH_TG_SERVICE_LOGIN (сидится в app/db.py::_seed_tg_bot_user),
используя фичи t1 — RunCreate.marker и projects.use_env_flag/--env (app/schemas.py,
app/core/runner.py): маркер, выбранный кнопкой/введённый в /run, передаётся в
RunCreate.marker как есть, раннер сам решает, добавлять ли `-m <marker>` и
`--env <stand>` к pytest (см. build_run_args ниже — зеркалит этот же формат для UI).

Разбор callback_data/команд и построение аргументов вынесены в чистые функции
(parse_callback, parse_run_command, build_run_args, format_*) без объектов aiogram —
их можно юнит-тестировать напрямую, без сети и без запуска бота.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
from dataclasses import dataclass, field

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import settings

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3.0
TERMINAL_STATUSES = {"passed", "failed", "cancelled"}
MAX_FAILED_LISTED = 15
MAX_REASON_LEN = 120

STATUS_RU = {
    "queued": "в очереди",
    "running": "выполняется",
    "passed": "пройден",
    "failed": "провален",
    "cancelled": "отменён",
}

MARKER_BUTTONS = [("Smoke", "smoke"), ("API", "api"), ("UI", "ui"), ("Все", None)]
MARKER_LABELS = dict(MARKER_BUTTONS)

RUN_USAGE = "Использование: /run <проект> <стенд> [маркер]"
STATUS_USAGE = "id прогона должен быть числом: /status [id]"
REPORT_USAGE = "Использование: /report <id>"
LAST_USAGE = "Использование: /last <проект>"

ACCESS_DENIED_MESSAGE = "Извините, у вас нет доступа к этому боту."
MENU_TEXT = "Выберите проект:"

# callback_data кодирует отсутствующее значение (стенд "без стенда", маркер "Все")
# этим токеном — project/stand в этой системе не содержат ":" и "_" отдельным полем.
_NONE_TOKEN = "_"


# ------------------------------------------------------------------ HTTP-клиент к test_hub
class HubClient:
    """Ходит в собственный REST API test_hub от имени сервисной учётки
    (settings.TH_TG_SERVICE_LOGIN/PASSWORD), переиспользуя cookie сессии между
    запросами и перелогиниваясь при 401 (например, после истечения сессии)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{settings.TH_PORT}")
        self._logged_in = False
        self._login_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _login(self) -> None:
        resp = await self._client.post(
            "/api/login",
            json={"login": settings.TH_TG_SERVICE_LOGIN, "password": settings.TH_TG_SERVICE_PASSWORD},
        )
        resp.raise_for_status()
        self._logged_in = True

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return
        async with self._login_lock:
            if not self._logged_in:
                await self._login()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        await self._ensure_login()
        resp = await self._client.request(method, url, **kwargs)
        if resp.status_code == 401:
            self._logged_in = False
            await self._ensure_login()
            resp = await self._client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp

    async def list_projects(self) -> list[dict]:
        resp = await self._request("GET", "/api/projects")
        return resp.json()

    async def list_stands(self, project: str) -> list[dict]:
        resp = await self._request("GET", f"/api/projects/{project}/stands")
        return resp.json()

    async def submit_run(self, project: str, stand: str | None, marker: str | None) -> dict:
        payload: dict = {"stand": stand, "target": "all"}
        if marker:
            payload["marker"] = marker
        resp = await self._request("POST", f"/api/projects/{project}/runs", json=payload)
        return resp.json()

    async def get_report(self, run_id: int) -> dict:
        resp = await self._request("GET", f"/api/runs/{run_id}/report")
        return resp.json()

    async def get_report_png(self, run_id: int) -> bytes:
        resp = await self._request("GET", f"/api/runs/{run_id}/report.png")
        return resp.content

    async def get_trend_png(self, run_id: int) -> bytes:
        resp = await self._request("GET", f"/api/runs/{run_id}/trend.png")
        return resp.content

    async def list_runs(self, project: str) -> list[dict]:
        resp = await self._request("GET", f"/api/projects/{project}/runs")
        return resp.json()

    async def cancel_run(self, run_id: int) -> dict:
        resp = await self._request("POST", f"/api/runs/{run_id}/cancel")
        return resp.json()


# ------------------------------------------------------------------ разбор текстовых команд
def parse_run_args(text: str) -> tuple[str, str, str | None]:
    """"<проект> <стенд> [маркер...]" — маркер может содержать пробелы (pytest -m
    допускает выражения вида "smoke and not slow"), поэтому всё, что идёт после
    стенда, склеивается в маркер целиком."""
    parts = text.split()
    if len(parts) < 2:
        raise ValueError(RUN_USAGE)
    project, stand, *rest = parts
    marker = " ".join(rest) if rest else None
    return project, stand, marker


def parse_run_command(text: str) -> tuple[str, str, str | None] | None:
    """То же, что parse_run_args, но без исключений — None при некорректном вводе."""
    try:
        return parse_run_args(text)
    except ValueError:
        return None


def parse_run_id(text: str, usage: str) -> int:
    parts = text.split()
    if not parts:
        raise ValueError(usage)
    try:
        return int(parts[0])
    except ValueError:
        raise ValueError(usage) from None


def parse_optional_run_id(text: str) -> int | None:
    parts = text.split()
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        raise ValueError(STATUS_USAGE) from None


def parse_project_name(text: str, usage: str) -> str:
    parts = text.split()
    if not parts:
        raise ValueError(usage)
    return parts[0]


# ------------------------------------------------------------------ callback_data кнопок
def _encode_token(value: str | None) -> str:
    return _NONE_TOKEN if value is None else value


def _decode_token(value: str) -> str | None:
    return None if value == _NONE_TOKEN else value


def build_callback(action: str, **fields: str | None) -> str:
    return ":".join([action, *(_encode_token(v) for v in fields.values())])


def parse_callback(data: str) -> dict:
    """callback_data → структура {"action": ..., ...}. Неизвестный/некорректный
    формат отдаёт {"action": "invalid", "raw": data} — вызывающий код решает, что
    с этим делать (в боте — молча ничего, см. cb_invalid)."""
    tokens = data.split(":")
    action, rest = tokens[0], tokens[1:]

    if action == "menu" and not rest:
        return {"action": "menu"}
    if action == "project" and len(rest) == 1:
        return {"action": "project", "project": rest[0]}
    if action == "stand" and len(rest) == 2:
        return {"action": "stand", "project": rest[0], "stand": _decode_token(rest[1])}
    if action == "marker" and len(rest) == 3:
        return {
            "action": "marker",
            "project": rest[0],
            "stand": _decode_token(rest[1]),
            "marker": _decode_token(rest[2]),
        }
    if action == "confirm" and len(rest) == 3:
        return {
            "action": "confirm",
            "project": rest[0],
            "stand": _decode_token(rest[1]),
            "marker": _decode_token(rest[2]),
        }
    if action in ("run_status", "run_report", "run_cancel") and len(rest) == 1:
        try:
            run_id = int(rest[0])
        except ValueError:
            return {"action": "invalid", "raw": data}
        return {"action": action, "run_id": run_id}
    return {"action": "invalid", "raw": data}


# ------------------------------------------------------------------ аргументы pytest (зеркалит app/core/runner.py::_execute)
def build_run_args(env_flag: bool, stand: str | None, marker: str | None) -> list[str]:
    """Фрагмент аргументов pytest, которые добавит раннер (app/core/runner.py::_execute,
    строки с `--env`/`-m`) поверх `pytest --alluredir=...` для данного выбора. Не
    запускает pytest сам — только зеркалит формат, чтобы боту было что показать
    пользователю на шаге подтверждения."""
    args: list[str] = []
    if env_flag and stand:
        args.extend(["--env", stand])
    if marker:
        args.extend(["-m", marker])
    return args


# ------------------------------------------------------------------ форматирование
def _stand_label(stand: str | None) -> str:
    return stand if stand is not None else "без стенда"


def _marker_label(marker: str | None) -> str:
    return MARKER_LABELS.get(marker, marker) if marker is not None else "Все"


def format_projects(projects: list[dict]) -> str:
    if not projects:
        return "Проектов пока нет."
    lines = ["Проекты:"]
    for project in projects:
        stands = ", ".join(s["name"] for s in project.get("stands", [])) or "—"
        lines.append(f"• {project['name']} (стенды: {stands})")
    return "\n".join(lines)


def _counts_line(counts: dict) -> str:
    return (
        f"passed: {counts.get('passed', 0)}, failed: {counts.get('failed', 0)}, "
        f"broken: {counts.get('broken', 0)}, skipped: {counts.get('skipped', 0)}"
    )


def format_status(report: dict) -> str:
    status_ru = STATUS_RU.get(report["status"], report["status"])
    lines = [
        f"Прогон #{report['id']} ({report.get('project')}) — {status_ru}",
        _counts_line(report.get("counts") or {}),
    ]
    return "\n".join(lines)


def _short_reason(test: dict) -> str:
    message = (test.get("message") or "").strip()
    if not message:
        return ""
    return message.splitlines()[0][:MAX_REASON_LEN]


def format_report(report: dict) -> str:
    status_ru = STATUS_RU.get(report["status"], report["status"])
    duration = report.get("duration")
    duration_str = f"{duration:.1f}с" if isinstance(duration, (int, float)) else "—"
    lines = [
        f"Прогон #{report['id']} ({report.get('project')}) — {status_ru}",
        _counts_line(report.get("counts") or {}),
        f"Длительность: {duration_str}",
    ]
    bad_tests = [t for t in report.get("tests", []) if t.get("status") in ("failed", "broken")]
    if bad_tests:
        lines.append("Упавшие тесты:")
        shown = bad_tests[:MAX_FAILED_LISTED]
        for t in shown:
            reason = _short_reason(t)
            suffix = f": {reason}" if reason else ""
            lines.append(f"  - {t.get('name')}{suffix}")
        remaining = len(bad_tests) - len(shown)
        if remaining > 0:
            lines.append(f"  …и ещё {remaining}")
    lines.append(f"http://127.0.0.1:{settings.TH_PORT}/project.html?name={report.get('project')}&run={report['id']}")
    return "\n".join(lines)


def _confirm_text(project: str, stand: str | None, marker: str | None, args: list[str]) -> str:
    lines = [f"Запустить {project} / {_stand_label(stand)} / {_marker_label(marker)}?"]
    if args:
        lines.append(f"Аргументы pytest: {' '.join(args)}")
    return "\n".join(lines)


# ------------------------------------------------------------------ inline-клавиатуры
def build_projects_keyboard(projects: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for project in projects:
        builder.button(text=project["name"], callback_data=build_callback("project", project=project["name"]))
    builder.adjust(1)
    return builder.as_markup()


def build_stands_keyboard(project: str, stands: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if stands:
        for stand in stands:
            builder.button(
                text=stand["name"], callback_data=build_callback("stand", project=project, stand=stand["name"])
            )
    else:
        builder.button(text="Без стенда", callback_data=build_callback("stand", project=project, stand=None))
    builder.button(text="« К проектам", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def build_marker_keyboard(project: str, stand: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, marker in MARKER_BUTTONS:
        builder.button(text=label, callback_data=build_callback("marker", project=project, stand=stand, marker=marker))
    builder.button(text="« К стендам", callback_data=build_callback("project", project=project))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def build_confirm_keyboard(project: str, stand: str | None, marker: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data=build_callback("confirm", project=project, stand=stand, marker=marker))
    builder.button(text="Отмена", callback_data="menu")
    builder.adjust(2)
    return builder.as_markup()


def build_run_keyboard(run_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Статус", callback_data=build_callback("run_status", run_id=str(run_id)))
    builder.button(text="Отчёт", callback_data=build_callback("run_report", run_id=str(run_id)))
    builder.button(text="Отменить", callback_data=build_callback("run_cancel", run_id=str(run_id)))
    builder.adjust(3)
    return builder.as_markup()


# ------------------------------------------------------------------ доступ
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


# ------------------------------------------------------------------ безопасное редактирование
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


async def _project_use_env_flag(client: HubClient, project: str) -> bool:
    try:
        projects = await client.list_projects()
    except httpx.HTTPError:
        return False
    row = next((p for p in projects if p["name"] == project), None)
    return bool(row and row.get("use_env_flag"))


# ------------------------------------------------------------------ фоновое ожидание прогона
async def _watch_run(bot: Bot, client: HubClient, run_chats: dict[int, int], run_id: int) -> None:
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
                await bot.send_message(chat_id, format_report(report))
            return


# ------------------------------------------------------------------ кнопочный флоу
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


@router.callback_query(F.data.startswith("stand:"))
async def cb_stand(query: CallbackQuery, client: HubClient) -> None:
    await query.answer()
    if query.message is None:
        return
    parsed = parse_callback(query.data)
    project, stand = parsed["project"], parsed["stand"]
    text = f"Проект: {project}\nСтенд: {_stand_label(stand)}\nВыберите набор тестов:"
    await _safe_edit(query.message, text, build_marker_keyboard(project, stand))


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


@router.callback_query(F.data.startswith("confirm:"))
async def cb_confirm(
    query: CallbackQuery, client: HubClient, run_chats: dict[int, int], last_run: dict[int, int], bot: Bot
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
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id))


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
    await _safe_edit(query.message, format_status(report), build_run_keyboard(run_id))


@router.callback_query(F.data.startswith("run_report:"))
async def cb_run_report(query: CallbackQuery, client: HubClient) -> None:
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
    await _safe_edit(query.message, format_report(report), build_run_keyboard(run_id))


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


# ------------------------------------------------------------------ текстовые команды (дублируют кнопки)
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
    asyncio.create_task(_watch_run(bot, client, run_chats, run_id))


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
async def cmd_report(message: Message, command: CommandObject, client: HubClient) -> None:
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
    await message.answer(format_report(report))


@router.message(Command("last"))
async def cmd_last(message: Message, command: CommandObject, client: HubClient) -> None:
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

    try:
        report = await client.get_report(runs[0]["id"])
    except httpx.HTTPError as exc:
        await _reply_http_error(message, exc, "получить отчёт")
        return
    await message.answer(format_report(report))


# ------------------------------------------------------------------ запуск/остановка приложения
@dataclass
class TgApplication:
    bot: Bot
    dispatcher: Dispatcher
    client: HubClient
    polling_task: "asyncio.Task | None" = field(default=None)


def build_application() -> TgApplication:
    bot = Bot(token=settings.TH_TG_BOT_TOKEN)
    client = HubClient()
    dispatcher = Dispatcher(client=client, run_chats={}, last_run={})
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
