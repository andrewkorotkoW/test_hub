"""Классификатор причин падения (app/core/failure_causes.py::classify) и
обнаружение волн (detect_waves) — docs/missions/2026-10-13_run_compare_and_causes.md,
часть 1. Сообщения в тестах ниже — как в примерах миссии (разбор прогонов #65/#66):
429/401/ReadTimeout/LoginError K8S_LOGIN/AssertionError/ai_chat-таймаут."""
from datetime import datetime, timedelta

from app.core import failure_causes as fc


# ------------------------------------------------------------------ classify(): по типу причины

def test_classify_429_is_throttling():
    message = "HTTPError: 429 Client Error: Too Many Requests for url: https://stand/api/login"
    assert fc.classify(message, None) == "throttling"


def test_classify_x_ratelimit_header_is_throttling():
    assert fc.classify("Response headers: X-RateLimit-Remaining: 0", None) == "throttling"


def test_classify_login_error_k8s_login_is_throttling():
    """Сессия не поднялась из-за троттлинга логина в k8s-стенде (см. memory) —
    LoginError без явного 429 в тексте всё равно классифицируется как throttling,
    не session, хотя речь о логине/сессии."""
    message = "LoginError: переменные окружения не заданы K8S_LOGIN/K8S_PASSWORD"
    assert fc.classify(message, None) == "throttling"


def test_classify_401_is_session():
    assert fc.classify("requests.exceptions.HTTPError: 401 Client Error: Unauthorized", None) == "session"


def test_classify_unauthenticated_is_session():
    assert fc.classify("AssertionError: expected 200, got Unauthenticated", None) == "session"


def test_classify_redirect_to_auth_main_is_session():
    assert fc.classify("Expected /cabinet, got redirected to /auth/main", None) == "session"


def test_classify_read_timeout_is_stand():
    message = "requests.exceptions.ReadTimeout: HTTPConnectionPool(host='stand', port=443): Read timed out."
    assert fc.classify(message, None) == "stand"


def test_classify_5xx_is_stand():
    assert fc.classify("HTTPError: 503 Service Unavailable", None) == "stand"


def test_classify_connection_reset_is_stand():
    assert fc.classify("ConnectionResetError: Connection reset by peer", None) == "stand"


def test_classify_playwright_goto_timeout_is_stand():
    message = 'playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.\nCall log:\n  - navigating to "https://stand/" , waiting until "load"\n  goto'
    assert fc.classify(message, None) == "stand"


def test_classify_playwright_locator_timeout_without_goto_is_code():
    """Тот же текст "Timeout 30000ms exceeded", но на локаторе (не навигация/сеть) —
    это баг теста/верстки, не стенд (см. правило в failure_causes.PATTERNS['stand'])."""
    message = 'playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.\nwaiting for locator("button.submit") to be visible'
    assert fc.classify(message, None) == "code"


def test_classify_assertion_error_is_code():
    assert fc.classify("AssertionError: assert 1 == 2, one is definitely not two", None) == "code"


def test_classify_key_error_is_code():
    assert fc.classify("KeyError: 'user_id'", None) == "code"


def test_classify_json_decode_error_without_5xx_is_code():
    assert fc.classify("json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)", None) == "code"


def test_classify_ai_chat_180s_timeout_is_stand():
    """tests/ui/ai_chat/** c таймаутом — LLM-стенд за 180с не ответил, не баг теста,
    даже если текст не совпадает с конкретным паттерном 'stand' (ровно "Timeout
    30000ms exceeded")."""
    message = "TimeoutError: ai_chat response not received within 180000ms"
    nodeid = "tests/ui/ai_chat/test_streaming.py::test_long_answer"
    assert fc.classify(message, None, nodeid) == "stand"


def test_classify_ai_chat_timeout_in_trace_also_counts():
    nodeid = "tests/ui/ai_chat/test_streaming.py::test_long_answer"
    assert fc.classify(None, "Traceback...\nTimeoutError: превышен таймаут ожидания ответа", nodeid) == "stand"


def test_classify_generic_timeout_outside_ai_chat_is_code():
    """Та же таймаут-формулировка, но тест не из tests/ui/ai_chat/** — особое правило
    не должно расширяться на произвольные таймауты по всему проекту."""
    message = "TimeoutError: response not received within 180000ms"
    nodeid = "tests/api/orders/test_orders.py::test_create"
    assert fc.classify(message, None, nodeid) == "code"


