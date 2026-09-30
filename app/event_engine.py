from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable

from .db import conn, utcnow
from .settings import settings

RunPrompt = Callable[[str, str, bool], Awaitable[str]]


def create_event_rule(name: str, entity_id: str, to_state: str | None, prompt: str, cooldown_seconds: int = 300, notify: bool = True) -> dict:
    with conn() as c:
        cur = c.execute("INSERT INTO event_rules(name,entity_id,to_state,prompt,cooldown_seconds,enabled,notify,created_at) VALUES(?,?,?,?,?,0,?,?)",
                        (name, entity_id, to_state, prompt, max(60, cooldown_seconds), 1 if notify else 0, utcnow()))
        rid = int(cur.lastrowid)
    return {"id": rid, "enabled": False, "message": "Created disabled; enable it from the dashboard/API after review."}


def set_rule_enabled(rule_id: int, enabled: bool):
    with conn() as c:
        if not c.execute("SELECT 1 FROM event_rules WHERE id=?", (rule_id,)).fetchone():
            raise KeyError(rule_id)
        c.execute("UPDATE event_rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))


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
    now = datetime.now(timezone.utc)
    for rule in rules:
        if rule["to_state"] not in (None, "", new_state):
            continue
        if rule["last_triggered"]:
            last = datetime.fromisoformat(rule["last_triggered"])
            if now - last < timedelta(seconds=int(rule["cooldown_seconds"])):
                continue
        with conn() as c:
            c.execute("UPDATE event_rules SET last_triggered=? WHERE id=?", (utcnow(), rule["id"]))
        context = f"\n\nEvent context: entity_id={entity_id}, new_state={new_state}, attributes={new_state_obj.get('attributes') or {}}"
        await run_prompt(f"event-rule:{rule['id']}", rule["prompt"] + context, bool(rule["notify"]))
