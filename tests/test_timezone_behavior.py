from datetime import datetime, timezone

from app import db
from app.scheduler import _next_run
from app.settings import settings
from app.time_utils import configure_process_timezone, now_iso, parse_datetime, timezone_name


def _set_tz(monkeypatch, name="Asia/Ho_Chi_Minh"):
    monkeypatch.setattr(settings, "timezone", name)
    configure_process_timezone()


def test_now_iso_uses_configured_timezone(monkeypatch):
    _set_tz(monkeypatch)
    value = now_iso()
    assert value.endswith("+07:00")
    assert timezone_name() == "Asia/Ho_Chi_Minh"


def test_parse_legacy_utc_converts_to_configured_timezone(monkeypatch):
    _set_tz(monkeypatch)
    dt = parse_datetime("2026-10-04T11:27:57+00:00")
    assert dt is not None
    assert dt.isoformat() == "2026-10-04T18:27:57+07:00"


def test_scheduler_interval_returns_configured_timezone(monkeypatch):
    _set_tz(monkeypatch)
    start = datetime(2026, 10, 4, 11, 0, 0, tzinfo=timezone.utc)
    result = _next_run("interval", "60", start)
    assert result.isoformat() == "2026-10-04T18:01:00+07:00"


def test_scheduler_daily_uses_configured_wall_clock(monkeypatch):
    _set_tz(monkeypatch)
    start = datetime(2026, 10, 4, 11, 0, 0, tzinfo=timezone.utc)  # 18:00 local
    result = _next_run("daily", "21:00", start)
    assert result.isoformat() == "2026-10-04T21:00:00+07:00"


def test_database_timestamp_normalization_converts_legacy_rows(monkeypatch, tmp_path):
    _set_tz(monkeypatch)
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "tz.db"))
    db.init_db()
    with db.conn() as c:
        c.execute(
            "INSERT INTO jobs(name,prompt,schedule_type,schedule_value,enabled,notify,notify_channel,zalo_thread_id,next_run,last_run,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy",
                "test",
                "interval",
                "60",
                1,
                0,
                "mobile",
                "",
                "2026-10-04T11:27:57+00:00",
                "2026-10-04T11:26:57+00:00",
                "2026-10-04T10:00:00+00:00",
            ),
        )
    changed = db.normalize_stored_timestamps()
    assert changed >= 3
    with db.conn() as c:
        row = c.execute("SELECT next_run,last_run,created_at FROM jobs WHERE name='legacy'").fetchone()
    assert row["next_run"].startswith("2026-10-04T18:27:57") and row["next_run"].endswith("+07:00")
    assert row["last_run"].startswith("2026-10-04T18:26:57") and row["last_run"].endswith("+07:00")
    assert row["created_at"].startswith("2026-10-04T17:00:00") and row["created_at"].endswith("+07:00")

def test_database_normalizes_owned_knowledge_json_timestamps(monkeypatch, tmp_path):
    import json
    from app import knowledge_governance as kg, rag

    _set_tz(monkeypatch)
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "tz-json.db"))
    db.init_db()
    kg.ensure_schema()
    with db.conn() as c:
        rag.ensure_schema(c)
        c.execute(
            "INSERT OR REPLACE INTO knowledge_index_state(id,data) VALUES(1,?)",
            (json.dumps({"status": "ready", "indexed_at": "2026-10-04T11:00:00+00:00", "scanned_at": "2026-10-04T10:59:00+00:00"}),),
        )
        scan = {"id": "s1", "created_at": "2026-10-04T11:30:00+00:00", "scanned_at": "2026-10-04T11:29:00+00:00"}
        c.execute("INSERT INTO knowledge_scans(id,created_at,payload) VALUES(?,?,?)", ("s1", scan["created_at"], json.dumps(scan)))
    db.normalize_stored_timestamps()
    with db.conn() as c:
        state = json.loads(c.execute("SELECT data FROM knowledge_index_state WHERE id=1").fetchone()["data"])
        scan = json.loads(c.execute("SELECT payload FROM knowledge_scans WHERE id='s1'").fetchone()["payload"])
    assert state["indexed_at"].startswith("2026-10-04T18:00:00") and state["indexed_at"].endswith("+07:00")
    assert state["scanned_at"].startswith("2026-10-04T17:59:00") and state["scanned_at"].endswith("+07:00")
    assert scan["created_at"].startswith("2026-10-04T18:30:00") and scan["created_at"].endswith("+07:00")
