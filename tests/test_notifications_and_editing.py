import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import knowledge_governance as kg
from app.db import conn, init_db
from app.event_engine import create_event_rule, handle_state_event, set_rule_enabled, update_event_rule
from app.integrations.zalo import ZaloClient
from app.integration_config import load_runtime_integration_overrides, save_integration_config
from app.message_format import format_mobile_notification, format_mobile_notification_title
from app.notifications import (
    get_notification_preference,
    resolve_zalo_thread_id,
    save_notification_preference,
    send_notification,
)
from app.scheduler import _next_run, create_job, scheduler_loop, set_job_enabled, update_job
from app.settings import settings


class _MobileHA:
    def __init__(self):
        self.calls = []

    async def notify(self, message, title="", actions=None):
        self.calls.append({"message": message, "title": title, "actions": actions})
        return {"ok": True}


class _RecordingZalo(ZaloClient):
    def __init__(self):
        super().__init__("http://invalid.local", "", "")
        self.requests = []

    async def ensure_login(self):
        return None

    async def _select_account(self, requested=""):
        return requested or "test-account"

    async def request(self, method, path, **kwargs):
        self.requests.append({"method": method, "path": path, **kwargs})
        return {"success": True}


class _Integrations:
    def __init__(self, zalo):
        self.zalo = zalo


class NotificationsAndEditingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        keys = (
            "db_path",
            "knowledge_dir",
            "zalo_enabled",
            "zalo_allow_send",
            "zalo_notification_thread_id",
            "zalo_notification_thread_type",
            "zalo_agent_allowed_thread_ids",
            "zalo_default_account",
            "scheduler_enabled",
            "event_agent_enabled",
        )
        self.old = {k: getattr(settings, k) for k in keys}
        settings.db_path = str(Path(self.tmp.name) / "data" / "test.db")
        settings.knowledge_dir = str(Path(self.tmp.name) / "knowledge")
        settings.zalo_enabled = False
        settings.zalo_allow_send = False
        settings.zalo_notification_thread_id = ""
        settings.zalo_notification_thread_type = 0
        settings.zalo_agent_allowed_thread_ids = ""
        settings.zalo_default_account = ""
        settings.scheduler_enabled = True
        settings.event_agent_enabled = True
        Path(settings.knowledge_dir).mkdir(parents=True)
        init_db()
        kg.ensure_schema()

    def tearDown(self):
        for k, v in self.old.items():
            setattr(settings, k, v)
        self.tmp.cleanup()

    def test_mobile_notification_is_plain_text_with_readable_emoji_structure(self):
        raw = "# Trạng thái nhà\n- **Đèn:** `on`\n> Kiểm tra lại\n\n**Kết luận:** ổn"
        text = format_mobile_notification(raw)
        self.assertIn("📌 Trạng thái nhà", text)
        self.assertIn("• Đèn: on", text)
        self.assertIn("💡 Kiểm tra lại", text)
        self.assertNotIn("**", text)
        self.assertNotIn("`", text)
        self.assertNotIn("# ", text)
        self.assertEqual(format_mobile_notification_title("HassMind · Knowledge"), "🤖 HassMind · Knowledge")

    def test_mobile_send_formats_message_and_preserves_actions(self):
        ha = _MobileHA()
        asyncio.run(
            send_notification(
                ha,
                None,
                "# Cảnh báo\n- **Cửa:** `open`",
                title="HassMind",
                channel="mobile",
                actions=[{"action": "YES", "title": "Duyệt"}],
            )
        )
        self.assertEqual(len(ha.calls), 1)
        call = ha.calls[0]
        self.assertTrue(call["title"].startswith("🤖 "))
        self.assertIn("📌 Cảnh báo", call["message"])
        self.assertNotIn("**", call["message"])
        self.assertEqual(call["actions"][0]["action"], "YES")

    def test_zalo_send_uses_chat_rich_text_compiler_and_existing_thread_fallback(self):
        settings.zalo_enabled = True
        settings.zalo_allow_send = True
        settings.zalo_agent_allowed_thread_ids = "*, zalo:thread-fallback"
        settings.zalo_notification_thread_id = ""
        zalo = _RecordingZalo()
        result = asyncio.run(
            send_notification(
                None,
                _Integrations(zalo),
                "- **Cửa chính:** Đang mở",
                title="HassMind · Event",
                channel="zalo",
                zalo_thread_id="",
            )
        )
        self.assertEqual(resolve_zalo_thread_id(""), "thread-fallback")
        self.assertEqual(result["thread_id"], "thread-fallback")
        self.assertEqual(len(zalo.requests), 1)
        body = zalo.requests[0]["json"]
        self.assertEqual(body["threadId"], "thread-fallback")
        # ZaloClient.send_message uses build_zalo_message_content, exactly like chat replies.
        self.assertIsInstance(body["message"], dict)
        self.assertIn("msg", body["message"])
        self.assertIn("styles", body["message"])
        self.assertNotIn("**", body["message"]["msg"])
        self.assertTrue(body["message"]["styles"])

    def test_long_zalo_notification_is_split_before_transport(self):
        settings.zalo_enabled = True
        settings.zalo_allow_send = True
        settings.zalo_agent_allowed_thread_ids = "thread-fallback"
        zalo = _RecordingZalo()
        message = "\n".join(
            f"- **Công tắc {i}:** {{green}}Bật{{/green}} · **Khu vực:** Phòng học"
            for i in range(80)
        )
        result = asyncio.run(
            send_notification(
                None,
                _Integrations(zalo),
                message,
                title="HassMind · Scheduler",
                channel="zalo",
            )
        )
        self.assertGreater(result["chunks"], 1)
        self.assertEqual(result["chunks"], len(zalo.requests))
        for request in zalo.requests:
            content = request["json"]["message"]
            self.assertLessEqual(len(content["msg"]), 900)
            self.assertLessEqual(len(content["styles"]), 40)

    def test_explicit_zalo_thread_overrides_default_then_allowed_list(self):
        settings.zalo_notification_thread_id = "zalo:default-thread"
        settings.zalo_agent_allowed_thread_ids = "allowed-thread"
        self.assertEqual(resolve_zalo_thread_id("explicit-thread"), "explicit-thread")
        self.assertEqual(resolve_zalo_thread_id(""), "default-thread")
        settings.zalo_notification_thread_id = ""
        self.assertEqual(resolve_zalo_thread_id(""), "allowed-thread")

    def test_zalo_default_notification_thread_persists_in_integration_config(self):
        save_integration_config(
            "zalo",
            {"notification_thread_id": "zalo:default-notify", "notification_thread_type": 1},
        )
        self.assertEqual(settings.zalo_notification_thread_id, "zalo:default-notify")
        self.assertEqual(settings.zalo_notification_thread_type, 1)
        settings.zalo_notification_thread_id = ""
        settings.zalo_notification_thread_type = 0
        load_runtime_integration_overrides()
        self.assertEqual(settings.zalo_notification_thread_id, "zalo:default-notify")
        self.assertEqual(settings.zalo_notification_thread_type, 1)
        self.assertEqual(resolve_zalo_thread_id(""), "default-notify")

    def test_notification_preference_persists_channel_and_thread(self):
        saved = save_notification_preference(
            "approvals", enabled=True, channel="zalo", zalo_thread_id="zalo:abc123"
        )
        self.assertEqual(saved["channel"], "zalo")
        self.assertEqual(saved["zalo_thread_id"], "abc123")
        self.assertEqual(get_notification_preference("approvals"), saved)

    def test_scheduler_create_and_edit_notification_route_without_auto_enable(self):
        created = create_job("Night report", "Summarize", "interval", "300", True, "zalo", "zalo:t1")
        jid = created["id"]
        with conn() as c:
            row = dict(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
        self.assertEqual(row["enabled"], 0)
        self.assertEqual(row["notify_channel"], "zalo")
        self.assertEqual(row["zalo_thread_id"], "t1")

        set_job_enabled(jid, True)
        updated = update_job(
            jid,
            name="Night report edited",
            prompt="Summarize carefully",
            schedule_type="daily",
            schedule_value="21:15",
            notify=False,
            notify_channel="mobile",
            zalo_thread_id="",
        )
        self.assertTrue(updated["enabled"])
        self.assertTrue(updated["next_run"])
        with conn() as c:
            row = dict(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["name"], "Night report edited")
        self.assertEqual(row["schedule_value"], "21:15")
        self.assertEqual(row["notify"], 0)
        self.assertEqual(row["notify_channel"], "mobile")

    def test_scheduler_interval_30_seconds_is_not_silently_clamped_to_60(self):
        now = datetime(2026, 10, 4, 11, 0, 0, tzinfo=timezone.utc)
        self.assertEqual((_next_run("interval", "30", now) - now).total_seconds(), 30)
        with self.assertRaises(ValueError):
            _next_run("interval", "29", now)

    def test_event_rule_create_and_edit_preserves_enabled_state_and_route(self):
        created = create_event_rule("Door", "binary_sensor.door", "on", "Check door", 120, True, "zalo", "t2")
        rid = created["id"]
        set_rule_enabled(rid, True)
        updated = update_event_rule(
            rid,
            name="Door edited",
            entity_id="binary_sensor.front_door",
            to_state="off",
            prompt="Check front door",
            cooldown_seconds=30,
            notify=True,
            notify_channel="mobile",
            zalo_thread_id="",
        )
        self.assertTrue(updated["enabled"])
        with conn() as c:
            row = dict(c.execute("SELECT * FROM event_rules WHERE id=?", (rid,)).fetchone())
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["name"], "Door edited")
        self.assertEqual(row["entity_id"], "binary_sensor.front_door")
        self.assertEqual(row["cooldown_seconds"], 60)
        self.assertEqual(row["notify_channel"], "mobile")

    def test_scheduler_runtime_passes_persisted_notification_route(self):
        created = create_job("Due", "Run due prompt", "interval", "300", True, "zalo", "runtime-job")
        jid = created["id"]
        with conn() as c:
            c.execute("UPDATE jobs SET enabled=1,next_run=? WHERE id=?", ("2000-01-01T00:00:00+00:00", jid))
        seen = []
        stop = asyncio.Event()

        async def run_prompt(session_id, prompt, notify, channel, thread_id):
            seen.append((session_id, prompt, notify, channel, thread_id))
            stop.set()
            return "done"

        asyncio.run(scheduler_loop(stop, run_prompt))
        self.assertEqual(seen, [(f"job:{jid}", "Run due prompt", True, "zalo", "runtime-job")])

    def test_event_runtime_passes_persisted_notification_route(self):
        created = create_event_rule("Door", "binary_sensor.door", "on", "Check door", 60, True, "zalo", "runtime-rule")
        rid = created["id"]
        set_rule_enabled(rid, True)
        seen = []

        async def run_prompt(session_id, prompt, notify, channel, thread_id):
            seen.append((session_id, prompt, notify, channel, thread_id))
            return "done"

        event = {"data": {"entity_id": "binary_sensor.door", "new_state": {"state": "on", "attributes": {"friendly_name": "Door"}}}}
        asyncio.run(handle_state_event(event, run_prompt))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], f"event-rule:{rid}")
        self.assertTrue(seen[0][1].startswith("Check door"))
        self.assertEqual(seen[0][2:], (True, "zalo", "runtime-rule"))

    def test_review_queue_returns_at_most_four_stale_proposals(self):
        ids = []
        for i in range(7):
            proposal = kg.create_proposal(
                [{"path": f"stale-{i}.md", "new_content": f"content {i}"}],
                f"proposal {i}",
            )
            ids.append(proposal["id"])
        with conn() as c:
            c.executemany("UPDATE knowledge_proposals SET status='stale' WHERE id=?", [(x,) for x in ids])
        rows = kg.list_proposals(limit=100)
        stale = [row for row in rows if row["status"] == "stale"]
        self.assertEqual(len(stale), 4)

    def test_init_db_migrates_old_job_and_rule_tables(self):
        old_db = Path(self.tmp.name) / "old.db"
        settings.db_path = str(old_db)
        with sqlite3.connect(old_db) as c:
            c.executescript(
                """
                CREATE TABLE jobs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,prompt TEXT NOT NULL,schedule_type TEXT NOT NULL,schedule_value TEXT NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 0,notify INTEGER NOT NULL DEFAULT 1,next_run TEXT,last_run TEXT,last_result TEXT,created_at TEXT NOT NULL
                );
                CREATE TABLE event_rules (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,entity_id TEXT NOT NULL,to_state TEXT,prompt TEXT NOT NULL,cooldown_seconds INTEGER NOT NULL DEFAULT 300,
                  enabled INTEGER NOT NULL DEFAULT 0,notify INTEGER NOT NULL DEFAULT 1,last_triggered TEXT,created_at TEXT NOT NULL
                );
                """
            )
        init_db()
        with conn() as c:
            job_cols = {row["name"] for row in c.execute("PRAGMA table_info(jobs)")}
            rule_cols = {row["name"] for row in c.execute("PRAGMA table_info(event_rules)")}
            pref = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notification_preferences'").fetchone()
        self.assertTrue({"notify_channel", "zalo_thread_id"} <= job_cols)
        self.assertTrue({"notify_channel", "zalo_thread_id"} <= rule_cols)
        self.assertIsNotNone(pref)


if __name__ == "__main__":
    unittest.main()
