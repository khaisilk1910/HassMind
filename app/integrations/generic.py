from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .base import JsonHttpClient

_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _validate_args(action: dict[str, Any], args: dict[str, Any]) -> None:
    schema = action.get("input_schema") or {}
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    unknown = sorted(set(args) - set(properties))
    if unknown:
        raise ValueError(f"Undeclared action arguments: {', '.join(unknown)}")
    missing = [name for name in required if name not in args]
    if missing:
        raise ValueError(f"Missing required action arguments: {', '.join(missing)}")
    for name, value in args.items():
        spec = properties.get(name) or {}
        expected = spec.get("type")
        valid = True
        if expected == "string":
            valid = isinstance(value, str)
        elif expected == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected == "boolean":
            valid = isinstance(value, bool)
        elif expected == "object":
            valid = isinstance(value, dict)
        elif expected == "array":
            valid = isinstance(value, list)
        if not valid:
            raise ValueError(f"Argument {name} must be {expected}")
        if "enum" in spec and value not in spec.get("enum", []):
            raise ValueError(f"Argument {name} is not in the allowed enum")
        if isinstance(value, str):
            if spec.get("minLength") is not None and len(value) < int(spec["minLength"]):
                raise ValueError(f"Argument {name} is shorter than minLength")
            if spec.get("maxLength") is not None and len(value) > int(spec["maxLength"]):
                raise ValueError(f"Argument {name} is longer than maxLength")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if spec.get("minimum") is not None and value < spec["minimum"]:
                raise ValueError(f"Argument {name} is below minimum")
            if spec.get("maximum") is not None and value > spec["maximum"]:
                raise ValueError(f"Argument {name} is above maximum")



class GenericHTTPIntegrationClient(JsonHttpClient):
    """HTTP client for operator-defined integrations and pre-declared API actions.

    The model never chooses an arbitrary URL or HTTP method. Web Admin defines a
    fixed action (method + relative path + schema) first; the model may only fill
    the declared arguments for actions explicitly enabled for the agent.
    """

    def __init__(
        self,
        base_url: str,
        health_path: str = "/health",
        timeout: float = 15.0,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(base_url, timeout=timeout, headers=headers)
        self.health_path = health_path or "/health"

    async def health(self, timeout: float | None = None) -> Any:
        return await self.request("GET", self.health_path, timeout=timeout)

    async def call_action(self, action: dict[str, Any], args: dict[str, Any]) -> Any:
        _validate_args(action, args or {})
        method = str(action.get("method") or "GET").upper()
        path = str(action.get("path") or "/")
        remaining = dict(args or {})

        for key in _PATH_PARAM_RE.findall(path):
            if key not in remaining:
                raise ValueError(f"Missing required path parameter: {key}")
            value = remaining.pop(key)
            path = path.replace("{" + key + "}", quote(str(value), safe=""))

        target = str(action.get("request_target") or "auto").lower()
        if target == "auto":
            target = "query" if method in {"GET", "DELETE"} else "json"
        if target == "query":
            return await self.request(method, path, params=remaining or None)
        return await self.request(method, path, json=remaining or {})
