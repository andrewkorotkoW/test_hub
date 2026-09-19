"""Telegram-бот test_hub: команды /projects /run /status /report /last.

Работает поверх REST API самого test_hub (app/routers/projects.py, app/routers/runs.py),
используя фичи t1 — RunCreate.marker и projects.use_env_flag/--env (app/schemas.py,
app/core/runner.py): маркер, введённый в /run, передаётся в RunCreate.marker как есть,
раннер сам решает, добавлять ли `-m <marker>` и `--env <stand>` к pytest.

Парсинг команд вынесен в чистые функции (parse_*, format_*) без объектов telegram —
их можно юнит-тестировать напрямую, без запуска бота или сети.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from .config import settings

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3.0
TERMINAL_STATUSES = {"passed", "failed", "cancelled"}
MAX_FAILED_LISTED = 15

STATUS_RU = {
    "queued": "в очереди",
    "running": "выполняется",
    "passed": "пройден",
    "failed": "провален",
    "cancelled": "отменён",
}

ACCESS_DENIED_MESSAGE = "Доступ запрещён."


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

    async def submit_run(self, project: str, stand: str, marker: str | None) -> dict:
        payload: dict = {"stand": stand, "target": "all"}
        if marker:
            payload["marker"] = marker
        resp = await self._request("POST", f"/api/projects/{project}/runs", json=payload)
        return resp.json()

    async def get_report(self, run_id: int) -> dict:
        resp = await self._request("GET", f"/api/runs/{run_id}/report")
        return resp.json()

    async def list_runs(self, project: str) -> list[dict]:
        resp = await self._request("GET", f"/api/projects/{project}/runs")
        return resp.json()


# ------------------------------------------------------------------ парсинг команд (без telegram-объектов)
def parse_run_args(text: str) -> tuple[str, str, str | None]:
    """"<проект> <стенд> [маркер...]" — маркер может содержать пробелы (pytest -m
    допускает выражения вида "smoke and not slow"), поэтому всё, что идёт после
    стенда, склеивается в маркер целиком."""
    parts = text.split()
    if len(parts) < 2:
        raise ValueError("Использование: /run <проект> <стенд> [маркер]")
    project, stand, *rest = parts
    marker = " ".join(rest) if rest else None
    return project, stand, marker


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
        raise ValueError("id прогона должен быть числом: /status [id]") from None


def parse_project_name(text: str, usage: str) -> str:
    parts = text.split()
    if not parts:
        raise ValueError(usage)
    return parts[0]


# ------------------------------------------------------------------ форматирование ответов
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
        lines.extend(f"  - {t.get('name')}" for t in shown)
        remaining = len(bad_tests) - len(shown)
        if remaining > 0:
            lines.append(f"  …и ещё {remaining}")
    lines.append(f"http://127.0.0.1:{settings.TH_PORT}/project.html?name={report.get('project')}&run={report['id']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ доступ
def _is_allowed(user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.TH_TG_ALLOWED_IDS


async def _check_access(update: Update) -> bool:
    user = update.effective_user
    if _is_allowed(user.id if user else None):
        return True
    if update.effective_chat is not None:
        await update.effective_chat.send_message(ACCESS_DENIED_MESSAGE)
    return False


def _client_of(context: ContextTypes.DEFAULT_TYPE) -> HubClient:
    return context.application.bot_data["client"]


async def _reply_http_error(update: Update, exc: httpx.HTTPError, action: str, not_found: str | None = None) -> None:
    if not_found is not None and isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        await update.effective_chat.send_message(not_found)
        return
    logger.warning("tg_bot: %s: %s", action, exc)
    await update.effective_chat.send_message(f"Не удалось {action}.")


# ------------------------------------------------------------------ фоновое ожидание прогона
async def _watch_run(application: Application, chat_id: int, run_id: int) -> None:
    client = application.bot_data["client"]
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            report = await client.get_report(run_id)
        except httpx.HTTPError as exc:
            logger.warning("tg_bot: не удалось опросить прогон #%s: %s", run_id, exc)
            continue
        if report["status"] in TERMINAL_STATUSES:
            await application.bot.send_message(chat_id, format_report(report))
            return


# ------------------------------------------------------------------ команды
async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    try:
        projects = await _client_of(context).list_projects()
    except httpx.HTTPError as exc:
        await _reply_http_error(update, exc, "получить список проектов")
        return
    await update.effective_chat.send_message(format_projects(projects))


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    text = " ".join(context.args) if context.args else ""
    try:
        project, stand, marker = parse_run_args(text)
    except ValueError as exc:
        await update.effective_chat.send_message(str(exc))
        return

    client = _client_of(context)
    try:
        projects = await client.list_projects()
    except httpx.HTTPError as exc:
        await _reply_http_error(update, exc, "получить список проектов")
        return

    project_row = next((p for p in projects if p["name"] == project), None)
    if project_row is None:
        await update.effective_chat.send_message(f"Проект «{project}» не найден. См. /projects.")
        return
    stand_names = {s["name"] for s in project_row.get("stands", [])}
    if stand not in stand_names:
        await update.effective_chat.send_message(f"Стенд «{stand}» не найден в проекте «{project}». См. /projects.")
        return

    try:
        run = await client.submit_run(project, stand, marker)
    except httpx.HTTPError as exc:
        await _reply_http_error(update, exc, "поставить прогон")
        return

    run_id = run["id"]
    chat_id = update.effective_chat.id
    context.application.bot_data.setdefault("last_run", {})[chat_id] = run_id
    await update.effective_chat.send_message(f"Прогон #{run_id} поставлен в очередь.")
    context.application.create_task(
        _watch_run(context.application, chat_id, run_id), update=update
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    text = " ".join(context.args) if context.args else ""
    try:
        run_id = parse_optional_run_id(text)
    except ValueError as exc:
        await update.effective_chat.send_message(str(exc))
        return

    chat_id = update.effective_chat.id
    if run_id is None:
        run_id = context.application.bot_data.get("last_run", {}).get(chat_id)
        if run_id is None:
            await update.effective_chat.send_message("Нет последнего прогона в этом чате. Укажите id: /status <id>")
            return

    try:
        report = await _client_of(context).get_report(run_id)
    except httpx.HTTPError as exc:
        await _reply_http_error(update, exc, "получить статус", not_found=f"Прогон #{run_id} не найден.")
        return
    await update.effective_chat.send_message(format_status(report))


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    text = " ".join(context.args) if context.args else ""
    try:
        run_id = parse_run_id(text, "Использование: /report <id>")
    except ValueError as exc:
        await update.effective_chat.send_message(str(exc))
        return

    try:
        report = await _client_of(context).get_report(run_id)
    except httpx.HTTPError as exc:
        await _reply_http_error(update, exc, "получить отчёт", not_found=f"Прогон #{run_id} не найден.")
        return
    await update.effective_chat.send_message(format_report(report))


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update):
        return
    text = " ".join(context.args) if context.args else ""
    try:
        project = parse_project_name(text, "Использование: /last <проект>")
    except ValueError as exc:
        await update.effective_chat.send_message(str(exc))
        return

    client = _client_of(context)
    try:
        runs = await client.list_runs(project)
    except httpx.HTTPError as exc:
        await _reply_http_error(update, exc, "получить прогоны", not_found=f"Проект «{project}» не найден.")
        return

    if not runs:
        await update.effective_chat.send_message(f"У проекта «{project}» ещё нет прогонов.")
        return

    try:
        report = await client.get_report(runs[0]["id"])
    except httpx.HTTPError as exc:
        await _reply_http_error(update, exc, "получить отчёт")
        return
    await update.effective_chat.send_message(format_report(report))


# ------------------------------------------------------------------ запуск/остановка приложения
def build_application() -> Application:
    application = ApplicationBuilder().token(settings.TH_TG_BOT_TOKEN).build()
    application.bot_data["client"] = HubClient()
    application.bot_data["last_run"] = {}
    application.add_handler(CommandHandler("projects", cmd_projects))
    application.add_handler(CommandHandler("run", cmd_run))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("report", cmd_report))
    application.add_handler(CommandHandler("last", cmd_last))
    return application


async def start_application(application: Application) -> None:
    await application.initialize()
    if application.updater is not None:
        await application.updater.start_polling()
    await application.start()


async def stop_application(application: Application) -> None:
    try:
        if application.updater is not None and application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        await application.shutdown()
    finally:
        client = application.bot_data.get("client")
        if client is not None:
            await client.aclose()
