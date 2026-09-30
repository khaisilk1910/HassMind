from pathlib import Path
from typing import Any
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from .settings import settings


def load_servers() -> dict:
    p = Path(settings.mcp_config)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("servers", {}) or {}


async def list_server_tools(server_name: str) -> list[dict[str, Any]]:
    server = load_servers().get(server_name)
    if not server:
        raise KeyError(f"Unknown MCP server: {server_name}")
    async with streamable_http_client(server["url"], headers=server.get("headers") or {}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [{"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema} for t in result.tools]


async def call_server_tool(server_name: str, tool_name: str, arguments: dict) -> Any:
    server = load_servers().get(server_name)
    if not server:
        raise KeyError(f"Unknown MCP server: {server_name}")
    async with streamable_http_client(server["url"], headers=server.get("headers") or {}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            content = []
            for item in result.content:
                content.append(getattr(item, "text", str(item)))
            return {"isError": bool(result.isError), "content": content}
