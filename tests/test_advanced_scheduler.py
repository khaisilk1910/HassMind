import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import conn, init_db
from app.scheduler import _next_run, _schedule_description, create_job, scheduler_loop
from app.settings import settings
from app.time_utils import configure_process_timezone


class AdvancedSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.old_timezone = settings.timezone
        settings.timezone = "Asia/Ho_Chi_Minh"
        configure_process_timezone()
        self.tz = ZoneInfo("Asia/Ho_Chi_Minh")

    def tearDown(self):
        settings.timezone = self.old_timezone
        configure_process_timezone()

    def test_weekly_runs_only_on_selected_weekdays(self):
        value = json.dumps({"time": "21:00", "weekdays": [0, 2, 4]})  # Mon/Wed/Fri
        start = datetime(2026, 10, 6, 22, 0, tzinfo=self.tz)  # Tuesday
        result = _next_run("weekly", value, start)
        self.assertEqual(result.isoformat(), "2026-10-07T21:00:00+07:00")

    def test_weekly_skips_same_day_time_that_already_passed(self):
        value = json.dumps({"time": "21:00", "weekdays": [0]})
        start = datetime(2026, 10, 5, 21, 0, tzinfo=self.tz)  # Monday exactly at slot
        result = _next_run("weekly", value, start)
        self.assertEqual(result.isoformat(), "2026-10-12T21:00:00+07:00")

    def test_window_same_day_repeats_until_stop_boundary(self):
        value = json.dumps({"start": "08:00", "end": "12:00", "every_minutes": 45, "weekdays": [0, 1, 2, 3, 4, 5, 6]})
        start = datetime(2026, 10, 5, 9, 1, tzinfo=self.tz)
        result = _next_run("window", value, start)
        self.assertEqual(result.isoformat(), "2026-10-05T09:30:00+07:00")

    def test_window_cross_midnight_uses_start_day_weekday(self):
        value = json.dumps({"start": "23:00", "end": "06:00", "every_minutes": 60, "weekdays": [0]})  # Monday start
        start = datetime(2026, 10, 6, 0, 10, tzinfo=self.tz)  # Tuesday, still Monday's window
        result = _next_run("window", value, start)
        self.assertEqual(result.isoformat(), "2026-10-06T01:00:00+07:00")

    def test_window_end_is_stop_boundary_not_execution(self):
        value = json.dumps({"start": "23:00", "end": "06:00", "every_minutes": 60, "weekdays": [0, 1, 2, 3, 4, 5, 6]})
        start = datetime(2026, 10, 6, 5, 0, tzinfo=self.tz)
        result = _next_run("window", value, start)
        self.assertEqual(result.isoformat(), "2026-10-06T23:00:00+07:00")

    def test_window_requires_weekday_and_distinct_bounds(self):
        with self.assertRaisesRegex(ValueError, "at least one day"):
            _next_run("window", json.dumps({"start": "23:00", "end": "06:00", "every_minutes": 60, "weekdays": []}), datetime(2026, 10, 5, 20, 0, tzinfo=self.tz))
        with self.assertRaisesRegex(ValueError, "must be different"):
            _next_run("window", json.dumps({"start": "23:00", "end": "23:00", "every_minutes": 60, "weekdays": [0]}), datetime(2026, 10, 5, 20, 0, tzinfo=self.tz))

    def test_once_accepts_future_local_datetime(self):
        start = datetime(2026, 10, 5, 20, 0, tzinfo=self.tz)
        result = _next_run("once", "2026-10-05T20:30", start)
        self.assertEqual(result.isoformat(), "2026-10-05T20:30:00+07:00")
        with self.assertRaisesRegex(ValueError, "future"):
            _next_run("once", "2026-10-05T19:30", start)

    def test_descriptions_are_human_readable(self):
        weekly = json.dumps({"time": "21:00", "weekdays": [0, 2, 6]})
        window = json.dumps({"start": "23:00", "end": "06:00", "every_minutes": 30, "weekdays": [0, 1, 2, 3, 4]})
        self.assertEqual(_schedule_description("weekly", weekly), "T2, T4, CN lúc 21:00")
        self.assertIn("23:00-06:00 · mỗi 30 phút", _schedule_description("window", window))


class SchedulerOneShotRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = settings.db_path
        self.old_scheduler = settings.scheduler_enabled
        self.old_timezone = settings.timezone
        settings.db_path = str(Path(self.tmp.name) / "data" / "scheduler.db")
        settings.scheduler_enabled = True
        settings.timezone = "Asia/Ho_Chi_Minh"
        configure_process_timezone()
        init_db()

    def tearDown(self):
        settings.db_path = self.old_db
        settings.scheduler_enabled = self.old_scheduler
        settings.timezone = self.old_timezone
        configure_process_timezone()
        self.tmp.cleanup()

    def test_once_job_disables_before_execution(self):
        created = create_job("One shot", "Run once", "once", "2099-01-01T08:00", False)
        jid = created["id"]
        with conn() as c:
            c.execute("UPDATE jobs SET enabled=1,next_run=? WHERE id=?", ("2000-01-01T00:00:00+07:00", jid))
        seen = []
        stop = asyncio.Event()

        async def run_prompt(session_id, prompt, notify, channel, thread_id):
            with conn() as c:
                row = c.execute("SELECT enabled,next_run FROM jobs WHERE id=?", (jid,)).fetchone()
            seen.append((session_id, row["enabled"], row["next_run"]))
            stop.set()
            return "done"

        asyncio.run(scheduler_loop(stop, run_prompt))
        self.assertEqual(seen, [(f"job:{jid}", 0, None)])


if __name__ == "__main__":
    unittest.main()
