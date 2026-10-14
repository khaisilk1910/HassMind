"""Conservative, read-only OpenAPI action discovery for administrator configured HTTP services.

Only public OpenAPI paths are fetched; discovery never invokes an endpoint listed
in the document. Discovered actions always require explicit Agent opt-in.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .custom_integrations import (_MAX_ACTIONS, _normalize_actions, _normalize_auth_type,
                                  _normalize_header, _normalize_relative_path,
                                  _normalize_url, _slugify)
from .settings import settings

SPEC_PATHS = ("/openapi.json", "/api/openapi.json", "/swagger.json",
              "/swagger/v1/swagger.json", "/v3/api-docs", "/api-docs")
MAX_DOCUMENT_BYTES = 3 * 1024 * 1024
METHODS = {"get", "post", "put", "patch", "delete"}


def _spec_path(value: str) -> str:
    path = _normalize_relative_path(value, "/openapi.json")
    parsed = urlparse(path)
    if parsed.query or parsed.fragment or "\\" in path or ".." in unquote(path).split("/"):
        raise ValueError("OpenAPI path must be a safe relative path without query/fragment")
    if "{" in path or "}" in path:
        raise ValueError("OpenAPI path cannot contain variables")
    return path


def _check_discovery_host(url: str) -> None:
    """Deny metadata/multicast/unspecified hosts; allow local Docker networks."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise ValueError("Invalid integration host")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Unable to resolve service host") from exc
    for result in addresses:
        ip = ipaddress.ip_address(result[4][0])
        if not ip.is_loopback and (ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved):
            raise ValueError("Unsafe target address for API discovery")


