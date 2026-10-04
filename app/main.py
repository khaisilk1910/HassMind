import asyncio
import hashlib
import json
import logging
import os
import platform
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .approvals import apply_approval, decide_by_action, decide_by_web, get_approval
from .custom_integrations import create_custom_integration, delete_custom_integration, update_custom_integration
from .auth import (
    change_password,
    change_username,
    cleanup_sessions,
    client_ip,
    client_ip_allowed,
    ensure_bootstrap_admin,
    list_sessions,
    list_auth_audit,
    login as admin_login,
    logout as admin_logout,
    reset_password,
    revoke_other_sessions,
    record_admin_audit,
    verify_password,
    session_from_request,
    require_session,
)
from .db import add_event, conn, get_messages, init_db, list_approvals, list_event_rules, list_jobs, recent_events, recent_tool_audit, scrub_sensitive_audit_history
from .event_engine import handle_state_event, set_rule_enabled
from .ha import HomeAssistantClient
from .ha_integrations import HAIntegrationBridge
from .integration_config import integration_config_view, load_runtime_integration_overrides, reset_integration_config, save_integration_config
from .integrations import IntegrationHub
from .message_format import split_zalo_message
from .observability import (
    current_request_id,
    exception,
    get_logger,
    info,
    log,
    log_context,
    log_file_info,
    recent_logs,
    sanitize_url,
    register_secret,
    setup_logging,
    uptime_seconds,
    warning,
)
from .rag import reindex_knowledge, search_knowledge
from .scheduler import scheduler_loop, set_job_enabled
from .settings import settings
from .skills import list_skills
from .telegram import telegram_loop
from .tools import ToolRuntime

os.umask(0o077)

APP_VERSION = "1.2.5"
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
setup_logging()
logger = get_logger("main")

ha: HomeAssistantClient | None = None
agent: Agent | None = None
stop_event = asyncio.Event()
tasks: list[asyncio.Task] = []
integrations: IntegrationHub | None = None
webhook_tasks: set[asyncio.Task] = set()


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _api_token_valid(value: str) -> bool:
    if not value:
        return False
    try:
        expected = settings.read_api_token()
    except RuntimeError:
        return False
    return secrets.compare_digest(value, expected)


async def require_access(
    request: Request,
    x_hassmind_token: str = Header(default=""),
    x_csrf_token: str = Header(default=""),
):
    if _api_token_valid(x_hassmind_token):
        request.state.auth_kind = "api_token"
        return {"kind": "api_token"}
    try:
        session = require_session(request, csrf_token=x_csrf_token, require_csrf=request.method.upper() not in SAFE_METHODS)
        request.state.auth_kind = "admin_session"
        request.state.admin_session = session
        return session
    except HTTPException as exc:
        warning(logger, "api_auth_failed", message="API token or admin session required", request_id=current_request_id(), component="api", status_code=exc.status_code)
        raise


async def require_admin(
    request: Request,
    x_csrf_token: str = Header(default=""),
):
    session = require_session(request, csrf_token=x_csrf_token, require_csrf=request.method.upper() not in SAFE_METHODS)
    request.state.auth_kind = "admin_session"
    request.state.admin_session = session
    return session


async def run_prompt(session_id: str, prompt: str, notify: bool) -> str:
    if agent is None or ha is None:
        raise RuntimeError("HassMind is starting")
    with log_context(session_id=session_id, source="system"):
        info(logger, "system_prompt_started", notify=notify, prompt_chars=len(prompt))
        result = await agent.chat(session_id, prompt, source="system")
        if notify:
            await ha.notify(result[:3500], title=f"HassMind · {session_id}")
        info(logger, "system_prompt_completed", result_chars=len(result), notify=notify)
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
        info(logger, "mobile_notification_action", action=action)
        decision = decide_by_action(action)
        if decision:
            aid, status = decision
            if status == "approved" and settings.auto_apply_after_approval:
                try:
                    result = await apply_approval(ha, aid)
                    await ha.notify(f"Đã áp dụng {aid}: {result['status']}", title="HassMind")
                    info(logger, "approval_applied_from_mobile", approval_id=aid, status=result.get("status"))
                except Exception:
                    exception(logger, "approval_mobile_apply_failed", message="Could not apply approval from mobile action", approval_id=aid)
                    await ha.notify(f"Không thể áp dụng {aid}", title="HassMind")
            elif status == "rejected":
                await ha.notify(f"Đã từ chối {aid}", title="HassMind")
                info(logger, "approval_rejected_from_mobile", approval_id=aid)
        return

    if et == "state_changed" and agent is not None:
        async def _run_rule():
            try:
                await handle_state_event(event, run_prompt)
            except Exception:
                exception(logger, "event_rule_processing_failed", entity_id=entity_id)

        task = asyncio.create_task(_run_rule(), name=f"event-rule:{entity_id or 'unknown'}")
        _remember_webhook_task(task)


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

    def _done(done: asyncio.Task) -> None:
        webhook_tasks.discard(done)
        if done.cancelled():
            return
        try:
            exc = done.exception()
        except asyncio.CancelledError:
            return
        if exc:
            log(
                logger,
                logging.ERROR,
                "background_task_failed",
                message="Background task failed",
                task_name=done.get_name(),
                error_type=type(exc).__name__,
                error=str(exc),
            )

    task.add_done_callback(_done)