def test_classify_ai_chat_without_timeout_hint_is_code():
    """nodeid из ai_chat, но сообщение не про таймаут — обычный баг теста."""
    nodeid = "tests/ui/ai_chat/test_streaming.py::test_long_answer"
    assert fc.classify("AssertionError: unexpected response text", None, nodeid) == "code"


# ------------------------------------------------------------------ classify(): приоритет

def test_classify_priority_throttling_over_session():
    """429 и 401 одновременно в тексте — throttling выигрывает (сессия часто не
    поднимается именно из-за троттлинга логина, см. docstring модуля)."""
    message = "429 Too Many Requests on login, then 401 Unauthorized on retry"
    assert fc.classify(message, None) == "throttling"


def test_classify_priority_session_over_stand():
    message = "401 Unauthorized, then upstream returned 503 on next request"
    assert fc.classify(message, None) == "session"


def test_classify_priority_stand_over_code():
    message = "AssertionError: expected 200, got 502 Bad Gateway"
    assert fc.classify(message, None) == "stand"


# ------------------------------------------------------------------ classify(): не роняется на мусоре

def test_classify_none_message_and_trace_is_code():
    assert fc.classify(None, None) == "code"


def test_classify_empty_strings_is_code():
    assert fc.classify("", "", "") == "code"


def test_classify_non_string_message_does_not_raise():
    """Вход за пределами заявленного message: str | None — внутренний re.search
    не умеет работать с нестроковым text ("\\n".join упадёт на не-str элементе
    message/trace) — classify должен проглотить исключение и вернуть 'code', а не
    выбросить TypeError и обрушить _finalize (см. докстринг модуля)."""
    assert fc.classify(12345, None) == "code"
    assert fc.classify(None, {"not": "a string"}) == "code"
    assert fc.classify([1, 2, 3], [4, 5]) == "code"


def test_classify_no_nodeid_does_not_raise_on_ai_chat_like_message():
    message = "TimeoutError: ai_chat response not received within 180000ms"
    assert fc.classify(message, None, None) == "code"


# ------------------------------------------------------------------ short_reason()

def test_short_reason_first_line_truncated():
    message = "x" * 200
    reason = fc.short_reason(message)
    assert len(reason) == fc.MAX_REASON_LEN


def test_short_reason_takes_first_line_only():
    assert fc.short_reason("AssertionError: boom\nTraceback details...") == "AssertionError: boom"


def test_short_reason_none_is_empty_string():
    assert fc.short_reason(None) == ""


# ------------------------------------------------------------------ detect_waves(): синтетический ряд

def _ts(base: datetime, offsets_seconds: list[int]) -> list[str]:
    return [(base + timedelta(seconds=s)).isoformat() for s in offsets_seconds]


def test_detect_waves_exactly_five_failures_in_two_minutes_is_a_wave():
    base = datetime(2026, 1, 1, 10, 0, 0)
    timestamps = _ts(base, [0, 30, 60, 90, 120])  # ровно 120с = 2 минуты
    results = [{"cause": "stand", "finished_ts": ts} for ts in timestamps]
    waves = fc.detect_waves(results)
    assert len(waves) == 1
    assert waves[0] == {
        "cause": "stand", "start_ts": "2026-01-01T10:00:00", "end_ts": "2026-01-01T10:02:00", "count": 5,
    }


def test_detect_waves_four_failures_in_two_minutes_is_not_a_wave():
    base = datetime(2026, 1, 1, 10, 0, 0)
    timestamps = _ts(base, [0, 30, 60, 90])
    results = [{"cause": "stand", "finished_ts": ts} for ts in timestamps]
    assert fc.detect_waves(results) == []


