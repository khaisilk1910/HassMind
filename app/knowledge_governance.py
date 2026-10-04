"""Human-reviewed Knowledge maintenance. This module never invokes the LLM or HA writes."""
from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from time import monotonic
from typing import Any

import yaml

from .db import conn, utcnow
from .observability import exception, get_logger, info
from .settings import settings
from . import rag

logger = get_logger("knowledge")
_lock = threading.RLock()
_scan_lock = asyncio.Lock()
_wake = asyncio.Event()
_BLOCKING_CODES = {"domain_conflict", "entity_conflict", "area_conflict"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_schema():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_control (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS knowledge_scans (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS knowledge_proposals (
          id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
          signature TEXT NOT NULL, payload TEXT NOT NULL, backup TEXT, decided_at TEXT, decided_by TEXT, error TEXT);
        CREATE INDEX IF NOT EXISTS idx_knowledge_proposals_status ON knowledge_proposals(status,created_at);
        CREATE TABLE IF NOT EXISTS knowledge_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, action TEXT NOT NULL,
          proposal_id TEXT, actor TEXT NOT NULL, details TEXT NOT NULL);
        """)


def _get(key, default=None):
    with conn() as c:
        row = c.execute("SELECT value FROM knowledge_control WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _set(key, value):
    with conn() as c:
        c.execute("INSERT INTO knowledge_control(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, _json(value)))


def audit(action, proposal_id=None, actor="system", details=None):
    with conn() as c:
        c.execute("INSERT INTO knowledge_audit(created_at,action,proposal_id,actor,details) VALUES(?,?,?,?,?)", (utcnow(), action, proposal_id, actor, _json(details or {})))
    info(logger, "knowledge_" + action, proposal_id=proposal_id, actor=actor)


def audit_log(limit=100):
    ensure_schema()
    with conn() as c:
        rows = c.execute("SELECT * FROM knowledge_audit ORDER BY id DESC LIMIT ?", (min(max(int(limit), 1), 500),)).fetchall()
    return [{**dict(r), "details": json.loads(r["details"])} for r in rows]


def monitor_config():
    ensure_schema()
    return _get("config", {"enabled": settings.knowledge_monitor_enabled, "scan_interval_seconds": settings.knowledge_scan_interval_seconds, "notify_enabled": settings.knowledge_notify_enabled})


def save_monitor_config(value, actor):
    with _lock:
        cfg = monitor_config()
        if set(value) - set(cfg):
            raise ValueError("Unknown Knowledge config option")
        cfg.update(value)
        if type(cfg["enabled"]) is not bool or type(cfg["notify_enabled"]) is not bool:
            raise ValueError("enabled and notify_enabled must be boolean")
        interval = cfg["scan_interval_seconds"]
        if type(interval) is not int or not 30 <= interval <= 86400:
            raise ValueError("scan_interval_seconds must be 30..86400")
        _set("config", cfg)
        audit("config_changed", actor=actor, details=cfg)
        _wake.set()
        return cfg


def _current_hash(path):
    target = rag.safe_knowledge_path(path)
    return _hash(_file_bytes(target)) if target.exists() else None


def _file_bytes(target):
    # Read at most the configured cap even if an external writer grows a file.
    with target.open("rb") as stream:
        data = stream.read(settings.knowledge_max_file_bytes + 1)
    if len(data) > settings.knowledge_max_file_bytes:
        raise ValueError("Knowledge file exceeds the configured size limit")
    return data


def _proposal_row(row):
    payload = json.loads(row["payload"])
    return {**payload, **{k: row[k] for k in ("id", "status", "created_at", "decided_at", "decided_by", "error")}}


def _proposal_summary(proposal):
    return {**proposal, "changes": [{k: v for k, v in change.items() if k not in {"new_content", "diff"}} for change in proposal["changes"]]}


def get_proposal(pid):
    ensure_schema()
    with conn() as c:
        row = c.execute("SELECT * FROM knowledge_proposals WHERE id=?", (pid,)).fetchone()
    if not row:
        raise KeyError(pid)
    return _proposal_row(row)


def list_proposals(limit=100):
    ensure_schema()
    with conn() as c:
        rows = c.execute("SELECT * FROM knowledge_proposals ORDER BY created_at DESC LIMIT ?", (min(max(int(limit), 1), 200),)).fetchall()
    return [_proposal_summary(_proposal_row(r)) for r in rows]


def create_proposal(changes, reason, *, kind="content", issues=None, fingerprint=None, actor="system"):
    """Store a concrete draft; not exported as an agent mutation tool."""
    with _lock:
        ensure_schema()
        if kind not in {"content", "reindex", "review"}:
            raise ValueError("Unsupported proposal kind")
        if kind == "content" and not changes:
            raise ValueError("Content proposal requires changes")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
            raise ValueError("A bounded reason is required")
        if len(changes) > 100:
            raise ValueError("Maximum 100 files per proposal")
        normalized, seen = [], set()
        total_bytes = 0
        for change in changes:
            path = str(change.get("path", ""))
            target = rag.safe_knowledge_path(path)
            path = target.relative_to(Path(settings.knowledge_dir).resolve()).as_posix()
            if path in seen:
                raise ValueError("Duplicate proposal path")
            seen.add(path)
            before_bytes = _file_bytes(target) if target.exists() else b""
            before = before_bytes.decode("utf-8-sig")
            expected = _hash(before_bytes) if target.exists() else None
            if "expected_hash" in change and change["expected_hash"] != expected:
                raise ValueError("Draft base is stale")
            operation = change.get("operation", "upsert")
            if operation not in {"upsert", "delete"}:
                raise ValueError("operation must be upsert or delete")
            after = change.get("new_content", "") if operation == "upsert" else ""
            if not isinstance(after, str) or len(after.encode("utf-8")) > settings.knowledge_max_file_bytes:
                raise ValueError("Proposal content too large or not text")
            total_bytes += len(before_bytes) + len(after.encode("utf-8"))
            if total_bytes > 16 * 1024 * 1024:
                raise ValueError("Maximum 16 MiB content per proposal")
            normalized.append({"path": path, "expected_hash": expected, "operation": operation, "new_content": after,
                "diff": "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile="a/"+path, tofile="b/"+path)),
                "new_hash": _hash(after.encode("utf-8")) if operation == "upsert" else None})
        fingerprint = fingerprint or rag.inspect_knowledge()["fingerprint"]
        payload = {"kind": kind, "reason": reason, "changes": normalized, "issues": issues or [], "fingerprint": fingerprint}
        signature = _hash(_json(payload).encode("utf-8"))
        with conn() as c:
            row = c.execute("SELECT * FROM knowledge_proposals WHERE signature=? AND (status='pending' OR (status='rejected' AND ?='system')) ORDER BY created_at DESC LIMIT 1", (signature, actor)).fetchone()
            if row:
                return _proposal_row(row)
            pid = uuid.uuid4().hex
            c.execute("INSERT INTO knowledge_proposals(id,status,created_at,signature,payload) VALUES(?,'pending',?,?,?)", (pid, utcnow(), signature, _json(payload)))
        audit("proposal_created", pid, actor, {"kind": kind, "paths": [x["path"] for x in normalized]})
        return get_proposal(pid)


def _dry_run_unlocked(proposal):
    issues = []
    blockers = []

    def add_issue(issue, *, blocking=False):
        item = dict(issue)
        item["blocking"] = bool(blocking)
        issues.append(item)
        if blocking:
            blockers.append(item)

    def conflict_touches_changed_path(issue, changed_paths):
        if issue.get("path") in changed_paths:
            return True
        for key in ("definitions", "members"):
            for ref in issue.get(key) or []:
                if isinstance(ref, dict) and ref.get("path") in changed_paths:
                    return True
        area_definition = issue.get("area_definition")
        return isinstance(area_definition, dict) and area_definition.get("path") in changed_paths

    snapshot = rag.inspect_knowledge()
    if proposal["status"] != "pending":
        add_issue({"code": "proposal_status", "severity": "error", "message": "Proposal is not pending"}, blocking=True)
    if snapshot["fingerprint"] != proposal["fingerprint"]:
        add_issue({"code": "stale_proposal", "severity": "error", "message": "Knowledge changed since this draft; scan/create a fresh proposal"}, blocking=True)
    if proposal["kind"] == "review":
        add_issue({"code": "manual_correction_required", "severity": "warning", "message": "Review proposals are findings only. Create a concrete corrected draft before approval."}, blocking=True)
    changed_paths = {c["path"] for c in proposal["changes"]}
    prospective = [r for r in snapshot["records"] if r["path"] not in changed_paths]

    # Existing hard parse/read errors always block because a successful apply must
    # finish with a healthy index. Cross-record ambiguity is warning-level and
    # blocks only a content draft that actually touches the conflicting records.
    for diagnostic in snapshot["diagnostics"]:
        if diagnostic.get("path") in changed_paths:
            continue
        is_error = diagnostic.get("severity") == "error"
        if is_error or proposal["kind"] in {"reindex", "review"}:
            add_issue(diagnostic, blocking=is_error)

    for change in proposal["changes"]:
        try:
            if _current_hash(change["path"]) != change["expected_hash"]:
                add_issue({"code": "stale_file", "severity": "error", "path": change["path"], "message": "File hash no longer matches the proposal base"}, blocking=True)
            if change["operation"] == "upsert":
                parsed = rag.parse_knowledge_text(change["path"], change["new_content"])
                for diagnostic in parsed["diagnostics"]:
                    blocking = diagnostic.get("severity") == "error" or diagnostic.get("code") in _BLOCKING_CODES
                    add_issue(diagnostic, blocking=blocking)
                prospective.extend(parsed["records"])
        except (ValueError, OSError, UnicodeError) as exc:
            add_issue({"code": "invalid_change", "severity": "error", "path": change["path"], "message": str(exc)}, blocking=True)

    if proposal["kind"] == "content":
        for diagnostic in rag.validate_catalog(prospective):
            is_error = diagnostic.get("severity") == "error"
            is_touched_conflict = diagnostic.get("code") in _BLOCKING_CODES and conflict_touches_changed_path(diagnostic, changed_paths)
            # Keep unrelated ambiguity visible but do not prevent an otherwise
            # safe draft from being applied. It remains unsafe for entity control
            # until corrected, as enforced by the registry resolver.
            add_issue(diagnostic, blocking=is_error or is_touched_conflict)

    # Re-index proposals contain no content mutation. Warning-level registry
    # ambiguity is intentionally reviewable but not an index failure; re-indexing
    # is allowed so the current files can become the active searchable catalog.
    return {"id": proposal["id"], "valid": not blockers, "issues": issues, "blocking_issues": blockers,
            "warning_count": sum(1 for i in issues if not i.get("blocking")),
            "changes": proposal["changes"], "kind": proposal["kind"]}


def dry_run(pid):
    with _lock:
        result = _dry_run_unlocked(get_proposal(pid))
        audit("dry_run", pid, details={"valid": result["valid"], "issues": result["issues"]})
        return result


def _write(path, data: bytes | None):
    target = rag.safe_knowledge_path(path)
    if data is None:
        if target.exists():
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after mkdir; root/path parents cannot be replaced by symlinks.
    target = rag.safe_knowledge_path(path)
    fd, temp = tempfile.mkstemp(prefix=".hassmind-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _restore(backup, *, expected=None, written=None):
    for item in reversed(backup):
        if expected is not None and _current_hash(item["path"]) != expected[item["path"]]:
            raise RuntimeError("Concurrent edit prevents restore: " + item["path"])
        _write(item["path"], base64.b64decode(item["content"]) if item["content"] is not None else None)
        if written is not None:
            written.append(item)


def _healthy_index():
    index = rag.reindex_knowledge()
    if index.get("errors") or index.get("retained_previous"):
        raise RuntimeError("Knowledge re-index failed; inspect index diagnostics")
    return index


def approve(pid, actor):
    """Called only after an authenticated admin approval, never a model/tool action."""
    with _lock:
        proposal = get_proposal(pid)
        check = _dry_run_unlocked(proposal)
        if not check["valid"]:
            audit("approve_blocked", pid, actor, {"issues": check["issues"]})
            raise ValueError(_json(check["issues"]))
        backup = []
        for change in proposal["changes"]:
            target = rag.safe_knowledge_path(change["path"])
            backup.append({"path": change["path"], "content": base64.b64encode(_file_bytes(target)).decode("ascii") if target.exists() else None, "before_hash": change["expected_hash"], "after_hash": change["new_hash"]})
        with conn() as c:
            c.execute("BEGIN IMMEDIATE")
            updated = c.execute("UPDATE knowledge_proposals SET status='applying',backup=?,decided_at=?,decided_by=? WHERE id=? AND status='pending'", (_json(backup), utcnow(), actor, pid))
            if updated.rowcount != 1:
                raise ValueError("Proposal was already decided")
        written = []
        try:
            for change, original in zip(proposal["changes"], backup):
                # Recheck at each write so a concurrent operator edit is never overwritten.
                if _current_hash(change["path"]) != change["expected_hash"]:
                    raise ValueError("File changed during apply")
                _write(change["path"], change["new_content"].encode("utf-8") if change["operation"] == "upsert" else None)
                written.append(original)
                if _current_hash(change["path"]) != change["new_hash"]:
                    raise RuntimeError("Post-write hash verification failed")
            index = _healthy_index()
            with conn() as c:
                c.execute("UPDATE knowledge_proposals SET status='applied',error=NULL WHERE id=?", (pid,))
            audit("applied", pid, actor, {"kind": proposal["kind"], "paths": [b["path"] for b in backup]})
            return {**get_proposal(pid), "index": index}
        except Exception as exc:
            recovery_error = None
            try:
                for item in written:
                    if _current_hash(item["path"]) != item["after_hash"]:
                        raise RuntimeError("Concurrent edit prevents automatic restore")
                _restore(written, expected={i["path"]: i["after_hash"] for i in written})
                _healthy_index()
            except Exception as rb:
                recovery_error = str(rb)
            with conn() as c:
                c.execute("UPDATE knowledge_proposals SET status=?,error=? WHERE id=?", ("recovery_required" if recovery_error else "failed", str(exc)+(('; restore: '+recovery_error) if recovery_error else ''), pid))
            audit("apply_failed", pid, actor, {"error_type": type(exc).__name__, "recovery_required": bool(recovery_error)})
            raise


def reject(pid, actor):
    with _lock:
        proposal = get_proposal(pid)
        if proposal["status"] != "pending":
            raise ValueError("Only a pending proposal can be rejected")
        with conn() as c:
            c.execute("UPDATE knowledge_proposals SET status='rejected',decided_at=?,decided_by=? WHERE id=? AND status='pending'", (utcnow(), actor, pid))
        audit("rejected", pid, actor)
        return get_proposal(pid)


def rollback(pid, actor):
    with _lock:
        proposal = get_proposal(pid)
        if proposal["status"] != "applied" or proposal["kind"] != "content":
            raise ValueError("Only applied content proposals have a rollback")
        with conn() as c:
            backup = json.loads(c.execute("SELECT backup FROM knowledge_proposals WHERE id=?", (pid,)).fetchone()[0])
        for item in backup:
            if _current_hash(item["path"]) != item["after_hash"]:
                audit("rollback_blocked", pid, actor, {"path": item["path"]})
                raise ValueError("Rollback would overwrite a newer file; create a reviewed draft instead")
        current = [{**x, "content": base64.b64encode(_file_bytes(rag.safe_knowledge_path(x["path"]))).decode("ascii") if rag.safe_knowledge_path(x["path"]).exists() else None} for x in backup]
        with conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("UPDATE knowledge_proposals SET status='rolling_back' WHERE id=? AND status='applied'", (pid,)).rowcount != 1:
                raise ValueError("Proposal already being rolled back")
        restored = []
        try:
            _restore(backup, expected={i["path"]: i["after_hash"] for i in backup}, written=restored)
            index = _healthy_index()
            with conn() as c:
                c.execute("UPDATE knowledge_proposals SET status='rolled_back',error=NULL WHERE id=?", (pid,))
            audit("rolled_back", pid, actor)
            return {**get_proposal(pid), "index": index}
        except Exception as exc:
            try:
                compensate = [i for i in current if i["path"] in {r["path"] for r in restored}]
                _restore(compensate, expected={i["path"]: i["before_hash"] for i in compensate})
                _healthy_index()
                status = "applied"
            except Exception:
                status = "recovery_required"
            with conn() as c:
                c.execute("UPDATE knowledge_proposals SET status=?,error=? WHERE id=?", (status, str(exc), pid))
            audit("rollback_failed", pid, actor, {"error_type": type(exc).__name__})
            raise


def recover_interrupted():
    """Recover a crash journal only when current bytes still belong to this operation."""
    with _lock:
        ensure_schema()
        with conn() as c:
            rows = c.execute("SELECT * FROM knowledge_proposals WHERE status IN ('applying','rolling_back')").fetchall()
        for row in rows:
            backup = json.loads(row["backup"] or "[]")
            try:
                expected = {}
                for item in backup:
                    current_hash = _current_hash(item["path"])
                    if current_hash not in {item["before_hash"], item["after_hash"]}:
                        raise ValueError("Interrupted operation has a concurrent external edit")
                    # Validate the same digest used by the per-file restore.
                    # Re-reading here could accidentally accept an operator edit
                    # made after validation and overwrite it during recovery.
                    expected[item["path"]] = current_hash
                _restore(backup, expected=expected)
                _healthy_index()
                status, error = "rolled_back", "Recovered interrupted operation at startup"
            except Exception as exc:
                status, error = "recovery_required", str(exc)
            with conn() as c:
                c.execute("UPDATE knowledge_proposals SET status=?,error=? WHERE id=?", (status, error, row["id"]))
            audit("startup_recovery", row["id"], details={"status": status})


def _clean_catalog(data):
    changed = False
    def clean(value):
        nonlocal changed
        if isinstance(value, list):
            for child in value:
                clean(child)
        elif isinstance(value, dict):
            eid = value.get("entity_id")
            if isinstance(eid, str) and "." in eid:
                domain = eid.split(".", 1)[0]
                kind = value.get("kind", value.get("type", "entity"))
                if domain in {"scene", "script"} or kind in {"scene", "script"}:
                    cleaned = dict(value)
                    for key in {"state", "last_changed", "last_updated", "last_reported", "context", "current_state"} & cleaned.keys():
                        cleaned.pop(key)
                else:
                    cleaned, removed = rag.strip_realtime_fields(value)
                if cleaned != value:
                    value.clear()
                    value.update(cleaned)
                    changed = True
                if value.get("domain") != domain:
                    value["domain"] = domain
                    changed = True
            # Only traverse catalog sections, never instructions/preferred_actions or prose.
            for key in ("entities", "scenes", "scripts", "records"):
                if key in value:
                    clean(value[key])
    clean(data)
    return changed


def _ha_issues(records, entities, areas, devices):
    issues = []
    live = {e["entity_id"]: e for e in entities if e.get("entity_id")}
    device_areas = {d["id"]: d.get("area_id") for d in devices if d.get("id")}
    area_map = {a["area_id"]: a for a in areas if a.get("area_id")}
    for record in records:
        eid = record.get("entity_id")
        if not eid:
            continue
        ha_record = live.get(eid)
        if ha_record is None:
            issues.append({"code": "unresolved_entity", "severity": "warning", "path": record["path"], "entity_id": eid, "message": "Entity is absent from the current HA entity registry; confirm/remove mapping manually"})
            continue
        if ha_record.get("disabled_by"):
            issues.append({"code": "disabled_entity", "severity": "warning", "path": record["source"], "entity_id": eid, "message": "Entity is disabled in HA"})
        area_id = ha_record.get("area_id") or device_areas.get(ha_record.get("device_id"))
        known_area = record.get("area_id") or record.get("area")
        if known_area and area_id and area_id in area_map:
            accepted = {rag.normalize(area_id), rag.normalize(area_map[area_id].get("name", ""))}
            if rag.normalize(known_area) not in accepted:
                issues.append({"code": "ha_area_mismatch", "severity": "warning", "path": record["source"], "entity_id": eid, "ha_area": area_id, "message": "Knowledge area differs from the current HA registry; review mapping manually"})
    return issues


def _scan_store(snapshot, ha_issues, ha_checked, ha_error, actor):
    with _lock:
        ensure_schema()
        previous = _get("manifest", {})
        manifest = {f["path"]: f.get("sha256") for f in snapshot["files"]}
        changes = {"added": sorted(set(manifest)-set(previous)), "modified": sorted(k for k in manifest.keys() & previous.keys() if manifest[k] != previous[k]), "deleted": sorted(set(previous)-set(manifest))}
        issues = snapshot["diagnostics"] + ha_issues
        proposals = []
        with conn() as c:
            obsolete = [dict(r) for r in c.execute("SELECT id,payload FROM knowledge_proposals WHERE status='pending'").fetchall() if json.loads(r["payload"])["fingerprint"] != snapshot["fingerprint"]]
            for old in obsolete:
                c.execute("UPDATE knowledge_proposals SET status='stale',error='Knowledge changed; create a fresh draft' WHERE id=? AND status='pending'", (old["id"],))
        for old in obsolete:
            audit("proposal_stale", old["id"])
        signature = _hash(_json({"fingerprint": snapshot["fingerprint"], "issues": issues}).encode("utf-8"))
        new_findings = signature != _get("last_findings_signature")
        if any(changes.values()):
            proposals.append(create_proposal([], "Review file changes and refresh the Knowledge index: "+_json(changes), kind="reindex", fingerprint=snapshot["fingerprint"]))
        for file in snapshot["files"]:
            if file.get("status") == "error" or Path(file["path"]).suffix.lower() not in {".yaml", ".yml", ".json"}:
                continue
            try:
                text = rag.safe_knowledge_path(file["path"]).read_text(encoding="utf-8-sig")
                parsed = json.loads(text) if file["path"].lower().endswith(".json") else yaml.safe_load(text)
                if _clean_catalog(parsed):
                    after = json.dumps(parsed, ensure_ascii=False, indent=2)+"\n" if file["path"].lower().endswith(".json") else yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
                    proposals.append(create_proposal([{"path": file["path"], "expected_hash": file["sha256"], "new_content": after}], "Remove realtime snapshots and align domain with entity_id. YAML formatting/comments may change; review the full diff before approving.", fingerprint=snapshot["fingerprint"]))
            except (ValueError, OSError, UnicodeError, yaml.YAMLError):
                continue
        if issues and new_findings:
            proposals.append(create_proposal([], "Knowledge findings require manual review; no entity rename or alias change is guessed automatically", kind="review", issues=issues, fingerprint=snapshot["fingerprint"]))
        scan = {"id": uuid.uuid4().hex, "created_at": utcnow(), "scanned_at": snapshot["scanned_at"], "changes": changes, "issues": issues, "proposals": [_proposal_summary(p) for p in proposals], "ha_checked": ha_checked, "ha_error": ha_error, "fingerprint": snapshot["fingerprint"], "new_findings": new_findings}
        with conn() as c:
            c.execute("INSERT INTO knowledge_scans(id,created_at,payload) VALUES(?,?,?)", (scan["id"], scan["created_at"], _json(scan)))
            c.execute("DELETE FROM knowledge_scans WHERE id NOT IN (SELECT id FROM knowledge_scans ORDER BY created_at DESC LIMIT 100)")
        _set("manifest", manifest)
        _set("last_findings_signature", signature)
        _set("latest_scan", scan)
        audit("scanned", actor=actor, details={"changes": changes, "issue_count": len(issues), "proposal_count": len(proposals), "ha_checked": ha_checked})
        return scan


async def scan_knowledge(ha=None, actor="system"):
    async with _scan_lock:
        snapshot = await asyncio.to_thread(rag.inspect_knowledge)
        ha_issues, ha_checked, ha_error = [], False, None
        if ha is not None:
            try:
                entities, areas, devices = await asyncio.wait_for(asyncio.gather(ha.entity_registry(), ha.ws_command({"type": "config/area_registry/list"}), ha.ws_command({"type": "config/device_registry/list"})), timeout=30)
                ha_issues = _ha_issues(snapshot["records"], entities, areas, devices)
                ha_checked = True
            except Exception as exc:
                ha_error = type(exc).__name__ + ": Home Assistant registry check unavailable; unresolved/stale checks deferred"
        scan = await asyncio.to_thread(_scan_store, snapshot, ha_issues, ha_checked, ha_error, actor)
        cfg = monitor_config()
        if ha is not None and cfg["notify_enabled"] and scan["new_findings"] and (scan["proposals"] or scan["issues"]):
            try:
                result = await ha.notify(f"Knowledge: {len(scan['issues'])} vấn đề, {len(scan['proposals'])} đề xuất. Mở Web Admin → Knowledge → Review changes để xem diff và Approve/Reject. Chưa thay đổi nội dung.", title="HassMind · Knowledge")
                audit("notification_skipped" if isinstance(result, dict) and result.get("skipped") else "notification_sent", details={"scan_id": scan["id"]})
            except Exception as exc:
                scan["notification_error"] = type(exc).__name__
                _set("latest_scan", scan)
                audit("notification_failed", details={"scan_id": scan["id"], "error_type": type(exc).__name__})
        return scan


def knowledge_status():
    ensure_schema()
    with conn() as c:
        pending = c.execute("SELECT COUNT(*) FROM knowledge_proposals WHERE status='pending'").fetchone()[0]
        recovery = c.execute("SELECT COUNT(*) FROM knowledge_proposals WHERE status='recovery_required'").fetchone()[0]
    return {"index": rag.index_status(), "monitor": monitor_config(), "latest_scan": _get("latest_scan"), "pending_count": pending, "recovery_required": recovery}


async def monitor_loop(stop, ha):
    next_scan = 0.0
    while not stop.is_set():
        cfg = monitor_config()
        try:
            if cfg["enabled"] and (monotonic() >= next_scan or _wake.is_set()):
                _wake.clear()
                await scan_knowledge(ha)
                next_scan = monotonic() + cfg["scan_interval_seconds"]
        except asyncio.CancelledError:
            raise
        except Exception:
            exception(logger, "knowledge_monitor_failed")
            next_scan = monotonic() + cfg["scan_interval_seconds"]
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
