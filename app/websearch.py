from time import perf_counter

import httpx

from .observability import exception, get_logger, info
from .settings import settings

logger = get_logger("websearch")


async def search_web(query: str, limit: int = 5) -> list[dict]:
    if not settings.searxng_url:
        raise RuntimeError("SEARXNG_URL is not configured")
    url = settings.searxng_url.rstrip("/") + "/search"
    started = perf_counter()
    info(logger, "web_search_started", query_chars=len(query), limit=limit, searxng_url=settings.searxng_url)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params={"q": query, "format": "json"})
            r.raise_for_status()
            data = r.json()
        out = []
        for item in (data.get("results") or [])[:limit]:
            out.append({"title": item.get("title"), "url": item.get("url"), "content": item.get("content")})
        info(logger, "web_search_completed", results=len(out), duration_ms=round((perf_counter() - started) * 1000, 2))
        return out
    except Exception:
        exception(logger, "web_search_failed", duration_ms=round((perf_counter() - started) * 1000, 2))
        raise
