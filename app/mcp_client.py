from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .mcp_connections import mcp_servers_runtime, list_mcp_connections
from .observability import exception, get_logger, info, preview, sanitize_url
from .settings import settings

logger = get_logger("mcp")


def load_servers() -> dict:
    p = Path(settings.mcp_config)
    servers = {}
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        servers = data.get("servers", {}) or {}
    # A disabled Web Admin entry must also shadow an older YAML server of the
    # same name; otherwise the legacy route could bypass the managed allowlist.
    try:
        for item in list_mcp_connections():
            servers.pop(item["id"], None)
        servers.update(mcp_servers_runtime())
    except __import__("sqlite3").OperationalError as exc:
        if "no such table" not in str(exc):
            raise
    # Managed servers enforce per-tool opt-in (legacy YAML is unchanged).
    return servers


async def discover_mcp_tools(url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """MCP protocol discovery (initialize + tools/list only, never tools/call)."""
    async with streamable_http_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [{"name": t.name, "description": (t.description or "")[:500],
                     "inputSchema": t.inputSchema} for t in result.tools[:100]]


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
    if server.get("managed") and tool_name not in (server.get("allowed_tools") or []):
        raise PermissionError("MCP tool is not approved in Integrations: " + tool_name)
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
