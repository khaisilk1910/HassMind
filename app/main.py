import asyncio
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agent import Agent
from .approvals import apply_approval, decide_by_action, decide_by_web, get_approval
from .db import add_event, conn, get_messages, init_db, list_approvals, list_event_rules, list_jobs, recent_events, recent_tool_audit, utcnow
from .event_engine import handle_state_event, set_rule_enabled
from .ha import HomeAssistantClient
from .ha_integrations import HAIntegrationBridge
from .integrations import IntegrationHub
from .rag import reindex_knowledge, search_knowledge
from .scheduler import scheduler_loop, set_job_enabled
from .settings import settings
from .skills import list_skills
from .telegram import telegram_loop
from .tools import ToolRuntime

ha: HomeAssistantClient | None = None
agent: Agent | None = None
stop_event = asyncio.Event()
tasks: list[asyncio.Task] = []
integrations: IntegrationHub | None = None
webhook_tasks: set[asyncio.Task] = set()


async def require_token(x_hassmind_token: str = Header(default="")):
    expected = settings.read_api_token()
    if not secrets.compare_digest(x_hassmind_token, expected):
        raise HTTPException(401, "Invalid X-HassMind-Token")


async def run_prompt(session_id: str, prompt: str, notify: bool) -> str:
    if agent is None or ha is None:
        raise RuntimeError("HassMind is starting")
    result = await agent.chat(session_id, prompt, source="system")
    if notify:
        await ha.notify(result[:3500], title=f"HassMind · {session_id}")
    return result


async def event_callback(event: dict[str, Any]):
    if ha is None:
        return
    et = event.get("event_type", "unknown")
    data = event.get("data") or {}
    entity_id = data.get("entity_id")
    add_event(et, entity_id, event)

    if et == "mobile_app_notification_action":
        action = data.get("action") or ""
        decision = decide_by_action(action)
        if decision:
            aid, status = decision
            if status == "approved" and settings.auto_apply_after_approval:
                try:
                    result = await apply_approval(ha, aid)
                    await ha.notify(f"Đã áp dụng {aid}: {result['status']}", title="HassMind")
                except Exception as e:
                    await ha.notify(f"Không thể áp dụng {aid}: {e}", title="HassMind")
            elif status == "rejected":
                await ha.notify(f"Đã từ chối {aid}", title="HassMind")
        return

    if et == "state_changed" and agent is not None:
        async def _run_rule():
            try:
                await handle_state_event(event, run_prompt)
            except Exception:
                pass
        asyncio.create_task(_run_rule())


