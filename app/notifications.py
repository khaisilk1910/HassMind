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
CONDITIONAL_NOTIFICATION_PROTOCOL_MARKER = "[HassMind conditional notification protocol]"
_REDUNDANT_RESULT_PREFIX_RE = re.compile(r"^\s*(?:\\?[*_~`]+\s*)?\(\s*Theo(?:\s+đúng)?\s+yêu(?:\s+cầu)?\s*(?:\)?\s*\\?[*_~`]+\s*)*\(?\s*", re.IGNORECASE)
_FEATURE_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")




def should_suppress_notification(value: str | None) -> bool:
    """Return True only for the explicit scheduler/event silent sentinel.

    Exact matching is intentional for callers that do not know the notification
    mode. Conditional Scheduler/Event runs have an additional guarded fallback in
    :func:`should_suppress_actionable_result`.
    """
    return str(value or "").strip() == NO_NOTIFY_TOKEN


def is_actionable_notification_prompt(prompt: str | None) -> bool:
    """Detect the private conditional-notification protocol added at runtime."""
    return CONDITIONAL_NOTIFICATION_PROTOCOL_MARKER in str(prompt or "")


_ACTIONABLE_IMPORTANT_RE = re.compile(
    r"\b(?:"
    r"lỗi|cảnh\s*báo|thất\s*bại|nguy\s*hiểm|mất\s*kết\s*nối|không\s*khả\s*dụng|"
    r"unavailable|unknown|error|failed|failure|cần\s*kiểm\s*tra|chưa\s*(?:được\s*)?xác\s*nhận|"
    r"không\s*xác\s*nhận|bất\s*thường|rò\s*rỉ|rất\s*nóng|quá\s*nóng|quá\s*lạnh"
    r")\b",
    re.IGNORECASE,
)
_ACTIONABLE_ACTION_RE = re.compile(
    r"\b(?:"
    r"đã\s+(?:bật|tắt|đặt|chuyển|điều\s*chỉnh|gửi\s+lệnh|thực\s*hiện|kích\s*hoạt|dừng)|"
    r"vừa\s+(?:bật|tắt|đặt|chuyển|điều\s*chỉnh)|"
    r"service\s*call\s*(?:đã\s*)?(?:thành\s*công|completed)|"
    r"action\s*(?:đã\s*)?(?:thực\s*hiện|executed|completed)"
    r")\b",
    re.IGNORECASE,
)
_ACTIONABLE_NOOP_PATTERNS = (
    re.compile(r"\bkhông\s+phát\s+hiện\b.{0,180}\bcần\s+(?:xử\s*lý|thao\s*tác|điều\s*chỉnh|can\s*thiệp)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bkhông\s+ghi\s+nhận\b.{0,180}\bcần\s+(?:xử\s*lý|thao\s*tác|điều\s*chỉnh|can\s*thiệp)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bkhông\s+có\b.{0,140}\bcần\s+(?:xử\s*lý|thao\s*tác|điều\s*chỉnh|can\s*thiệp|báo)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bkhông\s+cần\s+(?:thực\s*hiện\s+)?(?:action|xử\s*lý|thao\s*tác|điều\s*chỉnh|thay\s*đổi|can\s*thiệp)\b", re.IGNORECASE),
    re.compile(r"\bkhông\s+có\s+(?:action|thao\s*tác|xử\s*lý|thay\s*đổi)\b", re.IGNORECASE),
    re.compile(r"\bkhông\s+có\s+gì\s+cần\s+(?:báo|xử\s*lý|thao\s*tác)\b", re.IGNORECASE),
    re.compile(r"\b(?:mọi\s+thứ|hệ\s*thống|thiết\s*bị)\b.{0,120}\b(?:bình\s*thường|đúng\s+trạng\s*thái|tối\s*ưu)\b.{0,120}\bkhông\s+cần\b", re.IGNORECASE | re.DOTALL),
)


def should_suppress_actionable_result(value: str | None) -> bool:
    """Server-side fallback for conditional notifications.

    The model is instructed to return ``NO_NOTIFY_TOKEN`` for a no-op run, but
    some providers occasionally answer with a natural-language sentence such as
    "Không phát hiện thiết bị nào cần xử lý.". In actionable mode only, suppress
    those strong no-op statements as long as the same result contains no action,
    warning, device/sensor failure, or other condition that the operator should
    see. This keeps ``always`` mode unchanged.
    """
    if should_suppress_notification(value):
        return True
    text = clean_notification_result(value)
    if not text:
        return True
    if _ACTIONABLE_IMPORTANT_RE.search(text) or _ACTIONABLE_ACTION_RE.search(text):
        return False
    return any(pattern.search(text) for pattern in _ACTIONABLE_NOOP_PATTERNS)


