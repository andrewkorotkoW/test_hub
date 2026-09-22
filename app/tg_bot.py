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

from .config import settings

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3.0
TERMINAL_STATUSES = {"passed", "failed", "cancelled"}
MAX_FAILED_LISTED = 15
MAX_REASON_LEN = 120
TELEGRAM_CAPTION_LIMIT = 1024
MAX_FAILED_BUTTONS = 10
MAX_FAILED_LABEL_LEN = 40
MAX_ERROR_TEXT_LEN = 1500

STATUS_RU = {
    "queued": "в очереди",
    "running": "выполняется",
    "passed": "пройден",
    "failed": "провален",
    "cancelled": "отменён",
}

MARKER_BUTTONS = [("Smoke", "smoke"), ("API", "api"), ("UI", "ui"), ("Все", None)]
MARKER_LABELS = dict(MARKER_BUTTONS)

TREE_CACHE_TTL_SECONDS = 300
TREE_PAGE_SIZE = 8

RUN_USAGE = "Использование: /run <проект> <стенд> [маркер]"
STATUS_USAGE = "id прогона должен быть числом: /status [id]"
REPORT_USAGE = "Использование: /report <id>"
LAST_USAGE = "Использование: /last <проект>"
FLAKY_USAGE = "Использование: /flaky <проект> [стенд]"
FLAKY_TOP_N = 10
XFAIL_USAGE = "Использование: /xfail <проект> [стенд]"
XFAIL_TOP_N = 10

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

    async def submit_run(self, project: str, stand: str | None, marker: str | None, target: str = "all") -> dict:
        payload: dict = {"stand": stand, "target": target}
        if marker:
            payload["marker"] = marker
        resp = await self._request("POST", f"/api/projects/{project}/runs", json=payload)
        return resp.json()

    async def get_tests(self, project: str) -> dict:
        resp = await self._request("GET", f"/api/projects/{project}/tests")
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

    async def create_share_link(self, run_id: int, expires: str = "30d") -> dict:
        resp = await self._request("POST", f"/api/runs/{run_id}/share", json={"expires": expires})
        return resp.json()

    async def list_flaky(self, project: str, stand: str | None = None) -> list[dict]:
        params = {"stand": stand} if stand else {}
        resp = await self._request("GET", f"/api/projects/{project}/flaky", params=params)
        return resp.json()["items"]

    async def list_xfail(self, project: str, stand: str | None = None) -> list[dict]:
        params = {"stand": stand} if stand else {}
        resp = await self._request("GET", f"/api/projects/{project}/xfail", params=params)
        return resp.json()["items"]


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


def parse_flaky_args(text: str) -> tuple[str, str | None]:
    """"<проект> [стенд]" — стенд необязателен (агрегирует по всем стендам проекта,
    см. HubClient.list_flaky/app.core.flaky.list_stats с stand=None)."""
    parts = text.split()
    if not parts:
        raise ValueError(FLAKY_USAGE)
    project, *rest = parts
    return project, rest[0] if rest else None


def parse_xfail_args(text: str) -> tuple[str, str | None]:
    """"<проект> [стенд]" — то же соглашение, что и parse_flaky_args."""
    parts = text.split()
    if not parts:
        raise ValueError(XFAIL_USAGE)
    project, *rest = parts
    return project, rest[0] if rest else None


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
    if action in ("run_status", "run_report", "run_cancel", "run_trend", "run_share") and len(rest) == 1:
        try:
            run_id = int(rest[0])
        except ValueError:
            return {"action": "invalid", "raw": data}
        return {"action": action, "run_id": run_id}
    if action == "tests" and len(rest) == 2:
        return {"action": "tests", "project": rest[0], "stand": _decode_token(rest[1])}
    if action == "flaky" and len(rest) == 1:
        return {"action": "flaky", "project": rest[0]}
    if action in ("xfail", "xfail_check") and len(rest) == 1:
        return {"action": action, "project": rest[0]}
    if action in ("tree_open", "tree_page") and len(rest) == 1:
        try:
            value = int(rest[0])
        except ValueError:
            return {"action": "invalid", "raw": data}
        key = "node" if action == "tree_open" else "page"
        return {"action": action, key: value}
    if action in ("tree_up", "tree_refresh", "tree_select_file", "tree_clear", "tree_run") and not rest:
        return {"action": action}
    if action in ("fail_open", "fail_restart_one") and len(rest) == 2:
        try:
            run_id, index = int(rest[0]), int(rest[1])
        except ValueError:
            return {"action": "invalid", "raw": data}
        return {"action": action, "run_id": run_id, "index": index}
    if action == "fail_restart_all" and len(rest) == 1:
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