def _local_ref(document: dict[str, Any], obj: Any) -> Any:
    # Only local $ref pointers: never fetch URLs declared by an untrusted spec.
    for _ in range(5):
        if not isinstance(obj, dict) or "$ref" not in obj:
            break
        ref = obj["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise ValueError("External OpenAPI $ref is unsupported")
        cursor: Any = document
        for component in ref[2:].split("/"):
            component = component.replace("~1", "/").replace("~0", "~")
            if not isinstance(cursor, dict) or component not in cursor:
                raise ValueError("Unresolved OpenAPI $ref")
            cursor = cursor[component]
        obj = cursor
    if isinstance(obj, dict) and "$ref" in obj:
        raise ValueError("Circular OpenAPI $ref")
    return obj


def _field_schema(document: dict[str, Any], spec: Any) -> dict[str, Any]:
    spec = _local_ref(document, spec)
    if not isinstance(spec, dict):
        raise ValueError("Unsupported OpenAPI parameter schema")
    if "allOf" in spec and len(spec["allOf"]) == 1:
        return _field_schema(document, spec["allOf"][0])
    field_type = spec.get("type", "string")
    if isinstance(field_type, list):
        field_type = next((t for t in field_type if t != "null"), "string")
    if field_type not in {"string", "number", "integer", "boolean", "object", "array"}:
        raise ValueError("Unsupported parameter type")
    if spec.get("format") == "binary" or spec.get("contentEncoding") == "base64":
        raise ValueError("Binary upload parameters are not supported")
    value: dict[str, Any] = {"type": field_type}
    for key in ("description", "enum", "minimum", "maximum", "minLength", "maxLength", "default"):
        if key in spec:
            value[key] = spec[key]
    if field_type == "array":
        value["items"] = _field_schema(document, spec.get("items") or {"type": "string"})
    elif field_type == "object":
        # Nested bodies may be passed as JSON objects without arbitrary schemas.
        if "properties" in spec:
            props = spec["properties"]
            if not isinstance(props, dict) or len(props) > 40:
                raise ValueError("Unsupported nested body")
            value["properties"] = {k: _field_schema(document, v) for k, v in props.items()}
        value["additionalProperties"] = False
    return value


def _action_from_operation(document: dict[str, Any], path: str, method: str, operation: dict[str, Any],
                           inherited: list[Any], *, swagger: bool) -> dict[str, Any]:
    path = _normalize_relative_path(path, "/")
    if "?" in path or "#" in path:
        raise ValueError("Query/fragment in OpenAPI paths is unsupported")
    props: dict[str, Any] = {}
    required: list[str] = []
    locations: dict[str, str] = {}
    params = [*inherited, *(operation.get("parameters") or [])]
    body_spec = None
    for item in params:
        parameter = _local_ref(document, item)
        if not isinstance(parameter, dict):
            raise ValueError("Malformed parameter")
        location = parameter.get("in")
        if location not in {"path", "query", "body"}:
            continue
        if location == "body":
            body_spec = parameter.get("schema")
            continue
        name = str(parameter.get("name") or "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            raise ValueError("Unsupported parameter name")
        props[name] = _field_schema(document, parameter.get("schema") or parameter)
        if location == "query":
            locations[name] = "query"
        if location == "path" or parameter.get("required"):
            if name not in required:
                required.append(name)
    if not swagger and isinstance(operation.get("requestBody"), dict):
        body = _local_ref(document, operation["requestBody"])
        content = body.get("content") or {}
        body_spec = (content.get("application/json") or content.get("application/*+json") or {}).get("schema")
        if content and body_spec is None:
            raise ValueError("Only JSON request bodies are supported")
    if body_spec is not None:
        body = _local_ref(document, body_spec)
        if not isinstance(body, dict) or body.get("type", "object") != "object":
            raise ValueError("Only object-shaped JSON bodies are supported")
        if "allOf" in body or "oneOf" in body or "anyOf" in body:
            raise ValueError("Complex request body is unsupported")
        body_props = body.get("properties") or {}
        if not isinstance(body_props, dict):
            raise ValueError("Malformed body schema")
        for key, spec in body_props.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key) or key in props:
                raise ValueError("Invalid or duplicate body parameter")
            props[key] = _field_schema(document, spec)
            locations[key] = "json"
        for name in body.get("required") or []:
            if name not in required:
                required.append(name)
    if len(props) > 40:
        raise ValueError("Too many parameters")
    if method.lower() in {"get", "delete"} and any(v == "json" for v in locations.values()):
        raise ValueError("JSON body for GET/DELETE is unsupported")
    raw_name = str(operation.get("summary") or operation.get("operationId") or f"{method.upper()} {path}")
    name = raw_name[:120].strip()
    slug = _slugify(str(operation.get("operationId") or name))[:30].strip("-") or "operation"
    suffix = hashlib.sha256(f"{method}:{path}".encode()).hexdigest()[:7]
    action_id = f"{slug}-{suffix}"[:40]
    description = str(operation.get("description") or operation.get("summary") or "")[:700]
    return {
        "id": action_id, "name": name, "description": description,
        "enabled": True, "agent_enabled": False,
        "method": method.upper(), "path": path,
        "mode": "read" if method.lower() == "get" else "write",
        "request_target": "auto", "parameter_locations": locations,
        "input_schema": {"type": "object", "properties": props,
                         "required": required, "additionalProperties": False},
    }


def parse_openapi(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise ValueError("Response is not an OpenAPI/Swagger JSON document")
    if not (document.get("openapi") or document.get("swagger")):
        raise ValueError("Missing OpenAPI/Swagger version")
    swagger = bool(document.get("swagger"))
    # Swagger 2's basePath can be a relative prefix that is part of the API route.
    prefix = ""
    if swagger and document.get("basePath"):
        prefix = _normalize_relative_path(document["basePath"], "/").rstrip("/")
    actions: list[dict[str, Any]] = []
    warnings: list[str] = []
    paths = document["paths"]
    for path, entry in paths.items():
        if not isinstance(entry, dict):
            continue
        for method, operation in entry.items():
            if method.lower() not in METHODS or not isinstance(operation, dict):
                continue
            if len(actions) >= _MAX_ACTIONS:
                warnings.append(f"Giới hạn {_MAX_ACTIONS} actions; các endpoint còn lại chưa được nhập.")
                return {"actions": _normalize_actions(actions), "warnings": warnings}
            try:
                action = _action_from_operation(document, prefix + path, method, operation,
                                                entry.get("parameters") or [], swagger=swagger)
                # Validate each operation independently; skip incompatible endpoints.
                action = _normalize_actions([action])[0]
                actions.append(action)
            except (ValueError, TypeError, KeyError) as exc:
                warnings.append(f"Bỏ qua {method.upper()} {str(path)[:100]}: {str(exc)[:100]}")
    return {"actions": actions, "warnings": warnings[:30]}


async def discover_openapi(*, base_url: str, auth_type: str = "none", auth_header: str = "X-API-Key",
                           secret: str = "", existing_id: str = "", spec_path: str = "") -> dict[str, Any]:
    base_url = _normalize_url(base_url)
    parsed_url = urlparse(base_url)
    if parsed_url.query or parsed_url.fragment:
        raise ValueError("Base URL cannot contain a query or fragment")
    _check_discovery_host(base_url)
    auth_type = _normalize_auth_type(auth_type)
    auth_header = _normalize_header(auth_header, auth_type)
    if not secret and existing_id:
        # Existing saved credential can be used without exposing it to the browser.
        from .custom_integrations import list_custom_integrations
        from .custom_integrations import _secret_name
        record = next((item for item in list_custom_integrations() if item["id"] == existing_id), None)
        if record:
            secret = settings.read_runtime_secret(_secret_name(existing_id))
    headers = {"Accept": "application/json", "User-Agent": "HassMind-Discovery/1"}
    if secret and auth_type == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif secret and auth_type == "header":
        headers[auth_header] = secret
    candidates = [_spec_path(spec_path)] if spec_path else list(SPEC_PATHS)
    # API Base URLs frequently include /v1 while OpenAPI is served at origin root.
    root = f"{parsed_url.scheme}://{parsed_url.netloc}"
    urls = [(base_url.rstrip("/") + p, p) for p in candidates]
    if base_url.rstrip("/") != root:
        urls.extend((root + p, p) for p in candidates)
    # Include base path, if any; URLs always stay on the specified service origin.
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(4, connect=2), follow_redirects=False,
                                 trust_env=False, headers=headers) as client:
        for url, path in urls:
            try:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        errors.append(f"{path}: HTTP {response.status_code}")
                        continue
                    size = 0
                    chunks = []
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOCUMENT_BYTES:
                            raise ValueError("OpenAPI document exceeds 3 MB")
                        chunks.append(chunk)
                doc = json.loads(b"".join(chunks))
                result = parse_openapi(doc)
                base_prefix = parsed_url.path.rstrip("/")
                if base_prefix:
                    for action in result["actions"]:
                        if action["path"].startswith(base_prefix + "/"):
                            action["path"] = action["path"][len(base_prefix):]
                result.update({"found": True, "spec_path": path, "source": "OpenAPI/Swagger",
                               "action_count": len(result["actions"])})
                return result
            except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{path}: {type(exc).__name__}")
    return {"found": False, "actions": [], "warnings": [
        "Không tìm thấy OpenAPI/Swagger JSON. Dịch vụ có thể không công bố schema; hãy nhập spec path hoặc khai báo actions thủ công.",
        *errors[:6],
    ], "action_count": 0, "source": "none"}
