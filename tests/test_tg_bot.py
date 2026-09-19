"""Telegram-бот (app/tg_bot.py): чистые функции парсинга/форматирования без
сети и без объектов telegram, плюс HubClient поверх реального ASGI-приложения
(тот же трюк, что и в tests/conftest.py::client — ASGITransport вместо сокета)."""

import httpx
import pytest
from httpx import ASGITransport

from app.config import _parse_allowed_ids, settings
from app.db import get_connection
from app.main import app, lifespan
from app.security import verify_password
from app.tg_bot import (
    HubClient,
    _is_allowed,
    build_callback,
    build_confirm_keyboard,
    build_marker_keyboard,
    build_run_args,
    build_run_keyboard,
    build_stands_keyboard,
    format_projects,
    format_report,
    format_status,
    parse_callback,
    parse_optional_run_id,
    parse_project_name,
    parse_run_args,
    parse_run_command,
    parse_run_id,
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


@pytest.mark.parametrize("action", ["run_status", "run_report", "run_cancel"])
def test_parse_callback_run_actions(action):
    assert parse_callback(f"{action}:42") == {"action": action, "run_id": 42}


@pytest.mark.parametrize(
    "data",
    ["", "unknown", "project", "project:a:b", "run_status:not-a-number", "marker:a:b"],
)
def test_parse_callback_invalid_returns_invalid_action(data):
    assert parse_callback(data) == {"action": "invalid", "raw": data}


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


def test_build_run_keyboard_has_status_report_cancel():
    markup = build_run_keyboard(7)
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert data == ["run_status:7", "run_report:7", "run_cancel:7"]


# ------------------------------------------------------------------ lifespan: без токена бот не создаётся
async def test_lifespan_without_token_skips_bot(db_path, monkeypatch):
    monkeypatch.setattr(settings, "TH_TG_BOT_TOKEN", "")
    async with lifespan(app):
        assert app.state.tg_bot is None