# ------------------------------------------------------------------ дерево тестов (discover() -> плоский список узлов)
def build_flat_tree(tree: dict) -> list[dict]:
    """{file: {cls: [test, ...]}} (см. app/core/runner.py::discover) -> плоский
    список узлов dir/file/class/test с parent/children-индексами. Узел [0] —
    корень. Индекс узла в этом списке и есть то, что кодируется в callback_data
    (см. п.6 задачи) — путь файла/тест-функции туда не попадает, так что 64-байтный
    лимит Telegram не проблема независимо от длины реальных путей/имён тестов.
    nodeid зеркалит ui/project.js::nodeIdOf (file::cls::test либо file::test)."""
    nodes: list[dict] = [{"kind": "dir", "label": "", "parent": None, "children": []}]
    dir_index: dict[tuple[str, ...], int] = {(): 0}

    def get_dir(parts: tuple[str, ...]) -> int:
        if parts in dir_index:
            return dir_index[parts]
        parent_idx = get_dir(parts[:-1])
        idx = len(nodes)
        nodes.append({"kind": "dir", "label": parts[-1], "parent": parent_idx, "children": []})
        nodes[parent_idx]["children"].append(idx)
        dir_index[parts] = idx
        return idx

    for file_path in sorted(tree):
        parts = tuple(file_path.split("/"))
        parent_idx = get_dir(parts[:-1])
        file_idx = len(nodes)
        nodes.append({"kind": "file", "label": parts[-1], "parent": parent_idx, "children": []})
        nodes[parent_idx]["children"].append(file_idx)

        classes = tree[file_path]
        for cls_name in sorted(classes):
            tests = classes[cls_name]
            if cls_name:
                owner_idx = len(nodes)
                nodes.append({"kind": "class", "label": cls_name, "parent": file_idx, "children": []})
                nodes[file_idx]["children"].append(owner_idx)
            else:
                owner_idx = file_idx
            for test_name in tests:
                nodeid = f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}"
                test_idx = len(nodes)
                nodes.append(
                    {"kind": "test", "label": test_name, "nodeid": nodeid, "parent": owner_idx, "children": []}
                )
                nodes[owner_idx]["children"].append(test_idx)
    return nodes


def _sorted_children(nodes: list[dict], index: int) -> list[int]:
    return sorted(nodes[index]["children"], key=lambda i: nodes[i]["label"].lower())


def _breadcrumb(nodes: list[dict], index: int) -> str:
    parts = []
    node: int | None = index
    while node is not None:
        label = nodes[node]["label"]
        if label:
            parts.append(label)
        node = nodes[node]["parent"]
    return "/".join(reversed(parts)) or "/"


def _collect_test_nodeids(nodes: list[dict], index: int) -> list[str]:
    result: list[str] = []
    stack = [index]
    while stack:
        node = nodes[stack.pop()]
        if node["kind"] == "test":
            result.append(node["nodeid"])
        else:
            stack.extend(node["children"])
    return result


def _strip_param_suffix(nodeid: str) -> str:
    if nodeid.endswith("]") and "[" in nodeid:
        return nodeid[: nodeid.rindex("[")]
    return nodeid