async def _process_zalo_message(payload: dict[str, Any]) -> None:
    if agent is None or integrations is None or integrations.zalo is None:
        warning(logger, "zalo_message_skipped", reason="agent or Zalo integration unavailable")
        return
    if not settings.zalo_agent_reply_enabled or not settings.zalo_allow_send:
        info(logger, "zalo_message_skipped", reason="agent reply or send policy disabled")
        return

    text = _extract_zalo_text(payload)
    thread_id = str(payload.get("threadId") or payload.get("thread_id") or "").removeprefix("zalo:")
    if not text or not thread_id:
        warning(logger, "zalo_message_skipped", reason="missing text or thread_id")
        return

    allowed = settings.zalo_allowed_thread_ids
    if not allowed or (thread_id not in allowed and "*" not in allowed):
        info(logger, "zalo_message_skipped", reason="thread not allowed", thread_id=thread_id)
        return

    try:
        thread_type = int(payload.get("_threadType", payload.get("type", 0)))
    except (TypeError, ValueError):
        thread_type = 0
    account = str(payload.get("_accountId") or settings.zalo_default_account or "")
    session_id = f"zalo:{account or 'default'}:{thread_id}"

    with log_context(session_id=session_id, source="zalo", component="zalo"):
        try:
            info(logger, "zalo_agent_reply_started", thread_id=thread_id, account=account or "default", text_chars=len(text))
            answer = await agent.chat(session_id, text, source="zalo")
            chunks = split_zalo_message(answer)
            for chunk in chunks or ["Đã xử lý yêu cầu nhưng không có nội dung văn bản để gửi."]:
                await integrations.zalo.send_message(
                    thread_id=thread_id,
                    message=chunk,
                    thread_type=thread_type,
                    account_selection=account,
                )
            info(
                logger,
                "zalo_agent_reply_completed",
                thread_id=thread_id,
                answer_chars=len(answer),
                outbound_chunks=max(1, len(chunks)),
            )
        except Exception as exc:
            add_event("zalo_agent_error", thread_id, {"error": f"{type(exc).__name__}: {exc}"})
            exception(logger, "zalo_agent_reply_failed", thread_id=thread_id, error_type=type(exc).__name__)


async def _zalo_webhook_registration_loop() -> None:
    if integrations is None or integrations.zalo is None:
        return
    secret = settings.read_zalo_webhook_secret()
    base = settings.zalo_webhook_callback_base.rstrip("/")
    if not secret or not base:
        add_event("zalo_webhook_registration", None, {"status": "skipped", "reason": "missing callback base or webhook secret"})
        warning(logger, "zalo_webhook_registration_skipped", reason="missing callback base or webhook secret")
        return

    callback = f"{base}/webhooks/zalo/{secret}"
    last_status = ""
    while not stop_event.is_set():
        try:
            result = await integrations.zalo.ensure_hassmind_webhooks(callback)
            if last_status != "ok":
                add_event("zalo_webhook_registration", None, {"status": "ok", "result": result})
                info(logger, "zalo_webhook_registration_ok", callback=sanitize_url(callback))
            last_status = "ok"
            delay = 3600
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            current = f"{type(exc).__name__}: {exc}"
            if current != last_status:
                add_event("zalo_webhook_registration", None, {"status": "error", "error": current})
                exception(logger, "zalo_webhook_registration_failed", callback=sanitize_url(callback), retry_in_seconds=60)
            last_status = current
            delay = 60

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass


