from __future__ import annotations

from typing import Any

from .base import JsonHttpClient


class GenericHTTPIntegrationClient(JsonHttpClient):
    """Health/status client for user-defined HTTP integrations.

    Custom integrations are deliberately health-only. Adding agent tools/actions
    still requires an explicit typed adapter so a generic HTTP endpoint never
    becomes an unrestricted LLM-controlled request tunnel.
    """

    def __init__(
        self,
        base_url: str,
        health_path: str = "/health",
        timeout: float = 15.0,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(base_url, timeout=timeout, headers=headers)
        self.health_path = health_path or "/health"

    async def health(self, timeout: float | None = None) -> Any:
        return await self.request("GET", self.health_path, timeout=timeout)
