"""Кодирование/разбор callback_data инлайн-кнопок — чистые функции без объектов
aiogram, юнит-тестируются напрямую (tests/test_tg_bot.py)."""
from __future__ import annotations

# callback_data кодирует отсутствующее значение (стенд "без стенда", маркер "Все")
# этим токеном — project/stand в этой системе не содержат ":" и "_" отдельным полем.
_NONE_TOKEN = "_"


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
    if action == "run_section_confirm" and len(rest) == 2:
        return {"action": "run_section_confirm", "project": rest[0], "section": rest[1]}
    if action in ("run_status", "run_report", "run_cancel", "run_trend", "run_share") and len(rest) == 1:
        try:
            run_id = int(rest[0])
        except ValueError:
            return {"action": "invalid", "raw": data}
        return {"action": action, "run_id": run_id}
    if action == "tests" and len(rest) == 2:
        return {"action": "tests", "project": rest[0], "stand": _decode_token(rest[1])}
    if action in ("preset", "preset_confirm") and len(rest) == 3:
        try:
            preset_id = int(rest[2])
        except ValueError:
            return {"action": "invalid", "raw": data}
        return {"action": action, "project": rest[0], "stand": _decode_token(rest[1]), "preset_id": preset_id}
    if action == "flaky" and len(rest) == 1:
        return {"action": "flaky", "project": rest[0]}
    if action in ("xfail", "xfail_check") and len(rest) == 1:
        return {"action": action, "project": rest[0]}
    if action == "sched_toggle" and len(rest) == 2:
        try:
            schedule_id = int(rest[1])
        except ValueError:
            return {"action": "invalid", "raw": data}
        return {"action": "sched_toggle", "project": rest[0], "schedule_id": schedule_id}
    if action in ("tree_open", "tree_page") and len(rest) == 1:
        try:
            value = int(rest[0])
        except ValueError:
            return {"action": "invalid", "raw": data}
        key = "node" if action == "tree_open" else "page"
        return {"action": action, key: value}
    if action in (
        "tree_up", "tree_refresh", "tree_select_file", "tree_clear", "tree_run", "tree_run_confirm",
    ) and not rest:
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
