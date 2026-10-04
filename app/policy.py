from typing import Any
from .settings import settings


SENSITIVE_TOKENS = {
    "lock.", "alarm_control_panel.", "cover.garage", "shell_command.",
    "hassio.", "homeassistant.restart", "homeassistant.stop", "update.install",
}


def _entity_ids_from_target(target: dict | None) -> list[str]:
    if not isinstance(target, dict):
        return []
    value = target.get("entity_id")
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def assert_service_allowed(
    domain: str,
    service: str,
    *,
    target: dict | None = None,
    data: dict | None = None,
):
    domain = domain.strip()
    service = service.strip()
    if domain in settings.denied_domains:
        raise PermissionError(f"Direct service domain '{domain}' is blocked by HassMind policy")

    # Scripts can encapsulate arbitrary actions, so do not put the whole script
    # domain in ALLOW_SERVICE_DOMAINS. Permit only exact operator-approved script
    # entities, only via script.turn_on, without variables/data or indirect targets.
    if domain == "script":
        if service != "turn_on":
            raise PermissionError("Only script.turn_on is permitted for allowlisted script entities")
        if data:
            raise PermissionError("Allowlisted script.turn_on calls must not include service data/variables")
        if not isinstance(target, dict) or set(target) - {"entity_id"}:
            raise PermissionError("Allowlisted script calls require a direct entity_id target only")
        entity_ids = _entity_ids_from_target(target)
        if not entity_ids:
            raise PermissionError("Allowlisted script calls require at least one script entity_id")
        allowed = settings.allowed_script_entity_ids
        blocked = [entity_id for entity_id in entity_ids if entity_id not in allowed]
        if blocked:
            raise PermissionError("Script entity is not in ALLOW_SCRIPT_ENTITIES: " + ", ".join(blocked))
        return

    if domain not in settings.allowed_domains:
        raise PermissionError(f"Direct service domain '{domain}' is not in ALLOW_SERVICE_DOMAINS")
    if service.startswith("reload") or service in {"restart", "stop"}:
        raise PermissionError(f"Service '{domain}.{service}' is blocked by HassMind policy")


def config_risk(config: Any) -> str:
    text = str(config).lower()
    if any(token in text for token in SENSITIVE_TOKENS):
        return "high"
    if any(token in text for token in ("climate.", "switch.", "script.")):
        return "normal"
    return "low"
