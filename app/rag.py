from pathlib import Path
import sqlite3

from .db import conn, utcnow
from .settings import settings

ALLOWED = {".md", ".txt", ".yaml", ".yml", ".json"}


def chunks(text: str, size: int = 1400, overlap: int = 200):
    text = text.strip()
    if not text:
        return []
    out = []
    i = 0
    while i < len(text):
        out.append(text[i:i + size])
        if i + size >= len(text):
            break
        i += size - overlap
    return out


def reindex_knowledge() -> dict:
    root = Path(settings.knowledge_dir)
    root.mkdir(parents=True, exist_ok=True)
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED]
    count = 0
    with conn() as c:
        c.execute("DELETE FROM knowledge_chunks")
        try:
            c.execute("DELETE FROM knowledge_fts")
        except sqlite3.OperationalError:
            pass
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = str(path.relative_to(root))
            for idx, part in enumerate(chunks(text)):
                cur = c.execute("INSERT INTO knowledge_chunks(path,chunk_index,text,updated_at) VALUES(?,?,?,?)", (rel, idx, part, utcnow()))
                cid = int(cur.lastrowid)
                try:
                    c.execute("INSERT INTO knowledge_fts(chunk_id,path,text) VALUES(?,?,?)", (cid, rel, part))
                except sqlite3.OperationalError:
                    pass
                count += 1
    return {"files": len(files), "chunks": count}


def search_knowledge(query: str, limit: int = 8) -> list[dict]:
    with conn() as c:
        try:
            rows = c.execute("SELECT k.* FROM knowledge_fts f JOIN knowledge_chunks k ON k.id=f.chunk_id WHERE knowledge_fts MATCH ? LIMIT ?", (query, limit)).fetchall()
        except sqlite3.OperationalError:
            rows = c.execute("SELECT * FROM knowledge_chunks WHERE text LIKE ? OR path LIKE ? LIMIT ?", (f"%{query}%", f"%{query}%", limit)).fetchall()
    return [dict(r) for r in rows]
