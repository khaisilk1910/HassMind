"""Durable 60-second, text-first Zalo note drafts.

Drafts survive a process restart; the background sweeper finishes overdue drafts.
Photos are attached only after a draft was explicitly opened in that Zalo thread.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import notes
from .db import conn

WAIT_SECONDS = 60


def init_draft_db(c) -> None:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS zalo_note_drafts (
      session_id TEXT PRIMARY KEY,
      content TEXT NOT NULL,
      note_id TEXT,
      deadline REAL NOT NULL,
      account_id TEXT NOT NULL,
      thread_id TEXT NOT NULL,
      thread_type INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_zalo_note_drafts_deadline ON zalo_note_drafts(deadline);
    ''')


def get_draft(session: str) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute('SELECT * FROM zalo_note_drafts WHERE session_id=?', (session,)).fetchone()
        return dict(row) if row else None


def start_draft(session: str, content: str, account: str, thread: str, thread_type: int, *, now: float | None = None) -> dict[str, Any]:
    content = str(content).strip()
    if not content or len(content) > notes.MAX_NOTE_CHARS:
        raise ValueError('Hãy nhập nội dung ghi chú (tối đa 12.000 ký tự).')
    deadline = (time.time() if now is None else now) + WAIT_SECONDS
    with conn() as c:
        c.execute('''INSERT INTO zalo_note_drafts(session_id,content,note_id,deadline,account_id,thread_id,thread_type)
                     VALUES(?,?,NULL,?,?,?,?)
                     ON CONFLICT(session_id) DO UPDATE SET content=excluded.content,note_id=NULL,
                     deadline=excluded.deadline,account_id=excluded.account_id,
                     thread_id=excluded.thread_id,thread_type=excluded.thread_type''',
                  (session, content, deadline, account, thread, int(thread_type)))
    return get_draft(session)


def _create_note(draft: dict[str, Any], images: list[tuple[bytes, str]] | None = None) -> dict[str, Any]:
    content = draft['content']
    return notes.create_note(content.splitlines()[0].strip()[:110], content,
                             re.findall(r'#([\w\-]+)', content), images=images or [],
                             max_input_bytes=7 * 1024 * 1024)


def attach_draft_photos(session: str, photos: list[tuple[bytes, str]], *, now: float | None = None) -> dict[str, Any] | None:
    draft = get_draft(session)
    if not draft or draft['deadline'] <= (time.time() if now is None else now):
        return None
    if len(photos) > notes.MAX_IMAGES:
        raise ValueError('Một ghi chú chỉ chứa tối đa 5 ảnh.')
    if draft['note_id']:
        updated = notes.append_images(draft['note_id'], photos, max_input_bytes=7 * 1024 * 1024)
        if updated is None:
            raise ValueError('Ghi chú không còn tồn tại.')
        return updated
    saved = _create_note(draft, photos)
    with conn() as c:
        c.execute('UPDATE zalo_note_drafts SET note_id=? WHERE session_id=? AND note_id IS NULL',
                  (saved['id'], session))
    return saved


def finish_draft(session: str, *, now: float | None = None, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Finish one pending note. Return (note, draft context) for optional Zalo receipt."""
    draft = get_draft(session)
    if not draft or (not force and draft['deadline'] > (time.time() if now is None else now)):
        return None
    note = notes.get_note(draft['note_id']) if draft['note_id'] else _create_note(draft)
    if note is None:
        # A deleted, once-created note must not be recreated accidentally.
        with conn() as c:
            c.execute('DELETE FROM zalo_note_drafts WHERE session_id=?', (session,))
        return None
    with conn() as c:
        c.execute('DELETE FROM zalo_note_drafts WHERE session_id=?', (session,))
    return note, draft


def due_sessions(*, now: float | None = None) -> list[str]:
    with conn() as c:
        rows = c.execute('SELECT session_id FROM zalo_note_drafts WHERE deadline<=? ORDER BY deadline LIMIT 100',
                         (time.time() if now is None else now,)).fetchall()
        return [row[0] for row in rows]
