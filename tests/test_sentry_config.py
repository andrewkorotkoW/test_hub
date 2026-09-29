"""Sentry без настроек (TH_SENTRY_URL/TOKEN/ORG пустые): блок должен вести себя
тихо — не бросать исключений, отдавать connected=false с понятной причиной, а
не 500. См. п.1 «Тесты» в docs/missions/2026-09-29_sentry.md.

Роль на все sentry-роуты — qa (см. app/deps.py::require_roles, superadmin
проходит через любой require_roles неявно), поэтому ходим qa_client'ом.
"""
from app.config import settings
from app.core import sentry as sentry_client

from .conftest import register_project


def test_is_configured_false_without_any_env(monkeypatch):
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "")
    assert sentry_client.is_configured() is False


def test_is_configured_false_if_any_single_field_missing(monkeypatch):
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "https://sentry.example.ru")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "vshgu")
    assert sentry_client.is_configured() is False


def test_is_configured_true_with_all_three(monkeypatch):
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "https://sentry.example.ru")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "vshgu")
    assert sentry_client.is_configured() is True


def test_list_issues_raises_unavailable_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "")
    try:
        sentry_client.list_issues("proj", "develop")
    except sentry_client.SentryUnavailable:
        pass
    else:
        raise AssertionError("list_issues должен поднимать SentryUnavailable без настроек")


async def test_stand_issues_api_returns_disconnected_without_env_and_without_error(
    qa_client, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "")

    await register_project(qa_client, "sentry_cfg_proj", tmp_path)
    await qa_client.post(
        "/api/projects/sentry_cfg_proj/stands",
        json={"name": "develop", "url": "https://develop.example.ru"},
    )

    resp = await qa_client.get("/api/projects/sentry_cfg_proj/stands/develop/sentry/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["reason"] == "Sentry не настроен"
    assert data["issues"] == []


async def test_stand_issues_api_disconnected_reason_when_configured_but_stand_not_linked(
    qa_client, monkeypatch, tmp_path
):
    """Sentry настроен глобально, но у стенда не заполнены sentry_project/
    sentry_environment — отдельная, более конкретная причина."""
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "https://sentry.example.ru")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "vshgu")

    await register_project(qa_client, "sentry_cfg_proj2", tmp_path)
    await qa_client.post(
        "/api/projects/sentry_cfg_proj2/stands",
        json={"name": "develop", "url": "https://develop.example.ru"},
    )

    resp = await qa_client.get("/api/projects/sentry_cfg_proj2/stands/develop/sentry/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["reason"] == "У стенда не заполнены Sentry-проект и окружение"


async def test_run_sentry_api_returns_disconnected_without_env(qa_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", "")
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "")

    await register_project(qa_client, "sentry_cfg_proj3", tmp_path)
    await qa_client.post(
        "/api/projects/sentry_cfg_proj3/stands",
        json={"name": "develop", "url": "https://develop.example.ru"},
    )
    create_resp = await qa_client.post(
        "/api/projects/sentry_cfg_proj3/runs", json={"stand": "develop", "target": "all"}
    )
    assert create_resp.status_code == 201, create_resp.text
    run_id = create_resp.json()["id"]

    resp = await qa_client.get(f"/api/runs/{run_id}/sentry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["reason"] == "Sentry не настроен"