async def _sync_zalo_webhook_registration_task() -> None:
    global tasks
    existing = [task for task in tasks if task.get_name() == "zalo-webhook-register" and not task.done()]
    for task in existing:
        task.cancel()
    if existing:
        await asyncio.gather(*existing, return_exceptions=True)
    tasks = [task for task in tasks if task.get_name() != "zalo-webhook-register"]

    should_run = bool(
        integrations is not None
        and integrations.zalo is not None
        and settings.zalo_enabled
        and settings.zalo_webhook_enabled
        and settings.zalo_auto_register_webhook
    )
    if should_run:
        task = asyncio.create_task(_zalo_webhook_registration_loop(), name="zalo-webhook-register")
        tasks.append(task)
        info(logger, "zalo_webhook_registration_task_started")
    elif existing:
        info(logger, "zalo_webhook_registration_task_stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ha, agent, tasks, integrations
    startup_started = perf_counter()
    db_path = Path(settings.db_path)
    info(
        logger,
        "application_starting",
        version=APP_VERSION,
        python=sys.version.split()[0],
        pid=os.getpid(),
        uid=os.getuid() if hasattr(os, "getuid") else None,
        cwd=os.getcwd(),
        db_path=str(db_path),
        db_parent_exists=db_path.parent.exists(),
        db_parent_writable=os.access(db_path.parent, os.W_OK) if db_path.parent.exists() else False,
        log=log_file_info(),
    )
    try:
        init_db()
        load_runtime_integration_overrides()
        scrub_sensitive_audit_history()
        ensure_bootstrap_admin()
        cleanup_sessions()
        recovery = settings.read_admin_recovery_key()
        if recovery:
            register_secret(recovery)
        info(logger, "database_initialized", db_path=str(db_path), exists=db_path.exists(), size_bytes=db_path.stat().st_size if db_path.exists() else 0)
        stop_event.clear()
        ha = HomeAssistantClient()
        integrations = IntegrationHub()
        agent = Agent(ToolRuntime(ha, integrations))
        tasks = [
            asyncio.create_task(ha.listen_events(event_callback, stop_event), name="ha-events"),
            asyncio.create_task(scheduler_loop(stop_event, run_prompt), name="scheduler"),
            asyncio.create_task(telegram_loop(stop_event, lambda sid, text, src: agent.chat(sid, text, src)), name="telegram"),
        ]
        await _sync_zalo_webhook_registration_task()
        info(
            logger,
            "application_started",
            version=APP_VERSION,
            duration_ms=round((perf_counter() - startup_started) * 1000, 2),
            background_tasks=[t.get_name() for t in tasks],
        )
        yield
    except Exception:
        exception(
            logger,
            "application_startup_failed",
            message="HassMind startup failed",
            duration_ms=round((perf_counter() - startup_started) * 1000, 2),
        )
        raise
    finally:
        shutdown_started = perf_counter()
        info(logger, "application_stopping", task_count=len(tasks), webhook_task_count=len(webhook_tasks))
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
        info(logger, "application_stopped", duration_ms=round((perf_counter() - shutdown_started) * 1000, 2))


app = FastAPI(
    title="HassMind",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:64]
    started = perf_counter()
    remote_ip = request.client.host if request.client else None
    safe_url = sanitize_url(str(request.url)) if settings.log_include_content else sanitize_url(request.url.path)
    query_keys = list(request.query_params.keys())
    path = request.url.path
    admin_surface = path == "/" or path == "/login" or path == "/favicon.svg" or path.startswith("/static/") or path.startswith("/api/")
    with log_context(request_id=request_id, source="http", component="api"):
        if admin_surface and not client_ip_allowed(request):
            warning(logger, "admin_network_denied", client_ip=remote_ip, path=path)
            response = JSONResponse(status_code=403, content={"detail": "Access from this network is not allowed", "request_id": request_id})
        else:
            info(
                logger,
                "http_request_started",
                method=request.method,
                url=safe_url,
                query_keys=query_keys,
                client_ip=remote_ip,
                user_agent=(request.headers.get("user-agent") or "")[:500],
                component="api",
            )
            try:
                response = await call_next(request)
            except Exception:
                exception(
                    logger,
                    "http_request_unhandled_exception",
                    message="Unhandled exception while processing HTTP request",
                    method=request.method,
                    url=safe_url,
                    client_ip=remote_ip,
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                )
                raise
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if path in {"/", "/login"} or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        info(
            logger,
            "http_request_completed",
            method=request.method,
            url=safe_url,
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            client_ip=remote_ip,
            component="api",
        )
        return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = current_request_id() or uuid.uuid4().hex
    exception(
        logger,
        "api_unhandled_exception",
        message="Unhandled API exception",
        method=request.method,
        url=sanitize_url(str(request.url)),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": rid,
        },
        headers={"X-Request-ID": rid},
    )


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str | None = Field(default=None, max_length=128)


