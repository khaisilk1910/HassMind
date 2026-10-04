from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import conn, utcnow
from .observability import get_logger, info, register_secret, warning
from .settings import settings

logger = get_logger("custom_integrations")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_HEADER_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_AUTH_TYPES = {"none", "bearer", "header"}
_RESERVED_IDS = {"camera_tts", "facedetect", "zalo", "wyoming", "wyoming_vietnamese", "ha_custom"}


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
        raise ValueError("ID chỉ được gồm a-z, 0-9, dấu gạch ngang/gạch dưới và dài 2-64 ký tự")
    return integration_id


def _normalize_url(value: Any) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL phải là URL http/https hợp lệ")
    if parsed.username or parsed.password:
        raise ValueError("Base URL không được chứa username/password")
    return text.rstrip("/")


def _normalize_health_path(value: Any) -> str:
    text = str(value or "/health").strip() or "/health"
    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc or text.startswith("//"):
        raise ValueError("Health path phải là đường dẫn tương đối, ví dụ /health")
    if not text.startswith("/"):
        text = "/" + text
    if len(text) > 512:
        raise ValueError("Health path quá dài")
    return text


def _normalize_auth_type(value: Any) -> str:
    auth_type = str(value or "none").strip().lower()
    if auth_type not in _AUTH_TYPES:
        raise ValueError("Auth type phải là none, bearer hoặc header")
    return auth_type


def _normalize_header(value: Any, auth_type: str) -> str:
    header = str(value or "X-API-Key").strip() or "X-API-Key"
    if auth_type == "header" and not _HEADER_RE.fullmatch(header):
        raise ValueError("Tên HTTP header không hợp lệ")
    return header


def _secret_name(integration_id: str) -> str:
    return f"integration_custom_{integration_id}_secret"


def _secret_path(integration_id: str) -> Path:
    return Path(settings.runtime_secret_dir) / _secret_name(integration_id)


def _clean_payload(payload: dict[str, Any], *, existing_id: str = "") -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Tên Integration không được để trống")
    if len(name) > 120:
        raise ValueError("Tên Integration tối đa 120 ký tự")

    integration_id = _normalize_id(existing_id or str(payload.get("id") or ""), name)
    if not existing_id and integration_id in _RESERVED_IDS:
        raise ValueError(f"Integration ID '{integration_id}' được HassMind dành cho adapter tích hợp sẵn")
    icon = str(payload.get("icon") or "🔌").strip() or "🔌"
    if len(icon) > 16:
        raise ValueError("Icon quá dài")
    description = str(payload.get("description") or "").strip()
    if len(description) > 600:
        raise ValueError("Mô tả tối đa 600 ký tự")
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
    }


def _row_to_public(row: Any) -> dict[str, Any]:
    integration_id = str(row["id"])
    secret = settings.read_runtime_secret(_secret_name(integration_id))
    if secret:
        register_secret(secret)
    return {
        "id": integration_id,
        "name": str(row["name"]),
        "icon": str(row["icon"] or "🔌"),
        "description": str(row["description"] or ""),
        "enabled": bool(row["enabled"]),
        "base_url": str(row["base_url"]),
        "health_path": str(row["health_path"] or "/health"),
        "auth_type": str(row["auth_type"] or "none"),
        "auth_header": str(row["auth_header"] or "X-API-Key"),
        "secret_configured": bool(secret),
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
                   auth_type,auth_header,created_at,updated_at
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


def create_custom_integration(payload: dict[str, Any]) -> dict[str, Any]:
    clean = _clean_payload(payload)
    secret = str(payload.get("secret") or "").strip()
    if clean["auth_type"] != "none" and secret and len(secret) < 4:
        raise ValueError("Credential/secret quá ngắn")

    with conn() as c:
        exists = c.execute("SELECT 1 FROM custom_integrations WHERE id=?", (clean["id"],)).fetchone()
        if exists:
            raise ValueError(f"Integration ID '{clean['id']}' đã tồn tại")
        now = utcnow()
        c.execute(
            """
            INSERT INTO custom_integrations(
              id,name,icon,description,enabled,base_url,health_path,
              auth_type,auth_header,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                clean["id"], clean["name"], clean["icon"], clean["description"],
                1 if clean["enabled"] else 0, clean["base_url"], clean["health_path"],
                clean["auth_type"], clean["auth_header"], now, now,
            ),
        )
    if clean["auth_type"] != "none" and secret:
        settings.write_runtime_secret(_secret_name(clean["id"]), secret)
        register_secret(secret)
    info(logger, "custom_integration_created", integration_id=clean["id"], auth_type=clean["auth_type"])
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
        raise ValueError("Credential/secret quá ngắn")

    with conn() as c:
        c.execute(
            """
            UPDATE custom_integrations SET
              name=?,icon=?,description=?,enabled=?,base_url=?,health_path=?,
              auth_type=?,auth_header=?,updated_at=?
            WHERE id=?
            """,
            (
                clean["name"], clean["icon"], clean["description"],
                1 if clean["enabled"] else 0, clean["base_url"], clean["health_path"],
                clean["auth_type"], clean["auth_header"], utcnow(), integration_id,
            ),
        )

    secret_path = _secret_path(integration_id)
    if clean["auth_type"] == "none" or clear_secret:
        try:
            secret_path.unlink(missing_ok=True)
        except OSError as exc:
            warning(logger, "custom_integration_secret_delete_failed", integration_id=integration_id, error=str(exc))
            raise RuntimeError("Không thể xóa credential của Integration") from exc
    elif secret:
        settings.write_runtime_secret(_secret_name(integration_id), secret)
        register_secret(secret)

    info(logger, "custom_integration_updated", integration_id=integration_id, auth_type=clean["auth_type"])
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
        raise RuntimeError("Integration đã bị xóa nhưng không thể xóa file credential") from exc
    info(logger, "custom_integration_deleted", integration_id=integration_id)
