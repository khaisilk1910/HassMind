from typing import Any

from .approvals import apply_approval, create_approval, get_approval, notify_approval, propose_rollback
from .db import add_memory, recent_events, search_memory
from .event_engine import create_event_rule
from .ha import HomeAssistantClient
from .ha_integrations import HAIntegrationBridge
from .integrations import IntegrationHub
from .mcp_client import call_server_tool, list_server_tools, load_servers
from .rag import search_knowledge
from .scheduler import create_job
from .settings import settings
from .state_query import compact_state, search_states
from .skills import list_skills, read_skill
from .websearch import search_web



def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


def schemas() -> list[dict]:
    tools = [
        _fn("ha_list_entities", "List Home Assistant entities, optionally filtered by domain. Uses the live in-memory state snapshot when available.", {"domain": {"type": "string"}}),
        _fn("ha_search_states", "FAST status lookup: search current Home Assistant states by friendly name/entity_id keywords and optional domains in one live snapshot. Prefer this for room/device status questions instead of many ha_get_state calls.", {
            "query": {"type": "string", "description": "Keywords such as 'phong ngu', 'soc chip', 'dieu hoa'. Accent-insensitive."},
            "domains": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "state": {"type": "string", "description": "Optional exact state filter such as on/off/unavailable."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            "include_attributes": {"type": "boolean"},
        }),
        _fn("ha_get_states", "FAST batch lookup: get many exact entity states from one live snapshot. Prefer this over repeated ha_get_state calls when multiple entity_ids are known.", {
            "entity_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200},
            "include_attributes": {"type": "boolean"},
        }, ["entity_ids"]),
        _fn("ha_get_state", "Get one exact entity state and attributes. For multiple entities use ha_get_states.", {"entity_id": {"type": "string"}}, ["entity_id"]),
        _fn("ha_history", "Get recent Home Assistant history for an entity. start_time may be ISO8601.", {"entity_id": {"type": "string"}, "start_time": {"type": "string"}}, ["entity_id"]),
        _fn("ha_recent_events", "Read recent events captured by HassMind, including Home Assistant and enabled companion webhooks.", {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
        _fn("ha_call_service", "Call a Home Assistant service only if its domain is in the direct-action allowlist.", {"domain": {"type": "string"}, "service": {"type": "string"}, "data": {"type": "object"}}, ["domain", "service", "data"]),
        _fn("ha_entity_registry", "List Home Assistant entity-registry entries; useful for resolving automation/script unique IDs.", {"domain": {"type": "string"}}),
        _fn("ha_get_config", "Read an automation/script config by config ID (not necessarily entity_id).", {"kind": {"type": "string", "enum": ["automation", "script"]}, "target_id": {"type": "string"}}, ["kind", "target_id"]),
        _fn("ha_propose_config_change", "Create a human approval proposal for an automation/script replacement. It does not apply immediately.", {"kind": {"type": "string", "enum": ["automation", "script"]}, "target_id": {"type": "string"}, "new_config": {"type": "object"}, "reason": {"type": "string"}}, ["kind", "target_id", "new_config", "reason"]),
        _fn("ha_get_change", "Read proposal status/diff/audit fields.", {"change_id": {"type": "string"}}, ["change_id"]),
        _fn("ha_apply_approved_change", "Apply a change only when backend status is approved. Normally mobile/web approval auto-applies.", {"change_id": {"type": "string"}}, ["change_id"]),
        _fn("ha_propose_rollback", "Create an approval proposal to roll back an already applied change.", {"change_id": {"type": "string"}, "reason": {"type": "string"}}, ["change_id", "reason"]),
        _fn("memory_add", "Store a non-secret long-term fact useful to future home operations.", {"text": {"type": "string"}, "tags": {"type": "string"}}, ["text"]),
        _fn("memory_search", "Search HassMind long-term facts.", {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
        _fn("knowledge_search", "Search local indexed knowledge files mounted at /knowledge.", {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
        _fn("skill_list", "List installed HassMind operating skills.", {}),
        _fn("skill_read", "Read one installed skill workflow.", {"name": {"type": "string"}}, ["name"]),
        _fn("schedule_propose", "Create a recurring agent job in DISABLED state. Human must enable it in dashboard/API.", {"name": {"type": "string"}, "prompt": {"type": "string"}, "schedule_type": {"type": "string", "enum": ["interval", "daily"]}, "schedule_value": {"type": "string", "description": "interval seconds or daily HH:MM"}, "notify": {"type": "boolean"}}, ["name", "prompt", "schedule_type", "schedule_value"]),
        _fn("event_rule_propose", "Create a Home Assistant state-event agent rule in DISABLED state. Human must enable it in dashboard/API.", {"name": {"type": "string"}, "entity_id": {"type": "string"}, "to_state": {"type": "string"}, "prompt": {"type": "string"}, "cooldown_seconds": {"type": "integer"}, "notify": {"type": "boolean"}}, ["name", "entity_id", "prompt"]),
        _fn("web_search", "Search the web through the optional user-hosted SearXNG instance.", {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"]),
        _fn("mcp_servers", "List configured external MCP servers.", {}),
        _fn("mcp_list_tools", "List tools exposed by an external MCP server.", {"server": {"type": "string"}}, ["server"]),
        _fn("mcp_call", "Call one external MCP tool. External MCP server permissions are configured by the operator.", {"server": {"type": "string"}, "tool": {"type": "string"}, "arguments": {"type": "object"}}, ["server", "tool", "arguments"]),
    ]

    # Companion-container tools are only advertised when their adapter is enabled.
    if any((settings.camera_tts_enabled, settings.facedetect_enabled, settings.zalo_enabled, settings.wyoming_enabled)):
        tools.append(_fn("integrations_status", "Check connectivity/status of enabled HassMind companion-container adapters.", {}))

    if settings.camera_tts_enabled:
        tools.extend([
            _fn("camera_tts_cameras", "List Camera TTS EZVIZ cameras and queue/capability state.", {}),
            _fn("camera_tts_job", "Read Camera TTS EZVIZ async job status by job ID.", {"job_id": {"type": "string"}}, ["job_id"]),
            _fn("camera_tts_say", "Speak Vietnamese text through a configured camera speaker.", {
                "camera": {"type": "string"}, "text": {"type": "string"},
                "queue_mode": {"type": "string", "enum": ["add", "next", "play", "replace"]},
                "voice": {"type": "string"}, "rate": {"type": "string"}, "gain_db": {"type": "number"},
            }, ["camera", "text"]),
            _fn("camera_tts_media", "Play an audio/media URL through a configured camera speaker.", {
                "camera": {"type": "string"}, "url": {"type": "string"},
                "queue_mode": {"type": "string", "enum": ["add", "next", "play", "replace"]}, "title": {"type": "string"},
            }, ["camera", "url"]),
            _fn("camera_tts_ptz", "Move an enabled camera PTZ for a bounded duration.", {
                "camera": {"type": "string"},
                "direction": {"type": "string", "enum": ["left", "right", "up", "down", "up_left", "up_right", "down_left", "down_right", "zoom_in", "zoom_out"]},
                "speed": {"type": "integer", "minimum": 1, "maximum": 100},
                "duration": {"type": "number", "minimum": 0.05, "maximum": 10},
            }, ["camera", "direction"]),
            _fn("camera_tts_stop", "Stop current camera audio and clear its queue.", {"camera": {"type": "string"}}, ["camera"]),
        ])

    if settings.facedetect_enabled:
        tools.extend([
            _fn("facedetect_summary", "Read IRIS FaceDetect summary counters and latest recognition event.", {}),
            _fn("facedetect_events", "Read recent IRIS FaceDetect recognition events with optional filters.", {
                "page": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "event_type": {"type": "string"}, "camera_id": {"type": "string"}, "person_id": {"type": "string"},
            }),
            _fn("facedetect_people", "List people known to IRIS FaceDetect.", {}),
            _fn("facedetect_cameras", "List cameras configured in IRIS FaceDetect.", {}),
        ])

    if settings.zalo_enabled:
        tools.extend([
            _fn("zalo_accounts", "List logged-in Zalo accounts exposed by zalo-bot-server.", {}),
            _fn("zalo_send_message", "Send a Zalo message through a selected logged account. Outbound sending must be enabled by operator policy.", {
                "thread_id": {"type": "string"}, "message": {"type": "string"},
                "thread_type": {"type": "integer", "enum": [0, 1], "description": "0=user, 1=group"},
                "account_selection": {"type": "string"}, "ttl": {"type": "string"},
            }, ["thread_id", "message", "thread_type"]),
        ])

    if settings.ha_custom_integrations_enabled:
        tools.extend([
            _fn("ha_custom_integrations_status", "Check the uploaded Home Assistant custom components HassMind knows how to use.", {}),
            _fn("evn_accounts", "List EVN CSKH Monitor customer accounts available in Home Assistant.", {}),
            _fn("evn_summary", "Read EVN CSKH summary for one customer account.", {"account": {"type": "string"}}, ["account"]),
            _fn("evn_daily", "Read EVN daily consumption data for one customer account.", {"account": {"type": "string"}}, ["account"]),
            _fn("evn_monthly", "Read EVN monthly consumption/billing data for one customer account.", {"account": {"type": "string"}}, ["account"]),
            _fn("lunar_convert_date", "Convert Vietnamese solar/lunar dates using am_lich_viet_nam and return its detailed service response.", {
                "conversion_type": {"type": "string", "enum": ["solar_to_lunar", "lunar_to_solar"]},
                "day": {"type": "integer", "minimum": 1, "maximum": 31},
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "year": {"type": "integer", "minimum": 1800, "maximum": 2199},
            }, ["conversion_type", "day", "month", "year"]),
            _fn("shopping_profiles", "Discover Shopping History config-entry IDs from its Home Assistant sensors.", {}),
            _fn("shopping_list", "Read detailed Shopping History orders through its Home Assistant WebSocket API.", {
                "entry_id": {"type": "string"}, "year": {"type": "integer"},
            }, ["entry_id"]),
            _fn("shopping_add", "Add an order through shopping_history.add_order. Operator must enable mutations.", {
                "entry_id": {"type": "string"}, "name": {"type": "string"}, "place": {"type": "string"}, "category": {"type": "string"},
                "price": {"type": "number", "minimum": 0}, "quantity": {"type": "number", "minimum": 0.000001}, "vat": {"type": "number", "minimum": 0, "maximum": 100},
                "status": {"type": "string"}, "model": {"type": "string"}, "manufacturer": {"type": "string"},
                "warranty_months": {"type": "integer", "minimum": 0}, "purchase_date": {"type": "string"}, "note": {"type": "string"},
            }, ["entry_id", "name", "place", "category", "price", "quantity", "status"]),
            _fn("shopping_edit", "Edit an order through shopping_history.edit_order. Operator must enable mutations.", {
                "entry_id": {"type": "string"}, "order_id": {"type": "integer", "minimum": 1}, "name": {"type": "string"}, "place": {"type": "string"}, "category": {"type": "string"},
                "price": {"type": "number", "minimum": 0}, "quantity": {"type": "number", "minimum": 0.000001}, "vat": {"type": "number", "minimum": 0, "maximum": 100},
                "status": {"type": "string"}, "model": {"type": "string"}, "manufacturer": {"type": "string"},
                "warranty_months": {"type": "integer", "minimum": 0}, "purchase_date": {"type": "string"}, "note": {"type": "string"},
            }, ["entry_id", "order_id", "name", "place", "category", "price", "quantity", "status"]),
            _fn("shopping_delete", "Delete one Shopping History order. Requires both mutation and delete policies enabled.", {
                "entry_id": {"type": "string"}, "order_id": {"type": "integer", "minimum": 1},
            }, ["entry_id", "order_id"]),
            _fn("yt_dlp_search", "Search media via the Home Assistant yt_dlp integration.", {
                "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }, ["query"]),
            _fn("yt_dlp_play", "Play a remote media URL on a Home Assistant media_player using yt_dlp. Operator policy can disable playback.", {
                "url": {"type": "string"}, "media_player": {"type": "string"},
            }, ["url", "media_player"]),
            _fn("yt_dlp_download", "Start a yt_dlp download inside Home Assistant. Operator policy must explicitly enable downloads.", {
                "url": {"type": "string"}, "media_type": {"type": "string", "enum": ["video", "audio"]}, "wait_for_completion": {"type": "boolean"},
            }, ["url"]),
            _fn("yt_dlp_get_job", "Read a yt_dlp download job by its 32-character job ID.", {"job_id": {"type": "string"}}, ["job_id"]),
        ])

    if settings.wyoming_enabled:
        tools.append(_fn("ha_tts_speak", "Speak text through Home Assistant TTS, preferring the Wyoming TTS entity when uniquely identifiable.", {
            "media_player_entity_id": {"type": "string"}, "message": {"type": "string"},
            "tts_entity_id": {"type": "string"}, "language": {"type": "string"}, "options": {"type": "object"},
        }, ["media_player_entity_id", "message"]))

    return tools


class ToolRuntime:
    def __init__(self, ha: HomeAssistantClient, integrations: IntegrationHub | None = None):
        self.ha = ha
        self.integrations = integrations or IntegrationHub()
        self.ha_integrations = HAIntegrationBridge(ha)

    async def call(self, name: str, args: dict) -> Any:
        # Core Home Assistant tools
        if name == "ha_list_entities":
            states = await self.ha.states()
            domain = args.get("domain")
            if domain:
                states = [s for s in states if s.get("entity_id", "").startswith(domain + ".")]
            return [{
                "entity_id": s.get("entity_id"),
                "state": s.get("state"),
                "friendly_name": (s.get("attributes") or {}).get("friendly_name"),
                "last_changed": s.get("last_changed"),
            } for s in states]
        if name == "ha_search_states":
            states = await self.ha.states()
            query = str(args.get("query") or "")
            domains = [str(x).strip() for x in (args.get("domains") or []) if str(x).strip()]
            state_filter = str(args.get("state") or "").strip()
            limit = min(max(int(args.get("limit", 80)), 1), 200)
            include_attributes = bool(args.get("include_attributes", True))
            return search_states(
                states, query=query, domains=domains, state_filter=state_filter,
                limit=limit, include_attributes=include_attributes,
            )
        if name == "ha_get_states":
            requested = [str(x).strip() for x in (args.get("entity_ids") or []) if str(x).strip()]
            if len(requested) > 200:
                requested = requested[:200]
            include_attributes = bool(args.get("include_attributes", True))
            states = await self.ha.states()
            by_id = {str(s.get("entity_id")): s for s in states if isinstance(s, dict) and s.get("entity_id")}
            found = [compact_state(by_id[eid], include_attributes=include_attributes) for eid in requested if eid in by_id]
            missing = [eid for eid in requested if eid not in by_id]
            return {"count": len(found), "states": found, "missing": missing}
        if name == "ha_get_state":
            return await self.ha.state(args["entity_id"])
        if name == "ha_history":
            return await self.ha.history(args["entity_id"], args.get("start_time") or None)
        if name == "ha_recent_events":
            return recent_events(int(args.get("limit", 25)))
        if name == "ha_call_service":
            return await self.ha.call_service(args["domain"], args["service"], args["data"])
        if name == "ha_entity_registry":
            entries = await self.ha.entity_registry()
            domain = args.get("domain")
            if domain:
                entries = [e for e in entries if str(e.get("entity_id", "")).startswith(domain + ".")]
            return entries
        if name == "ha_get_config":
            return await self.ha.config_get(args["kind"], args["target_id"])
        if name == "ha_propose_config_change":
            old = await self.ha.config_get(args["kind"], args["target_id"])
            approval = create_approval(args["kind"], args["target_id"], old, args["new_config"], args["reason"])
            await notify_approval(self.ha, approval, args["reason"])
            return {"id": approval["id"], "status": "pending", "risk": approval["risk"], "diff": approval["diff"], "message": "Approval notification sent"}
        if name == "ha_get_change":
            return get_approval(args["change_id"]) or {"error": "not found"}
        if name == "ha_apply_approved_change":
            return await apply_approval(self.ha, args["change_id"])
        if name == "ha_propose_rollback":
            return await propose_rollback(self.ha, args["change_id"], args["reason"])

        # Local memory/knowledge/automation helpers
        if name == "memory_add":
            return {"id": add_memory(args["text"], args.get("tags", ""))}
        if name == "memory_search":
            return search_memory(args["query"], int(args.get("limit", 10)))
        if name == "knowledge_search":
            return search_knowledge(args["query"], int(args.get("limit", 8)))
        if name == "skill_list":
            return list_skills()
        if name == "skill_read":
            return read_skill(args["name"])
        if name == "schedule_propose":
            return create_job(args["name"], args["prompt"], args["schedule_type"], args["schedule_value"], bool(args.get("notify", True)))
        if name == "event_rule_propose":
            return create_event_rule(args["name"], args["entity_id"], args.get("to_state") or None, args["prompt"], int(args.get("cooldown_seconds", 300)), bool(args.get("notify", True)))
        if name == "web_search":
            return await search_web(args["query"], int(args.get("limit", 5)))
        if name == "mcp_servers":
            return list(load_servers().keys())
        if name == "mcp_list_tools":
            return await list_server_tools(args["server"])
        if name == "mcp_call":
            return await call_server_tool(args["server"], args["tool"], args["arguments"])

        # Companion containers
        if name == "integrations_status":
            return await self.integrations.status()
        if name.startswith("camera_tts_"):
            client = self.integrations.camera_tts
            if client is None:
                raise RuntimeError("Camera TTS integration is disabled")
            if name not in {"camera_tts_cameras", "camera_tts_job"} and not settings.camera_tts_allow_actions:
                raise PermissionError("Camera TTS actions are disabled by CAMERA_TTS_ALLOW_ACTIONS")
            if name == "camera_tts_cameras":
                return await client.cameras()
            if name == "camera_tts_job":
                return await client.job(args["job_id"])
            if name == "camera_tts_say":
                return await client.say(
                    args["camera"], args["text"],
                    queue_mode=args.get("queue_mode") or "add",
                    voice=args.get("voice") or None,
                    rate=args.get("rate") or None,
                    gain_db=args.get("gain_db"),
                )
            if name == "camera_tts_media":
                return await client.media(args["camera"], args["url"], queue_mode=args.get("queue_mode") or "replace", title=args.get("title") or "")
            if name == "camera_tts_ptz":
                return await client.ptz(args["camera"], args["direction"], speed=int(args.get("speed", 50)), duration=float(args.get("duration", 0.35)))
            if name == "camera_tts_stop":
                return await client.stop(args["camera"])

        if name.startswith("facedetect_"):
            client = self.integrations.facedetect
            if client is None:
                raise RuntimeError("FaceDetect integration is disabled")
            if name == "facedetect_summary":
                return await client.summary()
            if name == "facedetect_events":
                return await client.events(
                    page=int(args.get("page", 1)), limit=int(args.get("limit", 20)),
                    event_type=args.get("event_type") or "", camera_id=args.get("camera_id") or "", person_id=args.get("person_id") or "",
                )
            if name == "facedetect_people":
                return await client.people()
            if name == "facedetect_cameras":
                return await client.cameras()

        if name.startswith("zalo_"):
            client = self.integrations.zalo
            if client is None:
                raise RuntimeError("Zalo integration is disabled")
            if name == "zalo_accounts":
                return await client.accounts()
            if name == "zalo_send_message":
                if not settings.zalo_allow_send:
                    raise PermissionError("Zalo sending is disabled by ZALO_ALLOW_SEND")
                return await client.send_message(
                    thread_id=args["thread_id"], message=args["message"], thread_type=int(args["thread_type"]),
                    account_selection=args.get("account_selection") or settings.zalo_default_account,
                    ttl=args.get("ttl") or None,
                )

        # Home Assistant custom components
        if name == "ha_custom_integrations_status":
            return await self.ha_integrations.status()
        if name == "evn_accounts":
            return await self.ha_integrations.evn_accounts()
        if name == "evn_summary":
            return await self.ha_integrations.evn_summary(args["account"])
        if name == "evn_daily":
            return await self.ha_integrations.evn_daily(args["account"])
        if name == "evn_monthly":
            return await self.ha_integrations.evn_monthly(args["account"])
        if name == "lunar_convert_date":
            return await self.ha_integrations.lunar_convert(args["conversion_type"], int(args["day"]), int(args["month"]), int(args["year"]))
        if name == "shopping_profiles":
            return await self.ha_integrations.shopping_profiles()
        if name == "shopping_list":
            return await self.ha_integrations.shopping_data(args["entry_id"], int(args["year"]) if args.get("year") is not None else None)
        if name == "shopping_add":
            return await self.ha_integrations.shopping_add(args)
        if name == "shopping_edit":
            return await self.ha_integrations.shopping_edit(args)
        if name == "shopping_delete":
            return await self.ha_integrations.shopping_delete(args["entry_id"], int(args["order_id"]))
        if name == "yt_dlp_search":
            return await self.ha_integrations.ytdlp_search(args["query"], int(args.get("limit", 10)))
        if name == "yt_dlp_play":
            return await self.ha_integrations.ytdlp_play(args["url"], args["media_player"])
        if name == "yt_dlp_download":
            return await self.ha_integrations.ytdlp_download(args["url"], args.get("media_type") or "video", bool(args.get("wait_for_completion", False)))
        if name == "yt_dlp_get_job":
            return await self.ha_integrations.ytdlp_job(args["job_id"])
        if name == "ha_tts_speak":
            return await self.ha_integrations.tts_speak(
                args["media_player_entity_id"], args["message"], args.get("tts_entity_id") or "", args.get("language") or "", args.get("options") or None
            )

        raise KeyError(f"Unknown tool: {name}")
