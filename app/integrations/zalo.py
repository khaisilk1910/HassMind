from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from .base import IntegrationError, JsonHttpClient


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
    ) -> Any:
        await self.ensure_login()
        selected = await self._select_account(account_selection)
        body: dict[str, Any] = {
            "message": {"msg": message},
            "threadId": str(thread_id).removeprefix("zalo:"),
            "type": int(thread_type),
            "accountSelection": str(selected),
        }
        if ttl is not None and ttl != "":
            body["ttl"] = ttl
        return await self.request("POST", "/api/sendMessageByAccount", json=body)

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
