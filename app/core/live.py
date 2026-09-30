"""Живой кадр UI-теста (POST/GET /api/runs/{id}/live, live.jpg) — контракт в
docs/missions/2026-10-01_live_stream.md, п.1-2. Кадр нигде не пишется на диск,
только в памяти процесса: по одному последнему кадру на run_id.

Троттлинг (контракт, п.1): плагин может слать кадры чаще 5/с — в память всегда
кладётся самый свежий кадр (live.jpg отдаёт его), но WS-рассылка (см.
app/routers/runs.py::upload_live_frame) пропускается, если с прошлой рассылки
этого run_id прошло меньше _THROTTLE_SECONDS, чтобы не забить сокет.

Чистка (контракт, п.2): кадр "протухает" сам через _EXPIRE_SECONDS после
последнего received_at — этого достаточно и для "прогон завершился 5 минут
назад" (плагин перестаёт слать кадры вместе с завершением теста/прогона), и
для старта сервера (модульный dict создаётся пустым при каждом импорте
процесса) — без threading.Timer и фоновых потоков, т.к. проверка ленивая, на
каждое обращение (see get_frame)."""
from __future__ import annotations

import time

_THROTTLE_SECONDS = 0.2
_EXPIRE_SECONDS = 300

_frames: dict[int, dict] = {}
_last_broadcast_at: dict[int, float] = {}


def clear_all() -> None:
    """Вызывается на старте сервера (app/main.py::lifespan) — на случай если
    процесс переиспользуется без реального рестарта (как init_db(), см. тесты
    lifespan-хуков в app/core/runner.py::register_finalize_hook)."""
    _frames.clear()
    _last_broadcast_at.clear()


def store_frame(run_id: int, nodeid: str, ts: float, step: str, jpeg_bytes: bytes) -> bool:
    """Сохраняет кадр как последний известный для run_id. Возвращает True, если
    его нужно разослать по WebSocket (троттлинг 5/с — см. модульный docstring),
    False — если кадр пришёл раньше чем через _THROTTLE_SECONDS после прошлой
    рассылки (память всё равно обновлена самым свежим кадром)."""
    now = time.time()
    _frames[run_id] = {
        "nodeid": nodeid,
        "ts": ts,
        "step": step,
        "jpeg_bytes": jpeg_bytes,
        "received_at": now,
    }
    last = _last_broadcast_at.get(run_id)
    if last is not None and now - last < _THROTTLE_SECONDS:
        return False
    _last_broadcast_at[run_id] = now
    return True


def get_frame(run_id: int) -> dict | None:
    """Последний кадр прогона или None, если кадров не было либо последний
    протух (старше _EXPIRE_SECONDS) — протухший кадр тут же вычищается."""
    frame = _frames.get(run_id)
    if frame is None:
        return None
    if time.time() - frame["received_at"] > _EXPIRE_SECONDS:
        _frames.pop(run_id, None)
        _last_broadcast_at.pop(run_id, None)
        return None
    return frame
