import asyncio
import json
from datetime import date, datetime, time, timedelta
from time import perf_counter
from typing import Awaitable, Callable

from .db import conn, utcnow
from .notifications import actionable_notification_prompt, always_notification_prompt, normalize_notification_channel
from .observability import exception, get_logger, info, log_context, warning
from .settings import settings
from .time_utils import local_tz, now as local_now, parse_datetime

RunPrompt = Callable[[str, str, bool, str, str], Awaitable[str]]
logger = get_logger("scheduler")
MIN_INTERVAL_SECONDS = 30
MIN_WINDOW_INTERVAL_MINUTES = 1
MAX_WINDOW_INTERVAL_MINUTES = 7 * 24 * 60
VALID_NOTIFY_MODES = {"always", "actionable"}
VALID_SCHEDULE_TYPES = {"daily", "interval", "weekly", "window", "once"}
WEEKDAY_LABELS = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")


def _normalize_notify_mode(value: str | None) -> str:
    mode = str(value or "always").strip().lower()
    if mode not in VALID_NOTIFY_MODES:
        raise ValueError("notify_mode must be always or actionable")
    return mode


def _parse_hhmm(value: object, field: str) -> tuple[int, int]:
    try:
        parts = str(value).strip().split(":")
        if len(parts) != 2:
            raise ValueError
        hh, mm = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be HH:MM") from None
    if not 0 <= hh <= 23 or not 0 <= mm <= 59:
        raise ValueError(f"{field} must be HH:MM")
    return hh, mm