def _extract_zalo_text(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        for key in ("msg", "content", "text"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("message", "content", "text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = value.get("msg") or value.get("content") or value.get("text")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return ""


def _remember_webhook_task(task: asyncio.Task) -> None:
    webhook_tasks.add(task)
    task.add_done_callback(webhook_tasks.discard)


async def _process_zalo_message(payload: dict[str, Any]) -> None:
    if agent is None or integrations is None or integrations.zalo is None:
        return
    if not settings.zalo_agent_reply_enabled or not settings.zalo_allow_send:
        return

    text = _extract_zalo_text(payload)
    thread_id = str(payload.get("threadId") or payload.get("thread_id") or "").removeprefix("zalo:")
    if not text or not thread_id:
        return

    allowed = settings.zalo_allowed_thread_ids
    if not allowed or (thread_id not in allowed and "*" not in allowed):
        return

    try:
        thread_type = int(payload.get("_threadType", payload.get("type", 0)))
    except (TypeError, ValueError):
        thread_type = 0
    account = str(payload.get("_accountId") or settings.zalo_default_account or "")
    session_id = f"zalo:{account or 'default'}:{thread_id}"

    try:
        answer = await agent.chat(session_id, text, source="zalo")
        await integrations.zalo.send_message(
            thread_id=thread_id,
            message=answer[:4000],
            thread_type=thread_type,
            account_selection=account,
        )
    except Exception as exc:
        add_event("zalo_agent_error", thread_id, {"error": f"{type(exc).__name__}: {exc}"})


async def _zalo_webhook_registration_loop() -> None:
    """Keep the HassMind message webhook present, including accounts that login later."""
    if integrations is None or integrations.zalo is None:
        return
    secret = settings.read_zalo_webhook_secret()
    base = settings.zalo_webhook_callback_base.rstrip("/")
    if not secret or not base:
        add_event("zalo_webhook_registration", None, {"status": "skipped", "reason": "missing callback base or webhook secret"})
        return

    callback = f"{base}/webhooks/zalo/{secret}"
    last_status = ""
    while not stop_event.is_set():
        try:
            result = await integrations.zalo.ensure_hassmind_webhooks(callback)
            if last_status != "ok":
                add_event("zalo_webhook_registration", None, {"status": "ok", "result": result})
            last_status = "ok"
            # Reconcile periodically so accounts logged in after startup are picked up.
            delay = 3600
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            current = f"{type(exc).__name__}: {exc}"
            if current != last_status:
                add_event("zalo_webhook_registration", None, {"status": "error", "error": current})
            last_status = current
            delay = 60

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ha, agent, tasks, integrations
    init_db()
    stop_event.clear()
    ha = HomeAssistantClient()
    integrations = IntegrationHub()
    agent = Agent(ToolRuntime(ha, integrations))
    tasks = [
        asyncio.create_task(ha.listen_events(event_callback, stop_event), name="ha-events"),
        asyncio.create_task(scheduler_loop(stop_event, run_prompt), name="scheduler"),
        asyncio.create_task(telegram_loop(stop_event, lambda sid, text, src: agent.chat(sid, text, src)), name="telegram"),
    ]
    if settings.zalo_enabled and settings.zalo_webhook_enabled and settings.zalo_auto_register_webhook:
        registration = asyncio.create_task(_zalo_webhook_registration_loop(), name="zalo-webhook-register")
        tasks.append(registration)
    yield
    stop_event.set()
    for t in tasks:
        t.cancel()
    for t in list(webhook_tasks):
        t.cancel()
    await asyncio.gather(*tasks, *list(webhook_tasks), return_exceptions=True)
    if integrations:
        await integrations.close()
    if ha:
        await ha.close()


app = FastAPI(title="HassMind v1", version="1.1.0", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


class ToggleIn(BaseModel):
    enabled: bool


class DecisionIn(BaseModel):
    approve: bool


class JobIn(BaseModel):
    name: str
    prompt: str
    schedule_type: str
    schedule_value: str
    notify: bool = True


class RuleIn(BaseModel):
    name: str
    entity_id: str
    to_state: str | None = None
    prompt: str
    cooldown_seconds: int = 300
    notify: bool = True


@app.get("/")
async def root():
    return FileResponse("/app/static/index.html")


@app.get("/health")
async def health():
    return {"ok": True, "name": settings.agent_name, "version": "1.1.0", "ha_url": settings.ha_url}


@app.get("/api/status", dependencies=[Depends(require_token)])
async def status():
    ha_ok = False
    ha_version = None
    if ha:
        try:
            cfg = await ha._get("/api/config")
            ha_ok = True
            ha_version = cfg.get("version")
        except Exception:
            pass
    return {"ok": True, "ha_connected": ha_ok, "ha_version": ha_version, "model": settings.openai_model, "scheduler": settings.scheduler_enabled, "event_agent": settings.event_agent_enabled}


@app.get("/api/integrations", dependencies=[Depends(require_token)])
async def integration_status():
    if ha is None or integrations is None:
        raise HTTPException(503, "Integrations are starting")
    companion = await integrations.status()
    custom = await HAIntegrationBridge(ha).status() if settings.ha_custom_integrations_enabled else {"enabled": False}
    return {
        "companion_containers": companion,
        "home_assistant_custom_components": custom,
        "policy": {
            "camera_tts_actions": settings.camera_tts_allow_actions,
            "zalo_send": settings.zalo_allow_send,
            "zalo_agent_reply": settings.zalo_agent_reply_enabled,
            "shopping_mutations": settings.shopping_allow_mutations,
            "shopping_delete": settings.shopping_allow_delete,
            "yt_dlp_playback": settings.ytdlp_allow_playback,
            "yt_dlp_downloads": settings.ytdlp_allow_downloads,
            "wyoming_tts": settings.wyoming_allow_tts,
        },
    }


@app.post("/webhooks/zalo/{secret}")
async def zalo_webhook(secret: str, payload: dict[str, Any]):
    if not settings.zalo_enabled or not settings.zalo_webhook_enabled:
        raise HTTPException(404, "Webhook disabled")
    expected = settings.read_zalo_webhook_secret()
    if not expected or not secrets.compare_digest(secret, expected):
        raise HTTPException(404, "Webhook not found")

    thread_id = str(payload.get("threadId") or payload.get("thread_id") or "")
    add_event("zalo_message", thread_id or None, payload)

    text = _extract_zalo_text(payload)
    allowed = settings.zalo_allowed_thread_ids
    normalized_thread = thread_id.removeprefix("zalo:")
    can_reply = bool(
        text
        and normalized_thread
        and settings.zalo_agent_reply_enabled
        and settings.zalo_allow_send
        and bool(allowed)
        and (normalized_thread in allowed or "*" in allowed)
    )
    if can_reply:
        _remember_webhook_task(asyncio.create_task(_process_zalo_message(payload), name=f"zalo:{normalized_thread}"))
    return {"accepted": True, "agent_reply_scheduled": can_reply}


@app.post("/api/chat", dependencies=[Depends(require_token)])
async def chat(body: ChatIn):
    if agent is None:
        raise HTTPException(503, "Agent is starting")
    sid = body.session_id or uuid.uuid4().hex
    answer = await agent.chat(sid, body.message, source="web")
    return {"session_id": sid, "answer": answer}


@app.get("/api/messages/{session_id}", dependencies=[Depends(require_token)])
async def messages(session_id: str):
    return get_messages(session_id, 100)


@app.get("/api/events", dependencies=[Depends(require_token)])
async def events(limit: int = 50):
    return recent_events(min(max(limit, 1), 200))


@app.get("/api/audit", dependencies=[Depends(require_token)])
async def audit(limit: int = 100):
    return recent_tool_audit(min(max(limit, 1), 500))


@app.get("/api/approvals", dependencies=[Depends(require_token)])
async def approvals():
    return list_approvals()


@app.get("/api/approvals/{aid}", dependencies=[Depends(require_token)])
async def approval(aid: str):
    row = get_approval(aid)
    if not row:
        raise HTTPException(404, "Not found")
    return row


@app.post("/api/approvals/{aid}/decision", dependencies=[Depends(require_token)])
async def approval_decision(aid: str, body: DecisionIn):
    if ha is None:
        raise HTTPException(503, "HA client unavailable")
    d = decide_by_web(aid, body.approve)
    if body.approve and settings.auto_apply_after_approval:
        d["apply"] = await apply_approval(ha, aid)
    return d


@app.get("/api/jobs", dependencies=[Depends(require_token)])
async def jobs():
    return list_jobs()


@app.post("/api/jobs", dependencies=[Depends(require_token)])
async def create_job_api(body: JobIn):
    from .scheduler import create_job
    return create_job(body.name, body.prompt, body.schedule_type, body.schedule_value, body.notify)


@app.patch("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
async def toggle_job(job_id: int, body: ToggleIn):
    set_job_enabled(job_id, body.enabled)
    return {"id": job_id, "enabled": body.enabled}


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
async def delete_job(job_id: int):
    with conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    return {"ok": True}


@app.get("/api/event-rules", dependencies=[Depends(require_token)])
async def rules():
    return list_event_rules()


@app.post("/api/event-rules", dependencies=[Depends(require_token)])
async def create_rule_api(body: RuleIn):
    from .event_engine import create_event_rule
    return create_event_rule(body.name, body.entity_id, body.to_state, body.prompt, body.cooldown_seconds, body.notify)


@app.patch("/api/event-rules/{rule_id}", dependencies=[Depends(require_token)])
async def toggle_rule(rule_id: int, body: ToggleIn):
    set_rule_enabled(rule_id, body.enabled)
    return {"id": rule_id, "enabled": body.enabled}


@app.delete("/api/event-rules/{rule_id}", dependencies=[Depends(require_token)])
async def delete_rule(rule_id: int):
    with conn() as c:
        c.execute("DELETE FROM event_rules WHERE id=?", (rule_id,))
    return {"ok": True}


@app.post("/api/knowledge/reindex", dependencies=[Depends(require_token)])
async def reindex():
    return reindex_knowledge()


@app.get("/api/knowledge/search", dependencies=[Depends(require_token)])
async def knowledge_search(q: str, limit: int = 8):
    return search_knowledge(q, min(max(limit, 1), 20))


@app.get("/api/skills", dependencies=[Depends(require_token)])
async def skills():
    return list_skills()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
