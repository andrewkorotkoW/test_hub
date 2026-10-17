"""Клиент YouTrack REST API (app/core/youtrack.py) на мок-сервере — тот же
приём, что в tests/test_sentry_client.py: подменяем `youtrack.httpx.post`
самодельной обёрткой над httpx.Client(transport=httpx.MockTransport(handler)),
реальный httpx-код разбора ответа отрабатывает как обычно."""
import httpx
import pytest

from app.config import settings
from app.core import youtrack

TOKEN = "super-secret-youtrack-token"


@pytest.fixture(autouse=True)
def _configured_youtrack(monkeypatch):
    monkeypatch.setattr(settings, "TH_YOUTRACK_URL", "https://tracker.example.ru")
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "PROJ-1")
    yield


def _install(monkeypatch, handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    def fake_post(url, *, headers=None, params=None, json=None, timeout=None):
        with httpx.Client(transport=httpx.MockTransport(wrapped)) as c:
            return c.post(url, headers=headers, params=params, json=json, timeout=timeout)

    monkeypatch.setattr(youtrack.httpx, "post", fake_post)
    return calls


def test_is_configured_true_when_all_three_set():
    assert youtrack.is_configured() is True


def test_is_configured_false_when_token_missing(monkeypatch):
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", "")
    assert youtrack.is_configured() is False


def test_issue_url_builds_from_settings():
    assert youtrack.issue_url() == "https://tracker.example.ru/issue/PROJ-1"


def test_post_comment_success_returns_id_and_url(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json={"id": "4-123", "$type": "IssueComment"}))
    result = youtrack.post_comment("тестовый текст")
    assert result == {"id": "4-123", "url": "https://tracker.example.ru/issue/PROJ-1"}
    assert len(calls) == 1
    assert calls[0].url.path == "/api/issues/PROJ-1/comments"
    assert calls[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_post_comment_token_never_appears_in_request_body(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json={"id": "1"}))
    youtrack.post_comment("текст без токена")
    body = calls[0].content.decode("utf-8")
    assert TOKEN not in body


def test_post_comment_401_raises_unauthorized_without_leaking_token(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(401, json={"error": "nope"}))
    with pytest.raises(youtrack.YouTrackUnauthorized) as exc_info:
        youtrack.post_comment("текст")
    assert TOKEN not in str(exc_info.value)


def test_post_comment_500_raises_unavailable(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(youtrack.YouTrackUnavailable):
        youtrack.post_comment("текст")


def test_post_comment_network_error_raises_unavailable(monkeypatch):
    def raising_post(url, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(youtrack.httpx, "post", raising_post)
    with pytest.raises(youtrack.YouTrackUnavailable):
        youtrack.post_comment("текст")


def test_post_comment_without_configuration_raises_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "")
    with pytest.raises(youtrack.YouTrackUnavailable):
        youtrack.post_comment("текст")
