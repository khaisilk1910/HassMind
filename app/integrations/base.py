from __future__ import annotations

from typing import Any

import httpx


class IntegrationError(RuntimeError):
    """Normalized error raised by a companion-service adapter."""


class JsonHttpClient:
    def __init__(self, base_url: str, timeout: float = 15.0, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers or {},
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        allow_404: bool = False,
    ) -> Any:
        try:
            response = await self.client.request(method, path, json=json, params=params, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise IntegrationError(f"{self.base_url}: request timeout") from exc
        except httpx.HTTPError as exc:
            raise IntegrationError(f"{self.base_url}: {type(exc).__name__}: {exc}") from exc

        if allow_404 and response.status_code == 404:
            return None
        if response.status_code >= 400:
            detail = response.text[:1000]
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("detail") or payload.get("error") or payload.get("message") or payload)[:1000]
            except ValueError:
                pass
            raise IntegrationError(f"HTTP {response.status_code} from {self.base_url}{path}: {detail}")

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}
