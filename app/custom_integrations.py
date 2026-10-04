from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import conn, utcnow
from .observability import get_logger, info, register_secret, warning
from .settings import settings

logger = get_logger("custom_integrations")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_ACTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
_HEADER_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_AUTH_TYPES = {"none", "bearer", "header"}
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_ACTION_MODES = {"read", "write"}
_REQUEST_TARGETS = {"auto", "query", "json"}
_RESERVED_IDS = {"camera_tts", "facedetect", "zalo", "telegram", "wyoming", "wyoming_vietnamese", "ha_custom"}
_MAX_ACTIONS = 24


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = slug[:64].strip("-")
    return slug or "integration"


def _normalize_id(value: str, fallback_name: str = "") -> str:
    integration_id = (value or "").strip().lower() or _slugify(fallback_name)
    if len(integration_id) == 1:
        integration_id += "-1"
    if not _ID_RE.fullmatch(integration_id):
        raise ValueError("Integration ID must use a-z, 0-9, '-' or '_' and be 2-64 characters")
    return integration_id


def _normalize_action_id(value: Any, fallback_name: str = "") -> str:
    action_id = str(value or "").strip().lower() or _slugify(fallback_name)[:40]
    if len(action_id) == 1:
        action_id += "-1"
    if not _ACTION_ID_RE.fullmatch(action_id):
        raise ValueError("Action ID must use a-z, 0-9, '-' or '_' and be 2-40 characters")
    return action_id


def _normalize_url(value: Any) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL must be a valid http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("Base URL must not contain username/password")
    return text.rstrip("/")


def _normalize_relative_path(value: Any, default: str = "/health") -> str:
    text = str(value or default).strip() or default
    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc or text.startswith("//"):
        raise ValueError("API path must be relative, for example /health or /api/items/{id}")
    if not text.startswith("/"):
        text = "/" + text
    if len(text) > 512:
        raise ValueError("API path is too long")
    return text


def _normalize_health_path(value: Any) -> str:
    return _normalize_relative_path(value, "/health")


def _normalize_auth_type(value: Any) -> str:
    auth_type = str(value or "none").strip().lower()
    if auth_type not in _AUTH_TYPES:
        raise ValueError("Auth type must be none, bearer or header")
    return auth_type


def _normalize_header(value: Any, auth_type: str) -> str:
    header = str(value or "X-API-Key").strip() or "X-API-Key"
    if auth_type == "header" and not _HEADER_RE.fullmatch(header):
        raise ValueError("Invalid HTTP header name")
    return header


def _normalize_input_schema(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Action input_schema is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("Action input_schema must be a JSON object")
    schema = deepcopy(value)
    if schema.get("type", "object") != "object":
        raise ValueError("Action input_schema.type must be object")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("Action input_schema.properties must be an object")
    if len(properties) > 40:
        raise ValueError("An action can expose at most 40 parameters")
    for key, spec in properties.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
            raise ValueError(f"Invalid action parameter name: {key!r}")
        if not isinstance(spec, dict):
            raise ValueError(f"Schema for parameter {key} must be an object")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(x, str) for x in required):
        raise ValueError("Action input_schema.required must be a list of strings")
    missing = [x for x in required if x not in properties]
    if missing:
        raise ValueError(f"Required parameters are not declared in properties: {', '.join(missing)}")
    schema["type"] = "object"
    schema["properties"] = properties
    schema["required"] = required
    schema["additionalProperties"] = False
    encoded = json.dumps(schema, ensure_ascii=False)
    if len(encoded) > 16000:
        raise ValueError("Action input_schema is too large")
    return schema


