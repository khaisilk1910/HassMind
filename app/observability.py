from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import traceback
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .settings import settings
from .time_utils import now_iso, to_local_iso

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")
_source: ContextVar[str] = ContextVar("source", default="")
_component: ContextVar[str] = ContextVar("component", default="")

SENSITIVE_KEY_RE = re.compile(
    r"(^|_)(token|password|passwd|secret|api[_-]?key|authorization|cookie|session_cookie|access[_-]?token|refresh[_-]?token|credential)s?($|_)",
    re.IGNORECASE,
)
BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
ZALO_WEBHOOK_RE = re.compile(r"(/webhooks/zalo/)[^/?#]+")
GENERIC_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(\b(?:token|password|passwd|secret|api[_-]?key|authorization|cookie|access[_-]?token|refresh[_-]?token|credential)\b\s*[:=]\s*)([^\s,;]+)"
)
JSON_SECRET_RE = re.compile(
    r'(?i)(["\'](?:token|password|passwd|secret|api[_-]?key|authorization|cookie|access[_-]?token|refresh[_-]?token|credential)["\']\s*:\s*["\'])(.*?)(["\'])'
)
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
OPENAI_KEY_RE = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")
GITHUB_KEY_RE = re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b", re.IGNORECASE)
TELEGRAM_BOT_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_known_secrets: set[str] = set()


def _is_sensitive_key(key: str) -> bool:
    raw = str(key).lower()
    compact = re.sub(r"[^a-z0-9]", "", raw)
    sensitive = (
        "password", "passwd", "secret", "apikey", "authorization", "cookie",
        "accesstoken", "refreshtoken", "authtoken", "credential", "clientsecret",
        "webhooksecret", "recoverykey", "privatekey",
    )
    if any(term in compact for term in sensitive):
        return True
    # Plain token keys are sensitive, but keep correlation fields such as session_id/request_id visible.
    if compact == "token" or compact.endswith("token") or compact.startswith("token"):
        return True
    return bool(SENSITIVE_KEY_RE.search(raw))


def register_secret(value: str | None) -> None:
    if isinstance(value, str):
        value = value.strip()
        if len(value) >= 8:
            _known_secrets.add(value)


def _register_configured_secrets() -> None:
    for value in settings.configured_secret_values():
        register_secret(value)


def _local_iso() -> str:
    return now_iso(timespec="milliseconds")


def sanitize_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        query = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            query.append((key, "[REDACTED]" if _is_sensitive_key(key) else val))
        path = ZALO_WEBHOOK_RE.sub(r"\1[REDACTED]", parts.path)
        return urlunsplit((parts.scheme, host, path, urlencode(query), ""))
    except Exception:
        return ZALO_WEBHOOK_RE.sub(r"\1[REDACTED]", value)


def _sanitize_string(value: str, max_chars: int = 12000) -> str:
    value = BEARER_RE.sub("Bearer [REDACTED]", value)
    value = ZALO_WEBHOOK_RE.sub(r"\1[REDACTED]", value)
    value = OPENAI_KEY_RE.sub("[REDACTED_API_KEY]", value)
    value = GITHUB_KEY_RE.sub("[REDACTED_API_KEY]", value)
    value = TELEGRAM_BOT_RE.sub("[REDACTED_TOKEN]", value)
    value = JWT_RE.sub("[REDACTED_TOKEN]", value)
    value = JSON_SECRET_RE.sub(r"\1[REDACTED]\3", value)
    value = GENERIC_SECRET_ASSIGN_RE.sub(r"\1[REDACTED]", value)
    for secret in sorted(_known_secrets, key=len, reverse=True):
        if secret and secret in value:
            value = value.replace(secret, "[REDACTED]")
    if len(value) > max_chars:
        return value[:max_chars] + f"…[truncated {len(value) - max_chars} chars]"
    return value