def test_detect_waves_adjacent_windows_merge_into_one():
    """Два кластера по 5 падений, разделённые всего 10 секундами (меньше окна) —
    должны склеиться в одну волну на 10 падений, а не остаться двумя отдельными."""
    base = datetime(2026, 1, 1, 10, 0, 0)
    cluster_a = _ts(base, [0, 10, 20, 30, 40])
    cluster_b = _ts(base, [50, 60, 70, 80, 90])
    results = [{"cause": "stand", "finished_ts": ts} for ts in cluster_a + cluster_b]
    waves = fc.detect_waves(results)
    assert len(waves) == 1
    assert waves[0]["count"] == 10
    assert waves[0]["start_ts"] == "2026-01-01T10:00:00"
    assert waves[0]["end_ts"] == "2026-01-01T10:01:30"


def test_detect_waves_distant_clusters_stay_separate():
    base = datetime(2026, 1, 1, 10, 0, 0)
    cluster_a = _ts(base, [0, 10, 20, 30, 40])
    cluster_b = _ts(base, [300, 310, 320, 330, 340])  # +5 минут — далеко за окном
    results = [{"cause": "stand", "finished_ts": ts} for ts in cluster_a + cluster_b]
    waves = fc.detect_waves(results)
    assert len(waves) == 2
    assert [w["count"] for w in waves] == [5, 5]


def test_detect_waves_different_causes_do_not_merge():
    """Пять throttling и пять session в одном и том же окне времени — две разные
    волны (по причине), не одна общая на 10 падений."""
    base = datetime(2026, 1, 1, 10, 0, 0)
    timestamps = _ts(base, [0, 20, 40, 60, 80])
    results = (
        [{"cause": "throttling", "finished_ts": ts} for ts in timestamps]
        + [{"cause": "session", "finished_ts": ts} for ts in timestamps]
    )
    waves = fc.detect_waves(results)
    assert len(waves) == 2
    assert {w["cause"] for w in waves} == {"throttling", "session"}
    for w in waves:
        assert w["count"] == 5


def test_detect_waves_code_cause_never_forms_a_wave():
    """code — не инфраструктурная причина, волны считаются только по
    throttling/session/stand (failure_causes.INFRA_CAUSES)."""
    base = datetime(2026, 1, 1, 10, 0, 0)
    timestamps = _ts(base, [0, 10, 20, 30, 40])
    results = [{"cause": "code", "finished_ts": ts} for ts in timestamps]
    assert fc.detect_waves(results) == []


def test_detect_waves_entries_without_finished_ts_are_ignored():
    base = datetime(2026, 1, 1, 10, 0, 0)
    timestamps = _ts(base, [0, 10, 20, 30])
    results = [{"cause": "stand", "finished_ts": ts} for ts in timestamps]
    results.append({"cause": "stand", "finished_ts": None})
    results.append({"cause": "stand", "finished_ts": "not-a-timestamp"})
    # всего 6 падений stand, но только 4 с валидным finished_ts -> не волна
    assert fc.detect_waves(results) == []


def test_detect_waves_empty_input_is_empty_list():
    assert fc.detect_waves([]) == []


# ------------------------------------------------------------------ detect_waves(): профиль #66 из миссии

def test_detect_waves_matches_mission_66_profile_two_waves():
    """#66: 70×429 09:43–09:50 и 15×429 10:44–10:47 — ровно 2 волны (пример из
    docs/missions/2026-10-13_run_compare_and_causes.md, раздел «Волны»)."""
    first_start = datetime(2026, 10, 10, 9, 43, 0)
    first_end = datetime(2026, 10, 10, 9, 50, 0)
    first_count = 70
    first = [
        first_start + (first_end - first_start) * i / (first_count - 1)
        for i in range(first_count)
    ]

    second_start = datetime(2026, 10, 10, 10, 44, 0)
    second_end = datetime(2026, 10, 10, 10, 47, 0)
    second_count = 15
    second = [
        second_start + (second_end - second_start) * i / (second_count - 1)
        for i in range(second_count)
    ]

    results = [{"cause": "throttling", "finished_ts": ts.isoformat()} for ts in first + second]
    waves = fc.detect_waves(results)

    assert len(waves) == 2
    assert waves[0]["start_ts"] == "2026-10-10T09:43:00"
    assert waves[0]["end_ts"] == "2026-10-10T09:50:00"
    assert waves[0]["count"] == 70
    assert waves[1]["start_ts"] == "2026-10-10T10:44:00"
    assert waves[1]["end_ts"] == "2026-10-10T10:47:00"
    assert waves[1]["count"] == 15
