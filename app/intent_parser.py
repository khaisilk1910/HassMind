"""Validate untrusted AI device-intent JSON; this module has no LLM dependencies."""
from __future__ import annotations

import json
import math
import re


def parse_device_status_intent(raw: str, allowed_ids: set[str]) -> dict:
    """Permit only read-only intent labels and pre-approved Device Registry IDs."""
    result = {"intent": "clarify", "device_id": "", "confidence": 0.0}
    value = str(raw or "").strip()
    if len(value) > 4096:
        return result
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE).strip()
    try:
        payload = json.loads(value)
    except (ValueError, TypeError):
        return result
    if not isinstance(payload, dict):
        return result
    intent = str(payload.get("intent") or "").lower().strip()
    if intent not in {"device_status", "other", "clarify"}:
        return result
    confidence_value = payload.get("confidence", 0.0)
    try:
        confidence = float(confidence_value) if not isinstance(confidence_value, bool) else 0.0
    except (ValueError, TypeError):
        confidence = 0.0
    if not math.isfinite(confidence):
        return result
    identity = str(payload.get("device_id") or "").strip()
    return {"intent": intent, "device_id": identity if identity in allowed_ids else "",
            "confidence": max(0.0, min(1.0, confidence))}