def _nodeid_to_full_name(nodeid: str) -> str:
    """Пересчитывает pytest nodeid (file.py::Class::test[param], см. build_flat_tree)
    в то же представление, что allure_pytest кладёт в fullName результата
    (allure_pytest.utils.allure_full_name: "{dotted.module.path}{.Class}?#{test}",
    без параметров parametrize) — так падающий тест из отчёта можно сопоставить
    с реальным nodeid для перезапуска."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def build_full_name_index(nodes: list[dict]) -> dict[str, str]:
    """fullName (см. _nodeid_to_full_name) -> реальный nodeid без параметров
    parametrize (pytest сам подберёт по такому базовому id все его вариации)."""
    index: dict[str, str] = {}
    for node in nodes:
        if node["kind"] == "test":
            index.setdefault(_nodeid_to_full_name(node["nodeid"]), _strip_param_suffix(node["nodeid"]))
    return index


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


def _bad_tests(report: dict) -> list[dict]:
    return [t for t in report.get("tests", []) if t.get("status") in ("failed", "broken")]


def _short_reason(test: dict) -> str:
    message = (test.get("message") or "").strip()
    if not message:
        return ""
    return message.splitlines()[0][:MAX_REASON_LEN]


def _short_test_label(name: str) -> str:
    """allure fullName — "{dotted.module.path}{.Class}?#{test}" (см. allure_pytest.utils.
    allure_full_name) — короткое имя это часть после "#", как label теста в дереве
    (build_flat_tree), а не полный путь модуля."""
    short = (name or "").rsplit("#", 1)[-1] or "?"
    if len(short) > MAX_FAILED_LABEL_LEN:
        short = short[: MAX_FAILED_LABEL_LEN - 1] + "…"
    return short


def _error_text(test: dict) -> str:
    parts = [p for p in (test.get("message"), test.get("trace")) if p]
    text = "\n\n".join(parts).strip()
    if not text:
        return "Текст ошибки недоступен."
    if len(text) > MAX_ERROR_TEXT_LEN:
        text = text[:MAX_ERROR_TEXT_LEN].rstrip() + "…"
    return text


def format_report(report: dict) -> str:
    status_ru = STATUS_RU.get(report["status"], report["status"])
    duration = report.get("duration")
    duration_str = f"{duration:.1f}с" if isinstance(duration, (int, float)) else "—"
    lines = [
        f"Прогон #{report['id']} ({report.get('project')}) — {status_ru}",
        _counts_line(report.get("counts") or {}),
        f"Длительность: {duration_str}",
    ]
    bad_tests = _bad_tests(report)
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


def format_flaky(project: str, stand: str | None, items: list[dict]) -> str:
    header = f"Нестабильные тесты «{project}»" + (f" / {stand}" if stand else "") + ":"
    top = items[:FLAKY_TOP_N]
    if not top:
        return f"{header}\nПока нет данных (мало прогонов) или все тесты стабильны."
    lines = [header]
    for item in top:
        percent = round(item["score"] * 100)
        short = (item.get("test") or "").rsplit("#", 1)[-1]
        stand_suffix = "" if stand else f", стенд {item.get('stand')}"
        lines.append(f"• {short}: {percent}% ({item.get('fails', 0)}/{item.get('runs', 0)} упал{stand_suffix})")
    return "\n".join(lines)


def format_xfail(project: str, items: list[dict]) -> str:
    header = f"Известные дефекты «{project}»:"
    if not items:
        return f"{header}\nДефектов не найдено."
    top = items[:XFAIL_TOP_N]
    lines = [header]
    for item in top:
        short = (item.get("test") or "").rsplit("#", 1)[-1]
        mark = "можно снять xfail (xpass)" if item.get("state") == "xpass" else "xfail"
        lines.append(f"• {short} [{item.get('stand')}]: {mark}")
    remaining = len(items) - len(top)
    if remaining > 0:
        lines.append(f"…и ещё {remaining}")
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
    builder.button(text="Флаки", callback_data=build_callback("flaky", project=project))
    builder.button(text="Дефекты", callback_data=build_callback("xfail", project=project))
    builder.button(text="« К проектам", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def build_back_keyboard(callback_data: str, label: str = "« Назад") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=label, callback_data=callback_data)
    return builder.as_markup()


def build_marker_keyboard(project: str, stand: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, marker in MARKER_BUTTONS:
        builder.button(text=label, callback_data=build_callback("marker", project=project, stand=stand, marker=marker))
    builder.button(text="Выбрать тесты", callback_data=build_callback("tests", project=project, stand=stand))
    builder.button(text="« К стендам", callback_data=build_callback("project", project=project))
    builder.adjust(2, 2, 1, 1)
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
    builder.button(text="Тренд", callback_data=build_callback("run_trend", run_id=str(run_id)))
    builder.button(text="Поделиться", callback_data=build_callback("run_share", run_id=str(run_id)))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def build_report_keyboard(run_id: int, failed: list[dict]) -> InlineKeyboardMarkup:
    """Обычная клавиатура прогона (build_run_keyboard) + до MAX_FAILED_BUTTONS кнопок
    упавших/сломанных тестов. Индекс кнопки — позиция в этом же списке `failed`,
    закэшированном per run_id (см. failed_cache) — сам callback_data хранит только
    run_id и индекс, не имя теста, поэтому укладывается в лимит Telegram (64 байта)
    независимо от длины nodeid/fullName (тот же приём, что и в дереве тестов)."""
    builder = InlineKeyboardBuilder(markup=build_run_keyboard(run_id).inline_keyboard)
    for index, test in enumerate(failed[:MAX_FAILED_BUTTONS]):
        builder.row(
            InlineKeyboardButton(
                text=f"❌ {_short_test_label(test.get('name') or '')}",
                callback_data=build_callback("fail_open", run_id=str(run_id), index=str(index)),
            )
        )
    return builder.as_markup()


def build_fail_detail_keyboard(run_id: int, index: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Перезапустить этот тест",
        callback_data=build_callback("fail_restart_one", run_id=str(run_id), index=str(index)),
    )
    builder.button(text="Перезапустить все упавшие", callback_data=build_callback("fail_restart_all", run_id=str(run_id)))
    builder.adjust(1)
    return builder.as_markup()


def _tree_item_label(node: dict, selected: set[str]) -> str:
    if node["kind"] == "test":
        mark = "✅" if node["nodeid"] in selected else "▫️"
        return f"{mark} {node['label']}"
    icon = {"dir": "📁", "file": "📄", "class": "🗂"}[node["kind"]]
    return f"{icon} {node['label']}"


def build_tree_text(nodes: list[dict], project: str, stand: str | None, node: int, selected: set[str], error: str | None) -> str:
    lines = [f"Проект: {project}", f"Стенд: {_stand_label(stand)}"]
    if error:
        lines.append(f"⚠️ {error}")
    lines.append(f"Путь: {_breadcrumb(nodes, node)}")
    lines.append(f"Выбрано тестов: {len(selected)}")
    lines.append("Выберите папку, файл или тест:" if nodes[node]["children"] else "Здесь пусто.")
    return "\n".join(lines)


def build_tree_keyboard(
    nodes: list[dict], project: str, stand: str | None, node: int, page: int, selected: set[str]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    children = _sorted_children(nodes, node)
    start = page * TREE_PAGE_SIZE
    page_items = children[start : start + TREE_PAGE_SIZE]
    for child_idx in page_items:
        child = nodes[child_idx]
        builder.row(
            InlineKeyboardButton(
                text=_tree_item_label(child, selected),
                callback_data=build_callback("tree_open", node=str(child_idx)),
            )
        )

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton(text="‹ назад", callback_data=build_callback("tree_page", page=str(page - 1))))
    if start + TREE_PAGE_SIZE < len(children):
        nav_row.append(InlineKeyboardButton(text="вперёд ›", callback_data=build_callback("tree_page", page=str(page + 1))))
    if nav_row:
        builder.row(*nav_row)

    top_row = []
    if nodes[node]["parent"] is not None:
        top_row.append(InlineKeyboardButton(text="⬆ уровень выше", callback_data="tree_up"))
    top_row.append(InlineKeyboardButton(text="Обновить дерево", callback_data="tree_refresh"))
    builder.row(*top_row)

    if nodes[node]["kind"] == "file":
        builder.row(InlineKeyboardButton(text="Выбрать все в файле", callback_data="tree_select_file"))

    builder.row(
        InlineKeyboardButton(text="Сбросить", callback_data="tree_clear"),
        InlineKeyboardButton(text=f"Запустить выбранные ({len(selected)})", callback_data="tree_run"),
    )
    builder.row(InlineKeyboardButton(text="« К набору", callback_data=build_callback("stand", project=project, stand=stand)))
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


# ------------------------------------------------------------------ кэш дерева тестов (per project, TTL ~5 минут)
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


# ------------------------------------------------------------------ фоновое ожидание прогона
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
                caption = format_report(report)
                failed = _bad_tests(report)
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
    await query.answer()

    target = "\n".join(sorted(selected))
    try:
        run = await client.submit_run(state["project"], state["stand"], None, target=target)
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
    await _safe_edit(query.message, format_status(report), build_run_keyboard(run_id))


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
    caption = format_report(report)
    failed = _bad_tests(report)
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


# ------------------------------------------------------------------ упавшие тесты: текст ошибки и перезапуск
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
    caption = format_report(report)
    failed = _bad_tests(report)
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
    caption = format_report(report)
    failed = _bad_tests(report)
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
