from __future__ import annotations

from typing import Any

from .base import IntegrationError, JsonHttpClient


class CameraTTSClient(JsonHttpClient):
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0):
        headers = {"X-API-Key": api_key} if api_key else {}
        super().__init__(base_url, timeout=timeout, headers=headers)
        self.api_key = api_key

    async def health(self, timeout: float = 3.0) -> dict[str, Any]:
        data = await self.request("GET", "/health", timeout=timeout)
        return data if isinstance(data, dict) else {"status": "unknown", "data": data}

    def _require_key(self) -> None:
        if not self.api_key:
            raise IntegrationError("CAMERA_TTS_API_KEY is empty")

    async def cameras(self) -> Any:
        self._require_key()
        return await self.request("GET", "/cameras")

    async def job(self, job_id: str) -> Any:
        self._require_key()
        return await self.request("GET", f"/jobs/{job_id}")

    async def say(
        self,
        camera: str,
        text: str,
        *,
        queue_mode: str = "add",
        voice: str | None = None,
        rate: str | None = None,
        gain_db: float | None = None,
    ) -> Any:
        self._require_key()
        body: dict[str, Any] = {"text": text, "queue_mode": queue_mode}
        if voice:
            body["voice"] = voice
        if rate:
            body["rate"] = rate
        if gain_db is not None:
            body["gain_db"] = gain_db
        return await self.request("POST", f"/say/{camera}", json=body)

    async def media(self, camera: str, url: str, *, queue_mode: str = "replace", title: str = "") -> Any:
        self._require_key()
        body: dict[str, Any] = {"url": url, "queue_mode": queue_mode}
        if title:
            body["title"] = title
        return await self.request("POST", f"/media/{camera}", json=body)

    async def ptz(self, camera: str, direction: str, *, speed: int = 50, duration: float = 0.35) -> Any:
        self._require_key()
        return await self.request(
            "POST",
            f"/ptz/{camera}",
            json={"direction": direction, "speed": speed, "duration": duration},
        )

    async def stop(self, camera: str) -> Any:
        self._require_key()
        return await self.request("POST", f"/stop/{camera}", json={})