def _notification_output_contract(*, include_noop_example: bool = True) -> str:
    text = (
        "Kết quả này sẽ được gửi trực tiếp cho người dùng dưới dạng thông báo. "
        "Hãy trả lời ngắn gọn, trực tiếp vào kết quả thực tế; không mở đầu bằng các câu như "
        "'Theo đúng yêu cầu', 'Theo yêu cầu của bạn' hoặc mô tả lại quy tắc gửi thông báo. "
        "Không bọc toàn bộ câu trả lời trong ngoặc, dấu * hoặc các ký hiệu Markdown. "
    )
    if include_noop_example:
        text += (
            "Nếu không phát hiện thiết bị/sự kiện cần xử lý, hãy nói rõ điều đó bằng một câu tự nhiên, ví dụ "
            "'✅ Không phát hiện thiết bị nào cần xử lý.'"
        )
    return text


def always_notification_prompt(prompt: str) -> str:
    """Add presentation guidance for results that are always delivered."""
    return (
        str(prompt or "").rstrip()
        + "\n\n---\n"
        + "[HassMind notification output protocol]\n"
        + _notification_output_contract()
    )


def actionable_notification_prompt(prompt: str) -> str:
    """Add the private result contract used by conditional Scheduler/Event rules."""
    return (
        str(prompt or "").rstrip()
        + "\n\n---\n"
        + CONDITIONAL_NOTIFICATION_PROTOCOL_MARKER + "\n"
        + "Tác vụ này dùng chế độ chỉ thông báo khi có kết quả cần báo. "
          "Nếu lần chạy không thực hiện action/service nào, không có lỗi/cảnh báo, không có sensor hoặc thiết bị cần kiểm tra, "
          "và kết quả chỉ là trạng thái bình thường/không cần xử lý, thì KHÔNG được viết câu xác nhận trạng thái. "
          f"Hãy trả về DUY NHẤT chuỗi {NO_NOTIFY_TOKEN} và không thêm bất kỳ ký tự nào. "
          "Chỉ gửi nội dung tự nhiên khi thực sự có action, lỗi, cảnh báo, trạng thái bất thường hoặc vấn đề người dùng cần biết. "
        + _notification_output_contract(include_noop_example=False)
    )


def clean_notification_result(value: str | None) -> str:
    """Remove transport-hostile wrappers without rewriting the result semantics.

    Older model outputs occasionally started with malformed text such as
    ``*(Theo đúng yêu*(Hệ thống ...).*``.  That leaked raw markup into mobile
    notifications and made an otherwise useful result look broken.  We only
    strip that redundant meta-prefix plus orphan boundary markers; all actual
    result text is preserved.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    original = text
    text = re.sub(r"\\([*_~`#])", r"\1", text)
    match = _REDUNDANT_RESULT_PREFIX_RE.match(text)
    stripped_meta = bool(match)
    if match:
        text = text[match.end():].lstrip()
    text = re.sub(r"^(?:[*_~`]{1,3}\s*)+", "", text)
    text = re.sub(r"(?:\s*[*_~`]{1,3})+$", "", text).strip()
    if stripped_meta:
        # The malformed prefix usually opens a parenthesis around the real
        # result. Remove only that matching-looking final wrapper.
        text = re.sub(r"\)\s*([.!?])?\s*$", lambda m: (m.group(1) or ""), text).strip()
        text = re.sub(
            r",?\s*(?:đúng\s+)?theo\s+(?:điều\s+kiện|yêu\s+cầu)\s+không\s+(?:được\s+)?gửi\s+thông\s+báo\s*([.!?]?)$",
            lambda m: (m.group(1) or "."),
            text,
            flags=re.IGNORECASE,
        ).strip()
    if text and text[0] not in "#->" and not re.match(r"^[\u2600-\u27BF\U0001F300-\U0001FAFF]", text):
        if re.search(r"\b(?:không phát hiện|không ghi nhận|không có .* cần xử lý|bình thường|hoàn tất|thành công)\b", text, re.IGNORECASE):
            text = "✅ " + text
        elif re.search(r"\b(?:cảnh báo|lỗi|thất bại|nguy hiểm|mất kết nối|không khả dụng)\b", text, re.IGNORECASE):
            text = "⚠️ " + text
    return text or original


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
        clean_message = clean_notification_result(message)
        mobile_message = format_mobile_notification(clean_message)
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
    body = clean_notification_result(message)
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
