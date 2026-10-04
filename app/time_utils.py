from __future__ import annotations

import os
import time as _time
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .settings import settings


def timezone_name() -> str:
    """Return the single timezone HassMind uses for application timestamps."""
    return str(settings.timezone or os.getenv("TIMEZONE") or os.getenv("TZ") or "UTC").strip() or "UTC"


@lru_cache(maxsize=16)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            f"Invalid TIMEZONE/TZ '{name}'. Use an IANA timezone such as Asia/Ho_Chi_Minh."
        ) from exc


def local_tz() -> ZoneInfo:
    return _zone(timezone_name())


def configure_process_timezone() -> str:
    """Synchronize TIMEZONE, TZ and libc/Python local time with HassMind settings."""
    name = timezone_name()
    _zone(name)  # fail fast on invalid configuration
    os.environ["TIMEZONE"] = name
    os.environ["TZ"] = name
    if hasattr(_time, "tzset"):
        _time.tzset()
    return name


def now() -> datetime:
    return datetime.now(local_tz())


def now_iso(*, timespec: str = "microseconds") -> str:
    return now().isoformat(timespec=timespec)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        # Legacy HassMind rows could be naive. Treat them as already being in
        # the configured local zone instead of silently assuming UTC.
        dt = dt.replace(tzinfo=local_tz())
    return dt.astimezone(local_tz())


def to_local_iso(value: str | datetime | None, *, timespec: str = "microseconds") -> str | None:
    dt = parse_datetime(value)
    return dt.isoformat(timespec=timespec) if dt is not None else None
