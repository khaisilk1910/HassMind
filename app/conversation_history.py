"""Bounded, source-isolated conversation context for every interactive topic.

The database stores the entire session transcript. The agent receives a compact
recent window plus a few *relevant* older exchanges, never stale HA readings as
live evidence. All older content is untrusted conversation data.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .db import get_messages, get_older_session_messages
from .settings import settings

_STOP = {
    "toi", "ban", "minh", "cua", "cho", "the", "nay", "kia", "khong", "nhung",
    "mot", "nhieu", "noi", "den", "voi", "tren", "duoi", "nhu", "vay", "thi",
    "hay", "da", "dang", "duoc", "can", "muon", "giup", "lam", "sao", "nao",
    "bao", "nhieu", "tai", "vi", "sao", "vua", "roi", "truoc", "do", "lien",
    "quan", "hoi", "cau", "van", "de", "phan", "xem", "lai", "cu", "tu", "co",
    "la", "va", "oi", "chi", "tiet", "noi", "dung", "may", "cai", "gi",
    "what", "this", "that", "about", "tell", "more", "again", "please", "the",
    "and", "for", "with", "can", "you", "how", "why", "was", "were",
}


def _normalize(value: str) -> str:
    raw = unicodedata.normalize("NFD", str(value or "").casefold()).replace("đ", "d")
    unaccented = "".join(c for c in raw if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9_.]+", " ", unaccented)


def _terms(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if len(t) >= 3 and t not in _STOP}


def _bound_recent(history: list[dict[str, str]], max_chars: int) -> list[dict[str, str]]:
    """Retain latest turns and never truncate the currently submitted question."""
    remaining = max_chars
    result: list[dict[str, str]] = []
    for index, item in enumerate(reversed(history)):
        content = str(item.get("content") or "")
        current = index == 0 and item.get("role") == "user"
        max_message = len(content) if current else (3500 if item.get("role") == "assistant" else 2400)
        if not current and remaining < 200:
            break
        if current:
            part = content
        else:
            part = content[:max(0, min(len(content), max_message, remaining))]
            if len(part) < len(content):
                part += "\n[Phần còn lại đã lược bớt trong ngữ cảnh]"
        remaining -= len(part)
        result.append({"role": item["role"], "content": part})
    return list(reversed(result))


def _recall_older(rows: list[dict[str, Any]], question: str, limit: int, char_budget: int) -> list[dict[str, str]]:
    """Rank historical *user questions*, then include the adjacent assistant reply."""
    terms = _terms(question)
    if not terms or not rows or limit <= 0:
        return []
    candidates: list[tuple[int, int, list[dict[str, str]]]] = []
    for idx, row in enumerate(rows):
        if row["role"] != "user":
            continue
        previous_terms = _terms(row["content"])
        shared = previous_terms & terms
        if not shared:
            continue
        # An unusual specific topic word outweighs generic phrasing.
        score = sum(3 if len(term) >= 6 else (2 if len(term) >= 4 else 1) for term in shared)
        if score < 2:
            continue
        pair = [{"role": "user", "content": row["content"]}]
        if idx + 1 < len(rows) and rows[idx + 1]["role"] == "assistant":
            pair.append({"role": "assistant", "content": rows[idx + 1]["content"]})
        candidates.append((score, idx, pair))
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    picked: list[tuple[int, list[dict[str, str]]]] = []
    remaining = char_budget
    for score, idx, pair in candidates:
        if len(picked) >= limit or remaining < 160:
            break
        excerpt = []
        for item in pair:
            text = str(item["content"])
            capacity = min(1100 if item["role"] == "assistant" else 900, max(0, remaining))
            if capacity < 80:
                break
            excerpt.append({"role": item["role"], "content": text[:capacity]})
            remaining -= min(len(text), capacity)
        if excerpt:
            picked.append((idx, excerpt))
    # Chronological order maintains the original flow when several older items match.
    return [message for _, pair in sorted(picked, key=lambda x: x[0]) for message in pair]


def context_for_agent(session_id: str, source: str, user_text: str, history_limit: int) -> tuple[list[dict[str, str]], str]:
    """Return the recent chat messages and an optional bounded relevant-older excerpt.

    Scheduler/Event ``system`` runs must not inherit past chat, even with same id.
    """
    if source == "system":
        return ([{"role": "user", "content": user_text}], "")
    count = max(2, int(history_limit))
    recent = _bound_recent(
        get_messages(session_id, count, source=source),
        settings.conversation_context_max_chars,
    )
    # A giant previous answer can shrink the actual window: let retrieval scan
    # messages that could not fit, not only those outside the nominal limit.
    older = get_older_session_messages(
        session_id, source, skip=len(recent), limit=settings.conversation_recall_scan_messages,
    )
    recalled = _recall_older(
        older, user_text, limit=settings.conversation_recall_exchanges,
        char_budget=settings.conversation_recall_max_chars,
    )
    if not recalled:
        return recent, ""
    # JSON encoding makes boundaries and attribution explicit to the model.
    return recent, json.dumps(recalled, ensure_ascii=False)


def is_contextual_followup(text: str) -> bool:
    """Conservative gating: ambiguous references should not invoke deterministic HA actions."""
    n = _normalize(text).strip()
    if not n:
        return False
    phrases = (
        "vay", "the con", "con", "con no", "no", "cai do", "cai nay",
        "dieu do", "dieu nay", "phan do", "phan nay", "van de do", "van de nay",
        "o tren", "phia tren", "ben tren", "o truoc", "luc nay", "hoi nay",
        "luc truoc", "truoc do", "ban nay", "ban do", "vua roi", "quay lai",
        "nhac lai", "tiep tuc", "noi tiep", "giai thich them", "chi tiet hon",
        "ro hon", "ngan gon hon", "rut gon", "viet lai", "sua lai", "tom tat",
        "bo sung", "them vao", "so sanh voi cai", "why is it", "what about",
        "and that", "explain more", "summarize that", "rewrite it",
    )
    if any(n == p or n.startswith(p + " ") for p in phrases):
        return True
    pronouns = (" no ", " cai do ", " dieu do ", " o tren ", " vua roi ", " luc nay ", " truoc do ")
    padded = f" {n} "
    return any(p in padded for p in pronouns)
