from __future__ import annotations

import json
import re
from typing import Any

from .db import conn, utcnow
from .message_format import format_mobile_notification, format_mobile_notification_title, split_zalo_message
from .observability import get_logger, info, warning
from .settings import settings

logger = get_logger("notifications")
VALID_NOTIFICATION_CHANNELS = {"mobile", "zalo"}
NO_NOTIFY_TOKEN = "__HASSMIND_NO_NOTIFY__"
_FEATURE_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")




def should_suppress_notification(value: str | None) -> bool:
    """Return True only for the explicit scheduler/event silent sentinel.

    Exact matching is intentional: ordinary answers such as "không có gì cần báo"
    must never be hidden accidentally.
    """
    return str(value or "").strip() == NO_NOTIFY_TOKEN


def actionable_notification_prompt(prompt: str) -> str:
    """Add the private result contract used by conditional Scheduler jobs."""
    return (
        str(prompt or "").rstrip()
        + "\n\n---\n"
        + "[HassMind Scheduler notification protocol]\n"
        + "Job này dùng chế độ chỉ thông báo khi có kết quả cần báo. "
          "Nếu sau khi kiểm tra/thực hiện tác vụ, theo đúng yêu cầu của người dùng không có nội dung nào được phép gửi thông báo, "
          f"hãy trả về DUY NHẤT chuỗi {NO_NOTIFY_TOKEN} và không thêm bất kỳ ký tự nào. "
          "Chỉ dùng chuỗi này khi điều kiện im lặng trong prompt của người dùng thực sự được thỏa mãn."
    )


def normalize_notification_channel(value: str | None) -> str:
    channel = str(value or "mobile").strip().lower()
    if channel not in VALID_NOTIFICATION_CHANNELS:
        raise ValueError("notify_channel must be mobile or zalo")
    return channel


def _normalize_thread_id(value: str | None) -> str:
    thread_id = str(value or "").strip().removeprefix("zalo:")
    if thread_id == "*":
        return ""
    return thread_id[:255]


def resolve_zalo_thread_id(explicit: str | None = None) -> str:
    """Resolve a notification target without requiring duplicate configuration.

    Priority: per-feature/per-rule thread -> Zalo notification default -> the first
    concrete Allowed thread ID already configured for the Zalo agent. A wildcard
    is never used as an outbound destination.
    """
    explicit_id = _normalize_thread_id(explicit)
    if explicit_id:
        return explicit_id
    configured = _normalize_thread_id(getattr(settings, "zalo_notification_thread_id", ""))
    if configured:
        return configured
    candidates = sorted(x for x in settings.zalo_allowed_thread_ids if x and x != "*")
    return candidates[0] if candidates else ""


