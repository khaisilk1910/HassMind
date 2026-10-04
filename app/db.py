import json
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings
from .observability import exception, get_logger, info, redact

logger = get_logger("database")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        rule_columns = {row["name"] for row in c.execute("PRAGMA table_info(event_rules)").fetchall()}
        if "notify_channel" not in rule_columns:
            c.execute("ALTER TABLE event_rules ADD COLUMN notify_channel TEXT NOT NULL DEFAULT 'mobile'")
        if "zalo_thread_id" not in rule_columns:
            c.execute("ALTER TABLE event_rules ADD COLUMN zalo_thread_id TEXT NOT NULL DEFAULT ''")
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

