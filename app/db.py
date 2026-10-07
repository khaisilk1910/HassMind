import json
import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .settings import settings
from .time_utils import now_iso, timezone_name, to_local_iso
from .observability import exception, get_logger, info, redact

logger = get_logger("database")


def utcnow() -> str:
    """Backward-compatible name: timestamps are emitted in configured TIMEZONE/TZ."""
    return now_iso()


_TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "messages": ("created_at",),
    "approvals": ("created_at", "decided_at", "applied_at"),
    "events": ("created_at",),
    "jobs": ("next_run", "last_run", "created_at"),
    "event_rules": ("last_triggered", "created_at"),
    "memory_facts": ("created_at",),
    "knowledge_chunks": ("updated_at",),
    "knowledge_records": ("updated_at",),
    "knowledge_manifest": ("indexed_at",),
    "knowledge_scans": ("created_at",),
    "knowledge_proposals": ("created_at", "decided_at"),
    "knowledge_audit": ("created_at",),
    "tool_audit": ("created_at",),
    "runtime_issues": ("first_seen", "last_seen", "resolved_at"),
    "admin_users": ("created_at", "updated_at", "last_login_at", "password_changed_at", "locked_until"),
    "admin_sessions": ("created_at", "last_seen_at", "expires_at"),
    "auth_audit": ("created_at",),
    "integration_settings": ("updated_at",),
    "custom_integrations": ("created_at", "updated_at"),
    "notification_preferences": ("updated_at",),
}

_TIME_JSON_KEYS = {
    "created_at", "updated_at", "indexed_at", "scanned_at", "decided_at", "applied_at",
    "next_run", "last_run", "last_triggered", "last_login_at", "password_changed_at",
    "locked_until", "last_seen_at", "expires_at", "timestamp", "ts",
}


def _normalize_owned_time_json(value: Any) -> tuple[Any, bool]:
    changed = False
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _TIME_JSON_KEYS and isinstance(item, str):
                normalized = to_local_iso(item)
                if normalized is not None and normalized != item:
                    out[key] = normalized
                    changed = True
                    continue
            normalized_item, item_changed = _normalize_owned_time_json(item)
            out[key] = normalized_item
            changed = changed or item_changed
        return out, changed
    if isinstance(value, list):
        out_list = []
        for item in value:
            normalized_item, item_changed = _normalize_owned_time_json(item)
            out_list.append(normalized_item)
            changed = changed or item_changed
        return out_list, changed
    return value, False