class ToggleIn(BaseModel):
    enabled: bool


class DecisionIn(BaseModel):
    approve: bool


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20000)
    schedule_type: str = Field(min_length=1, max_length=32)
    schedule_value: str = Field(min_length=1, max_length=128)
    notify: bool = True


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    entity_id: str = Field(min_length=1, max_length=255)
    to_state: str | None = Field(default=None, max_length=255)
    prompt: str = Field(min_length=1, max_length=20000)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    notify: bool = True


class ClientLogIn(BaseModel):
    level: str = Field(default="ERROR", max_length=16)
    event: str = Field(default="browser_error", max_length=128)
    message: str = Field(max_length=12000)
    stack: str = Field(default="", max_length=30000)
    url: str = Field(default="", max_length=2048)
    session_id: str = Field(default="", max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UsernameChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_username: str = Field(min_length=1, max_length=64)


class PasswordResetIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    recovery_key: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=256)


class ApiTokenRotateIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    token: str = Field(default="", max_length=4096)
    generate: bool = False


class RecoveryKeyRotateIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)


class IntegrationConfigIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class CustomIntegrationIn(BaseModel):
    id: str = Field(default="", max_length=64)
    name: str = Field(min_length=1, max_length=120)
    icon: str = Field(default="🔌", max_length=16)
    description: str = Field(default="", max_length=600)
    enabled: bool = True
    base_url: str = Field(min_length=1, max_length=2048)
    health_path: str = Field(default="/health", max_length=512)
    auth_type: str = Field(default="none", max_length=32)
    auth_header: str = Field(default="X-API-Key", max_length=128)
    secret: str = Field(default="", max_length=4096)
    clear_secret: bool = False


@app.get("/")
async def root(request: Request):
    if not session_from_request(request, touch=False):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/login")
async def login_page(request: Request):
    if session_from_request(request, touch=False):
        return RedirectResponse("/", status_code=303)
    return FileResponse(str(STATIC_DIR / "login.html"), headers={"Cache-Control": "no-store"})


