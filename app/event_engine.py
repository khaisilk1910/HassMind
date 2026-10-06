from datetime import timedelta
from time import perf_counter
from typing import Awaitable, Callable

from .db import conn, utcnow
from .notifications import action_only_notification_prompt, actionable_notification_prompt, always_notification_prompt, normalize_notification_channel
from .observability import exception, get_logger, info, log_context
from .settings import settings
from .time_utils import now as local_now, parse_datetime

RunPrompt = Callable[[str, str, bool, str, str], Awaitable[str]]
logger = get_logger("event_engine")
VALID_NOTIFY_MODES = {"always", "actionable", "action_only"}


def _normalize_notify_mode(value: str | None) -> str:
    mode = str(value or "always").strip().lower()
    if mode not in VALID_NOTIFY_MODES:
        raise ValueError("notify_mode must be always, actionable or action_only")
    return mode



def _clean_thread_id(value: str | None) -> str:
    return str(value or "").strip().removeprefix("zalo:")[:255]


def create_event_rule(
    name: str,
    entity_id: str,
    to_state: str | None,
    prompt: str,
    cooldown_seconds: int = 300,
    notify: bool = True,
    notify_channel: str = "mobile",
    zalo_thread_id: str = "",
    notify_mode: str = "always",
) -> dict:
    channel = normalize_notification_channel(notify_channel)
    mode = _normalize_notify_mode(notify_mode)
    cooldown = max(60, int(cooldown_seconds))
    thread_id = _clean_thread_id(zalo_thread_id)
    with conn() as c:
        cur = c.execute(
            "INSERT INTO event_rules(name,entity_id,to_state,prompt,cooldown_seconds,enabled,notify,notify_channel,zalo_thread_id,notify_mode,created_at) VALUES(?,?,?,?,?,0,?,?,?,?,?)",
            (name, entity_id, to_state, prompt, cooldown, 1 if notify else 0, channel, thread_id, mode, utcnow()),
        )
        rid = int(cur.lastrowid)
    info(logger, "event_rule_created", rule_id=rid, name=name, entity_id=entity_id, to_state=to_state, cooldown_seconds=cooldown, notify=notify, notify_channel=channel, notify_mode=mode)
    return {"id": rid, "enabled": False, "message": "Created disabled; enable it from the dashboard/API after review."}


def update_event_rule(
    rule_id: int,
    *,
    name: str,
    entity_id: str,
    to_state: str | None,
    prompt: str,
    cooldown_seconds: int,
    notify: bool,
    notify_channel: str,
    zalo_thread_id: str = "",
    notify_mode: str = "always",
) -> dict:
    channel = normalize_notification_channel(notify_channel)
    mode = _normalize_notify_mode(notify_mode)
    cooldown = max(60, int(cooldown_seconds))
    thread_id = _clean_thread_id(zalo_thread_id)
    with conn() as c:
        row = c.execute("SELECT enabled FROM event_rules WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise KeyError(rule_id)
        c.execute(
            """
            UPDATE event_rules SET name=?,entity_id=?,to_state=?,prompt=?,cooldown_seconds=?,notify=?,notify_channel=?,zalo_thread_id=?,notify_mode=?
            WHERE id=?
            """,
            (name, entity_id, to_state, prompt, cooldown, 1 if notify else 0, channel, thread_id, mode, rule_id),
        )
    info(logger, "event_rule_updated", rule_id=rule_id, name=name, entity_id=entity_id, to_state=to_state, cooldown_seconds=cooldown, notify=notify, notify_channel=channel, notify_mode=mode)
    return {"id": rule_id, "enabled": bool(row["enabled"])}


def set_rule_enabled(rule_id: int, enabled: bool):
    with conn() as c:
        if not c.execute("SELECT 1 FROM event_rules WHERE id=?", (rule_id,)).fetchone():
            raise KeyError(rule_id)
        c.execute("UPDATE event_rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
    info(logger, "event_rule_enabled_changed", rule_id=rule_id, enabled=enabled)


async def handle_state_event(event: dict, run_prompt: RunPrompt):
    if not settings.event_agent_enabled:
        return
    data = event.get("data") or {}
    entity_id = data.get("entity_id")
    new_state_obj = data.get("new_state") or {}
    new_state = new_state_obj.get("state")
    if not entity_id:
        return
    with conn() as c:
        rows = c.execute("SELECT * FROM event_rules WHERE enabled=1 AND entity_id=?", (entity_id,)).fetchall()
        rules = [dict(r) for r in rows]
    if not rules:
        return
    info(logger, "state_event_rules_found", entity_id=entity_id, new_state=new_state, rule_count=len(rules))
    now = local_now()
    for rule in rules:
        if rule["to_state"] not in (None, "", new_state):
            continue
        if rule["last_triggered"]:
            last = parse_datetime(rule["last_triggered"])
            if last is not None and now - last < timedelta(seconds=int(rule["cooldown_seconds"])):
                continue
        with conn() as c:
            c.execute("UPDATE event_rules SET last_triggered=? WHERE id=?", (utcnow(), rule["id"]))
        context = f"\n\nEvent context: entity_id={entity_id}, new_state={new_state}, attributes={new_state_obj.get('attributes') or {}}"
        sid = f"event-rule:{rule['id']}"
        started = perf_counter()
        with log_context(session_id=sid, source="event_rule", component="event_engine"):
            try:
                notify_mode = _normalize_notify_mode(rule.get("notify_mode"))
                runtime_prompt = rule["prompt"] + context
                if bool(rule["notify"]):
                    if notify_mode == "action_only":
                        runtime_prompt = action_only_notification_prompt(runtime_prompt)
                    elif notify_mode == "actionable":
                        runtime_prompt = actionable_notification_prompt(runtime_prompt)
                    else:
                        runtime_prompt = always_notification_prompt(runtime_prompt)
                info(logger, "event_rule_triggered", rule_id=rule["id"], entity_id=entity_id, new_state=new_state, notify=bool(rule["notify"]), notify_channel=rule.get("notify_channel") or "mobile", notify_mode=notify_mode)
                await run_prompt(
                    sid,
                    runtime_prompt,
                    bool(rule["notify"]),
                    rule.get("notify_channel") or "mobile",
                    rule.get("zalo_thread_id") or "",
                )
                info(logger, "event_rule_completed", rule_id=rule["id"], duration_ms=round((perf_counter() - started) * 1000, 2))
            except Exception:
                exception(logger, "event_rule_failed", rule_id=rule["id"], entity_id=entity_id, duration_ms=round((perf_counter() - started) * 1000, 2))
                raise
