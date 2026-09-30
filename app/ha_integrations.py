from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import quote

from .ha import HomeAssistantClient
from .settings import settings


class HAIntegrationBridge:
    """Typed adapters for the uploaded Home Assistant custom components.

    These calls deliberately bypass the generic ha_call_service allowlist only
    for explicitly modeled service names. That prevents an LLM from turning a
    custom-component domain into an unrestricted service tunnel.
    """

    def __init__(self, ha: HomeAssistantClient):
        self.ha = ha

    @staticmethod
    def _service_response(raw: Any) -> Any:
        if isinstance(raw, dict) and "service_response" in raw:
            return raw.get("service_response")
        return raw

    async def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "evn_cskh_monitor": {"ok": False, "status": "not_detected"},
            "am_lich_viet_nam": {"ok": False, "status": "not_detected"},
            "shopping_history": {"ok": False, "status": "not_detected"},
            "yt_dlp": {"ok": False, "status": "not_detected"},
        }
        try:
            ping = await self.ha._get("/api/evncskh/ping")
            out["evn_cskh_monitor"] = {"ok": True, "status": "ok", "data": ping}
        except Exception as exc:
            out["evn_cskh_monitor"]["error"] = f"{type(exc).__name__}: {exc}"

        try:
            services = await self.ha.services()
            by_domain: dict[str, set[str]] = defaultdict(set)
            for item in services if isinstance(services, list) else []:
                domain = str(item.get("domain") or "")
                for service in (item.get("services") or {}).keys():
                    by_domain[domain].add(str(service))
            expectations = {
                "am_lich_viet_nam": {"convert_date"},
                "shopping_history": {"add_order", "edit_order", "delete_order"},
                "yt_dlp": {"search", "play", "get_job"},
            }
            for domain, expected in expectations.items():
                found = by_domain.get(domain, set())
                if found:
                    out[domain] = {
                        "ok": expected.issubset(found),
                        "status": "ok" if expected.issubset(found) else "partial",
                        "services": sorted(found),
                    }
        except Exception as exc:
            for domain in ("am_lich_viet_nam", "shopping_history", "yt_dlp"):
                out[domain].setdefault("error", f"{type(exc).__name__}: {exc}")
        return out

    # EVN CSKH Monitor: authenticated HTTP views exposed by the integration.
    async def evn_accounts(self) -> Any:
        return await self.ha._get("/api/evncskh/options")

    async def evn_summary(self, account: str) -> Any:
        return await self.ha._get(f"/api/evncskh/summary/{quote(account, safe='')}")

    async def evn_daily(self, account: str) -> Any:
        return await self.ha._get(f"/api/evncskh/daily/{quote(account, safe='')}")

    async def evn_monthly(self, account: str) -> Any:
        return await self.ha._get(f"/api/evncskh/monthly/{quote(account, safe='')}")

    # Vietnamese lunar calendar: service supports response=ONLY.
    async def lunar_convert(self, conversion_type: str, day: int, month: int, year: int) -> Any:
        raw = await self.ha.call_service_raw(
            "am_lich_viet_nam",
            "convert_date",
            {
                "conversion_type": conversion_type,
                "day": day,
                "month": month,
                "year": year,
            },
            return_response=True,
        )
        return self._service_response(raw)

    # Shopping History: read detail through its recorder-safe WebSocket API.
    async def shopping_profiles(self) -> list[dict[str, Any]]:
        states = await self.ha.states()
        profiles: dict[str, dict[str, Any]] = {}
        for state in states:
            attrs = state.get("attributes") or {}
            if not attrs.get("shopping_history"):
                continue
            entry_id = str(attrs.get("config_entry_id") or "")
            if not entry_id:
                continue
            profile = profiles.setdefault(
                entry_id,
                {
                    "entry_id": entry_id,
                    "entity_ids": [],
                    "years": [],
                    "friendly_names": [],
                },
            )
            profile["entity_ids"].append(state.get("entity_id"))
            year = attrs.get("nam")
            if isinstance(year, int) and year not in profile["years"]:
                profile["years"].append(year)
            friendly = attrs.get("friendly_name")
            if friendly and friendly not in profile["friendly_names"]:
                profile["friendly_names"].append(friendly)
        for profile in profiles.values():
            profile["years"].sort(reverse=True)
        return list(profiles.values())

    async def shopping_data(self, entry_id: str, year: int | None = None) -> Any:
        command: dict[str, Any] = {"type": "shopping_history/get_data", "entry_id": entry_id}
        if year is not None:
            command["year"] = year
        return await self.ha.ws_command(command)

    def _assert_shopping_mutation(self, delete: bool = False) -> None:
        if not settings.shopping_allow_mutations:
            raise PermissionError("Shopping History mutations are disabled by SHOPPING_ALLOW_MUTATIONS")
        if delete and not settings.shopping_allow_delete:
            raise PermissionError("Shopping History delete is disabled by SHOPPING_ALLOW_DELETE")

    async def shopping_add(self, data: dict[str, Any]) -> Any:
        self._assert_shopping_mutation()
        allowed = {
            "entry_id", "name", "place", "category", "price", "quantity", "vat", "status",
            "model", "manufacturer", "warranty_months", "purchase_date", "note",
        }
        clean = {k: v for k, v in data.items() if k in allowed}
        return await self.ha.call_service_raw("shopping_history", "add_order", clean)

    async def shopping_edit(self, data: dict[str, Any]) -> Any:
        self._assert_shopping_mutation()
        allowed = {
            "entry_id", "order_id", "name", "place", "category", "price", "quantity", "vat", "status",
            "model", "manufacturer", "warranty_months", "purchase_date", "note",
        }
        clean = {k: v for k, v in data.items() if k in allowed}
        return await self.ha.call_service_raw("shopping_history", "edit_order", clean)

    async def shopping_delete(self, entry_id: str, order_id: int) -> Any:
        self._assert_shopping_mutation(delete=True)
        return await self.ha.call_service_raw(
            "shopping_history", "delete_order", {"entry_id": entry_id, "order_id": order_id}
        )

    # yt-dlp services. Search and job lookup are read-only. Playback/download
    # are separately gated because they have side effects.
    async def ytdlp_search(self, query: str, limit: int = 10) -> Any:
        raw = await self.ha.call_service_raw(
            "yt_dlp", "search", {"query": query, "limit": limit}, return_response=True
        )
        return self._service_response(raw)

    async def ytdlp_job(self, job_id: str) -> Any:
        raw = await self.ha.call_service_raw(
            "yt_dlp", "get_job", {"job_id": job_id}, return_response=True
        )
        return self._service_response(raw)

    async def ytdlp_play(self, url: str, media_player: str) -> Any:
        if not settings.ytdlp_allow_playback:
            raise PermissionError("yt-dlp playback is disabled by YTDLP_ALLOW_PLAYBACK")
        raw = await self.ha.call_service_raw(
            "yt_dlp", "play", {"url": url, "media_player": media_player}, return_response=True
        )
        return self._service_response(raw)

    async def ytdlp_download(
        self,
        url: str,
        media_type: str = "video",
        wait_for_completion: bool = False,
    ) -> Any:
        if not settings.ytdlp_allow_downloads:
            raise PermissionError("yt-dlp downloads are disabled by YTDLP_ALLOW_DOWNLOADS")
        raw = await self.ha.call_service_raw(
            "yt_dlp",
            "download",
            {
                "url": url,
                "media_type": media_type,
                "wait_for_completion": wait_for_completion,
            },
            return_response=True,
        )
        return self._service_response(raw)

    # Home Assistant TTS is the compatibility boundary for the Wyoming server.
    # This avoids embedding the Wyoming wire protocol in HassMind itself.
    async def tts_speak(
        self,
        media_player_entity_id: str,
        message: str,
        tts_entity_id: str = "",
        language: str = "",
        options: dict[str, Any] | None = None,
    ) -> Any:
        if not settings.wyoming_allow_tts:
            raise PermissionError("Wyoming/HA TTS actions are disabled by WYOMING_ALLOW_TTS")

        entity = tts_entity_id.strip()
        if not entity:
            registry = await self.ha.entity_registry()
            tts_entries = [e for e in registry if str(e.get("entity_id") or "").startswith("tts.")]
            wyoming_entries = [e for e in tts_entries if str(e.get("platform") or "").lower() == "wyoming"]
            candidates = wyoming_entries or tts_entries
            if len(candidates) != 1:
                ids = [e.get("entity_id") for e in candidates]
                raise ValueError(f"Specify tts_entity_id; candidates={ids}")
            entity = str(candidates[0]["entity_id"])

        data: dict[str, Any] = {
            "entity_id": entity,
            "media_player_entity_id": media_player_entity_id,
            "message": message,
        }
        if language:
            data["language"] = language
        if options:
            data["options"] = options
        return await self.ha.call_service_raw("tts", "speak", data)