@app.get("/favicon.svg")
async def favicon():
    return FileResponse(str(STATIC_DIR / "favicon.svg"), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/auth/login")
async def auth_login(body: LoginIn, request: Request):
    user, raw_session, raw_csrf = admin_login(body.username, body.password, request)
    response = JSONResponse({"ok": True, "user": user, "csrf_token": raw_csrf})
    max_age = settings.admin_session_ttl_minutes * 60
    response.set_cookie(
        settings.admin_session_cookie,
        raw_session,
        max_age=max_age,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.admin_csrf_cookie,
        raw_csrf,
        max_age=max_age,
        httponly=False,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/auth/logout", dependencies=[Depends(require_admin)])
async def auth_logout(request: Request):
    admin_logout(request)
    response = JSONResponse({"ok": True})
    response.delete_cookie(settings.admin_session_cookie, path="/")
    response.delete_cookie(settings.admin_csrf_cookie, path="/")
    return response


@app.get("/api/auth/me", dependencies=[Depends(require_admin)])
async def auth_me(request: Request):
    session = request.state.admin_session
    return {
        "authenticated": True,
        "user": {
            "id": session["user_id"],
            "username": session["username"],
            "last_login_at": session.get("last_login_at"),
            "password_changed_at": session.get("password_changed_at"),
        },
        "csrf_token": request.cookies.get(settings.admin_csrf_cookie, ""),
        "session": {
            "created_at": session["created_at"],
            "last_seen_at": session["last_seen_at"],
            "expires_at": session["expires_at"],
        },
    }


@app.post("/api/auth/change-password", dependencies=[Depends(require_admin)])
async def auth_change_password(body: PasswordChangeIn, request: Request):
    session = request.state.admin_session
    change_password(session["user_id"], body.current_password, body.new_password, request)
    return {"ok": True}


@app.post("/api/auth/change-username", dependencies=[Depends(require_admin)])
async def auth_change_username(body: UsernameChangeIn, request: Request):
    session = request.state.admin_session
    username = change_username(session["user_id"], body.current_password, body.new_username, request)
    return {"ok": True, "username": username}


@app.post("/api/auth/reset-password")
async def auth_reset_password(body: PasswordResetIn, request: Request):
    reset_password(body.username, body.recovery_key, body.new_password, request)
    return {"ok": True}


@app.get("/api/auth/sessions", dependencies=[Depends(require_admin)])
async def auth_sessions(request: Request):
    session = request.state.admin_session
    return list_sessions(session["user_id"], request)


@app.post("/api/auth/sessions/revoke-others", dependencies=[Depends(require_admin)])
async def auth_revoke_sessions(request: Request):
    session = request.state.admin_session
    return {"ok": True, "revoked": revoke_other_sessions(session["user_id"], request)}


@app.get("/api/auth/audit", dependencies=[Depends(require_admin)])
async def auth_audit(limit: int = 50):
    return list_auth_audit(limit)


@app.get("/api/settings/security", dependencies=[Depends(require_admin)])
async def security_settings(request: Request):
    try:
        token = settings.read_api_token()
        token_fp = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        token_configured = True
    except RuntimeError:
        token_fp = ""
        token_configured = False
    return {
        "api_token": {
            "configured": token_configured,
            "source": settings.api_token_source(),
            "fingerprint": token_fp,
        },
        "admin": {
            "username": request.state.admin_session["username"],
            "recovery_enabled": bool(settings.read_admin_recovery_key()),
            "recovery_source": settings.admin_recovery_key_source(),
            "session_ttl_minutes": settings.admin_session_ttl_minutes,
            "session_idle_minutes": settings.admin_session_idle_minutes,
            "cookie_secure": settings.admin_cookie_secure,
            "allowed_networks": settings.admin_allowed_network_list,
            "password_min_length": settings.password_min_length,
            "password_storage": "argon2id_hash_only",
            "bootstrap_password_is_initial_only": True,
            "recovery_runtime_file": str(Path(settings.runtime_secret_dir) / settings.runtime_recovery_key_name),
        },
        "logging": {
            "secret_redaction": True,
            "content_logging": settings.log_include_content,
            "file": settings.log_file if settings.log_file_enabled else "disabled",
            "scrub_existing_logs_on_start": settings.log_scrub_existing_on_start,
            "scrub_existing_audit_on_start": settings.audit_scrub_existing_on_start,
        },
    }


@app.post("/api/settings/api-token", dependencies=[Depends(require_admin)])
async def rotate_api_token(body: ApiTokenRotateIn, request: Request):
    session = request.state.admin_session
    with conn() as c:
        row = c.execute("SELECT password_hash FROM admin_users WHERE id=?", (session["user_id"],)).fetchone()
    if not row or not verify_password(row["password_hash"], body.current_password):
        raise HTTPException(400, "Mật khẩu quản trị hiện tại không đúng.")
    if body.generate:
        token = secrets.token_urlsafe(48)
    else:
        token = body.token.strip()
        if len(token) < 32:
            raise HTTPException(400, "API token phải có ít nhất 32 ký tự.")
    settings.write_runtime_secret(settings.runtime_api_token_name, token)
    register_secret(token)
    info(logger, "api_token_rotated", by=session["username"], source="runtime_file")
    record_admin_audit("api_token_rotated", request, user_id=session["user_id"], username=session["username"], details="source=runtime_file")
    result = {
        "ok": True,
        "source": "runtime_file",
        "fingerprint": hashlib.sha256(token.encode("utf-8")).hexdigest()[:12],
    }
    if body.generate:
        result["token"] = token
    return result


@app.post("/api/settings/recovery-key", dependencies=[Depends(require_admin)])
async def rotate_recovery_key(body: RecoveryKeyRotateIn, request: Request):
    session = request.state.admin_session
    with conn() as c:
        row = c.execute("SELECT password_hash FROM admin_users WHERE id=?", (session["user_id"],)).fetchone()
    if not row or not verify_password(row["password_hash"], body.current_password):
        raise HTTPException(400, "Mật khẩu quản trị hiện tại không đúng.")
    recovery_key = secrets.token_urlsafe(48)
    settings.write_runtime_secret(settings.runtime_recovery_key_name, recovery_key)
    register_secret(body.current_password)
    register_secret(recovery_key)
    record_admin_audit("recovery_key_rotated", request, user_id=session["user_id"], username=session["username"], details="source=runtime_file")
    info(logger, "admin_recovery_key_rotated", by=session["username"], source="runtime_file")
    return {"ok": True, "source": "runtime_file", "recovery_key": recovery_key}


@app.get("/api/status", dependencies=[Depends(require_access)])
async def status():
    ha_ok = False
    ha_version = None
    ha_error = None
    if ha:
        try:
            cfg = await ha._get("/api/config")
            ha_ok = True
            ha_version = cfg.get("version")
        except Exception as exc:
            ha_error = f"{type(exc).__name__}: {exc}"
            warning(logger, "status_ha_check_failed", error=ha_error)
    return {
        "ok": True,
        "version": APP_VERSION,
        "uptime_seconds": uptime_seconds(),
        "ha_connected": ha_ok,
        "ha_version": ha_version,
        "ha_error": ha_error,
        "model": settings.openai_model,
        "scheduler": settings.scheduler_enabled,
        "event_agent": settings.event_agent_enabled,
        "log_level": settings.log_level.upper(),
        "log_file": settings.log_file if settings.log_file_enabled else "disabled",
    }


@app.get("/api/diagnostics", dependencies=[Depends(require_access)])
async def diagnostics():
    db_path = Path(settings.db_path)
    task_info = []
    for task in tasks:
        task_info.append({"name": task.get_name(), "done": task.done(), "cancelled": task.cancelled()})
    return {
        "app": {
            "name": settings.agent_name,
            "version": APP_VERSION,
            "uptime_seconds": uptime_seconds(),
            "pid": os.getpid(),
            "python": sys.version,
            "platform": platform.platform(),
        },
        "database": {
            "path": str(db_path),
            "exists": db_path.exists(),
            "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
            "parent_exists": db_path.parent.exists(),
            "parent_writable": os.access(db_path.parent, os.W_OK) if db_path.parent.exists() else False,
        },
        "logging": log_file_info(),
        "runtime": {
            "background_tasks": task_info,
            "webhook_tasks": len(webhook_tasks),
        },
        "configuration": {
            "ha_url": settings.ha_url,
            "openai_base_url": settings.openai_base_url,
            "openai_model": settings.openai_model,
            "searxng_url": settings.searxng_url,
            "camera_tts_enabled": settings.camera_tts_enabled,
            "camera_tts_url": settings.camera_tts_url,
            "facedetect_enabled": settings.facedetect_enabled,
            "facedetect_url": settings.facedetect_url,
            "zalo_enabled": settings.zalo_enabled,
            "zalo_url": settings.zalo_url,
            "wyoming_enabled": settings.wyoming_enabled,
            "wyoming_host": settings.wyoming_host,
            "wyoming_port": settings.wyoming_port,
            "ha_custom_integrations_enabled": settings.ha_custom_integrations_enabled,
        },
    }


@app.get("/api/logs", dependencies=[Depends(require_access)])
async def logs_api(
    limit: int = Query(default=250, ge=1, le=2000),
    level: str = "",
    component: str = "",
    q: str = "",
):
    return recent_logs(limit=limit, level=level, component=component, query=q)


@app.get("/api/logs/export", dependencies=[Depends(require_access)])
async def logs_export(
    limit: int = Query(default=2000, ge=1, le=2000),
    level: str = "",
    component: str = "",
    q: str = "",
):
    rows = list(reversed(recent_logs(limit=limit, level=level, component=component, query=q)))
    text = "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows)
    return PlainTextResponse(
        text,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="hassmind-logs-{APP_VERSION}.ndjson"'},
    )


@app.post("/api/client-log", dependencies=[Depends(require_access)])
async def client_log(body: ClientLogIn):
    level_name = body.level.upper()
    level = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }.get(level_name, logging.ERROR)
    with log_context(session_id=body.session_id or None, source="browser", component="frontend"):
        log(
            logger,
            level,
            f"browser_{body.event}",
            message=body.message,
            stack=body.stack[:20000],
            url=sanitize_url(body.url) if body.url else "",
            details=body.details,
            component="frontend",
        )
    return {"ok": True, "request_id": current_request_id()}


@app.get("/api/integrations/config", dependencies=[Depends(require_admin)])
async def integration_config_get():
    return integration_config_view()


@app.put("/api/integrations/config/{integration_id}", dependencies=[Depends(require_admin)])
async def integration_config_put(integration_id: str, body: IntegrationConfigIn, request: Request):
    if integrations is None:
        raise HTTPException(503, "Integrations are starting")
    try:
        result = save_integration_config(integration_id, body.values)
    except KeyError:
        raise HTTPException(404, "Unknown integration")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await integrations.reconfigure()
    await _sync_zalo_webhook_registration_task()
    record_admin_audit(
        "integration_config_saved",
        request,
        user_id=request.state.admin_session["user_id"],
        username=request.state.admin_session["username"],
        details=f"integration={integration_id}",
    )
    return {"ok": True, "config": result, "status": await integrations.status()}


@app.delete("/api/integrations/config/{integration_id}", dependencies=[Depends(require_admin)])
async def integration_config_delete(integration_id: str, request: Request):
    if integrations is None:
        raise HTTPException(503, "Integrations are starting")
    try:
        result = reset_integration_config(integration_id)
    except KeyError:
        raise HTTPException(404, "Unknown integration")
    await integrations.reconfigure()
    await _sync_zalo_webhook_registration_task()
    record_admin_audit(
        "integration_config_reset",
        request,
        user_id=request.state.admin_session["user_id"],
        username=request.state.admin_session["username"],
        details=f"integration={integration_id}",
    )
    return {"ok": True, "config": result, "status": await integrations.status()}


@app.post("/api/integrations/custom", dependencies=[Depends(require_admin)])
async def custom_integration_create(body: CustomIntegrationIn, request: Request):
    if integrations is None:
        raise HTTPException(503, "Integrations are starting")
    try:
        item = create_custom_integration(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await integrations.reconfigure()
    record_admin_audit(
        "custom_integration_created",
        request,
        user_id=request.state.admin_session["user_id"],
        username=request.state.admin_session["username"],
        details=f"integration={item['id']}",
    )
    return {"ok": True, "integration": item, "config": integration_config_view()}


@app.put("/api/integrations/custom/{integration_id}", dependencies=[Depends(require_admin)])
async def custom_integration_update(integration_id: str, body: CustomIntegrationIn, request: Request):
    if integrations is None:
        raise HTTPException(503, "Integrations are starting")
    try:
        item = update_custom_integration(integration_id, body.model_dump())
    except KeyError:
        raise HTTPException(404, "Unknown custom integration")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    await integrations.reconfigure()
    record_admin_audit(
        "custom_integration_updated",
        request,
        user_id=request.state.admin_session["user_id"],
        username=request.state.admin_session["username"],
        details=f"integration={integration_id}",
    )
    return {"ok": True, "integration": item, "config": integration_config_view()}


@app.delete("/api/integrations/custom/{integration_id}", dependencies=[Depends(require_admin)])
async def custom_integration_delete(integration_id: str, request: Request):
    if integrations is None:
        raise HTTPException(503, "Integrations are starting")
    try:
        delete_custom_integration(integration_id)
    except KeyError:
        raise HTTPException(404, "Unknown custom integration")
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    await integrations.reconfigure()
    record_admin_audit(
        "custom_integration_deleted",
        request,
        user_id=request.state.admin_session["user_id"],
        username=request.state.admin_session["username"],
        details=f"integration={integration_id}",
    )
    return {"ok": True, "config": integration_config_view()}


@app.get("/api/integrations", dependencies=[Depends(require_access)])
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
        warning(logger, "zalo_webhook_auth_failed")
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
    info(
        logger,
        "zalo_webhook_received",
        thread_id=normalized_thread,
        text_chars=len(text),
        reply_scheduled=can_reply,
    )
    if can_reply:
        _remember_webhook_task(asyncio.create_task(_process_zalo_message(payload), name=f"zalo:{normalized_thread}"))
    return {"accepted": True, "agent_reply_scheduled": can_reply}


@app.post("/api/chat", dependencies=[Depends(require_access)])
async def chat(body: ChatIn):
    if agent is None:
        raise HTTPException(503, "Agent is starting")
    sid = body.session_id or uuid.uuid4().hex
    with log_context(session_id=sid, source="web", component="chat_api"):
        info(logger, "chat_api_request", message_chars=len(body.message), component="chat_api")
        answer = await agent.chat(sid, body.message, source="web")
        info(logger, "chat_api_response", answer_chars=len(answer), component="chat_api")
    return {"session_id": sid, "answer": answer, "request_id": current_request_id()}


@app.get("/api/messages/{session_id}", dependencies=[Depends(require_access)])
async def messages(session_id: str):
    return get_messages(session_id, 100)


@app.get("/api/events", dependencies=[Depends(require_access)])
async def events(limit: int = 50):
    return recent_events(min(max(limit, 1), 200))


@app.get("/api/audit", dependencies=[Depends(require_access)])
async def audit(limit: int = 100):
    return recent_tool_audit(min(max(limit, 1), 500))


@app.get("/api/approvals", dependencies=[Depends(require_access)])
async def approvals():
    return list_approvals()


@app.get("/api/approvals/{aid}", dependencies=[Depends(require_access)])
async def approval(aid: str):
    row = get_approval(aid)
    if not row:
        raise HTTPException(404, "Not found")
    return row


@app.post("/api/approvals/{aid}/decision", dependencies=[Depends(require_access)])
async def approval_decision(aid: str, body: DecisionIn):
    if ha is None:
        raise HTTPException(503, "HA client unavailable")
    info(logger, "approval_decision", approval_id=aid, approve=body.approve)
    d = decide_by_web(aid, body.approve)
    if body.approve and settings.auto_apply_after_approval:
        d["apply"] = await apply_approval(ha, aid)
    return d


@app.get("/api/jobs", dependencies=[Depends(require_access)])
async def jobs():
    return list_jobs()


@app.post("/api/jobs", dependencies=[Depends(require_access)])
async def create_job_api(body: JobIn):
    from .scheduler import create_job
    return create_job(body.name, body.prompt, body.schedule_type, body.schedule_value, body.notify)


@app.patch("/api/jobs/{job_id}", dependencies=[Depends(require_access)])
async def toggle_job(job_id: int, body: ToggleIn):
    set_job_enabled(job_id, body.enabled)
    return {"id": job_id, "enabled": body.enabled}


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(require_access)])
async def delete_job(job_id: int):
    with conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    info(logger, "job_deleted", job_id=job_id)
    return {"ok": True}