def _parse_json_schedule(value: str, schedule_type: str) -> dict:
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        raise ValueError(f"{schedule_type} schedule_value must be valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError(f"{schedule_type} schedule_value must be a JSON object")
    return payload


def _parse_weekdays(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("weekdays must contain at least one day")
    days: list[int] = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError("weekdays must contain integers from 0 to 6")
        try:
            day = int(item)
        except (TypeError, ValueError):
            raise ValueError("weekdays must contain integers from 0 to 6") from None
        if day < 0 or day > 6:
            raise ValueError("weekdays must contain integers from 0 to 6")
        if day not in days:
            days.append(day)
    return tuple(sorted(days))


def _local_datetime(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hour=hh, minute=mm), tzinfo=local_tz())


def _next_daily(value: str, local: datetime) -> datetime:
    hh, mm = _parse_hhmm(value, "daily schedule_value")
    candidate = _local_datetime(local.date(), hh, mm)
    if candidate <= local:
        candidate = _local_datetime(local.date() + timedelta(days=1), hh, mm)
    return candidate


def _next_weekly(value: str, local: datetime) -> datetime:
    payload = _parse_json_schedule(value, "weekly")
    hh, mm = _parse_hhmm(payload.get("time"), "weekly time")
    weekdays = _parse_weekdays(payload.get("weekdays"))
    for offset in range(0, 8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        candidate = _local_datetime(day, hh, mm)
        if candidate > local:
            return candidate
    raise ValueError("weekly schedule has no future occurrence")


def _window_bounds(base_day: date, start_hh: int, start_mm: int, end_hh: int, end_mm: int) -> tuple[datetime, datetime]:
    start = _local_datetime(base_day, start_hh, start_mm)
    end_day = base_day if (end_hh, end_mm) > (start_hh, start_mm) else base_day + timedelta(days=1)
    end = _local_datetime(end_day, end_hh, end_mm)
    return start, end


def _next_window(value: str, local: datetime) -> datetime:
    payload = _parse_json_schedule(value, "window")
    start_hh, start_mm = _parse_hhmm(payload.get("start"), "window start")
    end_hh, end_mm = _parse_hhmm(payload.get("end"), "window end")
    if (start_hh, start_mm) == (end_hh, end_mm):
        raise ValueError("window start and end must be different")
    try:
        every_minutes = int(payload.get("every_minutes"))
    except (TypeError, ValueError):
        raise ValueError("window every_minutes must be an integer") from None
    if every_minutes < MIN_WINDOW_INTERVAL_MINUTES or every_minutes > MAX_WINDOW_INTERVAL_MINUTES:
        raise ValueError(
            f"window every_minutes must be between {MIN_WINDOW_INTERVAL_MINUTES} and {MAX_WINDOW_INTERVAL_MINUTES}"
        )
    weekdays = _parse_weekdays(payload.get("weekdays"))
    step_seconds = every_minutes * 60
    candidates: list[datetime] = []

    # Start one day in the past so an overnight window such as 23:00-06:00
    # can still schedule the next tick at 01:00 from the previous start day.
    for offset in range(-1, 8):
        base_day = local.date() + timedelta(days=offset)
        if base_day.weekday() not in weekdays:
            continue
        start, end = _window_bounds(base_day, start_hh, start_mm, end_hh, end_mm)
        if local < start:
            candidate = start
        elif local >= end:
            continue
        else:
            elapsed = max(0.0, (local - start).total_seconds())
            steps = int(elapsed // step_seconds) + 1
            candidate = start + timedelta(seconds=steps * step_seconds)
        # The end time is a stop boundary, not another execution time.
        if candidate < end and candidate > local:
            candidates.append(candidate)

    if not candidates:
        raise ValueError("window schedule has no future occurrence")
    return min(candidates)


def _next_once(value: str, local: datetime) -> datetime:
    raw = str(value or "").strip()
    try:
        candidate = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        raise ValueError("once schedule_value must be YYYY-MM-DDTHH:MM") from None
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=local_tz())
    else:
        candidate = candidate.astimezone(local_tz())
    if candidate <= local:
        raise ValueError("once schedule time must be in the future")
    return candidate


def _next_run(schedule_type: str, value: str, now: datetime | None = None) -> datetime:
    local = parse_datetime(now) if now is not None else local_now()
    if local is None:
        local = local_now()
    local = local.astimezone(local_tz())
    schedule_type = str(schedule_type or "").strip().lower()
    if schedule_type not in VALID_SCHEDULE_TYPES:
        raise ValueError("schedule_type must be daily, weekly, window, interval or once")
    if schedule_type == "interval":
        try:
            seconds = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("interval schedule_value must be an integer number of seconds") from None
        if seconds < MIN_INTERVAL_SECONDS:
            raise ValueError(f"interval schedule_value must be at least {MIN_INTERVAL_SECONDS} seconds")
        return local + timedelta(seconds=seconds)
    if schedule_type == "daily":
        return _next_daily(value, local)
    if schedule_type == "weekly":
        return _next_weekly(value, local)
    if schedule_type == "window":
        return _next_window(value, local)
    if schedule_type == "once":
        return _next_once(value, local)
    raise AssertionError("unreachable schedule type")


def _schedule_description(schedule_type: str, value: str) -> str:
    """Human-readable description used in logs and tests; never trusted as scheduler input."""
    schedule_type = str(schedule_type or "").strip().lower()
    try:
        if schedule_type == "daily":
            hh, mm = _parse_hhmm(value, "daily schedule_value")
            return f"Hàng ngày lúc {hh:02d}:{mm:02d}"
        if schedule_type == "interval":
            seconds = int(str(value).strip())
            if seconds % 3600 == 0:
                return f"Mỗi {seconds // 3600} giờ"
            if seconds % 60 == 0:
                return f"Mỗi {seconds // 60} phút"
            return f"Mỗi {seconds} giây"
        if schedule_type == "weekly":
            payload = _parse_json_schedule(value, "weekly")
            hh, mm = _parse_hhmm(payload.get("time"), "weekly time")
            days = _parse_weekdays(payload.get("weekdays"))
            return f"{', '.join(WEEKDAY_LABELS[d] for d in days)} lúc {hh:02d}:{mm:02d}"
        if schedule_type == "window":
            payload = _parse_json_schedule(value, "window")
            start_hh, start_mm = _parse_hhmm(payload.get("start"), "window start")
            end_hh, end_mm = _parse_hhmm(payload.get("end"), "window end")
            every = int(payload.get("every_minutes"))
            days = _parse_weekdays(payload.get("weekdays"))
            return (
                f"{', '.join(WEEKDAY_LABELS[d] for d in days)} · "
                f"{start_hh:02d}:{start_mm:02d}-{end_hh:02d}:{end_mm:02d} · mỗi {every} phút"
            )
        if schedule_type == "once":
            candidate = datetime.fromisoformat(str(value).strip())
            return f"Một lần {candidate.strftime('%d/%m/%Y %H:%M')}"
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        pass
    return f"{schedule_type} {value}".strip()


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
    notify_mode: str = "always",
) -> dict:
    channel = normalize_notification_channel(notify_channel)
    mode = _normalize_notify_mode(notify_mode)
    thread_id = _clean_thread_id(zalo_thread_id)
    schedule_type = str(schedule_type or "").strip().lower()
    nr = _next_run(schedule_type, schedule_value).isoformat()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO jobs(name,prompt,schedule_type,schedule_value,enabled,notify,notify_channel,zalo_thread_id,notify_mode,next_run,created_at) VALUES(?,?,?,?,0,?,?,?,?,?,?)",
            (name, prompt, schedule_type, schedule_value, 1 if notify else 0, channel, thread_id, mode, nr, utcnow()),
        )
        jid = int(cur.lastrowid)
    info(
        logger,
        "job_created",
        job_id=jid,
        name=name,
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        schedule_description=_schedule_description(schedule_type, schedule_value),
        notify=notify,
        notify_channel=channel,
        notify_mode=mode,
        next_run=nr,
    )
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
    notify_mode: str = "always",
) -> dict:
    channel = normalize_notification_channel(notify_channel)
    mode = _normalize_notify_mode(notify_mode)
    thread_id = _clean_thread_id(zalo_thread_id)
    schedule_type = str(schedule_type or "").strip().lower()
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
            UPDATE jobs SET name=?,prompt=?,schedule_type=?,schedule_value=?,notify=?,notify_channel=?,zalo_thread_id=?,notify_mode=?,next_run=?
            WHERE id=?
            """,
            (name, prompt, schedule_type, schedule_value, 1 if notify else 0, channel, thread_id, mode, nr, job_id),
        )
    info(
        logger,
        "job_updated",
        job_id=job_id,
        name=name,
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        schedule_description=_schedule_description(schedule_type, schedule_value),
        notify=notify,
        notify_channel=channel,
        notify_mode=mode,
        next_run=nr,
    )
    return {"id": job_id, "enabled": enabled, "next_run": nr}


def set_job_enabled(job_id: int, enabled: bool):
    with conn() as c:
        row = c.execute("SELECT schedule_type,schedule_value FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        nr = _next_run(row["schedule_type"], row["schedule_value"]).isoformat() if enabled else None
        c.execute("UPDATE jobs SET enabled=?,next_run=? WHERE id=?", (1 if enabled else 0, nr, job_id))
    info(logger, "job_enabled_changed", job_id=job_id, enabled=enabled, next_run=nr)


def _advance_due_jobs(now: datetime) -> list[dict]:
    """Atomically advance due jobs and return only jobs that should execute now.

    Missed recurring ticks are intentionally skipped: next_run is calculated from the
    current wall clock. One-shot jobs are disabled before execution so a restart or
    slow prompt cannot execute them twice.
    """
    runnable: list[dict] = []
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM jobs WHERE enabled=1 AND next_run IS NOT NULL "
            "AND julianday(next_run) <= julianday(?) ORDER BY julianday(next_run) LIMIT 10",
            (now.isoformat(),),
        ).fetchall()
        for row in rows:
            job = dict(row)
            try:
                if job["schedule_type"] == "once":
                    next_run = None
                    enabled = 0
                else:
                    next_run = _next_run(job["schedule_type"], job["schedule_value"], now).isoformat()
                    enabled = 1
                c.execute(
                    "UPDATE jobs SET enabled=?,next_run=?,last_run=? WHERE id=?",
                    (enabled, next_run, utcnow(), job["id"]),
                )
                runnable.append(job)
            except ValueError as exc:
                message = f"ERROR: invalid scheduler configuration: {exc}"
                c.execute(
                    "UPDATE jobs SET enabled=0,next_run=NULL,last_result=? WHERE id=?",
                    (message, job["id"]),
                )
                warning(
                    logger,
                    "job_disabled_invalid_schedule",
                    job_id=job["id"],
                    schedule_type=job.get("schedule_type"),
                    schedule_value=job.get("schedule_value"),
                    error=str(exc),
                )
    return runnable


async def scheduler_loop(stop: asyncio.Event, run_prompt: RunPrompt):
    info(logger, "scheduler_started", enabled=settings.scheduler_enabled)
    while not stop.is_set():
        try:
            if not settings.scheduler_enabled:
                await asyncio.sleep(10)
                continue
            now = local_now()
            jobs = _advance_due_jobs(now)
            if jobs:
                info(logger, "scheduler_due_jobs", count=len(jobs), job_ids=[job["id"] for job in jobs])
            for job in jobs:
                started = perf_counter()
                sid = f"job:{job['id']}"
                with log_context(session_id=sid, source="scheduler", component="scheduler"):
                    try:
                        notify_mode = _normalize_notify_mode(job.get("notify_mode"))
                        runtime_prompt = job["prompt"]
                        if bool(job["notify"]):
                            runtime_prompt = (
                                actionable_notification_prompt(runtime_prompt)
                                if notify_mode == "actionable"
                                else always_notification_prompt(runtime_prompt)
                            )
                        info(
                            logger,
                            "job_run_started",
                            job_id=job["id"],
                            name=job["name"],
                            notify=bool(job["notify"]),
                            notify_channel=job.get("notify_channel") or "mobile",
                            notify_mode=notify_mode,
                        )
                        result = await run_prompt(
                            sid,
                            runtime_prompt,
                            bool(job["notify"]),
                            job.get("notify_channel") or "mobile",
                            job.get("zalo_thread_id") or "",
                        )
                        info(
                            logger,
                            "job_run_completed",
                            job_id=job["id"],
                            duration_ms=round((perf_counter() - started) * 1000, 2),
                            result_chars=len(result),
                        )
                    except Exception as exc:
                        result = f"ERROR: {type(exc).__name__}: {exc}"
                        exception(
                            logger,
                            "job_run_failed",
                            job_id=job["id"],
                            duration_ms=round((perf_counter() - started) * 1000, 2),
                        )
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
