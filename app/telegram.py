import asyncio
from time import perf_counter
from typing import Awaitable, Callable

import httpx

from .observability import exception, get_logger, info, log_context, warning
from .settings import settings

ChatHandler = Callable[[str, str, str], Awaitable[str]]
logger = get_logger("telegram")


async def telegram_loop(stop: asyncio.Event, handle_chat: ChatHandler):
    token = settings.read_telegram_token()
    if not token:
        info(logger, "telegram_disabled", reason="token is empty")
        return
    base = f"https://api.telegram.org/bot{token}"
    offset = 0
    info(logger, "telegram_started", allowed_chat_ids_count=len(settings.telegram_allowed_ids))
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
                    if settings.telegram_allowed_ids and chat_id not in settings.telegram_allowed_ids:
                        warning(logger, "telegram_message_rejected", chat_id=chat_id, reason="chat id not allowed")
                        continue
                    sid = f"telegram:{chat_id}"
                    with log_context(session_id=sid, source="telegram", component="telegram"):
                        info(logger, "telegram_message_started", chat_id=chat_id, text_chars=len(text))
                        answer = await handle_chat(sid, text, "telegram")
                        send = await client.post(base + "/sendMessage", json={"chat_id": chat_id, "text": answer[:4000]})
                        send.raise_for_status()
                        info(logger, "telegram_message_completed", chat_id=chat_id, answer_chars=len(answer))
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
