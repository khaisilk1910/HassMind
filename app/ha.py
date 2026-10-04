import asyncio
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
import websockets

from .observability import exception, get_logger, info, preview, warning
from .policy import assert_service_allowed
from .settings import settings
from .state_query import normalize_text

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
logger = get_logger("home_assistant")

_SERVICE_TARGET_KEYS = {"entity_id", "device_id", "area_id", "floor_id", "label_id"}
_ENTITY_ID = re.compile(r"(?<![A-Za-z0-9_.])[a-z][a-z0-9_]*\.[a-z0-9_]+(?![A-Za-z0-9_]|\.[A-Za-z0-9_])")
_ENTITY_FIELDS = {"entity_id", "entity_ids", "media_player", "media_player_entity_id", "tts_entity_id"}
_ENTITY_ACTION_DOMAINS = {"light", "switch", "fan", "climate", "media_player", "scene", "script", "homeassistant", "cover", "lock", "alarm_control_panel", "input_boolean", "input_number", "input_select", "number", "select", "button", "tts"}
# Each chat owns its evidence. The shared HA client/runtime must never carry one
# user's entity resolution into another concurrent chat or scheduled agent run.
_KNOWLEDGE_CONTROL: ContextVar[dict | None] = ContextVar("hassmind_knowledge_control", default=None)


@contextmanager
def knowledge_control_context(user_text: str = ""):
    evidence = {
        "explicit_ids": set(_ENTITY_ID.findall(str(user_text or ""))),
        "resolved_ids": set(), "candidate_ids": set(), "blocked_ids": set(),
        "unsafe_resolution": False,
        "user_text": normalize_text(user_text),
        "broad_authorized": bool(re.search(r"\b(all|every|whole|tat ca|toan bo|het|area id|device id|floor id|label id)\b", normalize_text(user_text))),
    }
    token = _KNOWLEDGE_CONTROL.set(evidence)
    try:
        yield evidence
    finally:
        _KNOWLEDGE_CONTROL.reset(token)


def record_knowledge_evidence(result: dict | list[dict], *, resolution: bool = False) -> bool | None:
    evidence = _KNOWLEDGE_CONTROL.get()
    if evidence is None:
        # ToolRuntime also supports callers outside Agent.chat. Those callers can
        # explicitly use knowledge_control_context to bound a multi-tool turn.
        evidence = {"explicit_ids": set(), "resolved_ids": set(), "candidate_ids": set(),
                    "blocked_ids": set(), "unsafe_resolution": False, "broad_authorized": False, "user_text": ""}
        _KNOWLEDGE_CONTROL.set(evidence)
    rows = result.get("candidates", []) if isinstance(result, dict) else result
    ids = {str(row.get("entity_id")) for row in rows if isinstance(row, dict) and row.get("entity_id")}
    for row in rows:
        if isinstance(row, dict):
            # Legacy Markdown/text references can mention IDs without structured
            # metadata. Those mentions are suggestions, never action authority.
            ids.update(_ENTITY_ID.findall(str(row.get("text") or row.get("preview") or "")))
    evidence["candidate_ids"].update(ids)
    if not resolution:
        return
    entity_id = str(result.get("entity_id") or "")
    if entity_id:
        ids.add(entity_id)
    safe = bool(result.get("status") == "resolved" and result.get("safe_for_control")
                and result.get("match_type") in {"entity_id", "alias", "name", "area_domain"}
                and float(result.get("confidence") or 0) >= 0.85)
    if safe and evidence["unsafe_resolution"] and entity_id not in evidence["explicit_ids"]:
        original_query = normalize_text(result.get("query"))
        # A fallback state/registry read can return an ID or canonical name after
        # not_found, even when no first-pass candidates existed to taint. Only a
        # better lookup of the user's literal original phrase can remain safe.
        if result.get("match_type") == "entity_id" or not original_query or original_query not in evidence["user_text"]:
            safe = False
    if safe and entity_id:
        evidence["resolved_ids"].add(entity_id)
    else:
        evidence["blocked_ids"].update(ids)
        evidence["unsafe_resolution"] = True
    return bool(entity_id and (entity_id in evidence["explicit_ids"] or (safe and entity_id not in evidence["blocked_ids"])))


def _target_entity_ids(payload: Any) -> set[str]:
    ids: set[str] = set()
    if not isinstance(payload, dict):
        return ids
    for key, value in payload.items():
        if key in _ENTITY_FIELDS:
            values = value if isinstance(value, (list, tuple)) else [value]
            for item in values:
                if isinstance(item, str):
                    ids.update(part.strip() for part in item.split(",") if part.strip() and part.strip() != "all")
        elif isinstance(value, dict):
            ids.update(_target_entity_ids(value))
        elif isinstance(value, list):
            for item in value:
                ids.update(_target_entity_ids(item))
    return ids


def _has_broad_target(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for key, value in payload.items():
        if key in {"area_id", "device_id", "floor_id", "label_id"} and value:
            return True
        if key in _ENTITY_FIELDS:
            values = value if isinstance(value, (list, tuple)) else [value]
            if any(isinstance(item, str) and "all" in [part.strip() for part in item.split(",")] for item in values):
                return True
        if isinstance(value, dict) and _has_broad_target(value):
            return True
        if isinstance(value, list) and any(_has_broad_target(item) for item in value):
            return True
    return False


def assert_knowledge_target_safe(payload: dict, *, domain: str = "") -> set[str]:
    """Enforce identity evidence at the action boundary, independent of the LLM.

    A model cannot make a fuzzy/ambiguous candidate safe by looking up its copied
    entity_id next. A literal entity_id in the current user's instruction is an
    explicit selection. Broad HA selectors keep their existing policy semantics.
    Returns catalog-derived targets that should be checked against live HA.
    """
    evidence = _KNOWLEDGE_CONTROL.get()
    if evidence is None:
        return set()
    entity_ids = _target_entity_ids(payload)
    broad_target = _has_broad_target(payload)
    action_domain = str(domain or payload.get("domain") or "")
    # Omitting a target can mean "all" for HA entity services. An unsafe lookup
    # must not silently turn into a whole-domain action through an empty target.
    implicit_all = action_domain in _ENTITY_ACTION_DOMAINS and not entity_ids and not broad_target
    if evidence["unsafe_resolution"] and (broad_target or implicit_all) and not evidence["broad_authorized"]:
        raise PermissionError("An ambiguous/fuzzy Knowledge target cannot be replaced by a broad HA selector. Ask the user to select the target.")
    bound: set[str] = set()
    for entity_id in entity_ids:
        if entity_id in evidence["explicit_ids"]:
            continue
        blocked = entity_id in evidence["blocked_ids"]
        unresolved = entity_id in evidence["candidate_ids"] and entity_id not in evidence["resolved_ids"]
        unknown_after_failure = evidence["unsafe_resolution"] and entity_id not in evidence["resolved_ids"]
        if blocked or unresolved or unknown_after_failure:
            raise PermissionError(
                f"Knowledge target '{entity_id}' is ambiguous, fuzzy, or unconfirmed. "
                "Ask the user to select an exact entity_id in a new message before control."
            )
        if entity_id in evidence["resolved_ids"]:
            bound.add(entity_id)
    return bound


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

        catalog_targets = assert_knowledge_target_safe(payload, domain=domain)
        for entity_id in sorted(catalog_targets):
            live = await self.state(entity_id)
            if not isinstance(live, dict) or live.get("entity_id") != entity_id:
                raise PermissionError(f"Knowledge target '{entity_id}' is unresolved in current Home Assistant states")

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
