"""Разбор текстовых команд (/run, /status, /flaky, ...) — чистые функции без
объектов aiogram, юнит-тестируются напрямую (tests/test_tg_bot.py)."""
from __future__ import annotations

RUN_USAGE = "Использование: /run <проект> <стенд> [маркер]"


STATUS_USAGE = "id прогона должен быть числом: /status [id]"


FLAKY_USAGE = "Использование: /flaky <проект> [стенд]"


XFAIL_USAGE = "Использование: /xfail <проект> [стенд]"


STATS_USAGE = "Использование: /stats <проект> [стенд]"


STAGE_USAGE = "Использование: /stage <проект> <пресет>"


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


def parse_stats_args(text: str) -> tuple[str, str | None]:
    """"<проект> [стенд]" — то же соглашение, что и parse_flaky_args/parse_xfail_args."""
    parts = text.split()
    if not parts:
        raise ValueError(STATS_USAGE)
    project, *rest = parts
    return project, rest[0] if rest else None


def parse_stage_args(text: str) -> tuple[str, str]:
    """"<проект> <пресет>" — имя пресета может содержать пробелы (как и маркер
    в parse_run_args), поэтому всё после проекта склеивается в имя целиком."""
    parts = text.split()
    if len(parts) < 2:
        raise ValueError(STAGE_USAGE)
    project, *rest = parts
    return project, " ".join(rest)
