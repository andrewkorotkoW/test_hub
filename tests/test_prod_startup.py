"""TH_ENV=prod: отказ старта на незаменённом TH_SECRET (app/main.py::_check_prod_secret,
вызывается первой строкой lifespan) - задача t2 из
docs/missions/2026-09-30_server_readiness.md. dev-режим по-прежнему принимает дефолтный
'change-me' без каких-либо ошибок (текущее поведение владельца на его машине)."""
import pytest

from app.config import settings
from app.main import _check_prod_secret, app, lifespan


def test_check_prod_secret_raises_when_prod_and_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "TH_ENV", "prod")
    monkeypatch.setattr(settings, "TH_SECRET", "change-me")

    with pytest.raises(RuntimeError, match="TH_SECRET"):
        _check_prod_secret()


def test_check_prod_secret_allows_prod_with_real_secret(monkeypatch):
    monkeypatch.setattr(settings, "TH_ENV", "prod")
    monkeypatch.setattr(settings, "TH_SECRET", "a-real-random-secret-value")

    _check_prod_secret()  # не должно поднимать исключение


def test_check_prod_secret_allows_dev_with_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "TH_ENV", "dev")
    monkeypatch.setattr(settings, "TH_SECRET", "change-me")

    _check_prod_secret()  # dev-дефолт по-прежнему безопасен, не должен ничего ломать


async def test_lifespan_raises_before_startup_when_prod_and_default_secret(db_path, monkeypatch):
    monkeypatch.setattr(settings, "TH_ENV", "prod")
    monkeypatch.setattr(settings, "TH_SECRET", "change-me")
    monkeypatch.setattr(settings, "TH_TG_BOT_TOKEN", "")

    with pytest.raises(RuntimeError, match="TH_SECRET"):
        async with lifespan(app):
            pytest.fail("lifespan должен упасть до входа в тело, uvicorn не должен подняться")


async def test_lifespan_starts_normally_when_prod_and_real_secret(db_path, monkeypatch):
    monkeypatch.setattr(settings, "TH_ENV", "prod")
    monkeypatch.setattr(settings, "TH_SECRET", "a-real-random-secret-value")
    monkeypatch.setattr(settings, "TH_TG_BOT_TOKEN", "")

    async with lifespan(app):
        assert app.state.tg_bot is None
