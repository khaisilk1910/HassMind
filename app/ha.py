import asyncio
import json
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
import websockets

from .policy import assert_service_allowed
from .settings import settings

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class HomeAssistantClient:
    def __init__(self):
        self.base = settings.ha_url.rstrip("/")
        self.token = settings.read_ha_token()
        self.http = httpx.AsyncClient(
            timeout=20.0,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )

    async def close(self):
        await self.http.aclose()

    async def _get(self, path: str, params: dict | None = None):
        r = await self.http.get(self.base + path, params=params)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, data: dict | None = None, params: dict | None = None):
        r = await self.http.post(self.base + path, json=data or {}, params=params)
        r.raise_for_status()
        if not r.content:
            return {}
        return r.json()

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
                    return msg.get("result")

    async def entity_registry(self):
        return await self.ws_command({"type": "config/entity_registry/list"})

    async def listen_events(self, callback: EventCallback, stop: asyncio.Event):
        backoff = 2
        while not stop.is_set():
            try:
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
                    while not stop.is_set():
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if msg.get("type") == "event" and msg.get("event"):
                            await callback(msg["event"])
            except Exception:
                if stop.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
