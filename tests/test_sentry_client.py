"""Клиент Sentry Web API (app/core/sentry.py) на мок-сервере — п.2 «Тесты» в
docs/missions/2026-09-29_sentry.md: успешный список issues, 401/403/429,
network timeout, кэш на 60 с, токен не в ответах/тексте исключений.

httpx.get() — модульная функция без параметра transport, respx среди зависимостей
нет (см. testhub-run-events-markup-tests/tests/test_digest_testhub.py в другом
репо — тот же вывод про respx), поэтому подменяем `sentry_client.httpx.get`
самодельной обёрткой над httpx.Client(transport=httpx.MockTransport(handler)) —
реальный httpx-код разбора ответа/таймаутов отрабатывает как обычно, только
транспорт (сеть) заменён; каждый вызов handler фиксируется в списке calls, что
и позволяет проверить, что кэш не делает второй HTTP-запрос."""
import httpx
import pytest

from app.config import settings
from app.core import sentry as sentry_client

TOKEN = "super-secret-sentry-token"


@pytest.fixture(autouse=True)
def _configured_sentry(monkeypatch):
    monkeypatch.setattr(settings, "TH_SENTRY_URL", "https://sentry.example.ru")
    monkeypatch.setattr(settings, "TH_SENTRY_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "TH_SENTRY_ORG", "vshgu")
    sentry_client.clear_cache()
    yield
    sentry_client.clear_cache()


def _install(monkeypatch, handler):
    """handler(request) -> httpx.Response; возвращает список зафиксированных запросов."""
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    def fake_get(url, *, headers=None, params=None, timeout=None):
        with httpx.Client(transport=httpx.MockTransport(wrapped)) as c:
            return c.get(url, headers=headers, params=params, timeout=timeout)

    monkeypatch.setattr(sentry_client.httpx, "get", fake_get)
    return calls


RAW_ISSUE = {
    "id": "123",
    "title": "NullPointerException in checkout",
    "culprit": "checkout.views.pay",
    "level": "error",
    "count": "7",
    "userCount": "3",
    "firstSeen": "2026-09-29T09:00:00Z",
    "lastSeen": "2026-09-29T09:30:00Z",
    "permalink": "https://sentry.example.ru/organizations/vshgu/issues/123/",
}


# ------------------------------------------------------------------ успешный список issues

def test_list_issues_success_parses_fields(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=[RAW_ISSUE]))

    issues = sentry_client.list_issues("frontend", "develop")

    assert len(calls) == 1
    assert len(issues) == 1
    issue = issues[0]
    assert issue.id == "123"
    assert issue.title == "NullPointerException in checkout"
    assert issue.culprit == "checkout.views.pay"
    assert issue.level == "error"
    assert issue.count == 7
    assert issue.user_count == 3
    assert issue.first_seen == "2026-09-29T09:00:00Z"
    assert issue.last_seen == "2026-09-29T09:30:00Z"
    assert issue.permalink == "https://sentry.example.ru/organizations/vshgu/issues/123/"


def test_list_issues_request_url_and_query(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=[]))

    sentry_client.list_issues("frontend", "develop", since="-24h")

    assert len(calls) == 1
    request = calls[0]
    assert request.url.path == "/api/0/projects/vshgu/frontend/issues/"
    query = request.url.params["query"]
    assert "environment:develop" in query
    assert "firstSeen:>-24h" in query


