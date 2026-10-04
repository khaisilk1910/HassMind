from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .custom_integrations import list_custom_integrations
from .db import conn, utcnow
from .observability import get_logger, info, register_secret, warning
from .settings import Settings, settings

logger = get_logger("integration_config")


# The UI is generated from this catalog. Adding a new code-backed adapter only
# requires declaring its editable settings here; no stack/environment editing is
# required by the operator afterwards.
INTEGRATION_CATALOG: dict[str, dict[str, Any]] = {
    "camera_tts": {
        "name": "Camera TTS EZVIZ",
        "icon": "🔊",
        "kind": "companion",
        "description": "Phát TTS/media và điều khiển PTZ qua camera-tts-ezviz.",
        "fields": [
            {"name": "enabled", "setting": "camera_tts_enabled", "type": "boolean", "label": "Bật integration"},
            {"name": "url", "setting": "camera_tts_url", "type": "url", "label": "Base URL", "placeholder": "http://127.0.0.1:8124"},
            {"name": "api_key", "type": "secret", "label": "API key", "secret_name": "integration_camera_tts_api_key", "secret_reader": "read_camera_tts_key"},
            {"name": "allow_actions", "setting": "camera_tts_allow_actions", "type": "boolean", "label": "Cho phép TTS/media/PTZ"},
        ],
    },
    "facedetect": {
        "name": "IRIS FaceDetect",
        "icon": "👤",
        "kind": "companion",
        "description": "Đọc health, nhận diện, people và camera từ FaceDetect.",
        "fields": [
            {"name": "enabled", "setting": "facedetect_enabled", "type": "boolean", "label": "Bật integration"},
            {"name": "url", "setting": "facedetect_url", "type": "url", "label": "Base URL", "placeholder": "http://127.0.0.1:8181"},
        ],
    },
    "zalo": {
        "name": "Zalo Bot Server",
        "icon": "💬",
        "kind": "companion",
        "description": "Đọc tài khoản Zalo, gửi tin nhắn và nhận webhook có kiểm soát.",
        "fields": [
            {"name": "enabled", "setting": "zalo_enabled", "type": "boolean", "label": "Bật integration"},
            {"name": "url", "setting": "zalo_url", "type": "url", "label": "Base URL", "placeholder": "http://127.0.0.1:3100"},
            {"name": "username", "setting": "zalo_username", "type": "text", "label": "Username"},
            {"name": "password", "type": "secret", "label": "Password", "secret_name": "integration_zalo_password", "secret_reader": "read_zalo_password"},
            {"name": "default_account", "setting": "zalo_default_account", "type": "text", "label": "Default account ID", "placeholder": "Để trống nếu chỉ có 1 account"},
            {"name": "allow_send", "setting": "zalo_allow_send", "type": "boolean", "label": "Cho phép gửi tin nhắn"},
            {"name": "webhook_enabled", "setting": "zalo_webhook_enabled", "type": "boolean", "label": "Bật webhook nhận tin"},
            {"name": "webhook_secret", "type": "secret", "label": "Webhook secret", "secret_name": "integration_zalo_webhook_secret", "secret_reader": "read_zalo_webhook_secret"},
            {"name": "auto_register_webhook", "setting": "zalo_auto_register_webhook", "type": "boolean", "label": "Tự đăng ký webhook"},
            {"name": "webhook_callback_base", "setting": "zalo_webhook_callback_base", "type": "url", "label": "Callback base URL", "placeholder": "http://127.0.0.1:8090"},
            {"name": "agent_reply_enabled", "setting": "zalo_agent_reply_enabled", "type": "boolean", "label": "Cho phép Agent tự trả lời"},
            {"name": "agent_allowed_thread_ids", "setting": "zalo_agent_allowed_thread_ids", "type": "text", "label": "Allowed thread IDs", "placeholder": "id1,id2 hoặc *"},
            {"name": "notification_thread_id", "setting": "zalo_notification_thread_id", "type": "text", "label": "Thread ID thông báo mặc định", "placeholder": "Để trống = dùng thread cụ thể đầu tiên trong Allowed thread IDs"},
            {"name": "notification_thread_type", "setting": "zalo_notification_thread_type", "type": "integer", "label": "Loại thread thông báo (0=user, 1=group)", "min": 0, "max": 1},
        ],
    },
    "telegram": {
        "name": "Telegram Bot",
        "icon": "\U0001f4e8",
        "kind": "messaging",
        "description": "Nh\u1eadn tin nh\u1eafn Telegram, chuy\u1ec3n v\u00e0o HassMind Agent v\u00e0 tr\u1ea3 l\u1eddi qua Bot API.",
        "fields": [
            {"name": "enabled", "setting": "telegram_enabled", "type": "boolean", "label": "B\u1eadt integration"},
            {"name": "bot_token", "type": "secret", "label": "Bot token", "secret_name": "integration_telegram_bot_token", "secret_reader": "read_telegram_token"},
            {"name": "allowed_chat_ids", "setting": "telegram_allowed_chat_ids", "type": "text", "label": "Allowed chat IDs", "placeholder": "123456789,-1001234567890; \u0111\u1ec3 tr\u1ed1ng = cho ph\u00e9p m\u1ecdi chat"},
        ],
    },
    "wyoming": {
        "name": "Wyoming Vietnamese TTS",
        "icon": "🗣️",
        "kind": "companion",
        "description": "Health-check Wyoming và phát TTS qua Home Assistant tts.speak.",
        "fields": [
            {"name": "enabled", "setting": "wyoming_enabled", "type": "boolean", "label": "Bật integration"},
            {"name": "host", "setting": "wyoming_host", "type": "text", "label": "Host", "placeholder": "127.0.0.1"},
            {"name": "port", "setting": "wyoming_port", "type": "integer", "label": "Port", "min": 1, "max": 65535},
            {"name": "allow_tts", "setting": "wyoming_allow_tts", "type": "boolean", "label": "Cho phép TTS"},
            {"name": "tts_entity_id", "setting": "wyoming_tts_entity_id", "type": "text", "label": "Home Assistant TTS entity", "placeholder": "tts.piper (khuyến nghị cấu hình để phát nhanh và ổn định)"},
        ],
    },
    "ha_custom": {
        "name": "Home Assistant Custom Components",
        "icon": "🏠",
        "kind": "home_assistant",
        "description": "Adapter typed cho EVN, Âm lịch, Shopping History và yt-dlp trong Home Assistant.",
        "fields": [
            {"name": "enabled", "setting": "ha_custom_integrations_enabled", "type": "boolean", "label": "Bật nhóm custom component"},
            {"name": "shopping_allow_mutations", "setting": "shopping_allow_mutations", "type": "boolean", "label": "Shopping: cho phép thêm/sửa"},
            {"name": "shopping_allow_delete", "setting": "shopping_allow_delete", "type": "boolean", "label": "Shopping: cho phép xóa"},
            {"name": "ytdlp_allow_playback", "setting": "ytdlp_allow_playback", "type": "boolean", "label": "yt-dlp: cho phép phát"},
            {"name": "ytdlp_allow_downloads", "setting": "ytdlp_allow_downloads", "type": "boolean", "label": "yt-dlp: cho phép tải"},
        ],
    },
}


