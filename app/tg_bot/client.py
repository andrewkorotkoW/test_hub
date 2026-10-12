"""HTTP-клиент к собственному REST API test_hub (от имени сервисной учётки
бота) — используется handlers.py как в кнопочном, так и в командном флоу."""
from __future__ import annotations

import asyncio

import httpx

from ..config import settings


class HubClient:
    """Ходит в собственный REST API test_hub от имени сервисной учётки
    (settings.TH_TG_SERVICE_LOGIN/PASSWORD), переиспользуя cookie сессии между
    запросами и перелогиниваясь при 401 (например, после истечения сессии)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{settings.TH_PORT}")
        self._logged_in = False
        self._login_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _login(self) -> None:
        resp = await self._client.post(
            "/api/login",
            json={"login": settings.TH_TG_SERVICE_LOGIN, "password": settings.TH_TG_SERVICE_PASSWORD},
        )
        resp.raise_for_status()
        self._logged_in = True

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return
        async with self._login_lock:
            if not self._logged_in:
                await self._login()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        await self._ensure_login()
        resp = await self._client.request(method, url, **kwargs)
        if resp.status_code == 401:
            self._logged_in = False
            await self._ensure_login()
            resp = await self._client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp

    async def list_projects(self) -> list[dict]:
        resp = await self._request("GET", "/api/projects")
        return resp.json()

    async def list_stands(self, project: str) -> list[dict]:
        resp = await self._request("GET", f"/api/projects/{project}/stands")
        return resp.json()

    async def submit_run(
        self,
        project: str,
        stand: str | None,
        marker: str | None,
        target: str = "all",
        confirm_manual: bool = False,
    ) -> dict:
        payload: dict = {"stand": stand, "target": target}
        if marker:
            payload["marker"] = marker
        if confirm_manual:
            payload["confirm_manual"] = True
        resp = await self._request("POST", f"/api/projects/{project}/runs", json=payload)
        return resp.json()

    async def list_stand_presets(self, project: str, stand: str) -> list[dict]:
        resp = await self._request("GET", f"/api/projects/{project}/stands/{stand}/presets")
        return resp.json()

    async def get_tests(self, project: str) -> dict:
        resp = await self._request("GET", f"/api/projects/{project}/tests")
        return resp.json()

    async def get_report(self, run_id: int) -> dict:
        resp = await self._request("GET", f"/api/runs/{run_id}/report")
        return resp.json()

    async def get_report_png(self, run_id: int) -> bytes:
        resp = await self._request("GET", f"/api/runs/{run_id}/report.png")
        return resp.content

    async def get_trend_png(self, run_id: int) -> bytes:
        resp = await self._request("GET", f"/api/runs/{run_id}/trend.png")
        return resp.content

    async def list_runs(self, project: str) -> list[dict]:
        resp = await self._request("GET", f"/api/projects/{project}/runs")
        return resp.json()

    async def cancel_run(self, run_id: int) -> dict:
        resp = await self._request("POST", f"/api/runs/{run_id}/cancel")
        return resp.json()

    async def create_share_link(self, run_id: int, expires: str = "30d") -> dict:
        resp = await self._request("POST", f"/api/runs/{run_id}/share", json={"expires": expires})
        return resp.json()

    async def list_flaky(self, project: str, stand: str | None = None) -> list[dict]:
        params = {"stand": stand} if stand else {}
        resp = await self._request("GET", f"/api/projects/{project}/flaky", params=params)
        return resp.json()["items"]

    async def list_xfail(self, project: str, stand: str | None = None) -> list[dict]:
        params = {"stand": stand} if stand else {}
        resp = await self._request("GET", f"/api/projects/{project}/xfail", params=params)
        return resp.json()["items"]

    async def get_stats(self, project: str, stand: str | None = None) -> dict:
        params = {"stand": stand} if stand else {}
        resp = await self._request("GET", f"/api/projects/{project}/stats", params=params)
        return resp.json()

    async def list_schedules(self, project: str) -> list[dict]:
        resp = await self._request("GET", f"/api/projects/{project}/schedules")
        return resp.json()

    async def set_schedule_enabled(self, project: str, schedule_id: int, enabled: bool) -> dict:
        resp = await self._request(
            "PUT", f"/api/projects/{project}/schedules/{schedule_id}", json={"enabled": enabled}
        )
        return resp.json()
