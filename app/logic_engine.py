from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from .db import add_message, add_tool_audit, replace_last_assistant_message
from .error_memory import record_failure, record_success, recent_issue_for_operation
from .notifications import NO_NOTIFY_TOKEN
from .observability import exception, get_logger, info
from .policy import assert_service_allowed
from .settings import settings
from .state_query import normalize_text
from .time_utils import now as local_now, parse_datetime

logger = get_logger("logic_engine")

_ENTITY_RE = re.compile(r"\b[a-z_][a-z0-9_]*\.[a-z0-9_]+\b", re.IGNORECASE)
_PROFILE_RE = re.compile(r"(?:^|\n)\s*@logic-profile\s+([a-z0-9_-]{1,80})\b", re.IGNORECASE)
_COMPLEX_WORDS = (
    "neu", "khi ", "chi khi", "dong thoi", "hien dien", "presence", "occupancy",
    "neu nhu", "tru khi", "sau khi", "kiem tra tat ca", "tung phong", "khu vuc",
)
_QUERY_WORDS = (
    "trang thai", "hien tai", "dang ", "bao nhieu", "nhiet do", "do am", "status", "state",
    "co bat", "co tat", "on hay off", "bat hay tat", "kiem tra", "xem",
)

_HA_INTENT_WORDS = (
    "home assistant", "hass", "phong", "bep", "den", "quat", "dieu hoa", "climate",
    "sensor", "switch", "light", "fan", "media player", "remote", "presence", "hien dien",
    "trang thai", "nhiet do", "do am", "bat", "tat", "kiem tra", "xem",
)
_MODEL_REFUSAL_MARKERS = (
    "mo hinh ngon ngu", "nam ngoai kha nang", "khong duoc thiet ke de tro giup",
    "khong the giup ban viec do", "khong the ho tro giup ve dieu do",
    "chi co the tao van ban", "khong co kha nang hieu cung nhu tra loi yeu cau",
)

_LEGACY_JOB3_TV_IDS = {
    "media_player.xiaomi_tv_box_2",
    "remote.xiaomi_tv_box",
    "remote.box_phong_bep",
    "media_player.box_phong_bep_2",
    "remote.box_phong_khach",
    "media_player.box_phong_khach_2",
}
_POLITE_PREFIX = re.compile(r"^\s*(?:(?:hay|vui long|giup toi|giup minh|lam on)\s+)*", re.IGNORECASE)


@dataclass
class LogicDecision:
    handled: bool
    text: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    engine: str = "logic"


class LogicProfileStore:
    def __init__(self) -> None:
        self.builtin_dir = Path(settings.logic_profiles_dir)
        self.user_dir = Path(settings.user_logic_profiles_dir)

    @staticmethod
    def _safe_name(name: str) -> str:
        value = str(name or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,80}", value):
            raise ValueError("Invalid logic profile name")
        return value

    def load(self, name: str) -> dict[str, Any]:
        safe = self._safe_name(name)
        candidates = [self.user_dir / f"{safe}.json", self.builtin_dir / f"{safe}.json"]
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"Logic profile {safe} must be a JSON object")
            payload.setdefault("name", safe)
            return payload
        raise FileNotFoundError(f"Logic profile not found: {safe}")


