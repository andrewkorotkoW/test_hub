"""Рассылка событий одного прогона всем его WebSocket-подписчикам.

Выбор в пользу отдельного пути /ws/runs/{run_id} на подключение (а не одного общего
/ws с фильтрацией на клиенте) — сервер сам не шлёт лишний трафик подписчикам, которым
нужен только один конкретный прогон."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class RunHub:
    def __init__(self) -> None:
        self._subs: dict[int, set[WebSocket]] = defaultdict(set)

    def connect(self, run_id: int, ws: WebSocket) -> None:
        self._subs[run_id].add(ws)

    def disconnect(self, run_id: int, ws: WebSocket) -> None:
        self._subs[run_id].discard(ws)
        if not self._subs[run_id]:
            self._subs.pop(run_id, None)

    async def broadcast(self, run_id: int, message: dict[str, Any]) -> None:
        dead = []
        for ws in self._subs.get(run_id, ()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(run_id, ws)


hub = RunHub()