def redact(value: Any, key: str | None = None, depth: int = 0) -> Any:
    if key and _is_sensitive_key(str(key)):
        return "[REDACTED]"
    if depth > 8:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if key and "url" in key.lower():
            return sanitize_url(value)
        return _sanitize_string(value)
    if isinstance(value, dict):
        return {str(k): redact(v, str(k), depth + 1) for k, v in list(value.items())[:250]}
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [redact(v, None, depth + 1) for v in seq[:250]]
        if len(seq) > 250:
            out.append(f"[TRUNCATED {len(seq) - 250} ITEMS]")
        return out
    return _sanitize_string(str(value))




def _scrub_log_line(line: str) -> str:
    raw = line.rstrip("\n")
    try:
        parsed = json.loads(raw)
    except Exception:
        return _sanitize_string(raw, max_chars=max(12000, len(raw)))
    if isinstance(parsed, dict) and parsed.get("ts"):
        parsed["ts"] = to_local_iso(parsed.get("ts"), timespec="milliseconds") or parsed.get("ts")
    return json.dumps(redact(parsed), ensure_ascii=False, separators=(",", ":"), default=str)


def scrub_existing_log_files() -> int:
    """Best-effort in-place sanitization of current rotating log files before opening them."""
    if not settings.log_scrub_existing_on_start or not settings.log_file_enabled:
        return 0
    base = Path(settings.log_file)
    candidates = [base, *[Path(f"{base}.{i}") for i in range(1, max(1, settings.log_backup_count) + 1)]]
    scrubbed = 0
    for path in candidates:
        try:
            if not path.exists() or not path.is_file() or path.is_symlink():
                continue
            tmp = path.with_name(path.name + ".scrub.tmp")
            with path.open("r", encoding="utf-8", errors="replace") as src, tmp.open("w", encoding="utf-8", newline="\n") as dst:
                for line in src:
                    dst.write(_scrub_log_line(line) + "\n")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            scrubbed += 1
        except Exception:
            try:
                tmp = path.with_name(path.name + ".scrub.tmp")
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
    return scrubbed


def preview(value: Any, max_chars: int = 2000) -> Any:
    safe = redact(value)
    if settings.log_include_content:
        return safe
    if isinstance(safe, str):
        return {"type": "str", "chars": len(safe)}
    if isinstance(safe, dict):
        return {"type": "dict", "keys": list(safe.keys())[:50]}
    if isinstance(safe, list):
        return {"type": "list", "items": len(safe)}
    text = str(safe)
    return text[:max_chars]


def context_snapshot() -> dict[str, str]:
    return {
        "request_id": _request_id.get(),
        "session_id": _session_id.get(),
        "source": _source.get(),
    }


