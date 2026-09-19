"""Telegram-бот (app/tg_bot.py): чистые функции парсинга/форматирования без
сети и без объектов telegram, плюс HubClient поверх реального ASGI-приложения
(тот же трюк, что и в tests/conftest.py::client — ASGITransport вместо сокета)."""

import httpx
import pytest
from httpx import ASGITransport

from app.config import _parse_allowed_ids, settings
from app.db import get_connection
from app.main import app
from app.security import verify_password
from app.tg_bot import (
    HubClient,
    _is_allowed,
    format_projects,
    format_report,
    format_status,
    parse_optional_run_id,
    parse_project_name,
    parse_run_args,
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
