import difflib
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from .db import conn, utcnow
from .ha import HomeAssistantClient
from .notifications import get_notification_preference, send_notification
from .policy import config_risk
from .settings import settings
from .time_utils import now as local_now, parse_datetime


def canonical_hash(obj: dict) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def make_diff(old: dict, new: dict) -> str:
    a = json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    b = json.dumps(new, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    return "\n".join(difflib.unified_diff(a, b, fromfile="current", tofile="proposed", lineterm=""))


def create_approval(kind: str, target_id: str, old_config: dict, new_config: dict, reason: str, parent_change_id: str | None = None) -> dict:
    if kind not in {"automation", "script"}:
        raise ValueError("kind must be automation or script")
    if kind == "automation":
        new_config = dict(new_config)
        if "id" in new_config and str(new_config["id"]) != str(target_id):
            raise ValueError("automation id in proposed config must match target_id")
        new_config["id"] = str(target_id)
    aid = "chg_" + uuid.uuid4().hex[:14]
    approve_token = secrets.token_urlsafe(24)
    reject_token = secrets.token_urlsafe(24)
    diff = make_diff(old_config, new_config)
    risk = config_risk(new_config)
    with conn() as c:
        c.execute(
            """INSERT INTO approvals(id,kind,target_id,old_config,new_config,old_hash,reason,diff,risk,status,approve_token,reject_token,created_at,parent_change_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, kind, target_id, json.dumps(old_config, ensure_ascii=False), json.dumps(new_config, ensure_ascii=False),
             canonical_hash(old_config), reason, diff, risk, "pending", approve_token, reject_token, utcnow(), parent_change_id),
        )
    return {"id": aid, "status": "pending", "risk": risk, "diff": diff, "approve_token": approve_token, "reject_token": reject_token}


def get_approval(aid: str, include_secrets: bool = False) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["old_config"] = json.loads(d["old_config"])
    d["new_config"] = json.loads(d["new_config"])
    if not include_secrets:
        d.pop("approve_token", None)
        d.pop("reject_token", None)
    return d


def decide_by_action(action: str) -> tuple[str, str] | None:
    prefix, _, token = action.partition(":")
    if prefix not in {"HASSMIND_APPROVE", "HASSMIND_REJECT"} or not token:
        return None
    col = "approve_token" if prefix == "HASSMIND_APPROVE" else "reject_token"
    status = "approved" if prefix == "HASSMIND_APPROVE" else "rejected"
    with conn() as c:
        r = c.execute(f"SELECT id,status,created_at FROM approvals WHERE {col}=?", (token,)).fetchone()
        if not r or r["status"] != "pending":
            return None
        created = parse_datetime(r["created_at"])
        if created is not None and local_now() - created > timedelta(minutes=settings.approval_ttl_minutes):
            c.execute("UPDATE approvals SET status='expired',decided_at=?,decided_by=? WHERE id=?", (utcnow(), "mobile", r["id"]))
            return r["id"], "expired"
        c.execute("UPDATE approvals SET status=?,decided_at=?,decided_by=? WHERE id=?", (status, utcnow(), "mobile", r["id"]))
        return r["id"], status


def decide_by_web(aid: str, approve: bool) -> dict:
    status = "approved" if approve else "rejected"
    with conn() as c:
        r = c.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()
        if not r:
            raise KeyError(aid)
        if r["status"] != "pending":
            raise ValueError(f"Change is {r['status']}, not pending")
        c.execute("UPDATE approvals SET status=?,decided_at=?,decided_by=? WHERE id=?", (status, utcnow(), "web", aid))
    return {"id": aid, "status": status}


async def notify_approval(ha: HomeAssistantClient, approval: dict, reason: str, integrations=None):
    pref = get_notification_preference("approvals")
    if not pref["enabled"]:
        return {"skipped": True, "reason": "Approval notifications are disabled"}
    diff_excerpt = approval["diff"][-1800:] if approval.get("diff") else "(không có diff)"
    msg = (
        f"🔐 Yêu cầu duyệt thay đổi\n"
        f"ID: {approval['id']}\n"
        f"Mức rủi ro: {approval['risk']}\n\n"
        f"{reason}\n\n"
        f"Diff rút gọn:\n{diff_excerpt}"
    )
    return await send_notification(
        ha,
        integrations,
        msg,
        title="HassMind · Yêu cầu duyệt",
        channel=pref["channel"],
        zalo_thread_id=pref["zalo_thread_id"],
        actions=[
            {"action": f"HASSMIND_APPROVE:{approval['approve_token']}", "title": "Duyệt"},
            {"action": f"HASSMIND_REJECT:{approval['reject_token']}", "title": "Từ chối", "destructive": True},
        ],
    )


async def apply_approval(ha: HomeAssistantClient, aid: str) -> dict:
    row = get_approval(aid, include_secrets=True)
    if not row:
        raise KeyError(aid)
    if row["status"] != "approved":
        raise PermissionError(f"change status is {row['status']}, not approved")
    current = await ha.config_get(row["kind"], row["target_id"])
    if canonical_hash(current) != row["old_hash"]:
        with conn() as c:
            c.execute("UPDATE approvals SET status='conflict',error=? WHERE id=?", ("Current config changed after proposal", aid))
        raise RuntimeError("Conflict: current config changed after proposal")

    try:
        await ha.config_set(row["kind"], row["target_id"], row["new_config"])
        verify = await ha.config_get(row["kind"], row["target_id"])
        if canonical_hash(verify) != canonical_hash(row["new_config"]):
            try:
                await ha.config_set(row["kind"], row["target_id"], row["old_config"])
                status = "auto_rolled_back"
            except Exception as rb:
                status = "verify_failed"
                raise RuntimeError(f"Verification mismatch; rollback also failed: {rb}")
            with conn() as c:
                c.execute("UPDATE approvals SET status=?,error=? WHERE id=?", (status, "Verification hash mismatch after apply", aid))
            raise RuntimeError("Verification mismatch after apply; old config restored")
        with conn() as c:
            c.execute("UPDATE approvals SET status='applied',applied_at=?,error=NULL WHERE id=?", (utcnow(), aid))
        return {"ok": True, "id": aid, "status": "applied"}
    except Exception as e:
        with conn() as c:
            c.execute("UPDATE approvals SET error=? WHERE id=?", (str(e), aid))
        raise


async def propose_rollback(ha: HomeAssistantClient, aid: str, reason: str, integrations=None) -> dict:
    row = get_approval(aid, include_secrets=True)
    if not row:
        raise KeyError(aid)
    if row["status"] != "applied":
        raise ValueError("Only applied changes can be rolled back")
    current = await ha.config_get(row["kind"], row["target_id"])
    rb = create_approval(row["kind"], row["target_id"], current, row["old_config"], f"Rollback {aid}: {reason}", parent_change_id=aid)
    await notify_approval(ha, rb, f"Rollback {aid}: {reason}", integrations)
    return {"id": rb["id"], "status": "pending", "risk": rb["risk"], "diff": rb["diff"]}