def _runtime_secret_path(name: str) -> Path:
    return Path(settings.runtime_secret_dir) / name


def _saved_rows() -> dict[str, dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT integration_id, config_json FROM integration_settings").fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            value = json.loads(row["config_json"])
        except (TypeError, json.JSONDecodeError):
            warning(logger, "integration_config_invalid_json", integration_id=row["integration_id"])
            continue
        if isinstance(value, dict):
            result[str(row["integration_id"])] = value
    return result


def _coerce(field: dict[str, Any], value: Any) -> Any:
    kind = field["type"]
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ValueError(f"{field['name']} must be boolean")
    if kind == "integer":
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field['name']} must be integer") from exc
        minimum = field.get("min")
        maximum = field.get("max")
        if minimum is not None and number < minimum:
            raise ValueError(f"{field['name']} must be >= {minimum}")
        if maximum is not None and number > maximum:
            raise ValueError(f"{field['name']} must be <= {maximum}")
        return number
    text = str(value or "").strip()
    if kind == "url":
        if not text:
            raise ValueError(f"{field['name']} must not be empty")
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{field['name']} must be an http/https URL")
        if parsed.username or parsed.password:
            raise ValueError(f"{field['name']} must not contain credentials")
        return text.rstrip("/")
    return text


def load_runtime_integration_overrides() -> None:
    rows = _saved_rows()
    applied = 0
    for integration_id, values in rows.items():
        definition = INTEGRATION_CATALOG.get(integration_id)
        if not definition:
            continue
        by_name = {field["name"]: field for field in definition["fields"] if field["type"] != "secret"}
        for name, value in values.items():
            field = by_name.get(name)
            if not field:
                continue
            try:
                clean = _coerce(field, value)
            except ValueError as exc:
                warning(logger, "integration_config_override_skipped", integration_id=integration_id, field=name, error=str(exc))
                continue
            setattr(settings, field["setting"], clean)
            applied += 1
    # Register runtime integration secrets so logging redaction covers them.
    for definition in INTEGRATION_CATALOG.values():
        for field in definition["fields"]:
            if field["type"] != "secret":
                continue
            secret = settings.read_runtime_secret(field["secret_name"])
            if secret:
                register_secret(secret)
    info(logger, "integration_config_overrides_loaded", integrations=len(rows), fields=applied)


