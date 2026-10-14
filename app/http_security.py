"""Browser-facing boundary checks independent of reverse-proxy forwarded headers.

Only loopback/private IP literals and LAN-only host names are permitted by default.
Public FQDNs used behind a trusted HTTPS reverse proxy must be configured explicitly.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from fastapi import Request

from .settings import settings

_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$", re.ASCII)


def _parse_authority(value: str) -> tuple[str, int | None] | None:
    if not value or any(x in value for x in ("/", "\\", "@", "#", "?", ",", " ", "\t", "\r", "\n")):
        return None
    try:
        parsed = urlsplit("http://" + value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if not host or parsed.username is not None or parsed.password is not None:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOST_RE.fullmatch(host) or ".." in host or host.startswith("-") or host.endswith("-"):
            return None
    return host, port


def permitted_host(host_header: str) -> bool:
    parsed = _parse_authority(host_header)
    if not parsed:
        return False
    host, _ = parsed
    explicit = {part.strip().lower().rstrip(".") for part in settings.admin_allowed_hosts.split(",") if part.strip()}
    if host in explicit:
        return True
    try:
        address = ipaddress.ip_address(host)
        # Keep direct LAN/localhost access, but disallow public IP literal Host
        # values unless explicitly configured. IPv4-mapped IPv6 is normalized.
        if getattr(address, "ipv4_mapped", None):
            address = address.ipv4_mapped
        return bool(address.is_private or address.is_loopback or address.is_link_local) and not address.is_multicast
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith((".local", ".home.arpa"))


def permitted_origin(host_header: str, origin: str | None, fetch_site: str | None) -> bool:
    # Origin is not mandatory for non-browser API clients. Auth/CSRF is still
    # required in their absence. Block browser cross-site mutation attempts.
    if fetch_site == "cross-site":
        return False
    if not origin:
        return True
    host = _parse_authority(host_header)
    try:
        candidate = urlsplit(origin)
        if candidate.scheme not in {"http", "https"} or not candidate.netloc or candidate.username or candidate.password:
            return False
        if candidate.path or candidate.query or candidate.fragment:
            return False
        origin_host = (candidate.hostname or "").lower().rstrip(".")
        origin_port = candidate.port or (443 if candidate.scheme == "https" else 80)
    except ValueError:
        return False
    if host is None or origin_host != host[0]:
        return False
    # HTTP Host can omit its default port even if Origin specifies it.
    return (origin_port in {80, 443}) if host[1] is None else host[1] == origin_port

# An authenticated webhook is still a network-exposed ingestion surface. Keep
# the event writer and agent task scheduler safe from replay/flood traffic.
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

_webhook_guard = Lock()
_webhook_calls: dict[str, deque[float]] = defaultdict(deque)


def admit_webhook_request(client_address: str) -> bool:
    now = monotonic()
    with _webhook_guard:
        if len(_webhook_calls) > 1024:
            for address, attempts in list(_webhook_calls.items()):
                while attempts and attempts[0] <= now - 60:
                    attempts.popleft()
                if not attempts:
                    _webhook_calls.pop(address, None)
        if client_address not in _webhook_calls and len(_webhook_calls) >= 2048:
            return False
        calls = _webhook_calls[client_address]
        while calls and calls[0] <= now - 60:
            calls.popleft()
        if len(calls) >= 120:
            return False
        calls.append(now)
        return True
