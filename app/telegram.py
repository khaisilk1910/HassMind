import asyncio
import httpx
from typing import Awaitable, Callable
from .settings import settings

ChatHandler = Callable[[str, str, str], Awaitable[str]]


async def telegram_loop(stop: asyncio.Event, handle_chat: ChatHandler):
    token = settings.read_telegram_token()
    if not token:
        return
    base = f"https://api.telegram.org/bot{token}"
    offset = 0
    async with httpx.AsyncClient(timeout=40) as client:
        while not stop.is_set():
            try:
                r = await client.get(base + "/getUpdates", params={"timeout": 25, "offset": offset})
                r.raise_for_status()
                for upd in r.json().get("result", []):
                    offset = max(offset, int(upd["update_id"]) + 1)
                    msg = upd.get("message") or {}
                    text = msg.get("text")
                    chat_id = str((msg.get("chat") or {}).get("id", ""))
                    if not text or not chat_id:
                        continue
                    if settings.telegram_allowed_ids and chat_id not in settings.telegram_allowed_ids:
                        continue
                    answer = await handle_chat(f"telegram:{chat_id}", text, "telegram")
                    await client.post(base + "/sendMessage", json={"chat_id": chat_id, "text": answer[:4000]})
            except Exception:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
