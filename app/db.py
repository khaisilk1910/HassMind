import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def conn():
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(settings.db_path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
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
            """
        )
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(chunk_id UNINDEXED, path, text)")
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(fact_id UNINDEXED, text, tags)")
        except sqlite3.OperationalError:
            pass


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
                  (event_type, entity_id, json.dumps(payload, ensure_ascii=False), utcnow()))
        c.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)", (settings.event_retention,))


def recent_events(limit: int = 50) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
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
    with conn() as c:
        c.execute(
            "INSERT INTO tool_audit(tool_name,arguments,result,error,created_at) VALUES(?,?,?,?,?)",
            (tool_name, json.dumps(arguments, ensure_ascii=False, default=str),
             json.dumps(result, ensure_ascii=False, default=str)[:20000] if result is not None else None, error, utcnow()),
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
        out.append(d)
    return out
