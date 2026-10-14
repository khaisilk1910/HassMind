"""Calendar-day chat retention and bounded admin security log pagination."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import db
from app.auth import list_auth_audit, list_auth_audit_page
from app.settings import settings


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "data.db"))
    monkeypatch.setattr(settings, "timezone", "Asia/Ho_Chi_Minh")
    db.init_db()


def test_chat_messages_only_today_and_purged_on_new_day(isolated_db, monkeypatch):
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    monkeypatch.setattr(db, "local_now", lambda: datetime(2026, 10, 13, 17, 0, tzinfo=tz))
    with db.conn() as c:
        c.executemany(
            "INSERT INTO messages(session_id,role,content,source,created_at) VALUES(?,?,?,?,?)",
            [
                ("A", "user", "old local", "web", "2026-10-12T23:59:59+07:00"),
                ("A", "assistant", "old UTC-offset", "web", "2026-10-12T16:59:59+00:00"),
                ("A", "user", "today user", "web", "2026-10-13T00:00:00+07:00"),
                ("A", "assistant", "today assistant", "web", "2026-10-13T17:00:00+07:00"),
                ("B", "user", "old other source", "zalo", "2026-10-12T12:00:00+07:00"),
            ],
        )
    current = db.get_messages("A", 20, source="web", include_created_at=True)
    assert [r["content"] for r in current] == ["today user", "today assistant"]
    assert current[0]["created_at"] == "2026-10-13T00:00:00+07:00"
    assert [r["content"] for r in db.get_older_session_messages("A", "web", skip=0, limit=20)] == [
        "today user", "today assistant"
    ]
    assert db.cleanup_chat_history() == 3
    assert db.cleanup_chat_history() == 0

    # The moment the configured local calendar changes, yesterday's messages disappear.
    monkeypatch.setattr(db, "local_now", lambda: datetime(2026, 10, 14, 0, 0, tzinfo=tz))
    assert db.get_messages("A", 20, source="web") == []
    assert db.get_older_session_messages("A", "web", skip=0, limit=20) == []
    assert db.cleanup_chat_history() == 2
    assert db.get_messages("A", 20, source="web") == []


def test_default_context_shape_stays_unchanged(isolated_db):
    db.add_message("A", "user", "hello", "web")
    row = db.get_messages("A", source="web")[0]
    assert row == {"role": "user", "content": "hello"}
    assert "created_at" in db.get_messages("A", source="web", include_created_at=True)[0]


def test_auth_audit_pagination(isolated_db):
    with db.conn() as c:
        c.executemany(
            "INSERT INTO auth_audit(event,username,ip,success,details,created_at) VALUES(?,?,?,?,?,?)",
            [(f"event-{i}", "admin", "127.0.0.1", 1, "", "2026-10-13T11:00:00+07:00") for i in range(47)],
        )
    p1 = list_auth_audit_page()
    assert (p1["page"], p1["page_size"], p1["total"], p1["pages"]) == (1, 20, 47, 3)
    assert len(p1["items"]) == 20
    assert p1["items"][0]["event"] == "event-46"
    p2 = list_auth_audit_page(2, 20)
    assert len(p2["items"]) == 20 and p2["items"][0]["event"] == "event-26"
    p3 = list_auth_audit_page(999, 20)
    assert p3["page"] == 3 and len(p3["items"]) == 7
    assert len(list_auth_audit_page(1, 10)["items"]) == 10
    # Old API consumers calling /api/auth/audit?limit= are still supported.
    assert len(list_auth_audit(50)) == 47


def test_device_focus_does_not_cross_midnight(isolated_db, monkeypatch):
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    monkeypatch.setattr(db, "local_now", lambda: datetime(2026, 10, 13, 23, 59, tzinfo=tz))
    with db.conn() as c:
        c.execute(
            "INSERT INTO session_device_focus(session_id,source,device_id,updated_at) "
            "VALUES(?,?,?,?)",
            ("web1", "web", "ha-device", int(datetime(2026, 10, 13, 23, 59, tzinfo=tz).timestamp())),
        )
    monkeypatch.setattr(db, "local_now", lambda: datetime(2026, 10, 14, 0, 0, tzinfo=tz))
    assert db.read_session_device_focus("web1", "web", ttl_minutes=60) == ""
    db.cleanup_chat_history()
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM session_device_focus").fetchone()[0] == 0