class LogicEngine:
    """Deterministic fast path for Home Assistant operations.

    The engine deliberately handles only requests with strong structural evidence.
    Anything semantic, ambiguous or open-ended falls through to the AI agent.
    """

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.ha = runtime.ha
        self.profiles = LogicProfileStore()
        self._registry_cache: dict[str, Any] | None = None
        self._registry_cache_at = 0.0

    @staticmethod
    def _entity_ids(text: str) -> list[str]:
        out: list[str] = []
        for value in _ENTITY_RE.findall(str(text or "")):
            eid = value.lower()
            if eid not in out:
                out.append(eid)
        return out

    @staticmethod
    def _domain(entity_id: str) -> str:
        return entity_id.split(".", 1)[0].lower() if "." in entity_id else ""

    @staticmethod
    def _core_text(text: str) -> str:
        base = str(text or "").split("\n\n---\n[HassMind", 1)[0]
        base = base.split("\n\nEvent context:", 1)[0]
        return base.strip()

    @staticmethod
    def _normalized_without_runtime_protocol(text: str) -> str:
        return normalize_text(LogicEngine._core_text(text))

    @staticmethod
    def _is_complex(text: str) -> bool:
        normalized = LogicEngine._normalized_without_runtime_protocol(text)
        return any(word in normalized for word in _COMPLEX_WORDS)

    @staticmethod
    def _imperative_action(text: str) -> str | None:
        # Only accept a clear command at the start. Questions such as
        # "đang bật hay tắt?" must never be interpreted as side effects.
        raw = str(text or "").strip()
        normalized = normalize_text(raw)
        normalized = _POLITE_PREFIX.sub("", normalized).strip()
        off = bool(re.match(r"^(?:tat|turn off)\b", normalized))
        on = bool(re.match(r"^(?:bat|turn on)\b", normalized))
        if off == on:
            return None
        # Mixed commands require semantic planning; let AI handle them.
        action_terms = len(re.findall(r"\b(?:bat|tat|turn on|turn off)\b", normalized))
        if action_terms != 1:
            return None
        return "turn_off" if off else "turn_on"

    @staticmethod
    def _looks_like_state_query(text: str) -> bool:
        normalized = LogicEngine._normalized_without_runtime_protocol(text)
        if any(word in normalized for word in _QUERY_WORDS):
            return True
        return "?" in str(text or "")

    async def _resolve_named_entities(self, text: str) -> tuple[list[str], str | None]:
        """Resolve exact friendly names from the live HA snapshot without AI.

        Only literal normalized friendly-name spans are accepted. Short/generic names are
        intentionally ignored. If the same visible name maps to multiple entities, return
        a deterministic clarification instead of guessing.
        """
        normalized = normalize_text(text)
        if not normalized:
            return [], None
        states = await self.ha.states()
        matches: dict[str, list[tuple[str, str]]] = {}
        padded = f" {normalized} "
        for item in states:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("entity_id") or "").lower()
            attrs = item.get("attributes") or {}
            friendly = str(attrs.get("friendly_name") or "").strip()
            if not eid or not friendly:
                continue
            norm_name = normalize_text(friendly)
            # Avoid generic one-word matches such as "den" or "quat".
            if len(norm_name) < 5 or (" " not in norm_name and len(norm_name) < 7):
                continue
            if f" {norm_name} " in padded:
                matches.setdefault(norm_name, []).append((eid, friendly))
        if not matches:
            return [], None

        # Prefer the most specific literal names: if "den phong khach" matched,
        # discard a shorter "phong khach" match contained inside it.
        specific_names = [
            name for name in matches
            if not any(name != other and f" {name} " in f" {other} " for other in matches)
        ]
        ambiguous: list[tuple[str, list[tuple[str, str]]]] = []
        resolved: list[str] = []
        for name in sorted(specific_names, key=len, reverse=True):
            values = matches[name]
            entity_ids = sorted({eid for eid, _ in values})
            if len(entity_ids) > 1:
                ambiguous.append((name, values))
                continue
            if entity_ids[0] not in resolved:
                resolved.append(entity_ids[0])

        if ambiguous:
            lines = ["❓ Tôi tìm thấy nhiều entity có cùng tên. Hãy chọn đúng entity:"]
            shown = 0
            for _, values in ambiguous:
                for eid, friendly in values:
                    lines.append(f"- **{friendly}** — `{eid}`")
                    shown += 1
                    if shown >= 8:
                        break
                if shown >= 8:
                    break
            return [], "\n".join(lines)
        return resolved, None

    @staticmethod
    def _looks_like_legacy_bedroom_climate(text: str, *, source: str) -> bool:
        # Explicitly naming this operator-confirmed skill/profile is strong enough
        # evidence to use the deterministic implementation in chat as well as Scheduler.
        core = LogicEngine._core_text(text).lower()
        return "bedroom-climate-comfort" in core

    @staticmethod
    def _looks_like_home_assistant_intent(text: str) -> bool:
        normalized = LogicEngine._normalized_without_runtime_protocol(text)
        return any(word in normalized for word in _HA_INTENT_WORDS)

    @staticmethod
    def is_model_refusal(text: str) -> bool:
        normalized = normalize_text(text)
        return any(marker in normalized for marker in _MODEL_REFUSAL_MARKERS)

    @staticmethod
    def _requested_rooms(text: str) -> list[str]:
        normalized = LogicEngine._normalized_without_runtime_protocol(text)
        aliases = [
            ("Phòng Sóc Chíp", ("phong soc chip", "soc chip")),
            ("Phòng khách", ("phong khach",)),
            ("Phòng ngủ", ("phong ngu",)),
            ("Bếp", ("nha bep", "phong bep", "bep")),
        ]
        out: list[str] = []
        padded = f" {normalized} "
        for canonical, names in aliases:
            if any(f" {name} " in padded for name in names):
                out.append(canonical)
        return out

    async def _room_status_report(self, room_names: list[str]) -> LogicDecision:
        """Report operator-confirmed room signals without invoking the LLM.

        This is deliberately conservative: it uses only fixed mappings from logic
        profiles, so a short request such as "xem trạng thái phòng ngủ" remains
        useful even when the configured LLM refuses or does not support tools.
        """
        mapped: dict[str, dict[str, Any]] = {}
        try:
            climate_profile = self.profiles.load("bedroom-climate-comfort")
        except Exception:
            climate_profile = {}
        for room in climate_profile.get("rooms") or []:
            if not isinstance(room, dict):
                continue
            name = str(room.get("name") or "").strip()
            if not name:
                continue
            entry = mapped.setdefault(name, {})
            for key in ("temperature", "humidity", "presence", "climate"):
                value = str(room.get(key) or "").strip().lower()
                if value:
                    entry[key] = value
            fan = room.get("fan") or {}
            if isinstance(fan, dict):
                entry["fan"] = fan

        try:
            vacancy_profile = self.profiles.load("job3-vacancy-shutdown")
        except Exception:
            vacancy_profile = {}
        for area in vacancy_profile.get("areas") or []:
            if not isinstance(area, dict):
                continue
            name = str(area.get("name") or "").strip()
            if not name:
                continue
            entry = mapped.setdefault(name, {})
            presence = str(area.get("presence") or "").strip().lower()
            if presence:
                entry.setdefault("presence", presence)
            tv = [str(x).strip().lower() for x in (area.get("tv") or []) if str(x).strip()]
            if tv:
                entry["tv"] = tv

        selected = [(name, mapped.get(name) or {}) for name in room_names]
        entity_ids: list[str] = []
        for _name, entry in selected:
            for key in ("temperature", "humidity", "presence", "climate"):
                eid = str(entry.get(key) or "")
                if eid and eid not in entity_ids:
                    entity_ids.append(eid)
            fan = entry.get("fan") or {}
            if isinstance(fan, dict):
                for key in ("power", "entity"):
                    eid = str(fan.get(key) or "").lower()
                    if eid and eid not in entity_ids:
                        entity_ids.append(eid)
            for eid in entry.get("tv") or []:
                if eid not in entity_ids:
                    entity_ids.append(eid)

        if not entity_ids:
            return LogicDecision(False, reason="room_mapping_unavailable")

        states = await self.ha.states()
        by_id = {str(item.get("entity_id") or "").lower(): item for item in states if isinstance(item, dict)}
        trace = [{
            "tool": "ha_get_states", "round": 0, "status": "ok", "read_only": True,
            "side_effect": False, "arguments": {"entity_ids": entity_ids, "include_attributes": True, "engine": "logic-room"},
        }]
        add_tool_audit("ha_get_states", {"entity_ids": entity_ids, "include_attributes": True}, result={"engine": "logic-room", "count": sum(1 for eid in entity_ids if eid in by_id)})

        blocks: list[str] = []
        for room_name, entry in selected:
            if not entry:
                continue
            lines = [f"### 🏠 {room_name}"]

            presence_eid = str(entry.get("presence") or "")
            if presence_eid:
                item = by_id.get(presence_eid)
                state = str((item or {}).get("state") or "unknown").lower()
                label = "Có người" if state == "on" else ("Không có người" if state == "off" else state)
                lines.append(f"- **Hiện diện:** {label}")

            temp_eid = str(entry.get("temperature") or "")
            hum_eid = str(entry.get("humidity") or "")
            if temp_eid:
                item = by_id.get(temp_eid)
                state = str((item or {}).get("state") or "unknown")
                unit = str(((item or {}).get("attributes") or {}).get("unit_of_measurement") or "°C")
                lines.append(f"- **Nhiệt độ:** {state}{unit if state not in {'unknown','unavailable'} else ''}")
            if hum_eid:
                item = by_id.get(hum_eid)
                state = str((item or {}).get("state") or "unknown")
                unit = str(((item or {}).get("attributes") or {}).get("unit_of_measurement") or "%")
                lines.append(f"- **Độ ẩm:** {state}{unit if state not in {'unknown','unavailable'} else ''}")

            climate_eid = str(entry.get("climate") or "")
            if climate_eid:
                item = by_id.get(climate_eid) or {}
                state = str(item.get("state") or "unknown").lower()
                attrs = item.get("attributes") or {}
                target = attrs.get("temperature")
                hvac_action = str(attrs.get("hvac_action") or "").lower()
                detail = state
                if state != "off" and target is not None:
                    detail += f" · target {target}°C"
                if hvac_action and hvac_action not in {"off", ""}:
                    detail += f" · {hvac_action}"
                lines.append(f"- **Điều hòa:** {detail}")

            fan = entry.get("fan") or {}
            if isinstance(fan, dict) and fan:
                power_eid = str(fan.get("power") or "").lower()
                fan_eid = str(fan.get("entity") or "").lower()
                if power_eid:
                    power_state = str((by_id.get(power_eid) or {}).get("state") or "unknown").lower()
                    fan_text = power_state
                    if fan_eid:
                        attrs = (by_id.get(fan_eid) or {}).get("attributes") or {}
                        preset = attrs.get("preset_mode")
                        if preset:
                            fan_text += f" · {preset}"
                    lines.append(f"- **Quạt:** {fan_text}")

            tv_ids = list(entry.get("tv") or [])
            if tv_ids:
                tv_values = []
                for eid in tv_ids:
                    item = by_id.get(eid) or {}
                    tv_values.append(f"{eid.split('.',1)[0]}={str(item.get('state') or 'unknown')}")
                lines.append("- **TV:** " + " · ".join(tv_values))

            blocks.append("\n".join(lines))

        if not blocks:
            return LogicDecision(False, reason="room_mapping_unavailable")
        return LogicDecision(True, "## 📊 Trạng thái realtime\n\n" + "\n\n".join(blocks), trace, reason="mapped_room_status")

    @staticmethod
    def _looks_like_legacy_job3(text: str, *, source: str) -> bool:
        if source != "system":
            return False
        core = LogicEngine._core_text(text)
        if not _LEGACY_JOB3_TV_IDS.issubset(set(LogicEngine._entity_ids(core))):
            return False
        normalized = normalize_text(core)
        return (
            "den" in normalized
            and "quat" in normalized
            and "tat" in normalized
            and ("hien dien" in normalized or "presence" in normalized or "occupancy" in normalized)
        )

    async def try_handle(self, text: str, *, source: str = "web") -> LogicDecision:
        if not settings.logic_first_enabled:
            return LogicDecision(False, reason="logic_first_disabled")
        started = perf_counter()
        profile_match = _PROFILE_RE.search(str(text or ""))
        if profile_match:
            name = profile_match.group(1).lower()
            try:
                profile = self.profiles.load(name)
                result = await self._execute_profile(profile, source=source)
                info(logger, "logic_profile_completed", profile=name, handled=result.handled, duration_ms=round((perf_counter()-started)*1000, 2))
                return result
            except Exception as exc:
                exception(logger, "logic_profile_failed", profile=name, error_type=type(exc).__name__)
                return LogicDecision(
                    True,
                    text=f"⚠️ Logic profile `{name}` lỗi: {type(exc).__name__}: {exc}",
                    trace=[{"tool": "logic_profile", "status": "error", "read_only": True, "side_effect": False, "arguments": {"profile": name}, "error": f"{type(exc).__name__}: {exc}"}],
                    reason="logic_profile_error",
                )

        if self._looks_like_legacy_job3(text, source=source):
            try:
                profile = self.profiles.load("job3-vacancy-shutdown")
                result = await self._execute_profile(profile, source=source)
                result.reason = "legacy_job3_auto_profile"
                info(logger, "logic_legacy_job3_routed", duration_ms=round((perf_counter()-started)*1000, 2))
                return result
            except Exception as exc:
                exception(logger, "logic_legacy_job3_failed", error_type=type(exc).__name__)
                return LogicDecision(False, reason="legacy_job3_profile_unavailable")

        if self._looks_like_legacy_bedroom_climate(text, source=source):
            try:
                profile = self.profiles.load("bedroom-climate-comfort")
                result = await self._execute_profile(profile, source=source)
                result.reason = "legacy_bedroom_climate_auto_profile"
                info(logger, "logic_legacy_bedroom_climate_routed", duration_ms=round((perf_counter()-started)*1000, 2))
                return result
            except Exception as exc:
                exception(logger, "logic_legacy_bedroom_climate_failed", error_type=type(exc).__name__)
                return LogicDecision(False, reason="legacy_bedroom_climate_profile_unavailable")

        core_text = self._core_text(text)
        action = self._imperative_action(core_text)
        state_query = self._looks_like_state_query(core_text)

        # A room status request can be answered from operator-confirmed profile
        # mappings with one HA snapshot. Do this before the broad "complex" gate.
        requested_rooms = self._requested_rooms(core_text)
        if state_query and not action and requested_rooms:
            room_result = await self._room_status_report(requested_rooms)
            if room_result.handled:
                info(logger, "logic_room_status_completed", rooms=requested_rooms, duration_ms=round((perf_counter()-started)*1000, 2))
                return room_result

        if self._is_complex(core_text):
            return LogicDecision(False, reason="semantic_or_complex")
        entity_ids = self._entity_ids(core_text)
        if not entity_ids and (action or state_query):
            entity_ids, clarification = await self._resolve_named_entities(core_text)
            if clarification:
                return LogicDecision(True, clarification, reason="ambiguous_friendly_name")
        if not entity_ids:
            return LogicDecision(False, reason="no_exact_entity")

        if action:
            result = await self._direct_control(entity_ids, action, source=source)
            if result.handled:
                info(logger, "logic_direct_control_completed", entity_count=len(entity_ids), action=action, duration_ms=round((perf_counter()-started)*1000, 2))
                return result

        if state_query:
            result = await self._exact_state_query(entity_ids)
            info(logger, "logic_state_query_completed", entity_count=len(entity_ids), duration_ms=round((perf_counter()-started)*1000, 2))
            return result

        return LogicDecision(False, reason="semantic_or_complex")

    async def _exact_state_query(self, entity_ids: list[str]) -> LogicDecision:
        states = await self.ha.states()
        by_id = {str(item.get("entity_id") or ""): item for item in states if isinstance(item, dict)}
        found = [by_id[eid] for eid in entity_ids if eid in by_id]
        missing = [eid for eid in entity_ids if eid not in by_id]
        trace = [{
            "tool": "ha_get_states", "round": 0, "status": "ok", "read_only": True, "side_effect": False,
            "arguments": {"entity_ids": entity_ids, "include_attributes": True},
        }]
        add_tool_audit("ha_get_states", {"entity_ids": entity_ids, "include_attributes": True}, result={"count": len(found), "missing": missing, "engine": "logic"})
        lines = ["## 🏠 Trạng thái Home Assistant"]
        for item in found:
            lines.extend(self._format_state_lines(item))
        for eid in missing:
            lines.append(f"- ⚠️ `{eid}`: không tìm thấy trong state hiện tại")
        return LogicDecision(True, "\n".join(lines), trace, reason="exact_state_query")

    @staticmethod
    def _format_state_lines(item: dict[str, Any]) -> list[str]:
        attrs = item.get("attributes") or {}
        eid = str(item.get("entity_id") or "")
        name = str(attrs.get("friendly_name") or eid)
        state = str(item.get("state") or "unknown")
        status = f"**{name}:** `{state}`"
        details: list[str] = []
        units = attrs.get("unit_of_measurement")
        if units and state not in {"unknown", "unavailable"}:
            status = f"**{name}:** {state} {units}"
        for key, label in (
            ("current_temperature", "Nhiệt độ hiện tại"),
            ("temperature", "Mục tiêu"),
            ("humidity", "Độ ẩm"),
            ("percentage", "Mức quạt"),
            ("preset_mode", "Preset"),
            ("hvac_action", "HVAC"),
            ("battery", "Pin"),
            ("battery_level", "Pin"),
        ):
            if key in attrs and attrs.get(key) not in (None, ""):
                value = attrs.get(key)
                suffix = "%" if key in {"humidity", "percentage", "battery", "battery_level"} and isinstance(value, (int, float)) else ""
                if key in {"current_temperature", "temperature"} and isinstance(value, (int, float)):
                    suffix = "°C"
                details.append(f"{label}: {value}{suffix}")
        if details:
            return [f"- {status}", "  - " + " · ".join(details[:4])]
        return [f"- {status}"]

    async def _direct_control(self, entity_ids: list[str], action: str, *, source: str) -> LogicDecision:
        supported: dict[str, list[str]] = {}
        unsupported: list[str] = []
        for eid in entity_ids:
            domain = self._domain(eid)
            if action == "turn_off" and domain in {"light", "fan", "switch", "media_player", "input_boolean", "climate"}:
                supported.setdefault(domain, []).append(eid)
            elif action == "turn_on" and domain in {"light", "fan", "switch", "media_player", "input_boolean"}:
                supported.setdefault(domain, []).append(eid)
            else:
                unsupported.append(eid)
        if not supported:
            return LogicDecision(False, reason="unsupported_direct_action")
        if unsupported:
            # Mixed supported/unsupported exact targets are semantically ambiguous;
            # AI can explain or ask instead of partially acting.
            return LogicDecision(False, reason="mixed_direct_action_domains")

        # Repeated identical failures trigger a deterministic clarification instead
        # of hammering Home Assistant again.
        blocked: list[str] = []
        for domain, ids in supported.items():
            args = {"domain": domain, "service": action, "data": {}, "target": {"entity_id": ids}}
            issue = recent_issue_for_operation(
                "ha_call_service", args,
                minutes=settings.logic_repeat_failure_window_minutes,
                minimum_count=settings.logic_repeat_failure_limit,
            )
            if issue:
                blocked.append(f"{domain}.{action}: {issue.get('last_error')}")
                continue
            for eid in ids:
                single_args = {**args, "target": {"entity_id": eid}}
                entity_issue = recent_issue_for_operation(
                    "ha_call_service", single_args,
                    minutes=settings.logic_repeat_failure_window_minutes,
                    minimum_count=settings.logic_repeat_failure_limit,
                )
                if entity_issue:
                    blocked.append(f"{eid}: {entity_issue.get('last_error')}")
        if blocked:
            return LogicDecision(
                True,
                "⚠️ Thao tác này đã lỗi lặp lại gần đây nên tôi chưa gửi lại lệnh. "
                "Bạn muốn tôi thử lại không?\n- " + "\n- ".join(blocked[:4]),
                reason="repeated_failure_clarification",
            )

        traces: list[dict[str, Any]] = []
        calls: list[tuple[str, list[str], dict[str, Any]]] = []
        for domain, ids in supported.items():
            args = {"domain": domain, "service": action, "data": {}, "target": {"entity_id": ids}}
            calls.append((domain, ids, args))

        async def one_call(domain: str, ids: list[str], args: dict[str, Any]) -> tuple[str, list[str], dict[str, Any], Exception | None]:
            try:
                result = await self.runtime.call("ha_call_service", args)
                add_tool_audit("ha_call_service", args, result=result)
                return domain, ids, result if isinstance(result, dict) else {"result": result}, None
            except Exception as exc:
                add_tool_audit("ha_call_service", args, error=f"{type(exc).__name__}: {exc}")
                record_failure("ha_call_service", args, f"{type(exc).__name__}: {exc}", source=f"logic:{source}")
                if len(ids) > 1:
                    for eid in ids:
                        record_failure(
                            "ha_call_service",
                            {**args, "target": {"entity_id": eid}},
                            f"{type(exc).__name__}: {exc}",
                            source=f"logic:{source}",
                        )
                return domain, ids, {}, exc

        results = await asyncio.gather(*(one_call(*call) for call in calls))
        await asyncio.sleep(0)
        live = await self.ha.states(fresh=True)
        by_id = {str(item.get("entity_id") or ""): item for item in live if isinstance(item, dict)}
        wanted_state = "off" if action == "turn_off" else "on"
        success_ids: list[str] = []
        errors: list[str] = []
        for domain, ids, result, exc in results:
            args = {"domain": domain, "service": action, "data": {}, "target": {"entity_id": ids}}
            if exc is not None:
                traces.append({"tool": "ha_call_service", "round": 0, "status": "error", "read_only": False, "side_effect": True, "arguments": args, "error": f"{type(exc).__name__}: {exc}"})
                errors.append(f"{domain}: {exc}")
                continue
            verified = [eid for eid in ids if str((by_id.get(eid) or {}).get("state") or "") == wanted_state]
            if verified:
                success_ids.extend(verified)
                verified_args = {**args, "target": {"entity_id": verified}}
                traces.append({"tool": "ha_call_service", "round": 0, "status": "ok", "read_only": False, "side_effect": True, "arguments": verified_args, "verified": True})
                for eid in verified:
                    record_success("ha_call_service", {**args, "target": {"entity_id": eid}}, source=f"logic:{source}")
                if len(verified) == len(ids):
                    record_success("ha_call_service", args, source=f"logic:{source}")
            unverified = [eid for eid in ids if eid not in verified]
            if unverified:
                failed_args = {**args, "target": {"entity_id": unverified}}
                traces.append({"tool": "ha_call_service", "round": 0, "status": "unverified", "read_only": False, "side_effect": True, "arguments": failed_args, "verified": False})
                for eid in unverified:
                    record_failure(
                        "ha_call_service",
                        {**args, "target": {"entity_id": eid}},
                        f"Service returned but state was not verified as {wanted_state}",
                        source=f"logic:{source}",
                    )
                errors.append("chưa xác nhận: " + ", ".join(unverified))

        if success_ids:
            verb = "tắt" if action == "turn_off" else "bật"
            lines = [f"✅ Đã {verb} {len(success_ids)} thiết bị:"]
            for eid in success_ids:
                item = by_id.get(eid) or {}
                name = str((item.get("attributes") or {}).get("friendly_name") or eid)
                lines.append(f"- **{name}:** `{wanted_state}`")
            if errors:
                lines.append("- ⚠️ Một số target chưa xác nhận; không khẳng định đã thành công.")
            return LogicDecision(True, "\n".join(lines), traces, reason="exact_direct_control")
        if errors:
            return LogicDecision(True, "⚠️ Chưa xác nhận được thao tác: " + "; ".join(errors[:4]), traces, reason="direct_control_unverified")
        return LogicDecision(True, "⚠️ Không xác nhận được thay đổi trạng thái.", traces, reason="direct_control_unverified")

    async def _execute_profile(self, profile: dict[str, Any], *, source: str, dry_run: bool = False) -> LogicDecision:
        recipe = str(profile.get("recipe") or "").strip().lower()
        if recipe == "vacancy_shutdown":
            return await self._vacancy_shutdown(profile, source=source)
        if recipe == "state_report":
            ids = [str(x).strip().lower() for x in (profile.get("entity_ids") or []) if str(x).strip()]
            if not ids:
                raise ValueError("state_report requires entity_ids")
            return await self._exact_state_query(ids)
        if recipe == "bedroom_climate_comfort":
            return await self._bedroom_climate_comfort(profile, source=source, dry_run=dry_run)
        raise ValueError(f"Unsupported logic recipe: {recipe or '(empty)'}")

    async def dry_run_profile(self, name: str) -> dict[str, Any]:
        """Deterministically simulate a supported logic profile without side effects."""
        started = perf_counter()
        profile = self.profiles.load(name)
        recipe = str(profile.get("recipe") or "").strip().lower()
        if recipe != "bedroom_climate_comfort":
            raise ValueError(f"Logic profile dry-run is not implemented for recipe: {recipe or '(empty)'}")
        decision = await self._execute_profile(profile, source="web", dry_run=True)
        planned_actions: list[dict[str, Any]] = []
        for item in decision.trace:
            if not (isinstance(item, dict) and item.get("kind") == "planned_action"):
                continue
            args = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            policy = item.get("policy") if isinstance(item.get("policy"), dict) else {
                "status": "allowed", "reason": "Dry Run: action suppressed"
            }
            if str(item.get("tool") or "") == "ha_call_service":
                try:
                    assert_service_allowed(
                        str(args.get("domain") or ""),
                        str(args.get("service") or ""),
                        target=args.get("target") if isinstance(args.get("target"), dict) else None,
                        data=args.get("data") if isinstance(args.get("data"), dict) else {},
                    )
                    policy = {"status": "allowed", "reason": "Allowed by current HassMind policy; suppressed by Dry Run"}
                except Exception as exc:
                    policy = {"status": "blocked", "reason": str(exc)}
            planned_actions.append({
                "round": int(item.get("round") or 0),
                "tool": str(item.get("tool") or "ha_call_service"),
                "arguments": args,
                "summary": str(item.get("summary") or "action"),
                "executed": False,
                "policy": policy,
            })
        policy_statuses = [str((x.get("policy") or {}).get("status") or "") for x in planned_actions]
        overall_policy = "blocked" if any(x == "blocked" for x in policy_statuses) else ("allowed" if planned_actions else "no_action")
        policy_reasons: list[str] = []
        for action in planned_actions:
            reason = str((action.get("policy") or {}).get("reason") or "")
            if reason and reason not in policy_reasons:
                policy_reasons.append(reason)
        return {
            "ok": True,
            "dry_run": True,
            "profile": str(profile.get("name") or name),
            "tools": decision.trace,
            "expected_tools": list(dict.fromkeys(str(x.get("tool") or "") for x in decision.trace if isinstance(x, dict) and x.get("tool"))),
            "planned_actions": planned_actions,
            "policy": {
                "status": overall_policy,
                "reasons": policy_reasons,
            },
            "execution": {
                "actions_executed": 0,
                "read_tools_executed": sum(1 for x in decision.trace if isinstance(x, dict) and x.get("read_only") and x.get("status") == "ok"),
            },
            "response_preview": decision.text,
            "rounds": 1,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "engine": "logic",
            "reason": decision.reason,
        }

    async def _registry_snapshot(self) -> dict[str, Any]:
        now = perf_counter()
        ttl = max(15, int(settings.logic_registry_cache_seconds))
        if self._registry_cache is not None and now - self._registry_cache_at <= ttl:
            return self._registry_cache
        areas, entities, devices = await asyncio.gather(
            self.ha.area_registry(),
            self.ha.entity_registry(),
            self.ha.device_registry(),
        )
        snapshot = {
            "areas": areas if isinstance(areas, list) else [],
            "entities": entities if isinstance(entities, list) else [],
            "devices": devices if isinstance(devices, list) else [],
        }
        self._registry_cache = snapshot
        self._registry_cache_at = now
        return snapshot

    @staticmethod
    def _profile_areas(profile: dict[str, Any]) -> list[dict[str, Any]]:
        raw = profile.get("areas") or []
        if not isinstance(raw, list) or not raw:
            raise ValueError("vacancy_shutdown requires a non-empty areas list")
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Each vacancy_shutdown area must be an object")
            name = str(item.get("name") or "").strip()
            presence = str(item.get("presence") or "").strip().lower()
            if not name or not presence.startswith("binary_sensor."):
                raise ValueError("Each area requires name and binary_sensor presence")
            tv = [str(x).strip().lower() for x in (item.get("tv") or []) if str(x).strip()]
            out.append({"name": name, "presence": presence, "tv": tv})
        return out

    async def _vacancy_shutdown(self, profile: dict[str, Any], *, source: str) -> LogicDecision:
        areas = self._profile_areas(profile)
        switch_allowlist = {str(x).strip().lower() for x in (profile.get("switch_allowlist") or []) if str(x).strip()}
        allowed_domains = {str(x).strip().lower() for x in (profile.get("domains") or ["light", "fan", "switch"]) if str(x).strip()}
        allowed_domains &= {"light", "fan", "switch"}
        if not allowed_domains:
            raise ValueError("vacancy_shutdown has no allowed domains")

        # Read live states and registries concurrently. State cache is event-backed,
        # so this is usually memory-fast while registry metadata is TTL-cached.
        states_task = asyncio.create_task(self.ha.states(), name="logic-vacancy-states")
        registry_task = asyncio.create_task(self._registry_snapshot(), name="logic-vacancy-registry")
        states, registry = await asyncio.gather(states_task, registry_task)
        by_id = {str(item.get("entity_id") or "").lower(): item for item in states if isinstance(item, dict)}

        trace: list[dict[str, Any]] = [{
            "tool": "ha_get_states", "round": 0, "status": "ok", "read_only": True, "side_effect": False,
            "arguments": {"profile": str(profile.get("name") or "vacancy_shutdown"), "snapshot": "all_states"},
        }]

        # Resolve area ids deterministically through Home Assistant registries.
        area_name_by_id = {
            str(item.get("area_id") or item.get("id") or ""): str(item.get("name") or "")
            for item in registry["areas"] if isinstance(item, dict)
        }
        area_id_by_norm_name = {normalize_text(name): aid for aid, name in area_name_by_id.items() if aid and name}
        devices = {str(item.get("id") or ""): item for item in registry["devices"] if isinstance(item, dict) and item.get("id")}
        entity_area: dict[str, str] = {}
        for entry in registry["entities"]:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("entity_id") or "").lower()
            if not eid:
                continue
            area_id = str(entry.get("area_id") or "")
            if not area_id:
                device = devices.get(str(entry.get("device_id") or "")) or {}
                area_id = str(device.get("area_id") or "")
            if area_id:
                entity_area[eid] = area_id

        safe_areas: dict[str, dict[str, Any]] = {}
        for area in areas:
            presence_state = by_id.get(area["presence"])
            if not presence_state or str(presence_state.get("state") or "").lower() != "off":
                continue
            tv_states: list[str] = []
            tv_unsafe = False
            tv_active = False
            for tv_eid in area["tv"]:
                tv_item = by_id.get(tv_eid)
                if tv_item is None:
                    tv_unsafe = True
                    break
                state = str(tv_item.get("state") or "").lower()
                tv_states.append(state)
                if state in {"unknown", ""}:
                    tv_unsafe = True
                    break
                if state not in {"off", "unavailable"}:
                    tv_active = True
                    break
            if tv_unsafe or tv_active:
                continue
            area_id = area_id_by_norm_name.get(normalize_text(area["name"]))
            if not area_id:
                # Do not fuzzy-match room names. Missing registry evidence means skip.
                continue
            safe_areas[area_id] = area

        if not safe_areas:
            return LogicDecision(True, NO_NOTIFY_TOKEN, trace, reason="vacancy_no_safe_area")

        candidates_by_domain: dict[str, list[str]] = {domain: [] for domain in allowed_domains}
        candidate_area: dict[str, str] = {}
        for eid, item in by_id.items():
            domain = self._domain(eid)
            if domain not in allowed_domains or str(item.get("state") or "").lower() != "on":
                continue
            area_id = entity_area.get(eid)
            if area_id not in safe_areas:
                continue
            if domain == "switch" and eid not in switch_allowlist:
                # A switch load is semantically opaque. Only explicit operator-confirmed
                # switch entities are eligible; never infer from its friendly name.
                continue
            candidates_by_domain.setdefault(domain, []).append(eid)
            candidate_area[eid] = safe_areas[area_id]["name"]

        candidates_by_domain = {domain: ids for domain, ids in candidates_by_domain.items() if ids}
        if not candidates_by_domain:
            return LogicDecision(True, NO_NOTIFY_TOKEN, trace, reason="vacancy_no_candidate")

        async def turn_off(domain: str, ids: list[str]):
            base_args = {"domain": domain, "service": "turn_off", "data": {}}
            runnable: list[str] = []
            skipped: list[str] = []
            for eid in ids:
                single_args = {**base_args, "target": {"entity_id": eid}}
                issue = recent_issue_for_operation(
                    "ha_call_service", single_args,
                    minutes=settings.logic_repeat_failure_window_minutes,
                    minimum_count=settings.logic_repeat_failure_limit,
                )
                if issue:
                    skipped.append(eid)
                else:
                    runnable.append(eid)
            if not runnable:
                return domain, [], {**base_args, "target": {"entity_id": []}}, None, None, skipped
            args = {**base_args, "target": {"entity_id": runnable}}
            issue = recent_issue_for_operation(
                "ha_call_service", args,
                minutes=settings.logic_repeat_failure_window_minutes,
                minimum_count=settings.logic_repeat_failure_limit,
            )
            if issue:
                return domain, [], args, None, None, sorted(set(skipped + runnable))
            try:
                result = await self.runtime.call("ha_call_service", args)
                add_tool_audit("ha_call_service", args, result=result)
                return domain, runnable, args, result, None, skipped
            except Exception as exc:
                add_tool_audit("ha_call_service", args, error=f"{type(exc).__name__}: {exc}")
                record_failure("ha_call_service", args, f"{type(exc).__name__}: {exc}", source=f"logic-profile:{profile.get('name','vacancy_shutdown')}")
                if len(runnable) > 1:
                    for eid in runnable:
                        record_failure(
                            "ha_call_service",
                            {**base_args, "target": {"entity_id": eid}},
                            f"{type(exc).__name__}: {exc}",
                            source=f"logic-profile:{profile.get('name','vacancy_shutdown')}",
                        )
                return domain, runnable, args, None, exc, skipped

        raw_results = await asyncio.gather(*(turn_off(domain, ids) for domain, ids in candidates_by_domain.items()))
        live = await self.ha.states(fresh=True)
        live_by_id = {str(item.get("entity_id") or "").lower(): item for item in live if isinstance(item, dict)}
        verified: list[str] = []
        for domain, ids, args, result, exc, skipped in raw_results:
            if skipped:
                trace.append({
                    "tool": "runtime_issue_guard", "round": 0, "status": "skipped",
                    "read_only": True, "side_effect": False,
                    "arguments": {"entity_id": skipped, "service": f"{domain}.turn_off"},
                    "reason": "repeated_recent_failure",
                })
            if exc is not None:
                trace.append({"tool": "ha_call_service", "round": 0, "status": "error", "read_only": False, "side_effect": True, "arguments": args, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if not ids:
                continue
            ok_ids = [eid for eid in ids if str((live_by_id.get(eid) or {}).get("state") or "").lower() == "off"]
            if ok_ids:
                verified.extend(ok_ids)
                trace.append({"tool": "ha_call_service", "round": 0, "status": "ok", "read_only": False, "side_effect": True, "arguments": {**args, "target": {"entity_id": ok_ids}}, "verified": True})
                for eid in ok_ids:
                    record_success(
                        "ha_call_service",
                        {**args, "target": {"entity_id": eid}},
                        source=f"logic-profile:{profile.get('name','vacancy_shutdown')}",
                    )
                if len(ok_ids) == len(ids):
                    record_success("ha_call_service", args, source=f"logic-profile:{profile.get('name','vacancy_shutdown')}")
            bad_ids = [eid for eid in ids if eid not in ok_ids]
            if bad_ids:
                trace.append({"tool": "ha_call_service", "round": 0, "status": "unverified", "read_only": False, "side_effect": True, "arguments": {**args, "target": {"entity_id": bad_ids}}, "verified": False})
                for eid in bad_ids:
                    record_failure(
                        "ha_call_service",
                        {**args, "target": {"entity_id": eid}},
                        "Service returned but Home Assistant did not verify state=off",
                        source=f"logic-profile:{profile.get('name','vacancy_shutdown')}",
                    )

        if not verified:
            return LogicDecision(True, NO_NOTIFY_TOKEN, trace, reason="vacancy_no_verified_action")

        grouped: dict[str, list[str]] = {}
        for eid in verified:
            area_name = candidate_area.get(eid, "Khu vực")
            item = live_by_id.get(eid) or by_id.get(eid) or {}
            friendly = str((item.get("attributes") or {}).get("friendly_name") or eid)
            grouped.setdefault(area_name, []).append(friendly)
        lines = ["✅ Đã tắt thiết bị ở khu vực vắng người:"]
        for area_name in [area["name"] for area in areas]:
            for friendly in grouped.get(area_name, []):
                lines.append(f"- **{area_name}:** {friendly} → `off`")
        return LogicDecision(True, "\n".join(lines), trace, reason="vacancy_verified_actions")

    @staticmethod
    def _comfort_effective_temp(temperature: float, humidity: float) -> float:
        if humidity >= 80:
            return temperature + 1.0
        if humidity >= 70:
            return temperature + 0.6
        if humidity >= 65:
            return temperature + 0.3
        if humidity < 40:
            return temperature - 0.2
        return temperature

    @staticmethod
    def _climate_recently_changed(item: dict[str, Any], minutes: int = 15) -> bool:
        changed = parse_datetime(item.get("last_changed"))
        if changed is None:
            return False
        return local_now() - changed < timedelta(minutes=max(1, int(minutes)))

    async def _bedroom_climate_comfort(self, profile: dict[str, Any], *, source: str, dry_run: bool = False) -> LogicDecision:
        """Deterministic comfort controller: AC fixed at 27C, fan carries cooling intensity."""
        rooms = profile.get("rooms") or []
        if not isinstance(rooms, list) or not rooms:
            raise ValueError("bedroom_climate_comfort requires rooms")
        ac_target = float(profile.get("ac_target", 27))
        if ac_target != 27:
            raise ValueError("bedroom_climate_comfort requires ac_target=27")

        # One HA snapshot for all rooms and all decisions.
        states = await self.ha.states()
        by_id = {str(item.get("entity_id") or "").lower(): item for item in states if isinstance(item, dict)}
        trace: list[dict[str, Any]] = [{
            "tool": "ha_get_states", "round": 0, "status": "ok", "read_only": True,
            "side_effect": False, "arguments": {"profile": str(profile.get("name") or "bedroom-climate-comfort"), "snapshot": "all_states"},
        }]
        audit_source = f"logic-profile:{profile.get('name','bedroom-climate-comfort')}"

        async def run_room(room: dict[str, Any]) -> dict[str, Any]:
            name = str(room.get("name") or "Phòng").strip()
            temp_eid = str(room.get("temperature") or "").lower()
            hum_eid = str(room.get("humidity") or "").lower()
            presence_eid = str(room.get("presence") or "").lower()
            climate_eid = str(room.get("climate") or "").lower()
            fan_cfg = room.get("fan") or {}
            required = [temp_eid, hum_eid, presence_eid, climate_eid]
            if not all(required):
                return {"name": name, "status": "invalid", "summary": "thiếu mapping bắt buộc", "actions": [], "trace": []}
            missing = [eid for eid in required if eid not in by_id]
            if missing:
                return {"name": name, "status": "unsafe", "summary": "thiếu state: " + ", ".join(missing), "actions": [], "trace": []}
            presence = str(by_id[presence_eid].get("state") or "").lower()
            if presence != "on":
                status = "empty" if presence == "off" else "unsafe"
                return {"name": name, "status": status, "summary": f"presence={presence or 'unknown'}; không điều khiển", "actions": [], "trace": []}
            try:
                temperature = float(by_id[temp_eid].get("state"))
                humidity = float(by_id[hum_eid].get("state"))
            except (TypeError, ValueError):
                return {"name": name, "status": "unsafe", "summary": "sensor nhiệt độ/độ ẩm không hợp lệ", "actions": [], "trace": []}
            if not (-10 <= temperature <= 60 and 0 <= humidity <= 100):
                return {"name": name, "status": "unsafe", "summary": "sensor nhiệt độ/độ ẩm bất thường", "actions": [], "trace": []}

            effective = self._comfort_effective_temp(temperature, humidity)
            climate_item = by_id[climate_eid]
            climate_state = str(climate_item.get("state") or "").lower()
            if climate_state in {"", "unknown", "unavailable"}:
                return {"name": name, "status": "unsafe", "summary": f"climate={climate_state or 'unknown'}", "actions": [], "trace": []}
            climate_attrs = climate_item.get("attributes") or {}
            hvac_modes = {str(x).lower() for x in (climate_attrs.get("hvac_modes") or [])}
            current_target = climate_attrs.get("temperature")
            recently_changed = self._climate_recently_changed(climate_item, int(profile.get("climate_cooldown_minutes", 15)))

            # Decide comfort band and fan level first.
            if temperature <= 23.0 or effective <= 23.5:
                band = "Quá lạnh"
                desired_fan = "off"
                want_climate = "off"
            elif effective < 25.0:
                band = "Mát"
                desired_fan = "off"
                want_climate = "keep"
            elif effective < 26.0:
                band = "Dễ chịu"
                desired_fan = "1"
                want_climate = "keep"
            elif effective < 27.5:
                band = "Hơi ấm"
                desired_fan = "2"
                want_climate = "keep"
            elif effective < 29.0:
                band = "Ấm"
                desired_fan = "3"
                want_climate = "cool"
            elif effective < 30.5:
                band = "Nóng"
                desired_fan = "5" if temperature >= 30.0 else "4"
                want_climate = "cool"
            else:
                band = "Rất nóng"
                desired_fan = "6"
                want_climate = "cool"

            if str(fan_cfg.get("kind") or "") == "preset" and desired_fan != "off":
                # Map generic 1..6 bands to room-supported presets.
                desired_fan = "low" if desired_fan in {"1", "2"} else ("medium" if desired_fan == "3" else "high")

            room_trace: list[dict[str, Any]] = []
            planned: list[dict[str, Any]] = []

            def plan(domain: str, service: str, target_eid: str, data: dict[str, Any] | None = None, verify: tuple[str, Any] | None = None, label: str = "") -> None:
                planned.append({
                    "domain": domain, "service": service, "entity_id": target_eid,
                    "data": data or {}, "verify": verify, "label": label or f"{domain}.{service}",
                })

            fan_power = str(fan_cfg.get("power") or "").lower()
            fan_kind = str(fan_cfg.get("kind") or "").lower()
            fan_power_state = str((by_id.get(fan_power) or {}).get("state") or "").lower() if fan_power else ""

            # Fan plan.
            if desired_fan == "off":
                if fan_power and fan_power_state == "on":
                    plan("switch", "turn_off", fan_power, verify=("state", "off"), label="tắt quạt")
            elif fan_kind == "script_speed":
                speeds = fan_cfg.get("speeds") or {}
                script_eid = str(speeds.get(str(desired_fan)) or "").lower()
                script_item = by_id.get(script_eid) if script_eid else None
                if script_item is not None:
                    if fan_power and fan_power_state == "off":
                        plan("switch", "turn_on", fan_power, verify=("state", "on"), label="bật nguồn quạt")
                    last_triggered = parse_datetime((script_item.get("attributes") or {}).get("last_triggered"))
                    recent_same = bool(
                        fan_power_state == "on" and last_triggered is not None
                        and local_now() - last_triggered < timedelta(minutes=int(profile.get("fan_repeat_guard_minutes", 20)))
                    )
                    if not recent_same:
                        plan("script", "turn_on", script_eid, verify=None, label=f"gửi speed {desired_fan}")
            elif fan_kind == "preset":
                fan_eid = str(fan_cfg.get("entity") or "").lower()
                fan_item = by_id.get(fan_eid) or {}
                supported_presets = {str(x).lower() for x in ((fan_item.get("attributes") or {}).get("preset_modes") or [])}
                current_preset = str((fan_item.get("attributes") or {}).get("preset_mode") or "").lower()
                if fan_eid and desired_fan in supported_presets:
                    if fan_power and fan_power_state == "off":
                        plan("switch", "turn_on", fan_power, verify=("state", "on"), label="bật nguồn quạt")
                    if current_preset != desired_fan:
                        plan("fan", "set_preset_mode", fan_eid, {"preset_mode": desired_fan}, verify=("attribute:preset_mode", desired_fan), label=f"quạt {desired_fan}")

            # Climate plan. Top-level state is authoritative; target attribute never means power-on.
            if want_climate == "off":
                if climate_state in {"cool", "dry"}:
                    plan("climate", "turn_off", climate_eid, verify=("state", "off"), label="tắt điều hòa")
            elif want_climate == "cool":
                if "cool" not in hvac_modes:
                    return {
                        "name": name, "status": "unsafe", "summary": "climate không hỗ trợ cool",
                        "temperature": temperature, "humidity": humidity, "effective": effective, "band": band,
                        "actions": [], "trace": room_trace,
                    }
                # off->cool when hot is explicitly allowed even inside cooldown. For other mode
                # changes respect cooldown unless the room is very hot.
                if climate_state != "cool" and (climate_state == "off" or not recently_changed or effective >= 30.5):
                    plan("climate", "set_hvac_mode", climate_eid, {"hvac_mode": "cool"}, verify=("state", "cool"), label="bật cool")
                # Never leave an automatic target below 27C. Correct low targets immediately.
                target_num = None
                try:
                    target_num = float(current_target) if current_target is not None else None
                except (TypeError, ValueError):
                    target_num = None
                target_needs_fix = target_num is None or abs(target_num - 27.0) >= 0.1
                if target_needs_fix and (target_num is not None and target_num < 27.0 or not recently_changed or climate_state == "off" or effective >= 30.5):
                    plan("climate", "set_temperature", climate_eid, {"temperature": 27}, verify=("attribute:temperature", 27.0), label="đặt 27°C")
            else:  # keep
                # If already cooling below 27C, normalize upward to the operator policy.
                if climate_state == "cool":
                    try:
                        target_num = float(current_target)
                    except (TypeError, ValueError):
                        target_num = None
                    if target_num is not None and target_num < 27.0 and (not recently_changed or temperature <= 23.0):
                        plan("climate", "set_temperature", climate_eid, {"temperature": 27}, verify=("attribute:temperature", 27.0), label="đưa target về 27°C")

            # Execute per-room sequentially to preserve power/mode ordering; rooms themselves run in parallel.
            # In dry-run mode we keep the exact same deterministic planning but never call a mutation tool.
            sent: list[dict[str, Any]] = []
            for item in planned:
                args = {
                    "domain": item["domain"], "service": item["service"], "data": item["data"],
                    "target": {"entity_id": item["entity_id"]},
                }
                if dry_run:
                    sent.append({**item, "args": args, "dry_run": True})
                    room_trace.append({
                        "tool": "ha_call_service", "round": 0, "status": "suppressed",
                        "kind": "planned_action", "read_only": False, "side_effect": True,
                        "arguments": args, "executed": False,
                        "policy": {"status": "allowed", "reason": "Dry Run: action suppressed"},
                        "summary": item.get("label") or f"{item['domain']}.{item['service']}",
                    })
                    continue
                issue = recent_issue_for_operation(
                    "ha_call_service", args,
                    minutes=settings.logic_repeat_failure_window_minutes,
                    minimum_count=settings.logic_repeat_failure_limit,
                )
                if issue:
                    room_trace.append({
                        "tool": "runtime_issue_guard", "round": 0, "status": "skipped",
                        "read_only": True, "side_effect": False, "arguments": args,
                        "reason": "repeated_recent_failure",
                    })
                    continue
                try:
                    result = await self.runtime.call("ha_call_service", args)
                    add_tool_audit("ha_call_service", args, result=result)
                    sent.append({**item, "args": args})
                except Exception as exc:
                    add_tool_audit("ha_call_service", args, error=f"{type(exc).__name__}: {exc}")
                    record_failure("ha_call_service", args, f"{type(exc).__name__}: {exc}", source=audit_source)
                    room_trace.append({
                        "tool": "ha_call_service", "round": 0, "status": "error", "read_only": False,
                        "side_effect": True, "arguments": args, "error": f"{type(exc).__name__}: {exc}",
                    })

            return {
                "name": name, "status": "ok", "summary": "", "temperature": temperature,
                "humidity": humidity, "effective": effective, "band": band,
                "climate_before": climate_state, "target_before": current_target,
                "fan_desired": desired_fan, "sent": sent, "trace": room_trace,
            }

        room_results = await asyncio.gather(*(run_room(room) for room in rooms))

        if dry_run:
            display: list[str] = []
            for result in room_results:
                trace.extend(result.get("trace") or [])
                status = str(result.get("status") or "")
                if status == "ok":
                    sent = result.get("sent") or []
                    if sent:
                        labels = [str(x.get("label") or x.get("summary") or "action") for x in sent]
                        display.append(
                            f"🌡️ **{result['name']}:** {result['temperature']:.1f}°C · {result['humidity']:.0f}% · "
                            f"~{result['effective']:.1f}°C · **{result['band']}**\n"
                            f"- Dự kiến: " + " · ".join(labels)
                        )
                    else:
                        display.append(
                            f"🌡️ **{result['name']}:** {result['temperature']:.1f}°C · {result['humidity']:.0f}% · "
                            f"~{result['effective']:.1f}°C · **{result['band']}**\n"
                            "- Không có action dự kiến."
                        )
                elif status == "empty":
                    display.append(f"🏠 **{result['name']}:** không có người · không điều khiển.")
                else:
                    display.append(f"⚠️ **{result['name']}:** {result.get('summary') or 'không đủ dữ liệu an toàn'}")
            preview = "## 🧪 Dry Run · bedroom-climate-comfort\n\n" + "\n\n".join(display)
            preview += "\n\n*Không có action nào được thực thi.*"
            return LogicDecision(True, preview, trace, reason="climate_dry_run")

        # One fresh snapshot verifies all side effects across rooms.
        live = await self.ha.states(fresh=True)
        live_by_id = {str(item.get("entity_id") or "").lower(): item for item in live if isinstance(item, dict)}
        verified_actions: list[tuple[str, str]] = []
        unverified_actions: list[tuple[str, str]] = []
        display: list[str] = []

        for result in room_results:
            trace.extend(result.get("trace") or [])
            if result.get("status") != "ok":
                if source != "system" and result.get("status") == "unsafe":
                    display.append(f"⚠️ **{result['name']}:** {result.get('summary')}")
                continue
            successful_labels: list[str] = []
            for sent in result.get("sent") or []:
                eid = sent["entity_id"]
                verify = sent.get("verify")
                args = sent["args"]
                if verify is None:
                    # Script speed has no trustworthy state sensor. A successful service call means
                    # command sent, not that physical speed is proven.
                    trace.append({
                        "tool": "ha_call_service", "round": 0, "status": "ok", "read_only": False,
                        "side_effect": True, "arguments": args, "verified": False, "command_sent": True,
                    })
                    record_success("ha_call_service", args, source=audit_source)
                    verified_actions.append((result["name"], sent["label"]))
                    successful_labels.append(sent["label"])
                    continue
                item = live_by_id.get(eid) or {}
                key, wanted = verify
                actual: Any
                if key == "state":
                    actual = str(item.get("state") or "").lower()
                    ok = actual == str(wanted).lower()
                elif key.startswith("attribute:"):
                    attr = key.split(":", 1)[1]
                    actual = (item.get("attributes") or {}).get(attr)
                    if isinstance(wanted, (int, float)):
                        try:
                            ok = abs(float(actual) - float(wanted)) < 0.1
                        except (TypeError, ValueError):
                            ok = False
                    else:
                        ok = str(actual or "").lower() == str(wanted).lower()
                else:
                    ok = False
                if ok:
                    trace.append({
                        "tool": "ha_call_service", "round": 0, "status": "ok", "read_only": False,
                        "side_effect": True, "arguments": args, "verified": True,
                    })
                    record_success("ha_call_service", args, source=audit_source)
                    verified_actions.append((result["name"], sent["label"]))
                    successful_labels.append(sent["label"])
                else:
                    trace.append({
                        "tool": "ha_call_service", "round": 0, "status": "unverified", "read_only": False,
                        "side_effect": True, "arguments": args, "verified": False,
                    })
                    record_failure("ha_call_service", args, f"State verification failed for {sent['label']}", source=audit_source)
                    unverified_actions.append((result["name"], sent["label"]))

            if successful_labels:
                display.append(
                    f"🌡️ **{result['name']}:** {result['temperature']:.1f}°C · {result['humidity']:.0f}% · "
                    f"~{result['effective']:.1f}°C · **{result['band']}**\n"
                    f"- " + " · ".join(successful_labels)
                )

        if not verified_actions:
            if source == "system":
                return LogicDecision(True, NO_NOTIFY_TOKEN, trace, reason="climate_no_verified_action")
            if display:
                return LogicDecision(True, "\n".join(display), trace, reason="climate_no_action_with_warning")
            return LogicDecision(True, "✅ Không cần thay đổi thiết bị lúc này.", trace, reason="climate_no_action")

        if unverified_actions and source != "system":
            display.append("⚠️ Một số lệnh đã gửi nhưng Home Assistant chưa xác nhận state mới.")
        return LogicDecision(True, "\n\n".join(display), trace, reason="climate_verified_actions")


class LogicFirstOrchestrator:
    """Drop-in Agent-compatible facade: deterministic engine first, AI second."""

    def __init__(self, agent, logic: LogicEngine) -> None:
        self.agent = agent
        self.logic = logic

    def __getattr__(self, name: str):
        # Preserve the full Agent surface (for example Scenario Dry Run) while
        # routing normal chat/system execution through the deterministic layer.
        return getattr(self.agent, name)

    async def chat(self, session_id: str, user_text: str, source: str = "web") -> str:
        result = await self.chat_with_trace(session_id, user_text, source)
        return str(result.get("text") or "")

    async def dry_run_skill(self, name: str, user_text: str) -> dict[str, Any]:
        """Use deterministic profile simulation for skills that have a code implementation.

        This fixes the most important Logic-First boundary: selecting a deterministic
        skill in the admin Dry Run must not fall straight back to an LLM that may
        refuse or ignore Home Assistant tools.
        """
        from .skills import read_skill

        skill = read_skill(name, include_disabled=True)
        if not skill.get("valid", False):
            raise ValueError("Skill is invalid; fix validation errors before scenario dry-run")
        try:
            profile = self.logic.profiles.load(str(name).strip().lower())
            if str(profile.get("recipe") or "").strip().lower() == "bedroom_climate_comfort":
                result = await self.logic.dry_run_profile(str(name).strip().lower())
                result["skill"] = {
                    "name": skill.get("name"),
                    "version": skill.get("version"),
                    "source": skill.get("source"),
                    "enabled": skill.get("enabled"),
                    "valid": skill.get("valid"),
                }
                result["prompt"] = str(user_text or "").strip()
                return result
        except (FileNotFoundError, ValueError):
            pass
        return await self.agent.dry_run_skill(name, user_text)

    async def chat_with_trace(self, session_id: str, user_text: str, source: str = "web") -> dict[str, Any]:
        decision = await self.logic.try_handle(user_text, source=source)
        if decision.handled:
            add_message(session_id, "user", user_text, source)
            add_message(session_id, "assistant", decision.text, source)
            info(logger, "logic_first_handled", session_id=session_id, source=source, reason=decision.reason, trace_count=len(decision.trace))
            return {"text": decision.text, "tools": decision.trace, "engine": "logic", "reason": decision.reason}
        info(logger, "logic_first_fallback_ai", session_id=session_id, source=source, reason=decision.reason)
        detailed = await self.agent.chat_with_trace(session_id, user_text, source)
        if isinstance(detailed, dict):
            detailed.setdefault("engine", "ai")
            detailed.setdefault("reason", decision.reason)
            text_value = str(detailed.get("text") or "")
            tool_trace = detailed.get("tools") if isinstance(detailed.get("tools"), list) else []
            if (
                not tool_trace
                and self.logic._looks_like_home_assistant_intent(user_text)
                and self.logic.is_model_refusal(text_value)
            ):
                # Never surface generic "I am only a language model" prose for an HA
                # operation. If deterministic routing could not safely resolve it, ask
                # for the exact missing identity instead of pretending the feature is unsupported.
                fallback = (
                    "❓ Chưa xác định đủ dữ liệu để xử lý chắc chắn bằng Home Assistant. "
                    "Hãy nêu tên thiết bị/phòng cụ thể hoặc `entity_id`; HassMind sẽ kiểm tra state realtime trước khi thao tác."
                )
                if not replace_last_assistant_message(session_id, fallback, source):
                    add_message(session_id, "assistant", fallback, source)
                return {"text": fallback, "tools": [], "engine": "logic", "reason": "ai_refusal_guard"}
            return detailed
        return {"text": str(detailed or ""), "tools": [], "engine": "ai", "reason": decision.reason}