def test_list_issues_sends_bearer_token_header(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=[]))
    sentry_client.list_issues("frontend", "develop")
    assert calls[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_list_issues_missing_metadata_falls_back_to_empty_title(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(200, json=[{"id": "1", "level": "warning"}]))
    issues = sentry_client.list_issues("frontend", "develop")
    assert issues[0].title == ""
    assert issues[0].count == 0
    assert issues[0].user_count == 0


# ------------------------------------------------------------------ ошибки HTTP

def test_list_issues_401_raises_unauthorized(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(401, json={"detail": "invalid token"}))
    with pytest.raises(sentry_client.SentryUnauthorized):
        sentry_client.list_issues("frontend", "develop")


def test_list_issues_403_raises_unauthorized(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(403, json={"detail": "forbidden"}))
    with pytest.raises(sentry_client.SentryUnauthorized):
        sentry_client.list_issues("frontend", "develop")


def test_list_issues_429_raises_rate_limited(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(429, json={"detail": "rate limited"}))
    with pytest.raises(sentry_client.SentryRateLimited):
        sentry_client.list_issues("frontend", "develop")


def test_list_issues_500_raises_unavailable(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(sentry_client.SentryUnavailable):
        sentry_client.list_issues("frontend", "develop")


def test_list_issues_timeout_raises_unavailable(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    _install(monkeypatch, handler)
    with pytest.raises(sentry_client.SentryUnavailable):
        sentry_client.list_issues("frontend", "develop")


def test_list_issues_connect_error_raises_unavailable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    _install(monkeypatch, handler)
    with pytest.raises(sentry_client.SentryUnavailable):
        sentry_client.list_issues("frontend", "develop")


# ------------------------------------------------------------------ кэш 60с

def test_list_issues_repeated_call_within_ttl_uses_cache_not_second_request(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=[RAW_ISSUE]))

    first = sentry_client.list_issues("frontend", "develop")
    second = sentry_client.list_issues("frontend", "develop")

    assert len(calls) == 1, "повторный вызов в пределах 60с не должен делать второй HTTP-запрос"
    assert first == second


def test_list_issues_use_cache_false_forces_new_request(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=[RAW_ISSUE]))

    sentry_client.list_issues("frontend", "develop")
    sentry_client.list_issues("frontend", "develop", use_cache=False)

    assert len(calls) == 2


def test_list_issues_cache_expires_after_ttl(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=[RAW_ISSUE]))

    fake_now = [1000.0]
    monkeypatch.setattr(sentry_client.time, "monotonic", lambda: fake_now[0])

    sentry_client.list_issues("frontend", "develop")
    fake_now[0] += sentry_client.CACHE_TTL + 1
    sentry_client.list_issues("frontend", "develop")

    assert len(calls) == 2, "кэш должен считаться протухшим через CACHE_TTL секунд"


def test_list_issues_different_environment_is_not_cached_together(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json=[RAW_ISSUE]))

    sentry_client.list_issues("frontend", "develop")
    sentry_client.list_issues("frontend", "stage")

    assert len(calls) == 2


# ------------------------------------------------------------------ токен не должен попадать наружу

def test_token_not_present_in_returned_issue_data(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(200, json=[RAW_ISSUE]))
    issues = sentry_client.list_issues("frontend", "develop")
    for issue in issues:
        for value in (issue.title, issue.culprit, issue.level, issue.permalink, issue.first_seen, issue.last_seen):
            assert TOKEN not in str(value)


def test_token_not_present_in_unauthorized_exception_text(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(401, json={"detail": "invalid"}))
    with pytest.raises(sentry_client.SentryUnauthorized) as exc_info:
        sentry_client.list_issues("frontend", "develop")
    assert TOKEN not in str(exc_info.value)


def test_token_not_present_in_unavailable_exception_text(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    _install(monkeypatch, handler)
    with pytest.raises(sentry_client.SentryUnavailable) as exc_info:
        sentry_client.list_issues("frontend", "develop")
    assert TOKEN not in str(exc_info.value)


# ------------------------------------------------------------------ latest_event

def test_latest_event_success(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200, json={"eventID": "abc", "tags": []}))
    event = sentry_client.latest_event("123")
    assert event == {"eventID": "abc", "tags": []}
    assert calls[0].url.path == "/api/0/issues/123/events/latest/"


def test_latest_event_timeout_raises_unavailable(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    _install(monkeypatch, handler)
    with pytest.raises(sentry_client.SentryUnavailable):
        sentry_client.latest_event("123")


def test_latest_event_401_raises_unauthorized(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(401, json={}))
    with pytest.raises(sentry_client.SentryUnauthorized):
        sentry_client.latest_event("123")
