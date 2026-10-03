from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any, Awaitable, Callable

from .camera_tts import CameraTTSClient
from .facedetect import FaceDetectClient
from .zalo import ZaloClient
from ..observability import get_logger, info, warning
from ..settings import settings

logger = get_logger("integrations")


class IntegrationHub:
    def __init__(self):
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
        info(
            logger,
            "integration_hub_initialized",
            camera_tts=settings.camera_tts_enabled,
            facedetect=settings.facedetect_enabled,
            zalo=settings.zalo_enabled,
            wyoming=settings.wyoming_enabled,
            ha_custom_integrations=settings.ha_custom_integrations_enabled,
        )

    async def close(self) -> None:
        clients = [x for x in (self.camera_tts, self.facedetect, self.zalo) if x is not None]
        await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
        info(logger, "integration_hub_closed", clients=len(clients))

    async def _status_one(self, name: str, enabled: bool, fn: Callable[[], Awaitable[Any]] | None) -> tuple[str, dict[str, Any]]:
        if not enabled or fn is None:
            return name, {"enabled": False, "ok": False, "status": "disabled"}
        started = perf_counter()
        try:
            data = await fn()
            status = "ok"
            if isinstance(data, dict):
                status = str(data.get("status") or ("ok" if data.get("ok", True) else "error"))
            value = {"enabled": True, "ok": status not in {"error", "offline"}, "status": status, "data": data}
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
        pairs = await asyncio.gather(*jobs)
        return {name: value for name, value in pairs}
