"""Admin-managed MCP streamable-HTTP servers (legacy YAML remains supported)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from .custom_integrations import _normalize_header, _normalize_auth_type, _normalize_url
from .db import conn, utcnow
from .settings import settings
from .observability import register_secret


def _valid_id(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", str(value or "")):
        raise ValueError("MCP ID: 2-64 ký tự thường, số, dấu - hoặc _")
    return value


def _secret_id(server_id: str) -> str:
    return f"integration_mcp_{_valid_id(server_id)}_secret"


def _sanitize(payload: dict[str, Any], existing: str = "") -> dict[str, Any]:
    server_id = _valid_id(existing or str(payload.get("id") or ""))
    name = str(payload.get("name") or server_id).strip()[:120]
    if not name:
        raise ValueError("MCP name is required")
    url = _normalize_url(payload.get("url"))
    if urlparse(url).query or urlparse(url).fragment:
        raise ValueError("MCP URL must not contain a query or fragment")
    auth_type = _normalize_auth_type(payload.get("auth_type"))
    header = _normalize_header(payload.get("auth_header"), auth_type)
    tools = payload.get("allowed_tools") or []
    if not isinstance(tools, list) or len(tools) > 100 or any(not isinstance(t, str) or not t or len(t) > 120 for t in tools):
        raise ValueError("allowed_tools must be a list of up to 100 tool names")
    return {"id": server_id, "name": name, "url": url,
            "auth_type": auth_type, "auth_header": header,
            "enabled": bool(payload.get("enabled", True)), "allowed_tools": list(dict.fromkeys(tools))}


def list_mcp_connections() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM mcp_connections ORDER BY lower(name), id").fetchall()
    return [{"id": r["id"], "name": r["name"], "url": r["url"],
             "auth_type": r["auth_type"], "auth_header": r["auth_header"],
             "enabled": bool(r["enabled"]), "allowed_tools": json.loads(r["allowed_tools_json"]),
             "secret_configured": bool(settings.read_runtime_secret(_secret_id(r["id"]))),
             "source": "web_admin"} for r in rows]


def save_mcp_connection(payload: dict[str, Any], existing: str = "") -> dict[str, Any]:
    clean = _sanitize(payload, existing)
    credential = str(payload.get("secret") or "").strip()
    clear = bool(payload.get("clear_secret", False))
    if clean["auth_type"] != "none" and credential and len(credential) < 4:
        raise ValueError("MCP credential is too short")
    with conn() as c:
        row = c.execute("SELECT 1 FROM mcp_connections WHERE id=?", (clean["id"],)).fetchone()
        if existing and not row:
            raise KeyError(existing)
        if not existing and row:
            raise ValueError("MCP server ID already exists")
        now = utcnow()
        c.execute("""INSERT INTO mcp_connections
            (id,name,url,auth_type,auth_header,enabled,allowed_tools_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,
            url=excluded.url,auth_type=excluded.auth_type,auth_header=excluded.auth_header,
            enabled=excluded.enabled,allowed_tools_json=excluded.allowed_tools_json,
            updated_at=excluded.updated_at""",
            (clean["id"], clean["name"], clean["url"], clean["auth_type"], clean["auth_header"],
             int(clean["enabled"]), json.dumps(clean["allowed_tools"]), now, now))
    secret_file = Path(settings.runtime_secret_dir) / _secret_id(clean["id"])
    if clear or clean["auth_type"] == "none":
        secret_file.unlink(missing_ok=True)
    elif credential:
        settings.write_runtime_secret(_secret_id(clean["id"]), credential)
        register_secret(credential)
    return next(x for x in list_mcp_connections() if x["id"] == clean["id"])


def delete_mcp_connection(server_id: str) -> None:
    server_id = _valid_id(server_id)
    with conn() as c:
        result = c.execute("DELETE FROM mcp_connections WHERE id=?", (server_id,))
        if not result.rowcount:
            raise KeyError(server_id)
    (Path(settings.runtime_secret_dir) / _secret_id(server_id)).unlink(missing_ok=True)


def mcp_servers_runtime() -> dict[str, dict[str, Any]]:
    servers = {}
    for item in list_mcp_connections():
        if not item["enabled"]:
            continue
        secret = settings.read_runtime_secret(_secret_id(item["id"]))
        if secret:
            register_secret(secret)
        headers = {}
        if item["auth_type"] == "bearer" and secret:
            headers["Authorization"] = f"Bearer {secret}"
        elif item["auth_type"] == "header" and secret:
            headers[item["auth_header"]] = secret
        servers[item["id"]] = {"url": item["url"], "headers": headers,
                               "managed": True, "allowed_tools": item["allowed_tools"]}
    return servers
