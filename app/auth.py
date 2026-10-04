import hashlib
import ipaddress
import re
import secrets
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request

from .db import conn, utcnow
from .observability import get_logger, info, register_secret, warning
from .settings import settings
from .time_utils import now as local_now, parse_datetime

logger = get_logger("auth")
_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
# Used only to reduce username-enumeration timing differences for unknown accounts.
_dummy_password_hash = _password_hasher.hash("HassMindDummyPasswordTimingOnly-DoNotUse")
_rate_lock = threading.Lock()
_rate_events: dict[str, deque[float]] = defaultdict(deque)


def _now() -> datetime:
    return local_now()


def _parse_dt(value: str | None) -> datetime | None:
    return parse_datetime(value)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_username(value: str) -> str:
    return value.strip()


def validate_username(username: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
        raise ValueError("Tên đăng nhập phải dài 3-64 ký tự và chỉ gồm chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.")


def validate_password(password: str, username: str = "") -> None:
    if len(password) < settings.password_min_length:
        raise ValueError(f"Mật khẩu phải có ít nhất {settings.password_min_length} ký tự.")
    if len(password) > 256:
        raise ValueError("Mật khẩu quá dài.")
    if username and username.lower() in password.lower():
        raise ValueError("Mật khẩu không được chứa tên đăng nhập.")
    classes = sum(bool(re.search(pattern, password)) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if len(password) < 20 and classes < 3:
        raise ValueError("Mật khẩu dưới 20 ký tự phải có ít nhất 3 nhóm: chữ thường, chữ hoa, số, ký tự đặc biệt.")


def password_hash(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(hash_value: str, password: str) -> bool:
    try:
        return bool(_password_hasher.verify(hash_value, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _rate_limited(key: str, max_events: int, window_seconds: int) -> bool:
    import time

    now = time.monotonic()
    with _rate_lock:
        q = _rate_events[key]
        while q and q[0] <= now - window_seconds:
            q.popleft()
        return len(q) >= max_events


def _record_rate_failure(key: str) -> None:
    import time

    with _rate_lock:
        _rate_events[key].append(time.monotonic())


def _clear_rate_failures(key: str) -> None:
    with _rate_lock:
        _rate_events.pop(key, None)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def client_ip_allowed(request: Request) -> bool:
    raw = client_ip(request)
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    networks = settings.admin_allowed_network_list
    if not networks:
        return True
    for item in networks:
        try:
            if ip in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def ensure_bootstrap_admin() -> None:
    with conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()
        if int(row["n"]) > 0:
            return
    username = _clean_username(settings.admin_username)
    validate_username(username)
    password = settings.read_admin_bootstrap_password()
    if not password:
        raise RuntimeError(
            "No admin account exists and ADMIN_BOOTSTRAP_PASSWORD_FILE/ADMIN_BOOTSTRAP_PASSWORD is empty. "
            "Create secrets/admin_password.txt (recommended) or set ADMIN_BOOTSTRAP_PASSWORD."
        )
    validate_password(password, username)
    register_secret(password)
    now = utcnow()
    with conn() as c:
        c.execute(
            "INSERT INTO admin_users(username,password_hash,is_active,created_at,updated_at,password_changed_at) VALUES(?,?,?,?,?,?)",
            (username, password_hash(password), 1, now, now, now),
        )
    info(logger, "admin_bootstrapped", username=username)


def _audit(event: str, *, username: str = "", user_id: int | None = None, ip: str = "", success: bool, details: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO auth_audit(event,username,user_id,ip,success,details,created_at) VALUES(?,?,?,?,?,?,?)",
            (event, username[:64], user_id, ip[:64], 1 if success else 0, details[:500], utcnow()),
        )
        c.execute("DELETE FROM auth_audit WHERE id NOT IN (SELECT id FROM auth_audit ORDER BY id DESC LIMIT 5000)")


def login(username: str, password: str, request: Request) -> tuple[dict[str, Any], str, str]:
    username = _clean_username(username)
    ip = client_ip(request)
    user_rate_key = f"login:{ip}:{username.lower()}"
    ip_rate_key = f"login-ip:{ip}"
    window = settings.login_lock_minutes * 60
    if _rate_limited(ip_rate_key, settings.login_max_failures * 3, window) or _rate_limited(
        user_rate_key, settings.login_max_failures * 2, window
    ):
        _audit("login_rate_limited", username=username, ip=ip, success=False)
        raise HTTPException(429, "Quá nhiều lần đăng nhập. Hãy thử lại sau.")

    with conn() as c:
        row = c.execute("SELECT * FROM admin_users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        user = dict(row) if row else None

    generic = "Tên đăng nhập hoặc mật khẩu không đúng."
    if not user or not user.get("is_active"):
        # Deliberately perform an Argon2 verification even for an unknown user to
        # make the response time closer to a real bad-password attempt.
        verify_password(_dummy_password_hash, password)
        _record_rate_failure(user_rate_key)
        _record_rate_failure(ip_rate_key)
        _audit("login_failed", username=username, ip=ip, success=False, details="unknown_or_inactive_user")
        raise HTTPException(401, generic)

    locked_until = _parse_dt(user.get("locked_until"))
    if locked_until and locked_until > _now():
        _audit("login_locked", username=username, user_id=user["id"], ip=ip, success=False)
        raise HTTPException(429, "Tài khoản đang tạm khóa do nhiều lần đăng nhập sai. Hãy thử lại sau.")

    if not verify_password(user["password_hash"], password):
        _record_rate_failure(user_rate_key)
        _record_rate_failure(ip_rate_key)
        failures = int(user.get("failed_attempts") or 0) + 1
        lock_until = None
        if failures >= settings.login_max_failures:
            lock_until = (_now() + timedelta(minutes=settings.login_lock_minutes)).isoformat()
            failures = 0
        with conn() as c:
            c.execute("UPDATE admin_users SET failed_attempts=?, locked_until=?, updated_at=? WHERE id=?", (failures, lock_until, utcnow(), user["id"]))
        _audit("login_failed", username=username, user_id=user["id"], ip=ip, success=False, details="bad_password")
        warning(logger, "admin_login_failed", username=username, client_ip=ip)
        raise HTTPException(401, generic)

    _clear_rate_failures(user_rate_key)
    _clear_rate_failures(ip_rate_key)
    register_secret(password)
    if _password_hasher.check_needs_rehash(user["password_hash"]):
        with conn() as c:
            c.execute("UPDATE admin_users SET password_hash=?,updated_at=? WHERE id=?", (password_hash(password), utcnow(), user["id"]))

    raw_session = secrets.token_urlsafe(48)
    session_hash = _sha256(raw_session)
    raw_csrf = secrets.token_urlsafe(32)
    csrf_hash = _sha256(raw_csrf)
    now = _now()
    expires = now + timedelta(minutes=settings.admin_session_ttl_minutes)
    with conn() as c:
        c.execute("UPDATE admin_users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=? WHERE id=?", (now.isoformat(), now.isoformat(), user["id"]))
        c.execute(
            "INSERT INTO admin_sessions(id,user_id,csrf_hash,created_at,last_seen_at,expires_at,ip,user_agent) VALUES(?,?,?,?,?,?,?,?)",
            (session_hash, user["id"], csrf_hash, now.isoformat(), now.isoformat(), expires.isoformat(), ip[:64], (request.headers.get("user-agent") or "")[:500]),
        )
    _audit("login_success", username=user["username"], user_id=user["id"], ip=ip, success=True)
    info(logger, "admin_login_success", username=user["username"], client_ip=ip)
    user_public = {"id": user["id"], "username": user["username"], "last_login_at": now.isoformat()}
    return user_public, raw_session, raw_csrf


def _session_row(raw_session: str, *, touch: bool = True) -> dict[str, Any] | None:
    if not raw_session or len(raw_session) < 32:
        return None
    sid = _sha256(raw_session)
    with conn() as c:
        row = c.execute(
            """
            SELECT s.*,u.username,u.is_active,u.last_login_at,u.password_changed_at
            FROM admin_sessions s JOIN admin_users u ON u.id=s.user_id
            WHERE s.id=?
            """,
            (sid,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        now = _now()
        expires = _parse_dt(data.get("expires_at"))
        last_seen = _parse_dt(data.get("last_seen_at"))
        idle_cutoff = now - timedelta(minutes=settings.admin_session_idle_minutes)
        if not data.get("is_active") or not expires or expires <= now or not last_seen or last_seen <= idle_cutoff:
            c.execute("DELETE FROM admin_sessions WHERE id=?", (sid,))
            return None
        if touch and (now - last_seen).total_seconds() >= 60:
            c.execute("UPDATE admin_sessions SET last_seen_at=? WHERE id=?", (now.isoformat(), sid))
            data["last_seen_at"] = now.isoformat()
    data["raw_session_id"] = sid
    return data


def session_from_request(request: Request, *, touch: bool = True) -> dict[str, Any] | None:
    raw = request.cookies.get(settings.admin_session_cookie, "")
    return _session_row(raw, touch=touch)


def require_session(request: Request, csrf_token: str = "", require_csrf: bool = False) -> dict[str, Any]:
    session = session_from_request(request)
    if not session:
        raise HTTPException(401, "Phiên đăng nhập đã hết hạn hoặc không hợp lệ.")
    if require_csrf:
        if not csrf_token or not secrets.compare_digest(_sha256(csrf_token), session["csrf_hash"]):
            warning(logger, "csrf_validation_failed", username=session.get("username"), client_ip=client_ip(request))
            raise HTTPException(403, "CSRF token không hợp lệ.")
    return session


def logout(request: Request) -> None:
    raw = request.cookies.get(settings.admin_session_cookie, "")
    if raw:
        sid = _sha256(raw)
        with conn() as c:
            row = c.execute("SELECT u.username,s.user_id FROM admin_sessions s JOIN admin_users u ON u.id=s.user_id WHERE s.id=?", (sid,)).fetchone()
            c.execute("DELETE FROM admin_sessions WHERE id=?", (sid,))
        if row:
            _audit("logout", username=row["username"], user_id=row["user_id"], ip=client_ip(request), success=True)


def change_password(user_id: int, current_password: str, new_password: str, request: Request) -> None:
    with conn() as c:
        row = c.execute("SELECT * FROM admin_users WHERE id=?", (user_id,)).fetchone()
    if not row or not verify_password(row["password_hash"], current_password):
        _audit("password_change_failed", username=row["username"] if row else "", user_id=user_id, ip=client_ip(request), success=False)
        raise HTTPException(400, "Mật khẩu hiện tại không đúng.")
    try:
        validate_password(new_password, row["username"])
    except ValueError as exc:
        _audit(
            "password_change_failed",
            username=row["username"],
            user_id=user_id,
            ip=client_ip(request),
            success=False,
            details="password_policy_rejected",
        )
        raise HTTPException(400, str(exc)) from exc
    register_secret(current_password)
    register_secret(new_password)
    now = utcnow()
    with conn() as c:
        c.execute("UPDATE admin_users SET password_hash=?,password_changed_at=?,updated_at=? WHERE id=?", (password_hash(new_password), now, now, user_id))
        current_sid = _sha256(request.cookies.get(settings.admin_session_cookie, ""))
        c.execute("DELETE FROM admin_sessions WHERE user_id=? AND id<>?", (user_id, current_sid))
    _audit("password_changed", username=row["username"], user_id=user_id, ip=client_ip(request), success=True)
    info(logger, "admin_password_changed", username=row["username"])


def change_username(user_id: int, current_password: str, new_username: str, request: Request) -> str:
    new_username = _clean_username(new_username)
    try:
        validate_username(new_username)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with conn() as c:
        row = c.execute("SELECT * FROM admin_users WHERE id=?", (user_id,)).fetchone()
        if not row or not verify_password(row["password_hash"], current_password):
            raise HTTPException(400, "Mật khẩu hiện tại không đúng.")
        register_secret(current_password)
        try:
            c.execute("UPDATE admin_users SET username=?,updated_at=? WHERE id=?", (new_username, utcnow(), user_id))
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(409, "Tên đăng nhập đã tồn tại.") from exc
            raise
    _audit("username_changed", username=new_username, user_id=user_id, ip=client_ip(request), success=True, details=f"from={row['username']}")
    info(logger, "admin_username_changed", old_username=row["username"], username=new_username)
    return new_username


def reset_password(username: str, recovery_key: str, new_password: str, request: Request) -> None:
    ip = client_ip(request)
    rate_key = f"reset:{ip}"
    if _rate_limited(rate_key, 5, settings.login_lock_minutes * 60):
        raise HTTPException(429, "Quá nhiều yêu cầu khôi phục. Hãy thử lại sau.")
    expected = settings.read_admin_recovery_key()
    if not expected:
        raise HTTPException(503, "Khôi phục mật khẩu chưa được cấu hình trên máy chủ.")
    register_secret(expected)
    username = _clean_username(username)
    with conn() as c:
        row = c.execute("SELECT * FROM admin_users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    valid_key = bool(recovery_key) and secrets.compare_digest(recovery_key, expected)
    if not row or not valid_key:
        _record_rate_failure(rate_key)
        _audit("password_reset_failed", username=username, ip=ip, success=False)
        raise HTTPException(400, "Thông tin khôi phục không hợp lệ.")
    _clear_rate_failures(rate_key)
    try:
        validate_password(new_password, row["username"])
    except ValueError as exc:
        _audit(
            "password_reset_failed",
            username=row["username"],
            user_id=row["id"],
            ip=ip,
            success=False,
            details="password_policy_rejected",
        )
        raise HTTPException(400, str(exc)) from exc
    register_secret(new_password)
    now = utcnow()
    with conn() as c:
        c.execute(
            "UPDATE admin_users SET password_hash=?,failed_attempts=0,locked_until=NULL,password_changed_at=?,updated_at=? WHERE id=?",
            (password_hash(new_password), now, now, row["id"]),
        )
        c.execute("DELETE FROM admin_sessions WHERE user_id=?", (row["id"],))
    _audit("password_reset", username=row["username"], user_id=row["id"], ip=ip, success=True)
    info(logger, "admin_password_reset", username=row["username"], client_ip=ip)


def list_sessions(user_id: int, request: Request) -> list[dict[str, Any]]:
    current = _sha256(request.cookies.get(settings.admin_session_cookie, ""))
    with conn() as c:
        rows = c.execute("SELECT id,created_at,last_seen_at,expires_at,ip,user_agent FROM admin_sessions WHERE user_id=? ORDER BY last_seen_at DESC", (user_id,)).fetchall()
    return [
        {
            "id": r["id"][:12],
            "current": secrets.compare_digest(r["id"], current),
            "created_at": r["created_at"],
            "last_seen_at": r["last_seen_at"],
            "expires_at": r["expires_at"],
            "ip": r["ip"],
            "user_agent": r["user_agent"],
        }
        for r in rows
    ]


def revoke_other_sessions(user_id: int, request: Request) -> int:
    current = _sha256(request.cookies.get(settings.admin_session_cookie, ""))
    with conn() as c:
        cur = c.execute("DELETE FROM admin_sessions WHERE user_id=? AND id<>?", (user_id, current))
        count = int(cur.rowcount or 0)
    _audit("sessions_revoked", user_id=user_id, ip=client_ip(request), success=True, details=f"count={count}")
    return count




def record_admin_audit(event: str, request: Request, *, user_id: int | None = None, username: str = "", success: bool = True, details: str = "") -> None:
    _audit(event, username=username, user_id=user_id, ip=client_ip(request), success=success, details=details)

def list_auth_audit(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with conn() as c:
        rows = c.execute(
            "SELECT event,username,ip,success,details,created_at FROM auth_audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

def cleanup_sessions() -> None:
    now = _now()
    idle = now - timedelta(minutes=settings.admin_session_idle_minutes)
    with conn() as c:
        c.execute("DELETE FROM admin_sessions WHERE julianday(expires_at)<=julianday(?) OR julianday(last_seen_at)<=julianday(?)", (now.isoformat(), idle.isoformat()))