@app.get("/api/event-rules", dependencies=[Depends(require_access)])
async def rules():
    return list_event_rules()


@app.post("/api/event-rules", dependencies=[Depends(require_access)])
async def create_rule_api(body: RuleIn):
    from .event_engine import create_event_rule
    return create_event_rule(body.name, body.entity_id, body.to_state, body.prompt, body.cooldown_seconds, body.notify)


@app.patch("/api/event-rules/{rule_id}", dependencies=[Depends(require_access)])
async def toggle_rule(rule_id: int, body: ToggleIn):
    set_rule_enabled(rule_id, body.enabled)
    return {"id": rule_id, "enabled": body.enabled}


@app.delete("/api/event-rules/{rule_id}", dependencies=[Depends(require_access)])
async def delete_rule(rule_id: int):
    with conn() as c:
        c.execute("DELETE FROM event_rules WHERE id=?", (rule_id,))
    info(logger, "event_rule_deleted", rule_id=rule_id)
    return {"ok": True}


@app.post("/api/knowledge/reindex", dependencies=[Depends(require_access)])
async def reindex():
    result = reindex_knowledge()
    info(logger, "knowledge_reindexed", result=result)
    return result


@app.get("/api/knowledge/search", dependencies=[Depends(require_access)])
async def knowledge_search(q: str, limit: int = 8):
    return search_knowledge(q, min(max(limit, 1), 20))


@app.get("/api/skills", dependencies=[Depends(require_access)])
async def skills():
    return list_skills()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        access_log=False,
        log_config=None,
        server_header=False,
    )