def _recent_zalo_thread_type(thread_id: str) -> int | None:
    if not thread_id:
        return None
    try:
        with conn() as c:
            rows = c.execute(
                "SELECT payload FROM events WHERE event_type='zalo_message' AND (entity_id=? OR entity_id=?) ORDER BY id DESC LIMIT 10",
                (thread_id, f"zalo:{thread_id}"),
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                value = payload.get("_threadType", payload.get("threadType", payload.get("type")))
                if value is not None and int(value) in (0, 1):
                    return int(value)
            except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
                continue
    except Exception:
        return None
    return None


def resolve_zalo_thread_type(thread_id: str) -> int:
    recent = _recent_zalo_thread_type(thread_id)
    if recent is not None:
        return recent
    try:
        configured = int(getattr(settings, "zalo_notification_thread_type", 0))
    except (TypeError, ValueError):
        configured = 0
    return configured if configured in (0, 1) else 0


def get_notification_preference(feature: str, *, default_enabled: bool = True, default_channel: str = "mobile") -> dict[str, Any]:
    feature = str(feature or "").strip().lower()
    if not _FEATURE_RE.fullmatch(feature):
        raise ValueError("Invalid notification feature")
    channel = normalize_notification_channel(default_channel)
    try:
        with conn() as c:
            row = c.execute(
                "SELECT enabled,channel,zalo_thread_id,updated_at FROM notification_preferences WHERE feature=?",
                (feature,),
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return {"feature": feature, "enabled": bool(default_enabled), "channel": channel, "zalo_thread_id": "", "updated_at": None}
    try:
        stored_channel = normalize_notification_channel(row["channel"])
    except ValueError:
        stored_channel = channel
    return {
        "feature": feature,
        "enabled": bool(row["enabled"]),
        "channel": stored_channel,
        "zalo_thread_id": _normalize_thread_id(row["zalo_thread_id"]),
        "updated_at": row["updated_at"],
    }


def save_notification_preference(feature: str, *, enabled: bool, channel: str, zalo_thread_id: str = "") -> dict[str, Any]:
    feature = str(feature or "").strip().lower()
    if not _FEATURE_RE.fullmatch(feature):
        raise ValueError("Invalid notification feature")
    channel = normalize_notification_channel(channel)
    thread_id = _normalize_thread_id(zalo_thread_id)
    with conn() as c:
        c.execute(
            """
            INSERT INTO notification_preferences(feature,enabled,channel,zalo_thread_id,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(feature) DO UPDATE SET
              enabled=excluded.enabled,
              channel=excluded.channel,
              zalo_thread_id=excluded.zalo_thread_id,
              updated_at=excluded.updated_at
            """,
            (feature, 1 if enabled else 0, channel, thread_id, utcnow()),
        )
    info(logger, "notification_preference_saved", feature=feature, enabled=enabled, channel=channel, has_explicit_zalo_thread=bool(thread_id))
    return get_notification_preference(feature)


async def send_notification(
    ha,
    integrations,
    message: str,
    *,
    title: str = "HassMind",
    channel: str = "mobile",
    zalo_thread_id: str = "",
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Send one notification through the selected operator-controlled route."""
    channel = normalize_notification_channel(channel)
    if channel == "mobile":
        if ha is None:
            return {"skipped": True, "channel": "mobile", "reason": "Home Assistant client unavailable"}
        mobile_message = format_mobile_notification(message)
        mobile_title = format_mobile_notification_title(title)
        if actions:
            result = await ha.notify(mobile_message, title=mobile_title, actions=actions)
        else:
            result = await ha.notify(mobile_message, title=mobile_title)
        info(logger, "notification_sent", channel="mobile", message_chars=len(mobile_message), actions=bool(actions))
        if isinstance(result, dict):
            return {"channel": "mobile", **result}
        return {"channel": "mobile", "ok": True}

    if not settings.zalo_enabled:
        return {"skipped": True, "channel": "zalo", "reason": "Zalo integration is disabled"}
    if not settings.zalo_allow_send:
        return {"skipped": True, "channel": "zalo", "reason": "Zalo outbound sending is disabled"}
    client = getattr(integrations, "zalo", None) if integrations is not None else None
    if client is None:
        return {"skipped": True, "channel": "zalo", "reason": "Zalo client unavailable"}
    thread_id = resolve_zalo_thread_id(zalo_thread_id)
    if not thread_id:
        warning(logger, "notification_skipped", channel="zalo", reason="no notification thread configured")
        return {"skipped": True, "channel": "zalo", "reason": "No Zalo thread_id configured"}

    # The same rich-text compiler used by normal Zalo chat replies is used by
    # ZaloClient.send_message. Keep source markup here; it will be compiled to
    # msg + zca-js styles and never shown as raw Markdown markers.
    body = str(message or "").strip()
    if actions:
        body = body + "\n\n💡 Mở Web Admin → Approvals để Duyệt hoặc Từ chối thay đổi."
    rich = f"# 📢 {title}\n\n{body}".strip()
    chunks = split_zalo_message(rich) or [rich]
    thread_type = resolve_zalo_thread_type(thread_id)
    for chunk in chunks:
        await client.send_message(
            thread_id=thread_id,
            message=chunk,
            thread_type=thread_type,
            account_selection=settings.zalo_default_account,
        )
    info(logger, "notification_sent", channel="zalo", thread_id=thread_id, thread_type=thread_type, chunks=len(chunks))
    return {"ok": True, "channel": "zalo", "thread_id": thread_id, "thread_type": thread_type, "chunks": len(chunks)}