def _normalize_actions(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Actions JSON is invalid: {exc.msg}") from exc
    if not isinstance(value, list):
        raise ValueError("actions must be a list")
    if len(value) > _MAX_ACTIONS:
        raise ValueError(f"A custom integration can define at most {_MAX_ACTIONS} API actions")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Each API action must be an object")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("Each API action needs a display name")
        if len(name) > 120:
            raise ValueError("API action name is too long")
        action_id = _normalize_action_id(raw.get("id"), name)
        if action_id in seen:
            raise ValueError(f"Duplicate API action ID: {action_id}")
        seen.add(action_id)
        method = str(raw.get("method") or "GET").strip().upper()
        if method not in _METHODS:
            raise ValueError(f"Unsupported HTTP method for action {action_id}: {method}")
        mode = str(raw.get("mode") or ("read" if method == "GET" else "write")).strip().lower()
        if mode not in _ACTION_MODES:
            raise ValueError(f"Action {action_id} mode must be read or write")
        request_target = str(raw.get("request_target") or "auto").strip().lower()
        if request_target not in _REQUEST_TARGETS:
            raise ValueError(f"Action {action_id} request_target must be auto, query or json")
        path = _normalize_relative_path(raw.get("path"), "/")
        schema = _normalize_input_schema(raw.get("input_schema"))
        params = set(schema.get("properties", {}))
        placeholders = set(_PATH_PARAM_RE.findall(path))
        undeclared = sorted(placeholders - params)
        if undeclared:
            raise ValueError(f"Action {action_id} path parameters missing from input_schema: {', '.join(undeclared)}")
        description = str(raw.get("description") or "").strip()
        if len(description) > 700:
            raise ValueError("API action description is too long")
        out.append({
            "id": action_id,
            "name": name,
            "description": description,
            "enabled": bool(raw.get("enabled", True)),
            "agent_enabled": bool(raw.get("agent_enabled", False)),
            "method": method,
            "path": path,
            "mode": mode,
            "request_target": request_target,
            "input_schema": schema,
        })
    return out


def custom_action_tool_name(integration_id: str, action_id: str) -> str:
    safe_integration = re.sub(r"[^a-zA-Z0-9_]", "_", integration_id)
    safe_action = re.sub(r"[^a-zA-Z0-9_]", "_", action_id)
    base = f"ci_{safe_integration}_{safe_action}"
    digest = hashlib.sha256(f"{integration_id}\0{action_id}".encode("utf-8")).hexdigest()[:8]
    return base[:55].rstrip("_") + "_" + digest


def _secret_name(integration_id: str) -> str:
    return f"integration_custom_{integration_id}_secret"


def _secret_path(integration_id: str) -> Path:
    return Path(settings.runtime_secret_dir) / _secret_name(integration_id)


def _clean_payload(payload: dict[str, Any], *, existing_id: str = "") -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Integration name must not be empty")
    if len(name) > 120:
        raise ValueError("Integration name is limited to 120 characters")

    integration_id = _normalize_id(existing_id or str(payload.get("id") or ""), name)
    if not existing_id and integration_id in _RESERVED_IDS:
        raise ValueError(f"Integration ID '{integration_id}' is reserved by HassMind")
    icon = str(payload.get("icon") or "\U0001f50c").strip() or "\U0001f50c"
    if len(icon) > 16:
        raise ValueError("Icon is too long")
    description = str(payload.get("description") or "").strip()
    if len(description) > 600:
        raise ValueError("Integration description is limited to 600 characters")
    auth_type = _normalize_auth_type(payload.get("auth_type"))
    auth_header = _normalize_header(payload.get("auth_header"), auth_type)

    return {
        "id": integration_id,
        "name": name,
        "icon": icon,
        "description": description,
        "enabled": bool(payload.get("enabled", True)),
        "base_url": _normalize_url(payload.get("base_url")),
        "health_path": _normalize_health_path(payload.get("health_path")),
        "auth_type": auth_type,
        "auth_header": auth_header,
        "actions": _normalize_actions(payload.get("actions")),
    }


def _decode_actions(raw: Any) -> list[dict[str, Any]]:
    try:
        value = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    try:
        return _normalize_actions(value)
    except ValueError as exc:
        warning(logger, "custom_integration_actions_invalid", error=str(exc))
        return []


def _row_to_public(row: Any) -> dict[str, Any]:
    integration_id = str(row["id"])
    secret = settings.read_runtime_secret(_secret_name(integration_id))
    if secret:
        register_secret(secret)
    actions = _decode_actions(row["actions_json"] if "actions_json" in row.keys() else "[]")
    return {
        "id": integration_id,
        "name": str(row["name"]),
        "icon": str(row["icon"] or "\U0001f50c"),
        "description": str(row["description"] or ""),
        "enabled": bool(row["enabled"]),
        "base_url": str(row["base_url"]),
        "health_path": str(row["health_path"] or "/health"),
        "auth_type": str(row["auth_type"] or "none"),
        "auth_header": str(row["auth_header"] or "X-API-Key"),
        "secret_configured": bool(secret),
        "actions": actions,
        "action_count": len(actions),
        "agent_action_count": sum(1 for a in actions if a.get("enabled") and a.get("agent_enabled")),
        "source": "web_admin",
        "custom": True,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_custom_integrations() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            """
            SELECT id,name,icon,description,enabled,base_url,health_path,
                   auth_type,auth_header,actions_json,created_at,updated_at
            FROM custom_integrations
            ORDER BY lower(name), id
            """
        ).fetchall()
    return [_row_to_public(row) for row in rows]


def custom_runtime_integrations() -> list[dict[str, Any]]:
    items = list_custom_integrations()
    for item in items:
        secret = settings.read_runtime_secret(_secret_name(item["id"]))
        if secret:
            register_secret(secret)
        item["secret"] = secret
    return items


def custom_action_tool_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for item in list_custom_integrations():
        if not item.get("enabled"):
            continue
        for action in item.get("actions") or []:
            if not action.get("enabled") or not action.get("agent_enabled"):
                continue
            specs.append({
                "tool_name": custom_action_tool_name(str(item["id"]), str(action["id"])),
                "integration_id": str(item["id"]),
                "integration_name": str(item["name"]),
                "action": deepcopy(action),
            })
    return specs


def custom_tool_is_read_only(tool_name: str) -> bool:
    for spec in custom_action_tool_specs():
        if spec["tool_name"] == tool_name:
            return str(spec["action"].get("mode")) == "read"
    return False


def create_custom_integration(payload: dict[str, Any]) -> dict[str, Any]:
    clean = _clean_payload(payload)
    secret = str(payload.get("secret") or "").strip()
    if clean["auth_type"] != "none" and secret and len(secret) < 4:
        raise ValueError("Credential/secret is too short")

    with conn() as c:
        exists = c.execute("SELECT 1 FROM custom_integrations WHERE id=?", (clean["id"],)).fetchone()
        if exists:
            raise ValueError(f"Integration ID '{clean['id']}' already exists")
        now = utcnow()
        c.execute(
            """
            INSERT INTO custom_integrations(
              id,name,icon,description,enabled,base_url,health_path,
              auth_type,auth_header,actions_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                clean["id"], clean["name"], clean["icon"], clean["description"],
                1 if clean["enabled"] else 0, clean["base_url"], clean["health_path"],
                clean["auth_type"], clean["auth_header"], json.dumps(clean["actions"], ensure_ascii=False), now, now,
            ),
        )
    if clean["auth_type"] != "none" and secret:
        settings.write_runtime_secret(_secret_name(clean["id"]), secret)
        register_secret(secret)
    info(logger, "custom_integration_created", integration_id=clean["id"], auth_type=clean["auth_type"], actions=len(clean["actions"]))
    return next(item for item in list_custom_integrations() if item["id"] == clean["id"])


def update_custom_integration(integration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    integration_id = _normalize_id(integration_id)
    with conn() as c:
        row = c.execute("SELECT 1 FROM custom_integrations WHERE id=?", (integration_id,)).fetchone()
    if not row:
        raise KeyError(integration_id)

    clean = _clean_payload(payload, existing_id=integration_id)
    secret = str(payload.get("secret") or "").strip()
    clear_secret = bool(payload.get("clear_secret", False))
    if clean["auth_type"] != "none" and secret and len(secret) < 4:
        raise ValueError("Credential/secret is too short")

    with conn() as c:
        c.execute(
            """
            UPDATE custom_integrations SET
              name=?,icon=?,description=?,enabled=?,base_url=?,health_path=?,
              auth_type=?,auth_header=?,actions_json=?,updated_at=?
            WHERE id=?
            """,
            (
                clean["name"], clean["icon"], clean["description"],
                1 if clean["enabled"] else 0, clean["base_url"], clean["health_path"],
                clean["auth_type"], clean["auth_header"], json.dumps(clean["actions"], ensure_ascii=False), utcnow(), integration_id,
            ),
        )

    secret_path = _secret_path(integration_id)
    if clean["auth_type"] == "none" or clear_secret:
        try:
            secret_path.unlink(missing_ok=True)
        except OSError as exc:
            warning(logger, "custom_integration_secret_delete_failed", integration_id=integration_id, error=str(exc))
            raise RuntimeError("Could not remove custom integration credential") from exc
    elif secret:
        settings.write_runtime_secret(_secret_name(integration_id), secret)
        register_secret(secret)

    info(logger, "custom_integration_updated", integration_id=integration_id, auth_type=clean["auth_type"], actions=len(clean["actions"]))
    return next(item for item in list_custom_integrations() if item["id"] == integration_id)


def delete_custom_integration(integration_id: str) -> None:
    integration_id = _normalize_id(integration_id)
    with conn() as c:
        row = c.execute("SELECT 1 FROM custom_integrations WHERE id=?", (integration_id,)).fetchone()
        if not row:
            raise KeyError(integration_id)
        c.execute("DELETE FROM custom_integrations WHERE id=?", (integration_id,))
    try:
        _secret_path(integration_id).unlink(missing_ok=True)
    except OSError as exc:
        warning(logger, "custom_integration_secret_delete_failed", integration_id=integration_id, error=str(exc))
        raise RuntimeError("Integration was removed but its credential file could not be deleted") from exc
    info(logger, "custom_integration_deleted", integration_id=integration_id)
