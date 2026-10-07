import asyncio
import tempfile
from pathlib import Path

from app.db import conn, init_db
from app.event_engine import create_event_rule, handle_state_event
from app.scheduler import create_job, scheduler_loop
from app.settings import settings


def _prepare_db(tmp_path: Path):
    settings.db_path = str(tmp_path / "hassmind.db")
    init_db()


def test_scheduler_runs_due_jobs_concurrently():
    with tempfile.TemporaryDirectory() as td:
        old_db = settings.db_path
        old_enabled = settings.scheduler_enabled
        old_concurrency = settings.scheduler_max_concurrency
        try:
            _prepare_db(Path(td))
            settings.scheduler_enabled = True
            settings.scheduler_max_concurrency = 2
            ids = []
            for idx in range(2):
                row = create_job(f"job-{idx}", "Trạng thái sensor.test", "interval", "60", False)
                ids.append(row["id"])
            with conn() as c:
                for jid in ids:
                    c.execute("UPDATE jobs SET enabled=1,next_run=? WHERE id=?", ("2000-01-01T00:00:00+07:00", jid))

            active = 0
            max_active = 0
            completed = 0
            stop = asyncio.Event()

            async def run_prompt(session_id, prompt, notify, channel, thread_id):
                nonlocal active, max_active, completed
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.05)
                active -= 1
                completed += 1
                if completed == 2:
                    stop.set()
                return "done"

            asyncio.run(scheduler_loop(stop, run_prompt))
            assert completed == 2
            assert max_active == 2
        finally:
            settings.db_path = old_db
            settings.scheduler_enabled = old_enabled
            settings.scheduler_max_concurrency = old_concurrency


def test_event_rules_for_same_event_can_run_concurrently():
    with tempfile.TemporaryDirectory() as td:
        old_db = settings.db_path
        old_enabled = settings.event_agent_enabled
        old_concurrency = settings.event_rule_max_concurrency
        try:
            _prepare_db(Path(td))
            settings.event_agent_enabled = True
            settings.event_rule_max_concurrency = 2
            ids = []
            for idx in range(2):
                row = create_event_rule(f"rule-{idx}", "binary_sensor.test", "on", "Trạng thái light.test", 60, False)
                ids.append(row["id"])
            with conn() as c:
                for rid in ids:
                    c.execute("UPDATE event_rules SET enabled=1 WHERE id=?", (rid,))

            active = 0
            max_active = 0

            async def run_prompt(session_id, prompt, notify, channel, thread_id):
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.05)
                active -= 1
                return "done"

            event = {
                "event_type": "state_changed",
                "data": {
                    "entity_id": "binary_sensor.test",
                    "new_state": {"state": "on", "attributes": {}},
                },
            }
            asyncio.run(handle_state_event(event, run_prompt))
            assert max_active == 2
        finally:
            settings.db_path = old_db
            settings.event_agent_enabled = old_enabled
            settings.event_rule_max_concurrency = old_concurrency
