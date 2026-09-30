from __future__ import annotations

from typing import Any

from .base import JsonHttpClient


class FaceDetectClient(JsonHttpClient):
    async def health(self, timeout: float = 3.0) -> dict[str, Any]:
        data = await self.request("GET", "/api/health", timeout=timeout)
        return data if isinstance(data, dict) else {"status": "unknown", "data": data}

    async def summary(self) -> Any:
        return await self.request("GET", "/api/summary")

    async def events(
        self,
        *,
        page: int = 1,
        limit: int = 20,
        event_type: str = "",
        camera_id: str = "",
        person_id: str = "",
    ) -> Any:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if event_type:
            params["event_type"] = event_type
        if camera_id:
            params["camera_id"] = camera_id
        if person_id:
            params["person_id"] = person_id
        return await self.request("GET", "/api/events", params=params)

    async def people(self) -> Any:
        return await self.request("GET", "/api/people")

    async def cameras(self) -> Any:
        return await self.request("GET", "/api/cameras")
