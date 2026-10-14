from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from .base import IntegrationError, JsonHttpClient
from ..message_format import build_zalo_message_content
from ..observability import get_logger, info, warning

logger = get_logger("zalo")


class ZaloClient(JsonHttpClient):
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 15.0):
        super().__init__(base_url, timeout=timeout)
        self.username = username
        self.password = password
        self._login_lock = asyncio.Lock()

    async def health(self, timeout: float = 3.0) -> dict[str, Any]:
        data = await self.request("GET", "/api/health", timeout=timeout)
        return data if isinstance(data, dict) else {"status": "unknown", "data": data}

    async def _authenticated(self) -> bool:
        try:
            data = await self.request("GET", "/api/check-auth")
        except IntegrationError:
            return False
        if not isinstance(data, dict):
            return False
        return bool(data.get("authenticated") or data.get("success") and data.get("user"))

    async def ensure_login(self) -> None:
        if await self._authenticated():
            return
        if not self.username or not self.password:
            raise IntegrationError("Zalo API username/password is not configured")
        async with self._login_lock:
            if await self._authenticated():
                return
            data = await self.request(
                "POST",
                "/api/login",
                json={"username": self.username, "password": self.password},
            )
            if not isinstance(data, dict) or not data.get("success"):
                raise IntegrationError(f"Zalo API login failed: {data}")

    async def accounts(self) -> list[dict[str, Any]]:
        await self.ensure_login()
        data = await self.request("GET", "/api/accounts")
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        raise IntegrationError(f"Unexpected Zalo accounts response: {data}")

    async def _select_account(self, requested: str = "") -> str:
        if requested:
            return requested
        accounts = await self.accounts()
        online = [a for a in accounts if a.get("isOnline")]
        candidates = online or accounts
        if len(candidates) == 1:
            return str(candidates[0].get("ownId") or candidates[0].get("phoneNumber") or "")
        if not candidates:
            raise IntegrationError("No logged Zalo account is available")
        raise IntegrationError("Multiple Zalo accounts are available; specify account_selection or ZALO_DEFAULT_ACCOUNT")

    async def send_message(
        self,
        *,
        thread_id: str,
        message: str,
        thread_type: int,
        account_selection: str = "",
        ttl: str | int | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> Any:
        await self.ensure_login()
        selected = await self._select_account(account_selection)
        message_content = build_zalo_message_content(message)
        info(
            logger,
            "zalo_rich_text_compiled",
            msg_chars=len(str(message_content.get("msg") or "")),
            styles_count=len(message_content.get("styles") or []),
        )
        body: dict[str, Any] = {
            "message": message_content,
            "threadId": str(thread_id).removeprefix("zalo:"),
            "type": int(thread_type),
            "accountSelection": str(selected),
        }
        if attachments:
            raise IntegrationError("Use send_image() for Zalo photos; remote image URLs must go through /api/sendImageByAccount")
        if ttl is not None and ttl != "":
            body["ttl"] = ttl
        try:
            result = await self.request("POST", "/api/sendMessageByAccount", json=body)
            return result
        except IntegrationError as exc:
            # Older companion servers may validate `message` as msg-only. If
            # they explicitly reject the new styles field, retry once with the
            # already-compiled plain text. Do not retry timeouts/5xx because an
            # ambiguous transport failure could duplicate a message.
            detail = str(exc)
            if message_content.get("styles") and ("HTTP 400 " in detail or "HTTP 422 " in detail):
                warning(
                    logger,
                    "zalo_rich_text_styles_rejected",
                    message="Zalo companion rejected styles; retrying once with compiled plain text",
                )
                fallback = dict(body)
                fallback["message"] = {"msg": message_content["msg"]}
                return await self.request("POST", "/api/sendMessageByAccount", json=fallback)
            raise

    async def send_image(
        self, *, thread_id: str, image_url: str, thread_type: int,
        account_selection: str = "", message: str = "",
    ) -> Any:
        """Use the companion's actual URL-to-local-file image transport.

        zca-js requires a local filename (or a supported upload source), not an
        arbitrary URL/filename object in sendMessage.attachments.
        """
        await self.ensure_login()
        selected = await self._select_account(account_selection)
        result = await self.request(
            "POST", "/api/sendImageByAccount",
            json={"imagePath": image_url, "threadId": str(thread_id).removeprefix("zalo:"),
                  "type": int(thread_type), "accountSelection": str(selected), "message": message},
            timeout=40,
        )
        if not isinstance(result, dict) or result.get("success") is not True:
            raise IntegrationError(f"Zalo image upload rejected: {result}")
        receipt = result.get("data")
        if isinstance(receipt, dict) and isinstance(receipt.get("attachment"), list) and not receipt["attachment"]:
            raise IntegrationError("Zalo returned an empty attachment receipt")
        if result.get('deliveryStatus') not in (None, 'accepted'):
            raise IntegrationError(f"Zalo image send was not confirmed ({result['deliveryStatus']})")
        return result

    async def download_incoming_image(self, token: str) -> bytes:
        """Read an authenticated temporary photo captured by zalo-bot-server."""
        import re
        if not re.fullmatch(r"[0-9a-f]{48}", token):
            raise IntegrationError("Invalid incoming image token")
        await self.ensure_login()
        try:
            async with self.client.stream("GET", f"/api/incomingImage/{token}", timeout=20) as response:
                if response.status_code != 200:
                    raise IntegrationError(f"Zalo image relay HTTP {response.status_code}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 15 * 1024 * 1024:
                        raise IntegrationError("Incoming image exceeds 15 MB")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise IntegrationError("Zalo image relay connection failed") from exc

    async def get_webhook_account(self, own_id: str) -> dict[str, Any] | None:
        await self.ensure_login()
        data = await self.request(
            "GET",
            f"/api/webhook-accounts/{quote(str(own_id), safe='')}",
            allow_404=True,
        )
        if data is None:
            return None
        if isinstance(data, dict) and data.get("success"):
            payload = data.get("data")
            return payload if isinstance(payload, dict) else None
        return None

    async def ensure_hassmind_webhooks(self, callback_url: str) -> dict[str, Any]:
        """Add one message webhook per logged account without deleting other destinations."""
        await self.ensure_login()
        accounts = await self.accounts()
        results: list[dict[str, Any]] = []
        for account in accounts:
            own_id = str(account.get("ownId") or "").strip()
            if not own_id:
                continue
            config = await self.get_webhook_account(own_id)
            if config is None:
                created_account = await self.request(
                    "POST",
                    "/api/webhook-accounts",
                    json={"ownId": own_id, "label": "HassMind auto registration"},
                )
                if not isinstance(created_account, dict) or not created_account.get("success"):
                    results.append({"ownId": own_id, "status": "account_create_failed"})
                    continue
                config = created_account.get("data") or {}

            webhooks = config.get("webhooks") if isinstance(config, dict) else []
            if not isinstance(webhooks, list):
                webhooks = []
            existing = next(
                (
                    item
                    for item in webhooks
                    if isinstance(item, dict)
                    and item.get("url") == callback_url
                    and "message" in (item.get("events") or [])
                ),
                None,
            )
            if existing:
                results.append({"ownId": own_id, "status": "exists", "webhookId": existing.get("id")})
                continue

            created = await self.request(
                "POST",
                f"/api/webhook-accounts/{quote(own_id, safe='')}/webhooks",
                json={
                    "name": "HassMind",
                    "url": callback_url,
                    "events": ["message"],
                    "enabled": True,
                },
            )
            results.append(
                {
                    "ownId": own_id,
                    "status": "created" if isinstance(created, dict) and created.get("success") else "failed",
                    "webhookId": (created.get("data") or {}).get("id") if isinstance(created, dict) else None,
                }
            )
        return {"callback_url": callback_url, "accounts": results}