@contextmanager
def log_context(*, request_id: str | None = None, session_id: str | None = None, source: str | None = None, component: str | None = None) -> Iterator[None]:
    tokens: list[tuple[ContextVar[str], Any]] = []
    for var, value in ((_request_id, request_id), (_session_id, session_id), (_source, source), (_component, component)):
        if value is not None:
            tokens.append((var, var.set(value)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_request_id() -> str:
    return _request_id.get()


def _record_to_dict(record: logging.LogRecord) -> dict[str, Any]:
    ctx = context_snapshot()
    extra = redact(getattr(record, "hassmind", {}) or {})
    item: dict[str, Any] = {
        "ts": _local_iso(),
        "level": record.levelname,
        "logger": record.name,
        "event": extra.pop("event", "log"),
        "message": _sanitize_string(record.getMessage()),
    }
    for key, value in ctx.items():
        if value:
            item[key] = value
    if "component" in extra and extra["component"]:
        item["component"] = extra.pop("component")
    else:
        item["component"] = record.name.removeprefix("hassmind.")
    item.update(extra)
    if record.exc_info:
        exc_type = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        exc_value = str(record.exc_info[1]) if record.exc_info[1] else ""
        item["exception"] = {
            "type": exc_type,
            "message": _sanitize_string(exc_value),
            "traceback": _sanitize_string("".join(traceback.format_exception(*record.exc_info)), max_chars=30000),
        }
    return item


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_record_to_dict(record), ensure_ascii=False, separators=(",", ":"), default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        item = _record_to_dict(record)
        base = f"{item['ts']} {item['level']:<8} [{item.get('component','core')}] {item['event']}: {item['message']}"
        meta = {k: v for k, v in item.items() if k not in {"ts", "level", "component", "event", "message", "exception"}}
        if meta:
            base += " | " + json.dumps(meta, ensure_ascii=False, default=str)
        if item.get("exception"):
            base += "\n" + item["exception"]["traceback"]
        return base


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int):
        super().__init__()
        self.buffer: deque[dict[str, Any]] = deque(maxlen=max(100, capacity))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(_record_to_dict(record))
        except Exception:
            pass

    def read(self, *, limit: int = 200, level: str = "", component: str = "", query: str = "") -> list[dict[str, Any]]:
        level = level.upper().strip()
        component = component.lower().strip()
        query = query.lower().strip()
        rows = list(self.buffer)
        out: list[dict[str, Any]] = []
        for row in reversed(rows):
            if level and row.get("level") != level:
                continue
            if component and component not in str(row.get("component", "")).lower():
                continue
            if query and query not in json.dumps(row, ensure_ascii=False, default=str).lower():
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out


_ring_handler = RingBufferHandler(settings.log_ring_size)
_configured = False
_started_at = perf_counter()


def uptime_seconds() -> float:
    return round(perf_counter() - _started_at, 3)


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    _register_configured_secrets()
    scrubbed_files = scrub_existing_log_files()

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    root.handlers.clear()

    formatter: logging.Formatter = JsonFormatter() if settings.log_format.lower() == "json" else TextFormatter()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    _ring_handler.setFormatter(formatter)
    root.addHandler(_ring_handler)

    if settings.log_file_enabled:
        path = Path(settings.log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.is_symlink():
                raise RuntimeError("Refusing to write logs through a symbolic link")
            try:
                os.chmod(path.parent, 0o700)
            except OSError:
                pass
            file_handler = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=max(1024 * 1024, settings.log_max_bytes),
                backupCount=max(1, settings.log_backup_count),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except Exception as exc:
            root.error(
                "Unable to initialize log file; continuing with stdout and in-memory logs",
                extra={"hassmind": {"event": "log_file_init_failed", "path": str(path), "error_type": type(exc).__name__, "error": str(exc)}},
            )

    for noisy in ("httpcore", "httpx", "websockets.client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if scrubbed_files:
        logging.getLogger("hassmind.observability").info(
            "Sanitized existing log files",
            extra={"hassmind": {"event": "existing_logs_scrubbed", "files": scrubbed_files}},
        )


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"hassmind.{component}")


def log(logger: logging.Logger, level: int, event: str, message: str | None = None, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.log(level, message or event, extra={"hassmind": payload})


def info(logger: logging.Logger, event: str, message: str | None = None, **fields: Any) -> None:
    log(logger, logging.INFO, event, message, **fields)


def warning(logger: logging.Logger, event: str, message: str | None = None, **fields: Any) -> None:
    log(logger, logging.WARNING, event, message, **fields)


def error(logger: logging.Logger, event: str, message: str | None = None, **fields: Any) -> None:
    log(logger, logging.ERROR, event, message, **fields)


def exception(logger: logging.Logger, event: str, message: str | None = None, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.exception(message or event, extra={"hassmind": payload})


def recent_logs(limit: int = 200, level: str = "", component: str = "", query: str = "") -> list[dict[str, Any]]:
    return _ring_handler.read(limit=max(1, min(limit, 2000)), level=level, component=component, query=query)


def log_file_info() -> dict[str, Any]:
    path = Path(settings.log_file)
    return {
        "enabled": settings.log_file_enabled,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "level": settings.log_level.upper(),
        "format": settings.log_format.lower(),
        "include_content": settings.log_include_content,
        "ring_size": settings.log_ring_size,
    }
