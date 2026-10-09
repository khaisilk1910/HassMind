"""Trusted, session-local context for follow-up questions.

Prior assistant prose is never treated as a device ID or as a live state.  The
focus is a previously verified Knowledge Device identity, revalidated on use.
"""
from __future__ import annotations

import re
from typing import Any

from . import device_catalog, rag
from .db import clear_session_device_focus, read_session_device_focus, save_session_device_focus
from .settings import settings

# Narrow categories only: don't extrapolate arbitrary entities from language.
_PROPERTIES = {
    "voltage": ("dien ap", "voltage", "bao nhieu v", "so von"),
    "current": ("dong dien", "cuong do", "current", "bao nhieu a"),
    "power": ("cong suat", "power", "bao nhieu w", "tieu thu bao nhieu w"),
    "energy": ("dien nang", "dien tieu thu", "energy", "kwh"),
    "temperature": ("nhiet do", "temperature"),
    "humidity": ("do am", "humidity"),
    "battery": ("pin", "battery"),
    "switch": ("bat hay tat", "dang bat", "dang tat", "bat khong", "tat khong",
               "on hay off", "nguon dang", "switch dang"),
}
_FOLLOWUPS = ("no", "cai do", "thiet bi do", "may do", "cua no", "vay", "the", "con",
              "tiep", "nu a", "them", "o cam do", "ban do", "luc nay", "vua roi")
_READ = ("trang thai", "xem", "kiem tra", "bao nhieu", "thong so", "hien tai", "bao cao",
         "ra sao", "the nao", "nhu nao", "co bat", "co tat", "chi tiet", "liet ke")
_NEW_TOPIC = ("doi chu de", "chuyen chu de", "khong noi ve", "quen chuyen", "bo qua chuyen")
_EXPLICIT_OTHER = ("thoi tiet", "tin tuc", "gia vang", "chung khoan", "lich am", "hom nay la ngay", "may gio")
_ACK = {"ok", "oke", "cam on", "thanks", "duoc roi", "hieu roi", "dong y", "da ro"}


def _phrase(normalized: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalized} "


def focused_device(session_id: str, source: str) -> dict[str, str] | None:
    identity = read_session_device_focus(session_id, source, settings.conversation_focus_minutes)
    if not identity:
        return None
    # Validate against the current indexed Knowledge catalog, not earlier chat or AI text.
    for row in rag.load_catalog():
        if row.get("kind") != "device":
            continue
        match = (row.get("metadata") or {}).get("match") or {}
        if isinstance(match, dict) and match.get("device_id") == identity:
            return {"device_id": identity, "name": str(row.get("name") or identity),
                    "area": str(row.get("area") or "")}
    clear_session_device_focus(session_id, source)
    return None


def is_explicit_new_topic(text: str) -> bool:
    n = rag.normalize(text)
    return any(_phrase(n, phrase) for phrase in (*_NEW_TOPIC, *_EXPLICIT_OTHER))


def followup_subject(text: str) -> bool:
    n = rag.normalize(text)
    return any(_phrase(n, token) for token in _FOLLOWUPS) or bool(followup_property(text))


def followup_property(text: str) -> str | None:
    n = rag.normalize(text)
    found = [kind for kind, labels in _PROPERTIES.items() if any(_phrase(n, label) for label in labels)]
    return found[0] if len(found) == 1 else None


def followup_read_request(text: str) -> tuple[bool, str | None]:
    """Require overt read evidence; a pronoun by itself cannot trigger HA tools."""
    n = rag.normalize(text)
    if not n or is_explicit_new_topic(text):
        return False, None
    # Explanations, comparisons and assessments need semantics rather than a
    # bare sensor read. Never transform a compound action into a read.
    semantic = ("so sanh", "khac nhau", "tai sao", "vi sao", "giai thich", "lam sao",
                "co on khong", "binh thuong khong", "co nguy hiem", "co loi", "cao qua", "thap qua")
    if any(_phrase(n, token) for token in semantic):
        return False, None
    if any(_phrase(n, token) for token in ("tat no", "bat no", "mo no", "dong no", "reset no")):
        return False, None
    prop = followup_property(text)
    has_read = prop is not None or any(_phrase(n, phrase) for phrase in _READ)
    has_reference = any(_phrase(n, phrase) for phrase in _FOLLOWUPS)
    # 'còn điện áp?' and 'bao nhiêu W?' are also clearly relational queries.
    return (bool(prop or (has_reference and has_read)), prop)


def should_keep_focus(text: str) -> bool:
    n = rag.normalize(text)
    if is_explicit_new_topic(text):
        return False
    if n in _ACK:
        return True
    if followup_subject(text):
        return True
    return any(_phrase(n, phrase) for phrase in ("tai sao", "vi sao", "giai thich", "so sanh")) and bool(re.search(r"\b(?:no|do|nay|vay)\b", n))


def explicit_device(text: str) -> dict[str, Any]:
    return device_catalog.match_device_in_message(text)


def remember(session_id: str, source: str, selected: dict[str, str]) -> None:
    save_session_device_focus(session_id, source, selected["device_id"])
