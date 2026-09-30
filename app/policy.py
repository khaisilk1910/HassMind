from typing import Any
from .settings import settings


SENSITIVE_TOKENS = {
    "lock.", "alarm_control_panel.", "cover.garage", "shell_command.",
    "hassio.", "homeassistant.restart", "homeassistant.stop", "update.install",
}


def assert_service_allowed(domain: str, service: str):
    domain = domain.strip()
    if domain in settings.denied_domains:
        raise PermissionError(f"Direct service domain '{domain}' is blocked by HassMind policy")
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
