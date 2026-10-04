from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any, Awaitable, Callable

from .camera_tts import CameraTTSClient
from .facedetect import FaceDetectClient
from .generic import GenericHTTPIntegrationClient
from .zalo import ZaloClient
from ..custom_integrations import custom_action_tool_name, custom_runtime_integrations
from ..observability import get_logger, info, warning
from ..settings import settings
from ..telegram import telegram_health

logger = get_logger("integrations")


class IntegrationHub:
    def __init__(self):
        self.camera_tts: CameraTTSClient | None = None
        self.facedetect: FaceDetectClient | None = None
        self.zalo: ZaloClient | None = None
        self.custom: dict[str, GenericHTTPIntegrationClient] = {}
        self.custom_meta: dict[str, dict[str, Any]] = {}
        self.custom_tools: dict[str, tuple[str, dict[str, Any]]] = {}
        self._build_clients()
        info(
            logger,
            "integration_hub_initialized",
            camera_tts=settings.camera_tts_enabled,
            facedetect=settings.facedetect_enabled,
            zalo=settings.zalo_enabled,
            wyoming=settings.wyoming_enabled,
            ha_custom_integrations=settings.ha_custom_integrations_enabled,
            custom_integrations=len(self.custom_meta),
        )

    @staticmethod
    def _custom_headers(item: dict[str, Any]) -> dict[str, str]:
        auth_type = str(item.get("auth_type") or "none")
        secret = str(item.get("secret") or "")
        if auth_type == "bearer" and secret:
            return {"Authorization": f"Bearer {secret}"}
        if auth_type == "header" and secret:
            return {str(item.get("auth_header") or "X-API-Key"): secret}
        return {}

    def _build_clients(self) -> None:
        timeout = settings.integration_http_timeout
        self.camera_tts = (
            CameraTTSClient(settings.camera_tts_url, settings.read_camera_tts_key(), timeout)
            if settings.camera_tts_enabled
            else None
        )
        self.facedetect = (
            FaceDetectClient(settings.facedetect_url, timeout=timeout)
            if settings.facedetect_enabled
            else None
        )
        self.zalo = (
            ZaloClient(settings.zalo_url, settings.zalo_username, settings.read_zalo_password(), timeout)
            if settings.zalo_enabled
            else None
        )

        self.custom = {}
        self.custom_meta = {}
        self.custom_tools = {}
        for item in custom_runtime_integrations():
            integration_id = str(item["id"])
            self.custom_meta[integration_id] = item
            if not item.get("enabled"):
                continue
            self.custom[integration_id] = GenericHTTPIntegrationClient(
                str(item["base_url"]),
                health_path=str(item.get("health_path") or "/health"),
                timeout=timeout,
                headers=self._custom_headers(item),
            )
            for action in item.get("actions") or []:
                if action.get("enabled") and action.get("agent_enabled"):
                    tool_name = custom_action_tool_name(integration_id, str(action.get("id") or ""))
                    self.custom_tools[tool_name] = (integration_id, action)

    def _all_clients(self) -> list[Any]:
        return [
            x
            for x in (self.camera_tts, self.facedetect, self.zalo, *self.custom.values())
            if x is not None
        ]

    async def reconfigure(self) -> None:
        """Rebuild clients in-place so ToolRuntime keeps the same hub reference."""
        old_clients = self._all_clients()
        self._build_clients()
        await asyncio.gather(*(client.close() for client in old_clients), return_exceptions=True)
        info(
            logger,
            "integration_hub_reconfigured",
            camera_tts=settings.camera_tts_enabled,
            facedetect=settings.facedetect_enabled,
            zalo=settings.zalo_enabled,
            wyoming=settings.wyoming_enabled,
            ha_custom_integrations=settings.ha_custom_integrations_enabled,
            custom_integrations=len(self.custom_meta),
        )

    async def close(self) -> None:
        clients = self._all_clients()
        self.camera_tts = None
        self.facedetect = None
        self.zalo = None
        self.custom = {}
        self.custom_meta = {}
        self.custom_tools = {}
        await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
        info(logger, "integration_hub_closed", clients=len(clients))

    async def call_custom_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        target = self.custom_tools.get(tool_name)
        if target is None:
            raise KeyError(f"Unknown or disabled custom integration tool: {tool_name}")
        integration_id, action = target
        client = self.custom.get(integration_id)
        if client is None:
            raise RuntimeError(f"Custom integration {integration_id} is disabled")
        return await client.call_action(action, args)

    async def _status_one(self, name: str, enabled: bool, fn: Callable[[], Awaitable[Any]] | None) -> tuple[str, dict[str, Any]]:
        if not enabled or fn is None:
            return name, {"enabled": False, "ok": False, "status": "disabled"}
        started = perf_counter()
        try:
            data = await fn()
            status = "ok"
            ok = True
            if isinstance(data, dict):
                status = str(data.get("status") or ("ok" if data.get("ok", True) else "error"))
                ok = bool(data.get("ok", status not in {"error", "offline", "unreachable", "missing_token"}))
            else:
                ok = status not in {"error", "offline", "unreachable", "missing_token"}
            value = {"enabled": True, "ok": ok, "status": status, "data": data}
            info(logger, "integration_health_completed", integration=name, status=status, duration_ms=round((perf_counter() - started) * 1000, 2))
            return name, value
        except Exception as exc:
            warning(
                logger,
                "integration_health_failed",
                integration=name,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return name, {"enabled": True, "ok": False, "status": "unreachable", "error": f"{type(exc).__name__}: {exc}"}

    async def _wyoming_health(self) -> dict[str, Any]:
        reader = writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(settings.wyoming_host, settings.wyoming_port),
                timeout=settings.integration_health_timeout,
            )
            return {"status": "ok", "host": settings.wyoming_host, "port": settings.wyoming_port}
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def status(self) -> dict[str, Any]:
        jobs = [
            self._status_one(
                "telegram",
                settings.telegram_enabled,
                (lambda: telegram_health(settings.integration_health_timeout)) if settings.telegram_enabled else None,
            ),
            self._status_one(
                "camera_tts",
                settings.camera_tts_enabled,
                (lambda: self.camera_tts.health(settings.integration_health_timeout)) if self.camera_tts else None,
            ),
            self._status_one(
                "facedetect",
                settings.facedetect_enabled,
                (lambda: self.facedetect.health(settings.integration_health_timeout)) if self.facedetect else None,
            ),
            self._status_one(
                "zalo",
                settings.zalo_enabled,
                (lambda: self.zalo.health(settings.integration_health_timeout)) if self.zalo else None,
            ),
            self._status_one(
                "wyoming_vietnamese",
                settings.wyoming_enabled,
                self._wyoming_health if settings.wyoming_enabled else None,
            ),
        ]

        for integration_id, item in self.custom_meta.items():
            client = self.custom.get(integration_id)
            auth_required = item.get("auth_type") in {"bearer", "header"}
            secret_missing = auth_required and not bool(item.get("secret"))
            if item.get("enabled") and secret_missing:
                async def credential_missing() -> Any:
                    raise RuntimeError("credential is not configured")
                fn: Callable[[], Awaitable[Any]] | None = credential_missing
            else:
                fn = (lambda client=client: client.health(settings.integration_health_timeout)) if client else None
            jobs.append(self._status_one(f"custom:{integration_id}", bool(item.get("enabled")), fn))

        pairs = await asyncio.gather(*jobs)
        out = {name: value for name, value in pairs}
        for integration_id, item in self.custom_meta.items():
            key = f"custom:{integration_id}"
            if key in out:
                out[key]["custom"] = True
                out[key]["integration_id"] = integration_id
                out[key]["name"] = item.get("name")
                out[key]["base_url"] = item.get("base_url")
                out[key]["health_path"] = item.get("health_path")
                out[key]["actions"] = len(item.get("actions") or [])
                out[key]["agent_actions"] = sum(1 for action in (item.get("actions") or []) if action.get("enabled") and action.get("agent_enabled"))
        return out
