from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Any

from .db import conn, utcnow
from .time_utils import now as local_now, parse_datetime

_ENTITY_RE = re.compile(r"\b[a-z_][a-z0-9_]*\.[a-z0-9_]+\b", re.IGNORECASE)


def entity_ids_from_value(value: Any) -> list[str]:
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            for match in _ENTITY_RE.findall(item):
                eid = match.lower()
                if eid not in found:
                    found.append(eid)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, (list, tuple, set)):
            for child in item:
                walk(child)

    walk(value)
    return found


def operation_key(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    arguments = arguments or {}
    tool_name = str(tool_name or "unknown").strip().lower()
    if tool_name == "ha_call_service":
        domain = str(arguments.get("domain") or "").strip().lower()
        service = str(arguments.get("service") or "").strip().lower()
        entities = entity_ids_from_value(arguments.get("target") or arguments)
        suffix = ",".join(sorted(entities)) or "*"
        return f"ha_call_service:{domain}.{service}:{suffix}"
    entities = entity_ids_from_value(arguments)
    suffix = ",".join(sorted(entities)) or "*"
    return f"{tool_name}:{suffix}"


def _fingerprint(operation: str) -> str:
    return hashlib.sha256(operation.encode("utf-8", errors="ignore")).hexdigest()[:32]




def _ensure_table(c) -> None:
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_issues (
          fingerprint TEXT PRIMARY KEY,
          operation TEXT NOT NULL,
          target TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT 'runtime',
          count INTEGER NOT NULL DEFAULT 1,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          last_error TEXT NOT NULL DEFAULT '',
          resolved_at TEXT
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_runtime_issues_last_seen ON runtime_issues(last_seen DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_runtime_issues_target ON runtime_issues(target)")

def record_failure(
    tool_name: str,
    arguments: dict[str, Any] | None,
    error: str,
    *,
    source: str = "runtime",
) -> None:
    operation = operation_key(tool_name, arguments)
    fingerprint = _fingerprint(operation)
    entities = entity_ids_from_value(arguments or {})
    target = ("," + ",".join(sorted(entities)) + ",")[:1000] if entities else ""
    now = utcnow()
    message = str(error or "runtime error")[:2000]
    with conn() as c:
        _ensure_table(c)
        row = c.execute("SELECT count FROM runtime_issues WHERE fingerprint=?", (fingerprint,)).fetchone()
        if row:
            c.execute(
                """
                UPDATE runtime_issues
                SET count=count+1,last_seen=?,last_error=?,resolved_at=NULL,source=?,target=?,operation=?
                WHERE fingerprint=?
                """,
                (now, message, str(source or "runtime")[:64], target, operation[:1000], fingerprint),
            )
        else:
            c.execute(
                """
                INSERT INTO runtime_issues(
                  fingerprint,operation,target,source,count,first_seen,last_seen,last_error,resolved_at
                ) VALUES(?,?,?,?,1,?,?,?,NULL)
                """,
                (fingerprint, operation[:1000], target, str(source or "runtime")[:64], now, now, message),
            )


def record_success(tool_name: str, arguments: dict[str, Any] | None, *, source: str = "runtime") -> None:
    operation = operation_key(tool_name, arguments)
    fingerprint = _fingerprint(operation)
    now = utcnow()
    with conn() as c:
        _ensure_table(c)
        c.execute(
            "UPDATE runtime_issues SET resolved_at=?,source=? WHERE fingerprint=? AND resolved_at IS NULL",
            (now, str(source or "runtime")[:64], fingerprint),
        )


def recent_issue_for_operation(
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    minutes: int = 30,
    minimum_count: int = 2,
) -> dict[str, Any] | None:
    operation = operation_key(tool_name, arguments)
    fingerprint = _fingerprint(operation)
    with conn() as c:
        _ensure_table(c)
        row = c.execute(
            "SELECT * FROM runtime_issues WHERE fingerprint=? AND resolved_at IS NULL",
            (fingerprint,),
        ).fetchone()
    if not row or int(row["count"] or 0) < max(1, int(minimum_count)):
        return None
    last = parse_datetime(row["last_seen"])
    if last is None or local_now() - last > timedelta(minutes=max(1, int(minutes))):
        return None
    return dict(row)


def recent_issue_context(text: str, *, limit: int = 5, minutes: int = 1440) -> str:
    entity_ids = entity_ids_from_value(text)
    if not entity_ids:
        return ""
    threshold = local_now() - timedelta(minutes=max(1, int(minutes)))
    rows: list[dict[str, Any]] = []
    with conn() as c:
        _ensure_table(c)
        for entity_id in entity_ids[:20]:
            matches = c.execute(
                """
                SELECT * FROM runtime_issues
                WHERE resolved_at IS NULL AND target LIKE ?
                ORDER BY last_seen DESC LIMIT ?
                """,
                (f"%,{entity_id},%", max(1, int(limit))),
            ).fetchall()
            for row in matches:
                item = dict(row)
                seen = parse_datetime(item.get("last_seen"))
                if seen is not None and seen >= threshold:
                    rows.append(item)
    dedup: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda x: str(x.get("last_seen") or ""), reverse=True):
        dedup.setdefault(str(row.get("fingerprint") or ""), row)
    selected = list(dedup.values())[: max(1, int(limit))]
    if not selected:
        return ""
    bullets = []
    for row in selected:
        bullets.append(
            f"- {row.get('operation')}: failed {row.get('count')} time(s); last error: {row.get('last_error')}"
        )
    return (
        "Recent unresolved runtime issues for exact entities mentioned in this request. "
        "Use them as operational evidence, not as permission. Re-check live state/capability before repeating a failing action. "
        "If the same action remains ambiguous or unsafe, ask the user instead of retrying blindly.\n"
        + "\n".join(bullets)
    )


def list_recent_issues(limit: int = 50) -> list[dict[str, Any]]:
    with conn() as c:
        _ensure_table(c)
        rows = c.execute(
            "SELECT * FROM runtime_issues ORDER BY last_seen DESC LIMIT ?",
            (min(max(int(limit), 1), 200),),
        ).fetchall()
    return [dict(row) for row in rows]
