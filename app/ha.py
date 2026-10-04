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

_SERVICE_TARGET_KEYS = {"entity_id", "device_id", "area_id", "floor_id", "label_id"}


class HomeAssistantClient:
    def __init__(self):
        self.base = settings.ha_url.rstrip("/")
        self.token = settings.read_ha_token()
        self.http = httpx.AsyncClient(
            timeout=20.0,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        self._state_cache: dict[str, dict[str, Any]] = {}
        self._state_cache_at = 0.0
        self._state_cache_complete = False
        self._event_stream_live = False
        self._state_cache_lock = asyncio.Lock()
        info(logger, "ha_client_initialized", base_url=self.base, state_cache_ttl=settings.ha_state_cache_ttl)

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

    def _state_cache_fresh(self) -> bool:
        if not self._state_cache_complete:
            return False
        if self._event_stream_live:
            return True
        ttl = max(0.0, float(settings.ha_state_cache_ttl))
        return ttl > 0 and (perf_counter() - self._state_cache_at) <= ttl

    def _cache_state(self, state: dict[str, Any] | None, entity_id: str = "") -> None:
        eid = str((state or {}).get("entity_id") or entity_id or "").strip()
        if not eid or not self._state_cache_complete:
            return
        if state is None:
            self._state_cache.pop(eid, None)
        else:
            self._state_cache[eid] = state
        self._state_cache_at = perf_counter()

    def invalidate_state_cache(self) -> None:
        self._state_cache.clear()
        self._state_cache_complete = False
        self._state_cache_at = 0.0

    async def refresh_states(self) -> list[dict[str, Any]]:
        data = await self._get("/api/states")
        cache = {
            str(item.get("entity_id")): item
            for item in data
            if isinstance(item, dict) and item.get("entity_id")
        }
        self._state_cache = cache
        self._state_cache_complete = True
        self._state_cache_at = perf_counter()
        info(logger, "ha_state_cache_refreshed", entities=len(cache), event_stream_live=self._event_stream_live)
        return list(cache.values())

    async def states(self, *, fresh: bool = False):
        if not fresh and self._state_cache_fresh():
            return list(self._state_cache.values())
        async with self._state_cache_lock:
            if not fresh and self._state_cache_fresh():
                return list(self._state_cache.values())
            return await self.refresh_states()

    async def state(self, entity_id: str):
        entity_id = str(entity_id).strip()
        if self._state_cache_fresh() and entity_id in self._state_cache:
            return self._state_cache[entity_id]
        result = await self._get(f"/api/states/{entity_id}")
        if self._state_cache_complete and isinstance(result, dict):
            self._state_cache[entity_id] = result
            self._state_cache_at = perf_counter()
        return result

    async def history(self, entity_id: str, start_time: str | None = None):
        path = "/api/history/period" + (f"/{start_time}" if start_time else "")
        return await self._get(path, {"filter_entity_id": entity_id, "minimal_response": "true"})

    async def services(self):
        return await self._get("/api/services")

    @staticmethod
    def _normalize_target(target: dict[str, Any] | None) -> dict[str, Any]:
        if not target:
            return {}
        if not isinstance(target, dict):
            raise ValueError("Home Assistant service target must be an object")
        unknown = set(target) - _SERVICE_TARGET_KEYS
        if unknown:
            raise ValueError(f"Unsupported Home Assistant target keys: {', '.join(sorted(unknown))}")
        return {key: value for key, value in target.items() if value not in (None, "", [])}

    async def call_service_raw(
        self,
        domain: str,
        service: str,
        data: dict | None = None,
        *,
        target: dict[str, Any] | None = None,
        return_response: bool = False,
    ):
        """Call a Home Assistant action through the REST services endpoint.

        Home Assistant's YAML/UI action model separates ``target`` from ``data``.
        The REST endpoint accepts target selectors (entity_id/device_id/area_id/...)
        at the top level of the JSON service payload, so HassMind keeps the public
        action shape explicit and flattens it only at the transport boundary.
        """
        domain = str(domain or "").strip()
        service = str(service or "").strip()
        if not domain or not service:
            raise ValueError("Home Assistant service domain and service are required")
        if not isinstance(data or {}, dict):
            raise ValueError("Home Assistant service data must be an object")

        payload = dict(data or {})
        clean_target = self._normalize_target(target)
        for key, value in clean_target.items():
            if key in payload and payload[key] != value:
                raise ValueError(f"Conflicting Home Assistant target field: {key}")
            payload[key] = value

        params = {"return_response": ""} if return_response else None
        result = await self._post(f"/api/services/{domain}/{service}", payload, params=params)
        # Avoid returning a pre-action snapshot if a follow-up status check happens
        # before Home Assistant's state_changed event reaches our WebSocket listener.
        self.invalidate_state_cache()
        return result

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict | None = None,
        *,
        target: dict[str, Any] | None = None,
    ):
        assert_service_allowed(domain, service)
        return await self.call_service_raw(domain, service, data, target=target)

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

    def _ws_max_size(self) -> int:
        # websockets defaults to 1 MiB, which is too small for entity_registry/list
        # on medium/large Home Assistant installations. Keep a bounded ceiling.
        configured = int(settings.ha_ws_max_size)
        return min(max(configured, 1024 * 1024), 64 * 1024 * 1024)

    async def ws_command(self, command: dict) -> Any:
        started = perf_counter()
        command_type = str(command.get("type", "unknown"))
        info(logger, "ha_ws_command_started", command_type=command_type, command=preview(command))
        try:
            async with websockets.connect(self.ws_url(), open_timeout=10, close_timeout=5, max_size=self._ws_max_size()) as ws:
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
                    max_size=self._ws_max_size(),
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

                    # Events can interleave with subscription acknowledgements. Buffer them
                    # until the complete REST snapshot is loaded, then apply them in order.
                    pending_events: list[dict[str, Any]] = []
                    acknowledged: set[int] = set()
                    while acknowledged != {1, 2}:
                        handshake_msg = json.loads(await ws.recv())
                        if handshake_msg.get("type") == "result" and handshake_msg.get("id") in {1, 2}:
                            if not handshake_msg.get("success"):
                                raise RuntimeError(f"HA event subscription failed: {handshake_msg}")
                            acknowledged.add(int(handshake_msg["id"]))
                        elif handshake_msg.get("type") == "event" and isinstance(handshake_msg.get("event"), dict):
                            pending_events.append(handshake_msg["event"])

                    self._event_stream_live = False
                    try:
                        await self.refresh_states()
                    except Exception:
                        self.invalidate_state_cache()
                        warning(logger, "ha_state_cache_warm_failed", message="Unable to warm HA state cache; REST fallback remains available")
                    self._event_stream_live = True

                    async def _consume_event(event: dict[str, Any]) -> None:
                        if event.get("event_type") == "state_changed":
                            data = event.get("data") or {}
                            if isinstance(data, dict):
                                self._cache_state(data.get("new_state"), str(data.get("entity_id") or ""))
                        try:
                            await callback(event)
                        except Exception:
                            exception(logger, "ha_event_callback_failed", message="HA event callback failed")

                    for buffered_event in pending_events:
                        await _consume_event(buffered_event)

                    backoff = 2
                    info(
                        logger,
                        "ha_ws_connected",
                        subscriptions=["state_changed", "mobile_app_notification_action"],
                        buffered_events=len(pending_events),
                    )
                    while not stop.is_set():
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if msg.get("type") == "event" and isinstance(msg.get("event"), dict):
                            await _consume_event(msg["event"])
            except asyncio.CancelledError:
                self._event_stream_live = False
                info(logger, "ha_ws_cancelled")
                raise
            except Exception as exc:
                self._event_stream_live = False
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