def _normalize_json_timestamp_rows(c: sqlite3.Connection) -> int:
    changed = 0
    targets = (
        ("knowledge_index_state", "data", None),
        ("knowledge_scans", "payload", None),
        ("knowledge_control", "value", "key='latest_scan'"),
    )
    tables = {row["name"] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for table, column, where in targets:
        if table not in tables:
            continue
        columns = {row["name"] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            continue
        sql = f"SELECT rowid AS __rowid__, {column} FROM {table}" + (f" WHERE {where}" if where else "")
        for row in c.execute(sql).fetchall():
            raw = row[column]
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            normalized, did_change = _normalize_owned_time_json(parsed)
            if did_change:
                c.execute(
                    f"UPDATE {table} SET {column}=? WHERE rowid=?",
                    (json.dumps(normalized, ensure_ascii=False, separators=(",", ":")), row["__rowid__"]),
                )
                changed += 1
    return changed


def normalize_stored_timestamps() -> int:
    """Convert legacy UTC/offset timestamps to the configured application timezone.

    ISO-8601 offsets are preserved, so this is idempotent and safe across restarts.
    Tables created by optional subsystems are handled only when present.
    """
    changed = 0
    target_timezone = timezone_name()
    marker_key = "timestamp_timezone_v1"
    with conn() as c:
        tables = {row["name"] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "app_meta" in tables:
            marker = c.execute("SELECT value FROM app_meta WHERE key=?", (marker_key,)).fetchone()
            if marker and marker["value"] == target_timezone:
                return 0
        for table, wanted_columns in _TIMESTAMP_COLUMNS.items():
            if table not in tables:
                continue
            columns = {row["name"] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
            timestamp_columns = [name for name in wanted_columns if name in columns]
            if not timestamp_columns:
                continue
            select_cols = ",".join(["rowid AS __rowid__", *timestamp_columns])
            rows = c.execute(f"SELECT {select_cols} FROM {table}").fetchall()
            for row in rows:
                updates: dict[str, str] = {}
                for column in timestamp_columns:
                    raw = row[column]
                    if raw in (None, ""):
                        continue
                    normalized = to_local_iso(raw)
                    if normalized is not None and normalized != raw:
                        updates[column] = normalized
                if updates:
                    assignments = ",".join(f"{column}=?" for column in updates)
                    c.execute(
                        f"UPDATE {table} SET {assignments} WHERE rowid=?",
                        (*updates.values(), row["__rowid__"]),
                    )
                    changed += len(updates)
        changed += _normalize_json_timestamp_rows(c)
        if "app_meta" in tables:
            c.execute(
                "INSERT INTO app_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (marker_key, target_timezone),
            )
    if changed:
        info(logger, "database_timestamps_normalized", changed=changed, timezone=target_timezone)
    return changed


@contextmanager
def conn():
    db_path = Path(settings.db_path)
    parent = db_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass
        c = sqlite3.connect(settings.db_path, timeout=30)
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
    except Exception:
        exception(
            logger,
            "database_open_failed",
            message="Unable to open SQLite database",
            db_path=str(db_path),
            parent=str(parent),
            parent_exists=parent.exists(),
            parent_writable=os.access(parent, os.W_OK) if parent.exists() else False,
        )
        raise
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        exception(logger, "database_transaction_failed", db_path=str(db_path))
        raise
    finally:
        c.close()


def init_db():
    info(logger, "database_init_started", db_path=settings.db_path)
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'web',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id,id);

            CREATE TABLE IF NOT EXISTS approvals (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              target_id TEXT NOT NULL,
              old_config TEXT NOT NULL,
              new_config TEXT NOT NULL,
              old_hash TEXT NOT NULL,
              reason TEXT NOT NULL,
              diff TEXT NOT NULL,
              risk TEXT NOT NULL DEFAULT 'normal',
              status TEXT NOT NULL,
              approve_token TEXT NOT NULL UNIQUE,
              reject_token TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              decided_at TEXT,
              decided_by TEXT,
              applied_at TEXT,
              error TEXT,
              parent_change_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status,created_at DESC);

            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              entity_id TEXT,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_id ON events(id DESC);

            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              prompt TEXT NOT NULL,
              schedule_type TEXT NOT NULL,
              schedule_value TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 0,
              notify INTEGER NOT NULL DEFAULT 1,
              notify_channel TEXT NOT NULL DEFAULT 'mobile',
              zalo_thread_id TEXT NOT NULL DEFAULT '',
              notify_mode TEXT NOT NULL DEFAULT 'always',
              next_run TEXT,
              last_run TEXT,
              last_result TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_rules (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              entity_id TEXT NOT NULL,
              to_state TEXT,
              prompt TEXT NOT NULL,
              cooldown_seconds INTEGER NOT NULL DEFAULT 300,
              enabled INTEGER NOT NULL DEFAULT 0,
              notify INTEGER NOT NULL DEFAULT 1,
              notify_channel TEXT NOT NULL DEFAULT 'mobile',
              zalo_thread_id TEXT NOT NULL DEFAULT '',
              notify_mode TEXT NOT NULL DEFAULT 'always',
              last_triggered TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_facts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              text TEXT NOT NULL,
              tags TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT 'user',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_chunks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              path TEXT NOT NULL,
              chunk_index INTEGER NOT NULL,
              text TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(path,chunk_index)
            );

            CREATE TABLE IF NOT EXISTS tool_audit (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tool_name TEXT NOT NULL,
              arguments TEXT NOT NULL,
              result TEXT,
              error TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tool_audit_id ON tool_audit(id DESC);

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
            );
            CREATE INDEX IF NOT EXISTS idx_runtime_issues_last_seen ON runtime_issues(last_seen DESC);
            CREATE INDEX IF NOT EXISTS idx_runtime_issues_target ON runtime_issues(target);

            CREATE TABLE IF NOT EXISTS admin_users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_login_at TEXT,
              password_changed_at TEXT,
              failed_attempts INTEGER NOT NULL DEFAULT 0,
              locked_until TEXT
            );

            CREATE TABLE IF NOT EXISTS admin_sessions (
              id TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL,
              csrf_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              ip TEXT NOT NULL DEFAULT '',
              user_agent TEXT NOT NULL DEFAULT '',
              FOREIGN KEY(user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_admin_sessions_user ON admin_sessions(user_id,last_seen_at DESC);

            CREATE TABLE IF NOT EXISTS auth_audit (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event TEXT NOT NULL,
              username TEXT NOT NULL DEFAULT '',
              user_id INTEGER,
              ip TEXT NOT NULL DEFAULT '',
              success INTEGER NOT NULL DEFAULT 0,
              details TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_auth_audit_id ON auth_audit(id DESC);

            CREATE TABLE IF NOT EXISTS integration_settings (
              integration_id TEXT PRIMARY KEY,
              config_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS custom_integrations (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              icon TEXT NOT NULL DEFAULT '🔌',
              description TEXT NOT NULL DEFAULT '',
              enabled INTEGER NOT NULL DEFAULT 1,
              base_url TEXT NOT NULL,
              health_path TEXT NOT NULL DEFAULT '/health',
              auth_type TEXT NOT NULL DEFAULT 'none',
              auth_header TEXT NOT NULL DEFAULT 'X-API-Key',
              actions_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_custom_integrations_name ON custom_integrations(name);

            CREATE TABLE IF NOT EXISTS app_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notification_preferences (
              feature TEXT PRIMARY KEY,
              enabled INTEGER NOT NULL DEFAULT 1,
              channel TEXT NOT NULL DEFAULT 'mobile',
              zalo_thread_id TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL
            );
            """
        )
        job_columns = {row["name"] for row in c.execute("PRAGMA table_info(jobs)").fetchall()}
        if "notify_channel" not in job_columns:
            c.execute("ALTER TABLE jobs ADD COLUMN notify_channel TEXT NOT NULL DEFAULT 'mobile'")
        if "zalo_thread_id" not in job_columns:
            c.execute("ALTER TABLE jobs ADD COLUMN zalo_thread_id TEXT NOT NULL DEFAULT ''")
        if "notify_mode" not in job_columns:
            c.execute("ALTER TABLE jobs ADD COLUMN notify_mode TEXT NOT NULL DEFAULT 'always'")
        rule_columns = {row["name"] for row in c.execute("PRAGMA table_info(event_rules)").fetchall()}
        if "notify_channel" not in rule_columns:
            c.execute("ALTER TABLE event_rules ADD COLUMN notify_channel TEXT NOT NULL DEFAULT 'mobile'")
        if "zalo_thread_id" not in rule_columns:
            c.execute("ALTER TABLE event_rules ADD COLUMN zalo_thread_id TEXT NOT NULL DEFAULT ''")
        if "notify_mode" not in rule_columns:
            c.execute("ALTER TABLE event_rules ADD COLUMN notify_mode TEXT NOT NULL DEFAULT 'always'")
        custom_columns = {row["name"] for row in c.execute("PRAGMA table_info(custom_integrations)").fetchall()}
        if "actions_json" not in custom_columns:
            c.execute("ALTER TABLE custom_integrations ADD COLUMN actions_json TEXT NOT NULL DEFAULT '[]'")
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(chunk_id UNINDEXED, path, text)")
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(fact_id UNINDEXED, text, tags)")
        except sqlite3.OperationalError:
            pass
    info(logger, "database_init_completed", db_path=settings.db_path)


def add_message(session_id: str, role: str, content: str, source: str = "web"):
    with conn() as c:
        c.execute("INSERT INTO messages(session_id,role,content,source,created_at) VALUES(?,?,?,?,?)",
                  (session_id, role, content, source, utcnow()))


def get_messages(session_id: str, limit: int = 30) -> list[dict[str, str]]:
    with conn() as c:
        rows = c.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def add_event(event_type: str, entity_id: str | None, payload: dict):
    with conn() as c:
        c.execute("INSERT INTO events(event_type,entity_id,payload,created_at) VALUES(?,?,?,?)",
                  (event_type, entity_id, json.dumps(redact(payload), ensure_ascii=False), utcnow()))
        c.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)", (settings.event_retention,))


def recent_events(limit: int = 50) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = redact(json.loads(d["payload"]))
        d = redact(d)
        out.append(d)
    return out


def list_approvals(limit: int = 100) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT id,kind,target_id,reason,diff,risk,status,created_at,decided_at,decided_by,applied_at,error,parent_change_id FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_jobs() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def list_event_rules() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM event_rules ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]




def _paged_rows(table: str, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    if table not in {"jobs", "event_rules"}:
        raise ValueError("Unsupported paged table")
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    with conn() as c:
        total = int(c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        offset = (page - 1) * page_size
        rows = c.execute(
            f"SELECT * FROM {table} ORDER BY id DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
    }


def list_jobs_page(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    return _paged_rows("jobs", page, page_size)


def list_event_rules_page(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    return _paged_rows("event_rules", page, page_size)

def add_memory(text: str, tags: str = "", source: str = "user") -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO memory_facts(text,tags,source,created_at) VALUES(?,?,?,?)", (text, tags, source, utcnow()))
        fid = int(cur.lastrowid)
        try:
            c.execute("INSERT INTO memory_fts(fact_id,text,tags) VALUES(?,?,?)", (fid, text, tags))
        except sqlite3.OperationalError:
            pass
    return fid


def search_memory(query: str, limit: int = 10) -> list[dict[str, Any]]:
    with conn() as c:
        try:
            rows = c.execute("SELECT m.* FROM memory_fts f JOIN memory_facts m ON m.id=f.fact_id WHERE memory_fts MATCH ? LIMIT ?", (query, limit)).fetchall()
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = c.execute("SELECT * FROM memory_facts WHERE text LIKE ? OR tags LIKE ? ORDER BY id DESC LIMIT ?", (like, like, limit)).fetchall()
    return [dict(r) for r in rows]


def add_tool_audit(tool_name: str, arguments: dict, result: object | None = None, error: str | None = None):
    safe_arguments = redact(arguments)
    safe_result = redact(result) if result is not None else None
    safe_error = redact(error) if error is not None else None
    with conn() as c:
        c.execute(
            "INSERT INTO tool_audit(tool_name,arguments,result,error,created_at) VALUES(?,?,?,?,?)",
            (tool_name, json.dumps(safe_arguments, ensure_ascii=False, default=str),
             json.dumps(safe_result, ensure_ascii=False, default=str)[:20000] if safe_result is not None else None,
             str(safe_error)[:5000] if safe_error is not None else None, utcnow()),
        )


def recent_tool_audit(limit: int = 100) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM tool_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        try: d["arguments"]=json.loads(d["arguments"])
        except Exception: pass
        try: d["result"]=json.loads(d["result"]) if d["result"] else None
        except Exception: pass
        out.append(redact(d))
    return out

def _redact_json_text(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
        return json.dumps(redact(parsed), ensure_ascii=False, default=str)
    except Exception:
        return str(redact(value))


def scrub_sensitive_audit_history() -> dict[str, int]:
    """Sanitize pre-existing diagnostic/audit rows created by older HassMind builds."""
    counts = {"events": 0, "tool_audit": 0}
    if not settings.audit_scrub_existing_on_start:
        return counts
    with conn() as c:
        for row in c.execute("SELECT id,payload FROM events").fetchall():
            safe = _redact_json_text(row["payload"]) or "{}"
            if safe != row["payload"]:
                c.execute("UPDATE events SET payload=? WHERE id=?", (safe, row["id"]))
                counts["events"] += 1
        for row in c.execute("SELECT id,arguments,result,error FROM tool_audit").fetchall():
            arguments = _redact_json_text(row["arguments"]) or "{}"
            result = _redact_json_text(row["result"]) if row["result"] is not None else None
            error_text = str(redact(row["error"])) if row["error"] is not None else None
            if arguments != row["arguments"] or result != row["result"] or error_text != row["error"]:
                c.execute(
                    "UPDATE tool_audit SET arguments=?,result=?,error=? WHERE id=?",
                    (arguments, result, error_text, row["id"]),
                )
                counts["tool_audit"] += 1
    if counts["events"] or counts["tool_audit"]:
        info(logger, "audit_history_scrubbed", **counts)
    return counts

