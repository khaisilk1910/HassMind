"""Device-first Knowledge import. Registry lookups are live; file mutations use approval."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import yaml

from . import knowledge_governance, rag

CATALOG_PATH = "21-devices.yaml"


def _clean_string(value, limit=150):
    if not isinstance(value, str):
        raise ValueError("Name and aliases must be text")
    value = value.strip()
    if not value or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError("Invalid name or alias")
    return value


def _device_name(device):
    return str(device.get("name_by_user") or device.get("name") or "").strip() or str(device.get("id", ""))


def _read_catalog():
    target = rag.safe_knowledge_path(CATALOG_PATH)
    raw = target.read_bytes() if target.exists() else None
    if raw is not None and len(raw) > int(rag.settings.knowledge_max_file_bytes):
        raise ValueError("Device catalog file exceeds maximum size")
    content = yaml.safe_load(raw.decode("utf-8-sig")) if raw else None
    if content is None:
        content = {"schema_version": 1, "kind": "hassmind_device_catalog", "devices": []}
    if not isinstance(content, dict) or not isinstance(content.get("devices"), list):
        raise ValueError("21-devices.yaml must contain a devices list")
    if content.get("kind") not in (None, "hassmind_device_catalog") or str(content.get("schema_version", 1)) not in ("1", "1.0"):
        raise ValueError("Unsupported Device Catalog format")
    return content, hashlib.sha256(raw).hexdigest() if raw is not None else None


def _catalog_device_ids():
    document, _ = _read_catalog()
    return {str(item.get("match", {}).get("device_id") or item.get("device_id") or "")
            for item in document["devices"] if isinstance(item, dict) and isinstance(item.get("match"), dict)}


def discover(devices, entities, areas):
    """Group HA entity registry rows by stable device ID (read-only, no state snapshots)."""
    if not all(isinstance(rows, list) for rows in (devices, entities, areas)):
        raise ValueError("Home Assistant returned invalid registry data")
    selected = _catalog_device_ids()
    area_names = {item.get("area_id") or item.get("id"): item.get("name")
                  for item in areas if isinstance(item, dict)}
    grouped = {}
    for e in entities:
        if not isinstance(e, dict) or not isinstance(e.get("device_id"), str):
            continue
        domain = str(e.get("entity_id") or "").split(".", 1)[0]
        grouped.setdefault(e["device_id"], []).append({
            "entity_id": str(e.get("entity_id") or ""), "name": str(e.get("name") or e.get("original_name") or ""),
            "domain": domain, "disabled": bool(e.get("disabled_by")), "hidden": bool(e.get("hidden_by")),
            "device_class": str(e.get("device_class") or e.get("original_device_class") or ""),
        })
    result = []
    for d in devices:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
            continue
        linked = sorted(grouped.get(d["id"], []), key=lambda e: e["entity_id"])
        result.append({
            "device_id": d["id"], "name": _device_name(d),
            "area_id": str(d.get("area_id") or ""), "area": str(area_names.get(d.get("area_id")) or ""),
            "manufacturer": str(d.get("manufacturer") or ""), "model": str(d.get("model") or ""),
            "integration": ", ".join(sorted({e[0] for e in (d.get("identifiers") or []) if isinstance(e, (tuple, list)) and len(e) > 0 and isinstance(e[0], str)})),
            "entity_count": len(linked), "active_count": sum(not e["disabled"] for e in linked),
            "imported": d["id"] in selected, "entities": linked,
        })
    return sorted(result, key=lambda d: (rag.normalize(d["name"]), d["device_id"]))


def create_import_proposal(devices, device_id, name, aliases, actor):
    """Verify actual HA registry membership, then create a hash-checked approval draft."""
    device = next((d for d in devices if d["device_id"] == device_id), None)
    if not device:
        raise ValueError("Device no longer exists in Home Assistant; refresh the list")
    name = _clean_string(name)
    if not isinstance(aliases, list) or len(aliases) > 20:
        raise ValueError("Aliases must be a list of up to 20 items")
    aliases = list(dict.fromkeys(_clean_string(a) for a in aliases))
    document, original_hash = _read_catalog()
    existing = document["devices"]
    existing_ids = {str((item.get("match") or {}).get("device_id") or item.get("device_id") or "")
                    for item in existing if isinstance(item, dict)}
    if device_id in existing_ids:
        raise ValueError("This Device already exists in 21-devices.yaml")
    # Migrate a pre-existing hand-written template (no stable HA device_id yet)
    # only when all of its declared identifying fields agree with this live device.
    legacy_matches = []
    for index, item in enumerate(existing):
        if not isinstance(item, dict):
            continue
        match = item.get("match") or {}
        if not isinstance(match, dict) or match.get("device_id"):
            continue
        if rag.normalize(match.get("name") or item.get("name")) != rag.normalize(device["name"]):
            continue
        if any(match.get(field) and rag.normalize(match[field]) != rag.normalize(device.get(field))
               for field in ("manufacturer", "model")):
            continue
        legacy_matches.append(index)
    if len(legacy_matches) > 1:
        raise ValueError("Multiple legacy Device entries match this HA device; review 21-devices.yaml manually")
    upgrading = bool(legacy_matches)
    if upgrading:
        row = existing[legacy_matches[0]]
        row["name"] = name
        if aliases:
            row["aliases"] = list(dict.fromkeys([*(row.get("aliases") or []), *aliases]))
    else:
        slug = unicodedata.normalize("NFKD", name.casefold().replace("đ", "d"))
        slug = "".join(c for c in slug if not unicodedata.combining(c))
        slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")[:45] or "device"
        digest = hashlib.sha256(device_id.encode()).hexdigest()[:10]
        row = {"key": f"{slug}_{digest}", "name": name}
        if aliases:
            row["aliases"] = aliases
    if device.get("area") and not row.get("area"):
        row["area"] = device["area"]
    if device.get("area_id") and not row.get("area_id"):
        row["area_id"] = device["area_id"]
    row["match"] = {**(row.get("match") or {}), "device_id": device_id}
    for field in ("manufacturer", "model"):
        if device.get(field):
            row["match"][field] = device[field]
    row.setdefault("entities", {"mode": "auto", "include_disabled": False, "include_hidden": False})
    if not upgrading:
        document["devices"].append(row)
    output = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=108)
    action = "Xác nhận Device mẫu" if upgrading else "Thêm Device"
    return knowledge_governance.create_proposal(
        [{"path": CATALOG_PATH, "expected_hash": original_hash, "new_content": output}],
        f"{action} '{name}' ({device_id}) từ Home Assistant vào Knowledge", actor=actor)


def match_catalog_device(query, *, area=None):
    """Only exact normalized names/aliases identify a device; collisions must be clarified."""
    label = rag.normalize(query)
    if not label:
        return {"status": "not_found", "candidates": []}
    candidates = []
    for r in rag.load_catalog():
        if r.get("kind") != "device":
            continue
        if area and rag.normalize(area) not in (rag.normalize(r.get("area")), rag.normalize(r.get("area_id"))):
            continue
        if label not in {rag.normalize(s) for s in [r.get("name"), *r.get("aliases", [])]}:
            continue
        match = r.get("metadata", {}).get("match", {})
        if isinstance(match, dict) and isinstance(match.get("device_id"), str):
            candidates.append({"device_id": match["device_id"], "name": r["name"], "area": r.get("area", "")})
    return {"status": "resolved" if len(candidates) == 1 else "ambiguous" if candidates else "not_found", "candidates": candidates}


def match_device_in_message(message: str) -> dict:
    """Identify a *Knowledge-imported* Device in a longer Vietnamese status question.

    No HA entity names are consulted here. A Device is identified only by its
    operator-approved name/aliases and stable Registry ID. If two devices match,
    the caller must ask which one; a partial name never grants action authority.
    """
    query = rag.normalize(message)
    if not query:
        return {"status": "not_found", "candidates": []}
    padded = f" {query} "
    full_matches: dict[str, dict] = {}
    full_labels: dict[str, set[str]] = {}
    partial_matches: dict[str, dict] = {}
    for row in rag.load_catalog():
        if row.get("kind") != "device":
            continue
        metadata = row.get("metadata") or {}
        match = metadata.get("match") or {}
        device_id = str(match.get("device_id") or "").strip() if isinstance(match, dict) else ""
        if not device_id:
            continue
        candidate = {"device_id": device_id, "name": str(row.get("name") or device_id),
                     "area": str(row.get("area") or "")}
        labels = {rag.normalize(value) for value in [row.get("name"), *(row.get("aliases") or [])]}
        for label in labels:
            if not label or (len(label.split()) < 2 and len(label) < 8):
                continue
            if f" {label} " in padded:
                full_matches[device_id] = candidate
                full_labels.setdefault(device_id, set()).add(label)
                continue
            # Allow a missing final word ("ổ cắm bơm" -> "Ổ cắm Bơm Nước")
            # only with at least three contiguous name tokens. This is an
            # identity suggestion for a read-only status report, never control.
            words = label.split()
            if len(words) >= 4:
                prefix = " ".join(words[:-1])
                if len(prefix.split()) >= 3 and f" {prefix} " in padded:
                    partial_matches[device_id] = candidate
    # A longer exact Device name can contain another Device's short alias.
    # Select the longer name ONLY when the shorter alias does not also appear
    # outside its span ("pump A and pump B" must remain ambiguous).
    if len(full_matches) > 1:
        longest = max((len(label.split()), len(label), device_id, label)
                      for device_id, labels in full_labels.items() for label in labels)
        longest_words, longest_size, best_id, best_label = longest
        max_labels = [(device_id, label) for device_id, labels in full_labels.items()
                      for label in labels if (len(label.split()), len(label)) == (longest_words, longest_size)]
        if len({device_id for device_id, _ in max_labels}) == 1:
            remainder = padded.replace(f" {best_label} ", " ", 1)
            if not any(f" {label} " in remainder for other_id, labels in full_labels.items()
                       if other_id != best_id for label in labels):
                full_matches = {best_id: full_matches[best_id]}
    candidates = list(full_matches.values() if full_matches else partial_matches.values())
    return {"status": "resolved" if len(candidates) == 1 else "ambiguous" if candidates else "not_found",
            "candidates": sorted(candidates, key=lambda row: (rag.normalize(row["name"]), row["device_id"]))}
