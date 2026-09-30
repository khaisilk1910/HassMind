import httpx
from .settings import settings


async def search_web(query: str, limit: int = 5) -> list[dict]:
    if not settings.searxng_url:
        raise RuntimeError("SEARXNG_URL is not configured")
    url = settings.searxng_url.rstrip("/") + "/search"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params={"q": query, "format": "json"})
        r.raise_for_status()
        data = r.json()
    out = []
    for item in (data.get("results") or [])[:limit]:
        out.append({"title": item.get("title"), "url": item.get("url"), "content": item.get("content")})
    return out
