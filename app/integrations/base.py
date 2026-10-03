from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx

from ..observability import exception, get_logger, info, preview

logger = get_logger("integration_http")


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
        info(logger, "integration_client_initialized", base_url=self.base_url, timeout_seconds=timeout)

    async def close(self) -> None:
        await self.client.aclose()
        info(logger, "integration_client_closed", base_url=self.base_url)

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
        started = perf_counter()
        method = method.upper()
        info(
            logger,
            "integration_http_request_started",
            base_url=self.base_url,
            method=method,
            path=path,
            params=preview(params or {}),
            body=preview(json),
            timeout_seconds=timeout,
        )
        try:
            response = await self.client.request(method, path, json=json, params=params, timeout=timeout)
        except httpx.TimeoutException as exc:
            exception(
                logger,
                "integration_http_timeout",
                message="Companion integration request timed out",
                base_url=self.base_url,
                method=method,
                path=path,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            raise IntegrationError(f"{self.base_url}: request timeout") from exc
        except httpx.HTTPError as exc:
            exception(
                logger,
                "integration_http_transport_error",
                message="Companion integration transport error",
                base_url=self.base_url,
                method=method,
                path=path,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                error_type=type(exc).__name__,
            )
            raise IntegrationError(f"{self.base_url}: {type(exc).__name__}: {exc}") from exc

        duration_ms = round((perf_counter() - started) * 1000, 2)
        if allow_404 and response.status_code == 404:
            info(
                logger,
                "integration_http_request_completed",
                base_url=self.base_url,
                method=method,
                path=path,
                status_code=404,
                duration_ms=duration_ms,
                allowed_404=True,
            )
            return None
        if response.status_code >= 400:
            detail = response.text[:1000]
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("detail") or payload.get("error") or payload.get("message") or payload)[:1000]
            except ValueError:
                pass
            info(
                logger,
                "integration_http_error_response",
                base_url=self.base_url,
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                response=preview(detail),
            )
            raise IntegrationError(f"HTTP {response.status_code} from {self.base_url}{path}: {detail}")

        if not response.content:
            result: Any = {}
        else:
            try:
                result = response.json()
            except ValueError:
                result = {"text": response.text}
        info(
            logger,
            "integration_http_request_completed",
            base_url=self.base_url,
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            response=preview(result),
        )
        return result
