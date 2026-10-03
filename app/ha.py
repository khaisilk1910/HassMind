import asyncio
import json
from time import perf_counter
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
import websockets

from .observability import exception, get_logger, info, preview, warning
from .policy import assert_service_allowed
from .settings import settings

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
logger = get_logger("home_assistant")


class HomeAssistantClient:
    def __init__(self):
        self.base = settings.ha_url.rstrip("/")
        self.token = settings.read_ha_token()
        self.http = httpx.AsyncClient(
            timeout=20.0,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        info(logger, "ha_client_initialized", base_url=self.base)

    async def close(self):
        await self.http.aclose()
        info(logger, "ha_client_closed")

    async def _get(self, path: str, params: dict | None = None):
        started = perf_counter()
        info(logger, "ha_http_request_started", method="GET", path=path, params=preview(params or {}))
        try:
            r = await self.http.get(self.base + path, params=params)
            r.raise_for_status()
            data = r.json()
            info(
                logger,
                "ha_http_request_completed",
                method="GET",
                path=path,
                status_code=r.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                response=preview(data),
            )
            return data
        except Exception as exc:
            exception(
                logger,
                "ha_http_request_failed",
                message="Home Assistant GET request failed",
                method="GET",
                path=path,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                error_type=type(exc).__name__,
            )
            raise

    async def _post(self, path: str, data: dict | None = None, params: dict | None = None):
        started = perf_counter()
        payload = data or {}
        info(logger, "ha_http_request_started", method="POST", path=path, params=preview(params or {}), body=preview(payload))
        try:
            r = await self.http.post(self.base + path, json=payload, params=params)
            r.raise_for_status()
            result = {} if not r.content else r.json()
            info(
                logger,
                "ha_http_request_completed",
                method="POST",
                path=path,
                status_code=r.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                response=preview(result),
            )
            return result
        except Exception as exc:
            exception(
                logger,
                "ha_http_request_failed",
                message="Home Assistant POST request failed",
                method="POST",
                path=path,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                body=preview(payload),
                error_type=type(exc).__name__,
            )
            raise

    async def states(self):
        return await self._get("/api/states")

    async def state(self, entity_id: str):
        return await self._get(f"/api/states/{entity_id}")

    async def history(self, entity_id: str, start_time: str | None = None):
        path = "/api/history/period" + (f"/{start_time}" if start_time else "")
        return await self._get(path, {"filter_entity_id": entity_id, "minimal_response": "true"})

    async def services(self):
        return await self._get("/api/services")

    async def call_service_raw(self, domain: str, service: str, data: dict, *, return_response: bool = False):
        params = {"return_response": ""} if return_response else None
        return await self._post(f"/api/services/{domain}/{service}", data, params=params)

    async def call_service(self, domain: str, service: str, data: dict):
        assert_service_allowed(domain, service)
        return await self.call_service_raw(domain, service, data)

    async def notify(self, message: str, title: str = "HassMind", actions: list[dict] | None = None):
        if not settings.ha_notify_service:
            info(logger, "ha_notify_skipped", reason="HA_NOTIFY_SERVICE is empty")
            return {"skipped": True, "reason": "HA_NOTIFY_SERVICE is empty"}
        full = settings.ha_notify_service
        if "." in full:
            domain, service = full.split(".", 1)
        else:
            domain, service = "notify", full
        data: dict[str, Any] = {"message": message, "title": title}
        if actions:
            data["data"] = {"actions": actions}
        return await self.call_service_raw(domain, service, data)

    async def config_get(self, kind: str, target_id: str):
        if kind not in {"automation", "script"}:
            raise ValueError("kind must be automation or script")
        return await self._get(f"/api/config/{kind}/config/{target_id}")

    async def config_set(self, kind: str, target_id: str, config: dict):
        if kind not in {"automation", "script"}:
            raise ValueError("kind must be automation or script")
        return await self._post(f"/api/config/{kind}/config/{target_id}", config)

    def ws_url(self) -> str:
        p = urlparse(self.base)
        scheme = "wss" if p.scheme == "https" else "ws"
        return f"{scheme}://{p.netloc}/api/websocket"

    async def ws_command(self, command: dict) -> Any:
        started = perf_counter()
        command_type = str(command.get("type", "unknown"))
        info(logger, "ha_ws_command_started", command_type=command_type, command=preview(command))
        try:
            async with websockets.connect(self.ws_url(), open_timeout=10, close_timeout=5) as ws:
                hello = json.loads(await ws.recv())
                if hello.get("type") != "auth_required":
                    raise RuntimeError(f"Unexpected HA WS hello: {hello}")
                await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                auth = json.loads(await ws.recv())
                if auth.get("type") != "auth_ok":
                    raise PermissionError(f"HA WebSocket auth failed: {auth}")
                payload = {"id": 1, **command}
                await ws.send(json.dumps(payload))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == 1:
                        if not msg.get("success"):
                            raise RuntimeError(str(msg.get("error")))
                        result = msg.get("result")
                        info(
                            logger,
                            "ha_ws_command_completed",
                            command_type=command_type,
                            duration_ms=round((perf_counter() - started) * 1000, 2),
                            result=preview(result),
                        )
                        return result
        except Exception as exc:
            exception(
                logger,
                "ha_ws_command_failed",
                message="Home Assistant WebSocket command failed",
                command_type=command_type,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                error_type=type(exc).__name__,
            )
            raise

    async def entity_registry(self):
        return await self.ws_command({"type": "config/entity_registry/list"})

    async def listen_events(self, callback: EventCallback, stop: asyncio.Event):
        backoff = 2
        attempt = 0
        while not stop.is_set():
            try:
                attempt += 1
                info(logger, "ha_ws_connecting", attempt=attempt, ws_url=self.ws_url())
                async with websockets.connect(
                    self.ws_url(),
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=30,
                    ping_timeout=20,
                ) as ws:
                    hello = json.loads(await ws.recv())
                    if hello.get("type") != "auth_required":
                        raise RuntimeError(f"Unexpected WS hello: {hello}")
                    await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    auth = json.loads(await ws.recv())
                    if auth.get("type") != "auth_ok":
                        raise PermissionError(f"HA WebSocket auth failed: {auth}")
                    await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                    await ws.send(json.dumps({"id": 2, "type": "subscribe_events", "event_type": "mobile_app_notification_action"}))
                    backoff = 2
                    info(logger, "ha_ws_connected", subscriptions=["state_changed", "mobile_app_notification_action"])
                    while not stop.is_set():
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if msg.get("type") == "event" and msg.get("event"):
                            try:
                                await callback(msg["event"])
                            except Exception:
                                exception(logger, "ha_event_callback_failed", message="HA event callback failed")
            except asyncio.CancelledError:
                info(logger, "ha_ws_cancelled")
                raise
            except Exception as exc:
                if stop.is_set():
                    break
                warning(
                    logger,
                    "ha_ws_disconnected",
                    message="Home Assistant WebSocket disconnected; retrying",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    retry_in_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        info(logger, "ha_ws_stopped")
