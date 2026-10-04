import asyncio
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .db import conn, utcnow
from .notifications import normalize_notification_channel
from .observability import exception, get_logger, info, log_context
from .settings import settings

RunPrompt = Callable[[str, str, bool, str, str], Awaitable[str]]
logger = get_logger("scheduler")


def _next_run(schedule_type: str, value: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if schedule_type == "interval":
        seconds = max(60, int(value))
        return now + timedelta(seconds=seconds)
    if schedule_type == "daily":
        hh, mm = [int(x) for x in value.split(":", 1)]
        if not 0 <= hh <= 23 or not 0 <= mm <= 59:
            raise ValueError("daily schedule_value must be HH:MM")
        tz = ZoneInfo(settings.timezone)
        local = now.astimezone(tz)
        candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    raise ValueError("schedule_type must be interval or daily")


def _clean_thread_id(value: str | None) -> str:
    return str(value or "").strip().removeprefix("zalo:")[:255]


def create_job(
    name: str,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    notify: bool = True,
    notify_channel: str = "mobile",
    zalo_thread_id: str = "",
) -> dict:
    channel = normalize_notification_channel(notify_channel)
    thread_id = _clean_thread_id(zalo_thread_id)
    nr = _next_run(schedule_type, schedule_value).isoformat()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO jobs(name,prompt,schedule_type,schedule_value,enabled,notify,notify_channel,zalo_thread_id,next_run,created_at) VALUES(?,?,?,?,0,?,?,?,?,?)",
            (name, prompt, schedule_type, schedule_value, 1 if notify else 0, channel, thread_id, nr, utcnow()),
        )
        jid = int(cur.lastrowid)
    info(logger, "job_created", job_id=jid, name=name, schedule_type=schedule_type, schedule_value=schedule_value, notify=notify, notify_channel=channel, next_run=nr)
    return {"id": jid, "enabled": False, "next_run": nr, "message": "Created disabled; enable it from the dashboard/API after review."}


def update_job(
    job_id: int,
    *,
    name: str,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    notify: bool,
    notify_channel: str,
    zalo_thread_id: str = "",
) -> dict:
    channel = normalize_notification_channel(notify_channel)
    thread_id = _clean_thread_id(zalo_thread_id)
    # Validate before touching the persisted row.
    _next_run(schedule_type, schedule_value)
    with conn() as c:
        row = c.execute("SELECT enabled FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        enabled = bool(row["enabled"])
        nr = _next_run(schedule_type, schedule_value).isoformat() if enabled else None
        c.execute(
            """
            UPDATE jobs SET name=?,prompt=?,schedule_type=?,schedule_value=?,notify=?,notify_channel=?,zalo_thread_id=?,next_run=?
            WHERE id=?
            """,
            (name, prompt, schedule_type, schedule_value, 1 if notify else 0, channel, thread_id, nr, job_id),
        )
    info(logger, "job_updated", job_id=job_id, name=name, schedule_type=schedule_type, schedule_value=schedule_value, notify=notify, notify_channel=channel, next_run=nr)
    return {"id": job_id, "enabled": enabled, "next_run": nr}


def set_job_enabled(job_id: int, enabled: bool):
    with conn() as c:
        row = c.execute("SELECT schedule_type,schedule_value FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        nr = _next_run(row["schedule_type"], row["schedule_value"]).isoformat() if enabled else None
        c.execute("UPDATE jobs SET enabled=?,next_run=? WHERE id=?", (1 if enabled else 0, nr, job_id))
    info(logger, "job_enabled_changed", job_id=job_id, enabled=enabled, next_run=nr)


async def scheduler_loop(stop: asyncio.Event, run_prompt: RunPrompt):
    info(logger, "scheduler_started", enabled=settings.scheduler_enabled)
    while not stop.is_set():
        try:
            if not settings.scheduler_enabled:
                await asyncio.sleep(10)
                continue
            now = datetime.now(timezone.utc)
            with conn() as c:
                rows = c.execute(
                    "SELECT * FROM jobs WHERE enabled=1 AND next_run IS NOT NULL AND next_run<=? ORDER BY next_run LIMIT 10",
                    (now.isoformat(),),
                ).fetchall()
                jobs = [dict(r) for r in rows]
                for job in jobs:
                    nr = _next_run(job["schedule_type"], job["schedule_value"], now).isoformat()
                    c.execute("UPDATE jobs SET next_run=?,last_run=? WHERE id=?", (nr, utcnow(), job["id"]))
            if jobs:
                info(logger, "scheduler_due_jobs", count=len(jobs), job_ids=[job["id"] for job in jobs])
            for job in jobs:
                started = perf_counter()
                sid = f"job:{job['id']}"
                with log_context(session_id=sid, source="scheduler", component="scheduler"):
                    try:
                        info(logger, "job_run_started", job_id=job["id"], name=job["name"], notify=bool(job["notify"]), notify_channel=job.get("notify_channel") or "mobile")
                        result = await run_prompt(
                            sid,
                            job["prompt"],
                            bool(job["notify"]),
                            job.get("notify_channel") or "mobile",
                            job.get("zalo_thread_id") or "",
                        )
                        info(logger, "job_run_completed", job_id=job["id"], duration_ms=round((perf_counter() - started) * 1000, 2), result_chars=len(result))
                    except Exception as exc:
                        result = f"ERROR: {type(exc).__name__}: {exc}"
                        exception(logger, "job_run_failed", job_id=job["id"], duration_ms=round((perf_counter() - started) * 1000, 2))
                    with conn() as c:
                        c.execute("UPDATE jobs SET last_result=? WHERE id=?", (result[-8000:], job["id"]))
        except asyncio.CancelledError:
            info(logger, "scheduler_cancelled")
            raise
        except Exception:
            exception(logger, "scheduler_loop_failed", message="Scheduler loop iteration failed")
        finally:
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
    info(logger, "scheduler_stopped")
