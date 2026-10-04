from __future__ import annotations

import unicodedata
from typing import Any


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(text.replace("_", " ").replace("-", " ").split())


def compact_state(item: dict[str, Any], *, include_attributes: bool = True) -> dict[str, Any]:
    attrs = item.get("attributes") or {}
    out: dict[str, Any] = {
        "entity_id": item.get("entity_id"),
        "state": item.get("state"),
        "friendly_name": attrs.get("friendly_name"),
        "last_changed": item.get("last_changed"),
    }
    if not include_attributes or not isinstance(attrs, dict):
        return out

    compact: dict[str, Any] = {}
    preferred = (
        "device_class", "unit_of_measurement", "temperature", "current_temperature",
        "humidity", "target_count", "current", "power", "current_power",
        "current_power_w", "voltage", "battery", "battery_level", "illuminance",
        "brightness", "percentage", "hvac_action", "preset_mode", "fan_mode",
        "pm25", "pm2_5", "pm10", "aqi", "mode", "status",
    )
    for key in preferred:
        value = attrs.get(key)
        if isinstance(value, (str, int, float, bool)) or (value is None and key in attrs):
            compact[key] = value

    for key, value in attrs.items():
        if key in compact or key in {"friendly_name", "icon", "supported_features"}:
            continue
        if len(compact) >= 28:
            break
        if isinstance(value, (int, float, bool)) or (isinstance(value, str) and len(value) <= 120):
            compact[key] = value
    if compact:
        out["attributes"] = compact
    return out


def match_state(item: dict[str, Any], query: str, domains: list[str], state_filter: str) -> bool:
    eid = str(item.get("entity_id") or "")
    clean_domains = [str(domain).strip() for domain in domains if str(domain).strip()]
    if clean_domains and not any(eid.startswith(domain + ".") for domain in clean_domains):
        return False
    if state_filter and str(item.get("state") or "").lower() != state_filter.lower():
        return False
    if not query.strip():
        return True
    attrs = item.get("attributes") or {}
    haystack = normalize_text(" ".join((eid, str(attrs.get("friendly_name") or ""), str(attrs.get("device_class") or ""))))
    tokens = [t for t in normalize_text(query).split() if t]
    return bool(tokens) and all(token in haystack for token in tokens)


def search_states(
    states: list[dict[str, Any]],
    *,
    query: str = "",
    domains: list[str] | None = None,
    state_filter: str = "",
    limit: int = 80,
    include_attributes: bool = True,
) -> dict[str, Any]:
    domains = domains or []
    limit = min(max(int(limit), 1), 200)
    matches = [item for item in states if match_state(item, query, domains, state_filter)]
    return {
        "count": min(len(matches), limit),
        "total_matches": len(matches),
        "states": [compact_state(item, include_attributes=include_attributes) for item in matches[:limit]],
    }
