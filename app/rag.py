"""Static local Knowledge registry. Current Home Assistant state is never indexed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import threading
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import yaml

from .db import conn, utcnow
from .observability import get_logger, info
from .settings import settings
from .time_utils import parse_datetime

logger = get_logger("knowledge")
ALLOWED = {".md", ".txt", ".yaml", ".yml", ".json"}
KINDS = {"entity", "area", "scene", "script", "reference", "rules", "procedures"}
GROUPS = {"entities": "entity", "areas": "area", "scenes": "scene", "scripts": "script",
          "references": "reference", "rules": "rules", "procedures": "procedures",
          "entity": "entity", "area": "area", "scene": "scene", "script": "script",
          "reference": "reference", "rule": "rules", "procedure": "procedures"}
ENTITY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
REALTIME_FIELDS = {"state", "states", "current_state", "last_changed", "last_updated",
                   "last_reported", "context", "current_temperature", "current_humidity",
                   "temperature", "humidity", "battery", "battery_level", "power", "energy",
                   "brightness", "rgb_color", "hs_color", "color_temp", "color_temp_kelvin",
                   "hvac_action", "hvac_mode", "fan_mode", "percentage", "volume_level",
                   "media_position", "media_duration", "media_title", "availability",
                   "available", "is_on", "online", "value", "last_seen"}
STATIC_SECTIONS = {"preferred_actions", "actions", "service_data", "defaults", "presets", "capabilities", "static_limits", "parameters", "configuration"}
_INDEX_LOCK = threading.RLock()


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold().replace("đ", "d"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def chunks(text: str, size: int = 1400, overlap: int = 200) -> list[str]:
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk size must be positive and overlap smaller than size")
    text, out, i = text.strip(), [], 0
    while i < len(text):
        out.append(text[i:i + size])
        if i + size >= len(text):
            break
        i += size - overlap
    return out


def knowledge_root(create: bool = False) -> Path:
    raw = Path(settings.knowledge_dir).absolute()
    if raw.is_symlink() or getattr(raw, "is_junction", lambda: False)():
        raise ValueError("Knowledge root must not be a symlink or junction")
    if raw.exists() and not raw.is_dir():
        raise ValueError("Knowledge root must be a directory")
    if create:
        raw.mkdir(parents=True, exist_ok=True)
    return raw.resolve()


def safe_knowledge_path(relative: str, must_exist: bool = False) -> Path:
    """Validate a portable relative content path for proposal reads and writes."""
    if not isinstance(relative, str) or not relative or len(relative) > 512 or "\x00" in relative:
        raise ValueError("Invalid Knowledge path")
    if "\\" in relative or ":" in relative:
        raise ValueError("Knowledge paths must use relative forward slashes")
    portable = PurePosixPath(relative)
    if portable.is_absolute() or any(p in {".", ".."} or p.startswith(".") for p in portable.parts):
        raise ValueError("Knowledge path traversal and hidden paths are forbidden")
    if portable.suffix.lower() not in ALLOWED:
        raise ValueError("Unsupported Knowledge file extension")
    root, current = knowledge_root(), knowledge_root()
    for part in portable.parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError("Knowledge symlinks and junctions are forbidden")
    if not current.resolve().is_relative_to(root):
        raise ValueError("Knowledge path escapes configured directory")
    if must_exist and not current.is_file():
        raise ValueError("Knowledge file does not exist")
    return current


def _diag(code: str, message: str, path: str, *, severity: str = "warning", **extra) -> dict:
    return {"code": code, "severity": severity, "path": path, "message": message, **extra}


def _aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ValueError("aliases must be a string or a list of strings")
    return list(dict.fromkeys(x.strip() for x in value if x.strip()))


def _remove_live(value: Any, removed: list[str], prefix: str = "") -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key)
            location = f"{prefix}.{name}" if prefix else name
            if name.casefold() in REALTIME_FIELDS:
                removed.append(location)
            elif name.casefold() in STATIC_SECTIONS:
                # Desired service parameters and capability schemas are static.
                out[name] = item
            else:
                out[name] = _remove_live(item, removed, location)
        return out
    if isinstance(value, list):
        return [_remove_live(v, removed, prefix) for v in value]
    return value


def _record(raw: Any, kind: str, path: str, index: int, diagnostics: list[dict], body: str = "", location: str | None = None) -> dict | None:
    if isinstance(raw, str):
        raw = {"name": raw, "text": raw}
    if not isinstance(raw, dict):
        diagnostics.append(_diag("schema_error", "Registry record must be an object", path, severity="error"))
        return None
    legacy_type = str(raw.get("type", "")).casefold()
    declared = str(raw.get("kind", legacy_type if legacy_type in GROUPS or legacy_type in KINDS else kind)).casefold()
    kind = GROUPS.get(declared, declared)
    if kind not in KINDS:
        diagnostics.append(_diag("schema_error", f"Unsupported record kind: {kind}", path, severity="error", location=location))
        return None
    identity = str(raw.get("id", raw.get("entity_id", raw.get("area_id", f"{kind}-{index}"))))
    record_id = f"{path}#{kind}:{identity}:{index}"
    cleaned = dict(raw)
    if kind in {"entity", "scene", "script"}:
        removed: list[str] = []
        if kind == "entity":
            cleaned = _remove_live(cleaned, removed)
        else:
            # Scene/script payloads describe desired settings, e.g. brightness
            # and temperature. They are static instructions, not live snapshots.
            for field in ("state", "last_changed", "last_updated", "last_reported", "context", "current_state"):
                if field in cleaned:
                    removed.append(field)
                    cleaned.pop(field)
        if removed:
            diagnostics.append(_diag("realtime_fields", "Live state fields excluded; read current state from Home Assistant", path,
                                     record_id=record_id, entity_id=raw.get("entity_id", raw.get("id")), fields=removed, location=location))
    entity_id = cleaned.get("entity_id", cleaned.get("id") if kind in {"entity", "scene", "script"} else None)
    if entity_id is not None:
        entity_id = str(entity_id).strip()
    if kind in {"entity", "scene", "script"} and (not entity_id or not ENTITY_RE.fullmatch(entity_id)):
        diagnostics.append(_diag("schema_error", "Entity, scene and script require a valid entity_id", path,
                                 severity="error", record_id=record_id, location=location))
        return None
    declared_domain = cleaned.get("domain")
    if isinstance(declared_domain, (dict, list)):
        diagnostics.append(_diag("schema_error", "domain must be text", path, severity="error", record_id=record_id, location=location))
        return None
    domain = str(declared_domain or (entity_id.split(".", 1)[0] if entity_id else "")).strip()
    issues: list[str] = []
    if entity_id and domain != entity_id.split(".", 1)[0]:
        expected_domain = entity_id.split(".", 1)[0]
        issues.append("domain_conflict")
        diagnostics.append(_diag("domain_conflict", f"domain '{domain}' disagrees with entity_id prefix '{expected_domain}'", path,
                                 record_id=record_id, entity_id=entity_id, declared_domain=domain,
                                 expected_domain=expected_domain, location=location))
        domain = expected_domain
    if kind in {"scene", "script"} and domain != kind:
        issues.append("domain_conflict")
        diagnostics.append(_diag("domain_conflict", f"A {kind} record must use the {kind} domain", path,
                                 record_id=record_id, entity_id=entity_id, declared_domain=domain,
                                 expected_domain=kind, location=location))
    try:
        aliases = _aliases(cleaned.get("aliases", cleaned.get("alias")))
    except ValueError as exc:
        diagnostics.append(_diag("schema_error", str(exc), path, severity="error", record_id=record_id, location=location))
        return None
    name = cleaned.get("name", cleaned.get("friendly_name", cleaned.get("title", identity)))
    area = cleaned.get("area", "")
    area_id = cleaned.get("area_id", cleaned.get("id", "") if kind == "area" else "")
    if isinstance(area, dict):
        area_id, area = area.get("id", area_id), area.get("name", area.get("id", area_id))
    if any(isinstance(x, (dict, list)) for x in (name, area_id, area)):
        diagnostics.append(_diag("schema_error", "name, area and area_id must be text", path, severity="error", record_id=record_id, location=location))
        return None
    reserved = {"kind", "type", "entity_id", "id", "name", "friendly_name", "title", "alias", "aliases", "area", "area_id", "domain", "source"}
    metadata = json.loads(json.dumps({str(k): v for k, v in cleaned.items() if k not in reserved},
                                     ensure_ascii=False, default=str, allow_nan=False))
    source = str(cleaned.get("source") or path)
    content = str(cleaned.get("text", cleaned.get("content", cleaned.get("description", ""))))
    # Canonical content excludes stripped live fields, including original YAML.
    text = json.dumps({"kind": kind, "entity_id": entity_id, "name": str(name), "aliases": aliases,
                       "area": str(area), "area_id": str(area_id), "domain": domain, **metadata},
                      ensure_ascii=False, default=str)
    if body:
        text += "\n" + body
    return {"record_id": record_id, "kind": kind, "entity_id": entity_id, "name": str(name),
            "aliases": aliases, "area": str(area), "area_id": str(area_id), "domain": domain,
            "source": source, "path": path, "text": text, "preview": (content or body or text)[:360],
            "metadata": metadata, "issues": issues, "location": location or f"record[{index}]"}


def _members(value: Any, kind: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if any(k in value for k in ("entity_id", "name", "text", "content", "description", "aliases", "alias")):
            return [value]
        return [{"id": key, **item} if isinstance(item, dict) else {"id": key, "text": str(item)}
                for key, item in value.items()]
    if isinstance(value, str):
        return [value]
    raise ValueError(f"{kind} collection must be a list, object or text")


def _document_defaults(data: Any, diagnostics: list[dict], path: str) -> tuple[dict, dict[str, list[str]]]:
    """Per-area documents can declare area/domain/source once and aliases by ID."""
    defaults, alias_map = {}, {}
    if not isinstance(data, dict) or not any(g in data for g in ("entities", "scenes", "scripts")):
        return defaults, alias_map
    area = data.get("area")
    if isinstance(area, str):
        defaults["area"] = area
    elif isinstance(area, dict) and any(k in area for k in ("id", "area_id", "name")):
        defaults["area"] = area.get("name", area.get("id", area.get("area_id", "")))
        defaults["area_id"] = area.get("id", area.get("area_id", ""))
    for key in ("area_id", "domain", "source"):
        if key in data and not isinstance(data[key], (dict, list)):
            defaults[key] = data[key]
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict):
        diagnostics.append(_diag("schema_warning", "Document aliases should map entity IDs to alias lists or aliases to entity IDs", path))
        return defaults, alias_map
    for key, value in aliases.items():
        if ENTITY_RE.fullmatch(str(key)):
            alias_map.setdefault(str(key), []).extend(_aliases(value))
        else:
            targets = [value] if isinstance(value, str) else value
            if not isinstance(targets, list) or any(not isinstance(t, str) or not ENTITY_RE.fullmatch(t) for t in targets):
                raise ValueError("Document alias values must contain valid entity IDs")
            for target in targets:
                alias_map.setdefault(target, []).append(str(key))
    return defaults, alias_map


def parse_knowledge_text(path: str, text: str) -> dict:
    """Parse candidate content without touching files, for proposal validation."""
    diagnostics: list[dict] = []
    body = ""
    structured = Path(path).suffix.lower() in {".yaml", ".yml", ".json"}
    try:
        if Path(path).suffix.lower() == ".json":
            data = json.loads(text)
        elif structured:
            data = yaml.safe_load(text)
        elif text.startswith("---\n") or text.startswith("---\r\n"):
            parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
            if len(parts) != 3:
                raise ValueError("Unclosed Markdown YAML frontmatter")
            data, body, structured = yaml.safe_load(parts[1]), parts[2].strip(), True
        else:
            data = None
        raw_records: list[tuple[Any, str, str]] = []
        is_registry = False
        def semantic(value):
            return isinstance(value, dict) and ("kind" in value or "entity_id" in value
                   or str(value.get("type", "")).casefold() in GROUPS)
        def located_members(value, kind, base):
            if isinstance(value, list):
                return [(item, kind, f"{base}[{i}]") for i, item in enumerate(value)]
            if isinstance(value, dict):
                if any(k in value for k in ("entity_id", "name", "text", "content", "description", "aliases", "alias")):
                    return [(value, kind, base)]
                out = []
                for key, item in value.items():
                    member = {"id": key, **item} if isinstance(item, dict) else {"id": key, "text": str(item)}
                    out.append((member, kind, f'{base}[{json.dumps(str(key), ensure_ascii=False)}]'))
                return out
            if isinstance(value, str):
                return [(value, kind, base)]
            raise ValueError(f"{kind} collection must be a list, object or text")
        if semantic(data):
            is_registry = True
            raw_records = [(data, "entity" if "entity_id" in data else "reference", "$")]
        elif isinstance(data, dict) and any(k in GROUPS for k in data):
            is_registry = True
            for group, value in data.items():
                if group in GROUPS:
                    raw_records.extend(located_members(value, GROUPS[group], group))
        elif isinstance(data, dict) and data and all(ENTITY_RE.fullmatch(str(k)) for k in data):
            is_registry = True
            raw_records = located_members(data, "entity", "entities")
        elif isinstance(data, list) and any(semantic(v) for v in data):
            is_registry = True
            raw_records = [(v, "entity" if isinstance(v, dict) and "entity_id" in v else "reference", f"[{i}]") for i, v in enumerate(data)]
        if len(raw_records) > 10000:
            raise ValueError("File exceeds maximum 10000 registry records")
        if is_registry and isinstance(data, dict) and "schema_version" in data and str(data["schema_version"]) not in {"1", "1.0"}:
            raise ValueError("Unsupported registry schema_version; supported version is 1")
        defaults, alias_map = _document_defaults(data, diagnostics, path)
        records = []
        if is_registry:
            for i, (raw, kind, location) in enumerate(raw_records):
                if kind in {"entity", "scene", "script"} and isinstance(raw, dict):
                    raw = {**defaults, **raw}
                    entity_id = str(raw.get("entity_id", raw.get("id", "")))
                    if entity_id in alias_map:
                        raw["aliases"] = _aliases(raw.get("aliases", raw.get("alias"))) + alias_map[entity_id]
                result = _record(raw, kind, path, i, diagnostics, body, location)
                if result:
                    records.append(result)
            known_ids = {r["entity_id"] for r in records if r["entity_id"]}
            for entity_id in alias_map.keys() - known_ids:
                diagnostics.append(_diag("unresolved_alias", "Document alias targets an entity absent from this document", path, entity_id=entity_id))
        elif text.strip():
            for i, part in enumerate(chunks(text)):
                records.append({"record_id": f"{path}#reference:{i}", "kind": "reference", "entity_id": None,
                                "name": Path(path).stem, "aliases": [], "area": "", "area_id": "", "domain": "",
                                "source": path, "path": path, "text": part, "preview": part[:360],
                                "metadata": {"legacy": True}, "issues": [], "location": f"chunk[{i}]"})
        return {"records": records, "diagnostics": diagnostics}
    except (ValueError, TypeError, yaml.YAMLError, RecursionError) as exc:
        return {"records": [], "diagnostics": [_diag("schema_error", str(exc)[:500], path, severity="error")]}


def _conflict_ref(record: dict) -> dict:
    return {"path": record.get("path", ""), "location": record.get("location", ""),
            "record_id": record.get("record_id", ""), "entity_id": record.get("entity_id"),
            "name": record.get("name", ""), "area": record.get("area", ""),
            "area_id": record.get("area_id", ""), "domain": record.get("domain", ""),
            "aliases": list(record.get("aliases") or [])}


def _cross_validate(records: list[dict]) -> list[dict]:
    diagnostics, aliases, alias_labels, entities, areas, area_labels, area_label_text = [], {}, {}, {}, {}, {}, {}
    for r in records:
        if r["kind"] == "area":
            for label in [r["area_id"], r["name"], *r["aliases"]]:
                normalized = normalize(label)
                if normalized:
                    area_labels.setdefault(normalized, []).append(r)
                    area_label_text.setdefault(normalized, set()).add(str(label))
            if r["area_id"]:
                areas[normalize(r["area_id"])] = r
        if r["entity_id"] and r["kind"] in {"entity", "scene", "script"}:
            entities.setdefault(r["entity_id"], []).append(r)
            for alias in r["aliases"]:
                normalized = normalize(alias)
                if normalized:
                    aliases.setdefault(normalized, []).append(r)
                    alias_labels.setdefault(normalized, set()).add(str(alias))
    for entity_id, definitions in entities.items():
        signatures = {(normalize(r["name"]), normalize(r["area_id"] or r["area"]), r["domain"]) for r in definitions}
        if len(signatures) > 1:
            for r in definitions:
                r["issues"].append("entity_conflict")
            field_values = {
                "name": {normalize(r["name"]) for r in definitions},
                "area": {normalize(r["area_id"] or r["area"]) for r in definitions},
                "domain": {r["domain"] for r in definitions},
            }
            conflict_fields = [field for field, values in field_values.items() if len(values) > 1]
            refs = [_conflict_ref(r) for r in definitions]
            diagnostics.append(_diag(
                "entity_conflict",
                f"Entity '{entity_id}' has conflicting definitions in {len(definitions)} locations; differing fields: {', '.join(conflict_fields)}",
                definitions[0]["path"], entity_id=entity_id, location=definitions[0].get("location"),
                conflict_fields=conflict_fields, definitions=refs))
    for alias, members in aliases.items():
        if len({r["entity_id"] for r in members}) > 1:
            entity_ids = sorted({r["entity_id"] for r in members})
            display_alias = sorted(alias_labels.get(alias) or {alias}, key=lambda value: (normalize(value), value))[0]
            diagnostics.append(_diag(
                "alias_conflict",
                f"Alias '{display_alias}' maps to multiple entities: {', '.join(entity_ids)}; use area/domain to disambiguate",
                members[0]["path"], alias=display_alias, normalized_alias=alias, entity_ids=entity_ids, location=members[0].get("location"),
                definitions=[_conflict_ref(r) for r in members]))
    for label, members in area_labels.items():
        if len({r["area_id"] for r in members}) > 1:
            area_ids = sorted({r["area_id"] for r in members})
            display_label = sorted(area_label_text.get(label) or {label}, key=lambda value: (normalize(value), value))[0]
            diagnostics.append(_diag(
                "area_alias_conflict",
                f"Area label '{display_label}' maps to multiple area IDs: {', '.join(area_ids)}",
                members[0]["path"], alias=display_label, normalized_alias=label, area_ids=area_ids, location=members[0].get("location"),
                definitions=[_conflict_ref(r) for r in members]))
    for r in records:
        if r["entity_id"] and r["area_id"] and r["area"] and normalize(r["area_id"]) in areas:
            a = areas[normalize(r["area_id"])]
            accepted_labels = list(dict.fromkeys([a["area_id"], a["name"], *a["aliases"]]))
            if normalize(r["area"]) not in set(map(normalize, accepted_labels)):
                r["issues"].append("area_conflict")
                diagnostics.append(_diag(
                    "area_conflict",
                    f"Entity '{r['entity_id']}' uses area '{r['area']}' but area_id '{r['area_id']}' accepts: {', '.join(accepted_labels)}",
                    r["path"], entity_id=r["entity_id"], record_id=r["record_id"], location=r.get("location"),
                    actual_area=r["area"], area_id=r["area_id"], accepted_labels=accepted_labels,
                    area_definition=_conflict_ref(a)))
    return diagnostics


def validate_catalog(records: list[dict]) -> list[dict]:
    """Cross-file diagnostics for proposed or indexed records (also marks issues)."""
    return _cross_validate(records)


def strip_realtime_fields(record: dict) -> tuple[dict, list[str]]:
    """Conservative sanitizer shared with proposal generation; input is unchanged."""
    removed: list[str] = []
    return _remove_live(record, removed), removed


def inspect_knowledge() -> dict:
    """Bounded file snapshot and normalized records; never mutates content."""
    scanned = utcnow()
    diagnostics, files, records = [], [], []
    try:
        root = knowledge_root()
    except (OSError, ValueError) as exc:
        return {"root": str(settings.knowledge_dir), "files": [], "records": [], "diagnostics": [
            _diag("unsafe_root", str(exc), "", severity="error")], "fingerprint": "", "scanned_at": scanned}
    max_file = int(getattr(settings, "knowledge_max_file_bytes", 2 * 1024 * 1024))
    max_total = int(getattr(settings, "knowledge_max_total_bytes", 32 * 1024 * 1024))
    max_files = int(getattr(settings, "knowledge_max_files", 2000))
    total = 0
    if root.exists():
        def walk_error(exc):
            diagnostics.append(_diag("read_error", "Cannot enumerate Knowledge directory", "", severity="error"))
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
            kept = []
            for name in sorted(dirs):
                candidate = Path(directory) / name
                if name.startswith("."):
                    continue
                if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                    diagnostics.append(_diag("unsafe_path", "Symlink/junction directory skipped", candidate.relative_to(root).as_posix()))
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(names):
                path = Path(directory) / name
                if name.startswith(".") or path.suffix.lower() not in ALLOWED:
                    continue
                rel = path.relative_to(root).as_posix()
                row = {"path": rel, "sha256": "", "size": 0, "status": "error", "error": None, "records": 0}
                files.append(row)
                try:
                    if len(files) > max_files:
                        raise ValueError("Knowledge file count limit exceeded")
                    target = safe_knowledge_path(rel, must_exist=True)
                    size = target.stat().st_size
                    if size > max_file or total + size > max_total:
                        raise ValueError("Knowledge file/total byte limit exceeded")
                    with target.open("rb") as stream:
                        data = stream.read(max_file + 1)
                    if len(data) > max_file or total + len(data) > max_total:
                        raise ValueError("Knowledge file grew beyond byte limit")
                    total += len(data)
                    row.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
                    parsed = parse_knowledge_text(rel, data.decode("utf-8-sig"))
                    diagnostics.extend(parsed["diagnostics"])
                    row["records"] = len(parsed["records"])
                    errors = [d for d in parsed["diagnostics"] if d["severity"] == "error"]
                    row["status"] = "error" if errors else "ready"
                    row["error"] = "; ".join(e["message"] for e in errors) or None
                    records.extend(parsed["records"])
                except (OSError, UnicodeError, ValueError) as exc:
                    row["error"] = str(exc)[:500]
                    diagnostics.append(_diag("read_error", row["error"], rel, severity="error"))
                if len(files) > max_files:
                    break
            if len(files) > max_files:
                break
    diagnostics.extend(_cross_validate(records))
    files.sort(key=lambda f: f["path"])
    signature = {"files": [(f["path"], f["sha256"], f["status"]) for f in files],
                 "errors": sorted((d["code"], d["path"], d["message"]) for d in diagnostics if d["severity"] == "error")}
    fingerprint = hashlib.sha256(json.dumps(signature, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {"root": str(root), "files": files, "records": records, "diagnostics": diagnostics,
            "fingerprint": fingerprint, "scanned_at": scanned, "total_bytes": total}


def ensure_schema(c: sqlite3.Connection | None = None) -> None:
    if c is None:
        with conn() as connection:
            ensure_schema(connection)
        return
    # executescript would implicitly commit an active replacement transaction.
    statements = [
        "CREATE TABLE IF NOT EXISTS knowledge_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT,path TEXT NOT NULL,chunk_index INTEGER NOT NULL,text TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(path,chunk_index))",
        "CREATE TABLE IF NOT EXISTS knowledge_records (record_id TEXT PRIMARY KEY,kind TEXT NOT NULL,entity_id TEXT,path TEXT NOT NULL,data TEXT NOT NULL,updated_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_records_entity ON knowledge_records(entity_id)",
        "CREATE TABLE IF NOT EXISTS knowledge_manifest (path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,size INTEGER NOT NULL,status TEXT NOT NULL,error TEXT,records INTEGER NOT NULL,indexed_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS knowledge_index_state (id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS knowledge_chunk_records (chunk_id INTEGER PRIMARY KEY,record_id TEXT NOT NULL)",
    ]
    for statement in statements:
        c.execute(statement)
    try:
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(chunk_id UNINDEXED,path,text)")
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_lookup USING fts5(chunk_id UNINDEXED,text)")
    except sqlite3.OperationalError:
        pass


def reindex_knowledge() -> dict:
    """Transactional replacement. Bad input leaves the last good index intact."""
    with _INDEX_LOCK:
        snapshot = inspect_knowledge()
        errors = [d for d in snapshot["diagnostics"] if d["severity"] == "error"]
        result = {"files": len(snapshot["files"]), "chunks": 0, "records": len(snapshot["records"]),
                  "status": "error" if errors else "ready", "errors": errors,
                  "warnings": [d for d in snapshot["diagnostics"] if d["severity"] != "error"],
                  "fingerprint": snapshot["fingerprint"], "indexed_at": None, "scanned_at": snapshot["scanned_at"]}
        with conn() as c:
            ensure_schema(c)
            previous = c.execute("SELECT data FROM knowledge_index_state WHERE id=1").fetchone()
            if errors:
                old = json.loads(previous["data"]) if previous else {}
                result.update(indexed_at=old.get("indexed_at"), retained_previous=True,
                              indexed_fingerprint=old.get("indexed_fingerprint", old.get("fingerprint")),
                              chunks=old.get("chunks", 0), indexed_records=old.get("indexed_records", old.get("records", 0)))
                c.execute("INSERT OR REPLACE INTO knowledge_index_state(id,data) VALUES(1,?)", (json.dumps(result, ensure_ascii=False),))
            else:
                now = utcnow()
                for table in ("knowledge_chunk_records", "knowledge_records", "knowledge_chunks", "knowledge_manifest"):
                    c.execute(f"DELETE FROM {table}")
                try:
                    c.execute("DELETE FROM knowledge_fts")
                    c.execute("DELETE FROM knowledge_lookup")
                except sqlite3.OperationalError:
                    pass
                indices: dict[str, int] = {}
                for record in snapshot["records"]:
                    c.execute("INSERT INTO knowledge_records(record_id,kind,entity_id,path,data,updated_at) VALUES(?,?,?,?,?,?)",
                              (record["record_id"], record["kind"], record["entity_id"], record["path"], json.dumps(record, ensure_ascii=False), now))
                    for part in chunks(record["text"]):
                        i = indices.get(record["path"], 0)
                        indices[record["path"]] = i + 1
                        cur = c.execute("INSERT INTO knowledge_chunks(path,chunk_index,text,updated_at) VALUES(?,?,?,?)", (record["path"], i, part, now))
                        cid = int(cur.lastrowid)
                        c.execute("INSERT INTO knowledge_chunk_records(chunk_id,record_id) VALUES(?,?)", (cid, record["record_id"]))
                        try:
                            c.execute("INSERT INTO knowledge_fts(chunk_id,path,text) VALUES(?,?,?)", (cid, record["path"], part))
                            c.execute("INSERT INTO knowledge_lookup(chunk_id,text) VALUES(?,?)", (cid, normalize(" ".join([part, record["path"], record["name"], *record["aliases"]]))))
                        except sqlite3.OperationalError:
                            pass
                        result["chunks"] += 1
                for f in snapshot["files"]:
                    c.execute("INSERT INTO knowledge_manifest(path,sha256,size,status,error,records,indexed_at) VALUES(?,?,?,?,?,?,?)",
                              (f["path"], f["sha256"], f["size"], f["status"], f["error"], f["records"], now))
                result.update(indexed_at=now, indexed_fingerprint=snapshot["fingerprint"], indexed_records=len(snapshot["records"]), retained_previous=False)
                c.execute("INSERT OR REPLACE INTO knowledge_index_state(id,data) VALUES(1,?)", (json.dumps(result, ensure_ascii=False),))
        info(logger, "knowledge_index_finished", files=result["files"], records=result["records"], chunks=result["chunks"], status=result["status"])
        return result


def index_status() -> dict:
    with conn() as c:
        ensure_schema(c)
        row = c.execute("SELECT data FROM knowledge_index_state WHERE id=1").fetchone()
        manifest = [dict(r) for r in c.execute("SELECT * FROM knowledge_manifest ORDER BY path").fetchall()]
        legacy_count = c.execute("SELECT count(*) FROM knowledge_chunks").fetchone()[0]
        state = json.loads(row["data"]) if row else {"status": "not_indexed", "files": 0, "records": 0,
                                                    "chunks": legacy_count, "errors": [], "warnings": [], "indexed_at": None}
        control_warning = _control_index_warning(c, state)
    return {**state, "manifest": manifest, "static_only": True, "index_warning": control_warning,
            "stale": bool(control_warning and control_warning["code"] == "stale_index"), "control_safe": control_warning is None}


def _control_index_warning(c=None, state: dict | None = None, catalog_indexed_at: str | None = None) -> dict | None:
    """Use persisted scan/index state to gate control without scanning files."""
    if c is None:
        with conn() as connection:
            ensure_schema(connection)
            return _control_index_warning(connection, catalog_indexed_at=catalog_indexed_at)
    try:
        if state is None:
            row = c.execute("SELECT data FROM knowledge_index_state WHERE id=1").fetchone()
            state = json.loads(row["data"]) if row else {"status": "not_indexed"}
        if state.get("retained_previous") or state.get("status") == "error":
            return {"code": "index_error", "message": "The last valid index is retained for lookup only. Fix Knowledge errors and re-index before controlling devices by name or alias."}
        if state.get("status") != "ready":
            return {"code": "not_indexed", "message": "Knowledge has not been indexed; registry-derived control is unavailable."}
        if catalog_indexed_at and state.get("indexed_at") != catalog_indexed_at:
            return {"code": "index_changed", "message": "Knowledge was re-indexed during lookup; resolve the entity again before controlling it."}
        try:
            # Governance is optional; importing it here would create a cycle.
            row = c.execute("SELECT value FROM knowledge_control WHERE key='latest_scan'").fetchone()
        except sqlite3.OperationalError:
            return None
        scan = json.loads(row["value"]) if row else None
        indexed_hash = state.get("indexed_fingerprint", state.get("fingerprint"))
        if scan and scan.get("fingerprint") and scan["fingerprint"] != indexed_hash:
            # Re-indexing commits a newer snapshot and supersedes prior scans.
            scan_time = scan.get("scanned_at", scan.get("created_at"))
            index_time = state.get("scanned_at", state.get("indexed_at"))
            scan_dt = parse_datetime(scan_time) if scan_time else None
            index_dt = parse_datetime(index_time) if index_time else None
            if not scan_dt or not index_dt or scan_dt >= index_dt:
                return {"code": "stale_index", "message": "Knowledge changed after this index. Review changes and re-index before controlling devices by name or alias.",
                        "indexed_fingerprint": indexed_hash, "scan_fingerprint": scan["fingerprint"]}
        return None
    except (ValueError, TypeError, AttributeError):
        return {"code": "index_state_error", "message": "Knowledge index/scan state is invalid; re-index before controlling devices by name or alias."}


def load_catalog() -> list[dict]:
    with conn() as c:
        ensure_schema(c)
        return [{**json.loads(r["data"]), "updated_at": r["updated_at"]}
                for r in c.execute("SELECT data,updated_at FROM knowledge_records ORDER BY record_id").fetchall()]


DOMAIN_TERMS = {"light": ("den", "light", "lights"), "climate": ("may lanh", "dieu hoa", "air conditioner", "climate"),
                "switch": ("cong tac", "o cam", "switch"), "fan": ("quat", "fan"), "media_player": ("tv", "tivi", "loa", "media player"),
                "scene": ("scene", "ngu canh"), "script": ("script", "kich ban"), "sensor": ("sensor", "cam bien"),
                "cover": ("rem", "cua cuon", "cover"), "lock": ("khoa", "lock")}


def _area_labels(record: dict, catalog: list[dict]) -> set[str]:
    labels = {normalize(record.get("area")), normalize(record.get("area_id"))} - {""}
    for area in catalog:
        if area["kind"] == "area":
            area_labels = {normalize(area["name"]), normalize(area["area_id"]), *map(normalize, area["aliases"])}
            matches = (normalize(record["area_id"]) == normalize(area["area_id"])) if record.get("area_id") else bool(labels.intersection(area_labels))
            if matches:
                labels.update(area_labels)
    return labels - {""}


def _candidate(record: dict, query: str, catalog: list[dict], area: str | None, domain: str | None) -> dict | None:
    q = normalize(query)
    labels = _area_labels(record, catalog)
    if area and normalize(area) not in labels:
        return None
    if domain and normalize(domain) != normalize(record["domain"]):
        return None
    match_type, confidence = "none", 0.0
    if query.strip().casefold() == str(record["entity_id"]).casefold():
        match_type, confidence = "entity_id", 1.0
    elif q and q in {normalize(a) for a in record["aliases"]}:
        match_type, confidence = "alias", 0.98
    elif q and q == normalize(record["name"]):
        match_type, confidence = "name", 0.95
    else:
        terms = DOMAIN_TERMS.get(record["domain"], (normalize(record["domain"]),))
        padded = f" {q} "
        has_domain = bool(domain) or any(f" {normalize(t)} " in padded for t in terms if t)
        has_area = bool(area) or any(f" {a} " in padded for a in labels)
        if has_domain and has_area:
            remainder = padded
            for term in sorted([*terms, *labels], key=len, reverse=True):
                remainder = remainder.replace(f" {normalize(term)} ", " ")
            filler = {"bat", "tat", "mo", "dong", "trong", "tai", "o", "cho", "toi", "giup", "the", "in", "turn", "on", "off", "please"}
            if not (set(remainder.split()) - filler):
                match_type, confidence = "area_domain", 0.90
        if match_type == "none":
            scores = [SequenceMatcher(None, q, normalize(v)).ratio() for v in [record["name"], *record["aliases"], record["entity_id"]] if v]
            similarity = max(scores, default=0.0)
            if similarity >= 0.56:
                match_type, confidence = "fuzzy", round(min(0.79, similarity * 0.79), 4)
    if confidence == 0:
        return None
    return {key: record.get(key) for key in ("record_id", "entity_id", "name", "area", "area_id", "domain", "path", "source", "issues")} | {
        "confidence": confidence, "score": confidence, "match_type": match_type,
        "safe_for_control": match_type != "fuzzy" and not record.get("issues")}


def resolve_entity(query: str, area: str | None = None, domain: str | None = None) -> dict:
    query = str(query or "").strip()[:512]
    return _resolve_from_catalog(query, load_catalog(), area, domain)


def _resolve_from_catalog(query: str, catalog: list[dict], area: str | None, domain: str | None) -> dict:
    generation = next((r.get("updated_at") for r in catalog if r.get("updated_at")), None)
    control_warning = _control_index_warning(catalog_indexed_at=generation)
    result = {"query": query, "status": "not_found", "entity_id": None, "confidence": 0.0,
              "match_type": "none", "candidates": [], "safe_for_control": False, "index_warning": control_warning}
    if not query:
        return result
    areas = [r for r in catalog if r["kind"] == "area"]
    matches = [r for record in catalog if record.get("entity_id") and record["kind"] in {"entity", "scene", "script"}
               if (r := _candidate(record, query, areas, area, domain)) is not None]
    rank = {"entity_id": 5, "alias": 4, "name": 3, "area_domain": 2, "fuzzy": 1}
    matches.sort(key=lambda r: (-rank[r["match_type"]], -r["confidence"], r["entity_id"], r["record_id"]))
    if not matches:
        return result
    unique: dict[str, dict] = {}
    for candidate in matches:
        if candidate["entity_id"] not in unique:
            unique[candidate["entity_id"]] = candidate.copy()
        elif candidate.get("issues"):
            existing = unique[candidate["entity_id"]]
            existing["safe_for_control"] = False
            existing["issues"] = sorted(set(existing.get("issues", [])) | set(candidate["issues"]))
    candidates = list(unique.values())
    if control_warning:
        for candidate in candidates:
            candidate.update(safe_for_control=False, index_warning=control_warning)
    best = candidates[0]
    peers = [r for r in candidates if rank[r["match_type"]] == rank[best["match_type"]]
             and r["confidence"] >= best["confidence"] - 0.08]
    ambiguous = len(peers) > 1 or bool(best.get("issues"))
    result.update(status="ambiguous" if ambiguous else "resolved", entity_id=None if ambiguous else best["entity_id"],
                  confidence=best["confidence"], match_type=best["match_type"], candidates=candidates[:12],
                  safe_for_control=not ambiguous and best["safe_for_control"])
    return result


def _retrieval_rows(query: str, hits: dict[str, dict], limit: int, allowed_records: set[str] | None = None,
                    allow_legacy: bool = True) -> list[dict]:
    """Bound lexical candidates with safe normalized FTS; support non-FTS SQLite."""
    with conn() as c:
        ensure_schema(c)
        base = "SELECT k.*,l.record_id FROM knowledge_chunks k LEFT JOIN knowledge_chunk_records l ON k.id=l.chunk_id"
        eligibility = ""
        if allowed_records is not None:
            c.create_function("knowledge_eligible", 1, lambda record_id: int(record_id in allowed_records if record_id is not None else allow_legacy))
            eligibility = " AND knowledge_eligible(l.record_id)=1"
        candidates: dict[int, dict] = {}
        try:
            # Empty normalized FTS means an older index needs a migration re-index.
            if not c.execute("SELECT 1 FROM knowledge_lookup LIMIT 1").fetchone():
                raise sqlite3.OperationalError("Normalized Knowledge index not populated")
            tokens = list(dict.fromkeys(normalize(query).split()))[:32]
            expression = " OR ".join('"' + token + '"' for token in tokens)
            rows = c.execute(base + " JOIN knowledge_lookup f ON k.id=f.chunk_id WHERE knowledge_lookup MATCH ?" + eligibility + " ORDER BY bm25(knowledge_lookup) LIMIT ?",
                             (expression, min(1000, max(200, limit * 20)))).fetchall()
            candidates.update((r["id"], dict(r)) for r in rows)
        except sqlite3.OperationalError:
            return [dict(r) for r in c.execute(base + (" WHERE knowledge_eligible(l.record_id)=1" if eligibility else "") + " ORDER BY k.id").fetchall()]
        if hits:
            entity_ids = list(hits)
            placeholders = ",".join("?" for _ in entity_ids)
            rows = c.execute(base + f" JOIN knowledge_records r ON r.record_id=l.record_id WHERE r.entity_id IN ({placeholders})" + eligibility + " ORDER BY k.id LIMIT ?",
                             (*entity_ids, min(1000, max(200, limit * 20)))).fetchall()
            candidates.update((r["id"], dict(r)) for r in rows)
        return list(candidates.values())


def search_knowledge(query: str, limit: int = 8, area: str | None = None, domain: str | None = None,
                     kind: str | None = None) -> list[dict]:
    query = str(query or "").strip()[:512]
    limit = max(1, min(int(limit), 50))
    if not query or not normalize(query):
        return []
    if kind and kind not in KINDS:
        raise ValueError("Unsupported Knowledge kind")
    catalog = load_catalog()
    areas = [r for r in catalog if r["kind"] == "area"]
    indexed = {r["record_id"]: r for r in catalog}
    allowed_records = None
    if area or domain or kind:
        allowed_records = {r["record_id"] for r in catalog
                           if (not kind or r["kind"] == kind)
                           and (not domain or normalize(r["domain"]) == normalize(domain))
                           and (not area or normalize(area) in _area_labels(r, areas))}
    resolution = _resolve_from_catalog(query, catalog, area, domain)
    hits = {c["entity_id"]: c for c in resolution["candidates"]}
    q, tokens = normalize(query), set(normalize(query).split())
    rows = _retrieval_rows(query, hits, limit, allowed_records, allow_legacy=not area and not domain and kind in {None, "reference"})
    results = []
    for row in rows:
        item = dict(row)
        record = indexed.get(item.get("record_id"))
        record = record or {"kind": "reference", "entity_id": None, "name": Path(item["path"]).stem,
                            "aliases": [], "area": "", "area_id": "", "domain": "", "source": item["path"], "metadata": {"legacy": True}}
        if kind and record["kind"] != kind:
            continue
        if domain and normalize(record["domain"]) != normalize(domain):
            continue
        if area and normalize(area) not in _area_labels(record, areas):
            continue
        haystack = normalize(" ".join([item["text"], item["path"], record["name"], *record["aliases"]]))
        coverage = len(tokens & set(haystack.split())) / max(1, len(tokens))
        score = min(0.82, coverage * 0.72 + (0.10 if q in haystack else 0))
        hit = (_candidate(record, query, areas, area, domain) if record["entity_id"] in hits else None)
        if hit:
            score = max(score, hit["confidence"])
        if score <= 0:
            continue
        item.update({key: record.get(key) for key in ("kind", "entity_id", "name", "aliases", "area", "area_id", "domain", "source", "metadata")})
        item.update(score=round(score, 4), confidence=hit["confidence"] if hit else round(score, 4),
                    match_type=hit["match_type"] if hit else "text", preview=item["text"][:360],
                    safe_for_control=bool(hit and hit["safe_for_control"] and resolution["safe_for_control"]),
                    index_warning=resolution["index_warning"])
        results.append(item)
    results.sort(key=lambda r: (-r["score"], r["path"], r["chunk_index"]))
    return results[:limit]
