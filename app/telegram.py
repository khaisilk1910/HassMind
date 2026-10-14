import asyncio
import hashlib
import time
from time import perf_counter
from typing import Awaitable, Callable

import httpx

from .observability import exception, get_logger, info, log_context, register_secret, warning
from .settings import settings

ChatHandler = Callable[[str, str, str], Awaitable[str]]
logger = get_logger("telegram")


def _config_signature() -> tuple[bool, str, tuple[str, ...], tuple[str, ...]]:
    token = settings.read_telegram_token()
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else ""
    return bool(settings.telegram_enabled), digest, tuple(sorted(settings.telegram_allowed_ids)), tuple(sorted(settings.telegram_allowed_users))


def telegram_message_allowed(msg: dict) -> tuple[bool, str]:
    """Deny by default. A group needs BOTH an allowed chat and sender user ID."""
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    chat_id = str(chat.get("id") or "")
    sender_id = str(sender.get("id") or "")
    chat_type = str(chat.get("type") or "")
    if not settings.telegram_allowed_ids or chat_id not in settings.telegram_allowed_ids:
        return False, "chat_not_allowlisted"
    if not sender_id or msg.get("sender_chat") or sender.get("is_bot"):
        return False, "sender_not_verified"
    allowed_users = settings.telegram_allowed_users
    if chat_type == "private":
        if sender_id != chat_id or (allowed_users and sender_id not in allowed_users):
            return False, "private_sender_mismatch"
    elif chat_type in {"group", "supergroup"}:
        if not allowed_users or sender_id not in allowed_users:
            return False, "group_sender_not_allowlisted"
    else:
        return False, "unsupported_chat_type"
    message_date = msg.get("date")
    try:
        age = time.time() - float(message_date)
    except (TypeError, ValueError):
        return False, "missing_message_timestamp"
    if age > settings.telegram_max_message_age_seconds or age < -60:
        return False, "stale_or_future_message"
    return True, "ok"


async def telegram_health(timeout: float = 3.0) -> dict:
    if not settings.telegram_enabled:
        return {"enabled": False, "ok": False, "status": "disabled"}
    token = settings.read_telegram_token()
    if not token:
        return {"enabled": True, "ok": False, "status": "missing_token", "error": "Bot token is not configured"}
    register_secret(token)
    try:
        async with httpx.AsyncClient(base_url="https://api.telegram.org", timeout=timeout, follow_redirects=False) as client:
            response = await client.get(f"/bot{token}/getMe")
            payload = response.json() if response.content else {}
        if response.status_code >= 400 or not isinstance(payload, dict) or not payload.get("ok"):
            description = payload.get("description") if isinstance(payload, dict) else "Telegram Bot API error"
            return {"enabled": True, "ok": False, "status": "error", "error": str(description or "Telegram Bot API error")[:300]}
        bot = payload.get("result") or {}
        return {
            "enabled": True,
            "ok": True,
            "status": "ok",
            "bot_id": bot.get("id"),
            "username": bot.get("username"),
            "name": bot.get("first_name"),
            "allowed_chat_ids_count": len(settings.telegram_allowed_ids),
            "allowed_user_ids_count": len(settings.telegram_allowed_users),
        }
    except Exception as exc:
        return {"enabled": True, "ok": False, "status": "unreachable", "error": f"{type(exc).__name__}: {exc}"[:300]}


async def telegram_loop(stop: asyncio.Event, handle_chat: ChatHandler):
    if not settings.telegram_enabled:
        info(logger, "telegram_disabled", reason="integration disabled")
        return
    token = settings.read_telegram_token()
    if not token:
        info(logger, "telegram_disabled", reason="token is empty")
        return
    register_secret(token)
    base = f"https://api.telegram.org/bot{token}"
    offset = 0
    info(logger, "telegram_started", allowed_chat_ids_count=len(settings.telegram_allowed_ids), allowed_user_ids_count=len(settings.telegram_allowed_users))
    async with httpx.AsyncClient(timeout=40) as client:
        while not stop.is_set():
            try:
                poll_started = perf_counter()
                r = await client.get(base + "/getUpdates", params={"timeout": 25, "offset": offset})
                r.raise_for_status()
                updates = r.json().get("result", [])
                if updates:
                    info(logger, "telegram_updates_received", count=len(updates), duration_ms=round((perf_counter() - poll_started) * 1000, 2))
                for upd in updates:
                    offset = max(offset, int(upd["update_id"]) + 1)
                    msg = upd.get("message") or {}
                    text = msg.get("text")
                    chat_id = str((msg.get("chat") or {}).get("id", ""))
                    if not text or not chat_id:
                        continue
                    permitted, reason = telegram_message_allowed(msg)
                    if not permitted:
                        warning(logger, "telegram_message_rejected", chat_id=chat_id, reason=reason)
                        continue
                    sid = f"telegram:{chat_id}"
                    with log_context(session_id=sid, source="telegram", component="telegram"):
                        info(logger, "telegram_message_started", chat_id=chat_id, text_chars=len(text))
                        answer = await handle_chat(sid, text, "telegram")
                        chunks = [answer[i:i + 4000] for i in range(0, len(answer), 4000)] or [""]
                        for chunk in chunks:
                            send = await client.post(base + "/sendMessage", json={"chat_id": chat_id, "text": chunk})
                            send.raise_for_status()
                        info(logger, "telegram_message_completed", chat_id=chat_id, answer_chars=len(answer), chunks=len(chunks))
            except asyncio.CancelledError:
                info(logger, "telegram_cancelled")
                raise
            except Exception:
                exception(logger, "telegram_loop_error", message="Telegram polling or reply failed")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
    info(logger, "telegram_stopped")


async def telegram_supervisor(stop: asyncio.Event, handle_chat: ChatHandler):
    """Restart Telegram polling when Web Admin changes enable/token/chat policy."""
    child: asyncio.Task | None = None
    child_stop: asyncio.Event | None = None
    last_signature: tuple[bool, str, tuple[str, ...], tuple[str, ...]] | None = None
    info(logger, "telegram_supervisor_started")
    try:
        while not stop.is_set():
            signature = _config_signature()
            if signature != last_signature:
                if child_stop is not None:
                    child_stop.set()
                if child is not None:
                    child.cancel()
                    await asyncio.gather(child, return_exceptions=True)
                child = None
                child_stop = None
                last_signature = signature
                enabled, token_digest, allowed, allowed_users = signature
                if enabled and token_digest:
                    child_stop = asyncio.Event()
                    child = asyncio.create_task(telegram_loop(child_stop, handle_chat), name="telegram-poll")
                    info(logger, "telegram_supervisor_reconfigured", enabled=True, allowed_chat_ids_count=len(allowed), allowed_user_ids_count=len(allowed_users))
                else:
                    info(logger, "telegram_supervisor_reconfigured", enabled=enabled, token_configured=bool(token_digest))
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        raise
    finally:
        if child_stop is not None:
            child_stop.set()
        if child is not None:
            child.cancel()
            await asyncio.gather(child, return_exceptions=True)
        info(logger, "telegram_supervisor_stopped")
