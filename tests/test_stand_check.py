"""Проверка доступности стенда по URL (app/core/stand_check.py) — кнопка
«Проверить» в форме стенда (ui/stands.html) и рядом с выбором стенда во
вкладках «Запуск»/«Данные» (ui/project.html). См. app/routers/projects.py
для API-слоя.

httpx.get() подменяем так же, как в tests/test_sentry_client.py: обёртка над
httpx.Client(transport=httpx.MockTransport(handler)) — реальный разбор
ответа/таймаутов httpx отрабатывает как обычно, подменён только транспорт."""
import httpx

from app.core import stand_check

from .conftest import register_project


def _install(monkeypatch, handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    def fake_get(url, *, timeout=None, follow_redirects=None):
        with httpx.Client(transport=httpx.MockTransport(wrapped)) as c:
            return c.get(url, timeout=timeout, follow_redirects=follow_redirects)

    monkeypatch.setattr(stand_check.httpx, "get", fake_get)
    return calls


# ------------------------------------------------------------------ check_url()

def test_check_url_200_is_ok(monkeypatch):
    calls = _install(monkeypatch, lambda req: httpx.Response(200))

    result = stand_check.check_url("https://stand.example.ru")

    assert len(calls) == 1
    assert result.ok is True
    assert result.status_code == 200
    assert result.error is None
    assert result.elapsed_ms >= 0


def test_check_url_redirect_followed_and_ok(monkeypatch):
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(302, headers={"Location": "/auth/main"})
        return httpx.Response(200)

    calls = _install(monkeypatch, handler)

    result = stand_check.check_url("https://stand.example.ru/")

    assert len(calls) == 2  # редирект пройден -- login-страница стенда типично отвечает 302
    assert result.ok is True
    assert result.status_code == 200


def test_check_url_404_is_not_ok(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(404))

    result = stand_check.check_url("https://stand.example.ru")

    assert result.ok is False
    assert result.status_code == 404
    assert result.error == "HTTP 404"


def test_check_url_500_is_not_ok(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(500, text="boom"))

    result = stand_check.check_url("https://stand.example.ru")

    assert result.ok is False
    assert result.status_code == 500
    assert result.error == "HTTP 500"


def test_check_url_timeout_is_not_ok_without_status(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    _install(monkeypatch, handler)

    result = stand_check.check_url("https://stand.example.ru")

    assert result.ok is False
    assert result.status_code is None
    assert result.error == "Таймаут"


def test_check_url_connect_error_is_not_ok_without_status(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    _install(monkeypatch, handler)

    result = stand_check.check_url("https://stand.example.ru")

    assert result.ok is False
    assert result.status_code is None
    assert result.error == "Сеть недоступна"


def test_check_url_blank_is_url_not_set_without_network_attempt(monkeypatch):
    """Пустой url у стенда — осознанный выбор (проект берёт адрес из своего .env),
    не ошибка сети: отдельная причина, и никакого httpx.get вообще не происходит
    (реальный баг, найденный владельцем 23.10.2026, — стенд VSHGU/develop с
    url="" показывал «Сеть недоступна» вместо понятной причины)."""
    calls = _install(monkeypatch, lambda req: httpx.Response(200))

    for blank in ("", "   "):
        result = stand_check.check_url(blank)
        assert result.ok is False
        assert result.status_code is None
        assert result.error == "URL не задан"
        assert result.elapsed_ms == 0

    assert calls == []


# ------------------------------------------------------------------ API: POST /{name}/stands/check

async def test_check_stand_api_ok(qa_client, tmp_path, monkeypatch):
    await register_project(qa_client, "stand_check_api_proj", tmp_path)
    _install(monkeypatch, lambda req: httpx.Response(200))

    resp = await qa_client.post(
        "/api/projects/stand_check_api_proj/stands/check", json={"url": "https://stand.example.ru"}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["status_code"] == 200
    assert body["error"] is None
    assert isinstance(body["elapsed_ms"], int)


async def test_check_stand_api_unreachable_is_still_200_with_ok_false(qa_client, tmp_path, monkeypatch):
    """Недоступный стенд -- это нормальный, ожидаемый ответ кнопки «Проверить»,
    не ошибка API: 200 с ok=false, а не 4xx/5xx."""
    await register_project(qa_client, "stand_check_api_fail_proj", tmp_path)

    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    _install(monkeypatch, handler)

    resp = await qa_client.post(
        "/api/projects/stand_check_api_fail_proj/stands/check", json={"url": "https://down.example.ru"}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["status_code"] is None
    assert body["error"] == "Сеть недоступна"


async def test_check_stand_api_blank_url_is_url_not_set_not_network_error(qa_client, tmp_path):
    """Стенд с пустым url (проект берёт адрес из своего .env, см. StandCreate.url)
    -- отдельная причина, не «Сеть недоступна»."""
    await register_project(qa_client, "stand_check_api_blank_proj", tmp_path)
    resp = await qa_client.post(
        "/api/projects/stand_check_api_blank_proj/stands/check", json={"url": ""}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "URL не задан"


async def test_check_stand_api_works_for_unsaved_url(qa_client, tmp_path, monkeypatch):
    """Проверка не требует, чтобы стенд был уже сохранён -- форма добавления
    стенда шлёт сюда ровно то, что сейчас введено в поле URL."""
    await register_project(qa_client, "stand_check_api_unsaved_proj", tmp_path)
    _install(monkeypatch, lambda req: httpx.Response(200))

    stands = await qa_client.get("/api/projects/stand_check_api_unsaved_proj/stands")
    assert stands.json() == []  # ни одного стенда ещё не сохранено

    resp = await qa_client.post(
        "/api/projects/stand_check_api_unsaved_proj/stands/check",
        json={"url": "https://not-yet-saved.example.ru"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


async def test_check_stand_api_unknown_project_is_404(qa_client):
    resp = await qa_client.post(
        "/api/projects/does-not-exist/stands/check", json={"url": "https://x.example.ru"}
    )
    assert resp.status_code == 404


# ------------------------------------------------------------------ UI smoke: кнопки «Проверить»

import pathlib  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STANDS_HTML = (REPO_ROOT / "ui" / "stands.html").read_text()
STANDS_JS = (REPO_ROOT / "ui" / "stands.js").read_text()
PROJECT_HTML = (REPO_ROOT / "ui" / "project.html").read_text()
PROJECT_STANDS_JS = (REPO_ROOT / "ui" / "project-stands.js").read_text()
PROJECT_DATA_JS = (REPO_ROOT / "ui" / "project-data.js").read_text()
COMMON_JS = (REPO_ROOT / "ui" / "common.js").read_text()


def test_common_js_has_check_stand_url_helper():
    assert "async function checkStandUrl(projectName, url)" in COMMON_JS
    assert "/stands/check" in COMMON_JS


def test_stands_html_has_check_button():
    assert 'id="stand-check-btn"' in STANDS_HTML
    assert 'id="stand-check-result"' in STANDS_HTML


def test_stands_js_wires_check_button():
    assert 'standCheckBtn.addEventListener("click"' in STANDS_JS
    assert "checkStandUrl(project, url)" in STANDS_JS


def test_project_html_run_tab_has_check_button():
    assert 'id="stand-check-btn"' in PROJECT_HTML


def test_project_html_data_tab_has_check_button():
    assert 'id="data-stand-check-btn"' in PROJECT_HTML


def test_project_stands_js_wires_check_button():
    assert 'standCheckBtn.addEventListener("click"' in PROJECT_STANDS_JS
    assert "checkStandUrl(projectName, stand.url)" in PROJECT_STANDS_JS


def test_project_data_js_wires_check_button():
    assert 'dataStandCheckBtn.addEventListener("click"' in PROJECT_DATA_JS
    assert "checkStandUrl(projectName, stand.url)" in PROJECT_DATA_JS
