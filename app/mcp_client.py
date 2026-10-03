from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .observability import exception, get_logger, info, preview, sanitize_url
from .settings import settings

logger = get_logger("mcp")


def load_servers() -> dict:
    p = Path(settings.mcp_config)
    if not p.exists():
        info(logger, "mcp_config_missing", path=str(p))
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    servers = data.get("servers", {}) or {}
    return servers


async def list_server_tools(server_name: str) -> list[dict[str, Any]]:
    server = load_servers().get(server_name)
    if not server:
        raise KeyError(f"Unknown MCP server: {server_name}")
    started = perf_counter()
    info(logger, "mcp_list_tools_started", server=server_name, url=sanitize_url(server["url"]))
    try:
        async with streamable_http_client(server["url"], headers=server.get("headers") or {}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = [{"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema} for t in result.tools]
                info(logger, "mcp_list_tools_completed", server=server_name, count=len(tools), duration_ms=round((perf_counter() - started) * 1000, 2))
                return tools
    except Exception:
        exception(logger, "mcp_list_tools_failed", server=server_name, duration_ms=round((perf_counter() - started) * 1000, 2))
        raise


async def call_server_tool(server_name: str, tool_name: str, arguments: dict) -> Any:
    server = load_servers().get(server_name)
    if not server:
        raise KeyError(f"Unknown MCP server: {server_name}")
    started = perf_counter()
    info(logger, "mcp_tool_started", server=server_name, tool=tool_name, arguments=preview(arguments))
    try:
        async with streamable_http_client(server["url"], headers=server.get("headers") or {}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                content = []
                for item in result.content:
                    content.append(getattr(item, "text", str(item)))
                out = {"isError": bool(result.isError), "content": content}
                info(logger, "mcp_tool_completed", server=server_name, tool=tool_name, is_error=bool(result.isError), duration_ms=round((perf_counter() - started) * 1000, 2), result=preview(out))
                return out
    except Exception:
        exception(logger, "mcp_tool_failed", server=server_name, tool=tool_name, duration_ms=round((perf_counter() - started) * 1000, 2))
        raise