def _secret_status(field: dict[str, Any]) -> tuple[bool, str]:
    runtime_value = settings.read_runtime_secret(field["secret_name"])
    if runtime_value:
        return True, "web_admin"
    reader = getattr(settings, field["secret_reader"])
    value = reader()
    return bool(value), "stack_or_secret" if value else "missing"


def integration_config_view() -> dict[str, Any]:
    saved = _saved_rows()
    integrations: list[dict[str, Any]] = []
    for integration_id, definition in INTEGRATION_CATALOG.items():
        item = {
            "id": integration_id,
            "name": definition["name"],
            "icon": definition["icon"],
            "kind": definition["kind"],
            "description": definition["description"],
            "source": "web_admin" if integration_id in saved else "stack_or_default",
            "fields": [],
        }
        for field in definition["fields"]:
            public = {k: deepcopy(v) for k, v in field.items() if k not in {"setting", "secret_name", "secret_reader"}}
            if field["type"] == "secret":
                configured, source = _secret_status(field)
                public.update({"configured": configured, "source": source, "value": ""})
            else:
                public["value"] = getattr(settings, field["setting"])
            item["fields"].append(public)
        integrations.append(item)
    return {
        "integrations": integrations,
        "custom_integrations": list_custom_integrations(),
        "storage": {
            "config": settings.db_path,
            "secrets": settings.runtime_secret_dir,
            "note": "Web Admin overrides stack/default values. Secret values are never returned by the API.",
        },
    }


def save_integration_config(integration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    definition = INTEGRATION_CATALOG.get(integration_id)
    if not definition:
        raise KeyError(integration_id)
    fields = {field["name"]: field for field in definition["fields"]}
    unknown = set(payload) - set(fields)
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    persisted: dict[str, Any] = {}
    for name, field in fields.items():
        if field["type"] == "secret":
            raw = payload.get(name)
            if raw is None or str(raw).strip() == "":
                continue
            secret = str(raw).strip()
            if len(secret) < 4:
                raise ValueError(f"{name} is too short")
            settings.write_runtime_secret(field["secret_name"], secret)
            register_secret(secret)
            continue

        # PUT is full-form semantics. Missing fields retain their effective value
        # so older/newer UIs remain forward compatible.
        raw = payload[name] if name in payload else getattr(settings, field["setting"])
        clean = _coerce(field, raw)
        persisted[name] = clean
        setattr(settings, field["setting"], clean)

    with conn() as c:
        c.execute(
            """
            INSERT INTO integration_settings(integration_id, config_json, updated_at)
            VALUES(?,?,?)
            ON CONFLICT(integration_id) DO UPDATE SET
              config_json=excluded.config_json,
              updated_at=excluded.updated_at
            """,
            (integration_id, json.dumps(persisted, ensure_ascii=False), utcnow()),
        )
    info(logger, "integration_config_saved", integration_id=integration_id, fields=sorted(persisted))
    return integration_config_view()


def reset_integration_config(integration_id: str) -> dict[str, Any]:
    definition = INTEGRATION_CATALOG.get(integration_id)
    if not definition:
        raise KeyError(integration_id)
    baseline = Settings()

    # Remove runtime secret overrides first. If deletion fails, keep the DB
    # override intact so the UI never reports a successful reset while an old
    # runtime credential is still taking precedence.
    for field in definition["fields"]:
        if field["type"] != "secret":
            continue
        path = _runtime_secret_path(field["secret_name"])
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            warning(logger, "integration_runtime_secret_delete_failed", integration_id=integration_id, field=field["name"], error=str(exc))
            raise RuntimeError(f"Could not remove runtime secret for {field['name']}") from exc

    with conn() as c:
        c.execute("DELETE FROM integration_settings WHERE integration_id=?", (integration_id,))
    for field in definition["fields"]:
        if field["type"] != "secret":
            setattr(settings, field["setting"], getattr(baseline, field["setting"]))
    info(logger, "integration_config_reset", integration_id=integration_id)
    return integration_config_view()
