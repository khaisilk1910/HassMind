from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .settings import settings

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SKILL_BYTES = 128 * 1024
_MAX_DESCRIPTION = 1000
_MAX_NAME = 80


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _builtin_root() -> Path:
    return Path(settings.skills_dir)


def _user_root() -> Path:
    return Path(settings.user_skills_dir)


def _meta_root() -> Path:
    return _user_root() / ".meta"


def _history_root() -> Path:
    return _user_root() / ".history"


def _ensure_user_storage() -> None:
    try:
        for path in (_user_root(), _meta_root(), _history_root()):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
    except OSError as exc:
        raise RuntimeError(f"User skill storage is not writable: {_user_root()}") from exc


def _validate_name(name: str) -> str:
    value = str(name or "").strip()
    if not value or len(value) > _MAX_NAME or not _NAME_RE.fullmatch(value):
        raise ValueError("Skill name must use lowercase letters, numbers and single hyphens only")
    return value


def _meta_path(name: str) -> Path:
    return _meta_root() / f"{_validate_name(name)}.json"


def _user_path(name: str) -> Path:
    return _user_root() / f"{_validate_name(name)}.md"


def _history_dir(name: str) -> Path:
    return _history_root() / _validate_name(name)


def _atomic_write_text(path: Path, value: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp.write_text(value, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"Cannot write user skill storage: {path.parent}") from exc


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _load_meta(name: str) -> dict[str, Any]:
    path = _meta_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_meta(name: str, *, enabled: bool, version: int, created_at: str | None = None) -> dict[str, Any]:
    _ensure_user_storage()
    old = _load_meta(name)
    data = {
        "name": name,
        "enabled": bool(enabled),
        "version": max(1, int(version)),
        "created_at": created_at or old.get("created_at") or _now(),
        "updated_at": _now(),
    }
    _atomic_write_json(_meta_path(name), data)
    return data


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str, list[str]]:
    errors: list[str] = []
    if not raw.startswith("---\n"):
        return {}, raw.strip(), ["Missing YAML frontmatter"]
    closing = raw.find("\n---", 4)
    if closing < 0:
        return {}, raw.strip(), ["YAML frontmatter is not closed with ---"]
    meta_text = raw[4:closing]
    body = raw[closing + 4 :].lstrip("\r\n")
    try:
        loaded = yaml.safe_load(meta_text) or {}
    except yaml.YAMLError as exc:
        return {}, body.strip(), [f"Invalid YAML frontmatter: {exc}"]
    if not isinstance(loaded, dict):
        errors.append("YAML frontmatter must be a mapping")
        loaded = {}
    return loaded, body.strip(), errors


def validate_skill_content(raw: str, expected_name: str | None = None) -> dict[str, Any]:
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    errors: list[str] = []
    warnings: list[str] = []
    size = len(text.encode("utf-8"))
    if size > _MAX_SKILL_BYTES:
        errors.append(f"Skill is too large ({size} bytes; maximum {_MAX_SKILL_BYTES})")
    if "\x00" in text:
        errors.append("Skill contains a NUL byte")

    meta, body, fm_errors = _split_frontmatter(text)
    errors.extend(fm_errors)
    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    try:
        if name:
            _validate_name(name)
        else:
            errors.append("Frontmatter field 'name' is required")
    except ValueError as exc:
        errors.append(str(exc))
    if expected_name and name and name != expected_name:
        errors.append(f"Frontmatter name must remain '{expected_name}'")
    if not description:
        errors.append("Frontmatter field 'description' is required")
    elif len(description) > _MAX_DESCRIPTION:
        errors.append(f"Description is too long (maximum {_MAX_DESCRIPTION} characters)")
    elif len(description) < 20:
        warnings.append("Description is very short; routing quality may be reduced")
    if not body.strip():
        errors.append("Skill body must not be empty")
    elif len(body.strip()) < 40:
        warnings.append("Skill body is very short; add a concrete workflow and safety rules")
    if body and not re.search(r"^#{1,3}\s+", body, re.MULTILINE):
        warnings.append("Skill body has no headings; structured sections improve maintainability")

    allowed = {"name", "description"}
    unknown = sorted(str(k) for k in meta if k not in allowed)
    if unknown:
        warnings.append("Unknown frontmatter fields are ignored: " + ", ".join(unknown))

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "name": name,
        "description": description,
        "body": body,
        "bytes": size,
        "frontmatter": {"name": name, "description": description},
    }


def compose_skill(name: str, description: str, body: str) -> str:
    name = _validate_name(name)
    description = str(description or "").strip()
    body = str(body or "").strip()
    if not description:
        raise ValueError("Description is required")
    meta = yaml.safe_dump(
        {"name": name, "description": description},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    raw = f"---\n{meta}\n---\n\n{body}\n"
    result = validate_skill_content(raw, expected_name=name)
    if not result["ok"]:
        raise ValueError("; ".join(result["errors"]))
    return raw


def _parse_path(path: Path, source: str) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    # The filename is the stable management key. A mismatched frontmatter name
    # is invalid rather than silently aliasing another file.
    parsed = validate_skill_content(raw, expected_name=path.stem)
    return {
        "name": path.stem,
        "description": parsed.get("description") or "",
        "body": parsed.get("body") or raw.strip(),
        "raw": raw,
        "path": str(path),
        "source": source,
        "valid": bool(parsed["ok"]),
        "validation_errors": parsed["errors"],
        "validation_warnings": parsed["warnings"],
        "bytes": parsed["bytes"],
    }


def _load_root(root: Path, source: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for path in sorted(root.glob("*.md")):
        if path.is_symlink():
            item = {
                "name": path.stem, "description": "", "body": "", "raw": "",
                "path": str(path), "source": source, "valid": False,
                "validation_errors": ["Symbolic-link skill files are not allowed"],
                "validation_warnings": [], "bytes": 0,
            }
        else:
            try:
                item = _parse_path(path, source)
            except OSError:
                continue
        name = str(item["name"] or path.stem)
        # Invalid names can be displayed for repair, but they are never addressable
        # by the management API until their frontmatter/file is fixed manually.
        if not _NAME_RE.fullmatch(name):
            name = path.stem
            item["name"] = name
            item["valid"] = False
            item["validation_errors"] = list(item["validation_errors"]) + ["Invalid effective skill name"]
        result[name] = item
    return result


def _effective_map() -> dict[str, dict[str, Any]]:
    builtins = _load_root(_builtin_root(), "builtin")
    users = _load_root(_user_root(), "user")
    names = sorted(set(builtins) | set(users))
    result: dict[str, dict[str, Any]] = {}
    for name in names:
        base = builtins.get(name)
        item = dict(users.get(name) or base or {})
        try:
            meta = _load_meta(name)
            manageable = True
        except ValueError:
            # Manually-created files with invalid filenames remain visible to
            # Admin for diagnosis but cannot be addressed by CRUD endpoints.
            meta = {}
            manageable = False
        item["name"] = name
        item["manageable"] = manageable
        item["enabled"] = bool(meta.get("enabled", True))
        item["version"] = max(1, int(meta.get("version") or 1))
        item["override"] = bool(name in users and name in builtins)
        item["builtin_available"] = bool(base)
        item["protected"] = bool(base and name not in users)
        item["updated_at"] = str(meta.get("updated_at") or "")
        item["storage"] = "user" if name in users else "builtin"
        result[name] = item
    return result


def _public(item: dict[str, Any], *, include_body: bool = False) -> dict[str, Any]:
    fields = {
        "name",
        "description",
        "path",
        "source",
        "storage",
        "enabled",
        "version",
        "override",
        "builtin_available",
        "protected",
        "updated_at",
        "valid",
        "validation_errors",
        "validation_warnings",
        "bytes",
        "manageable",
    }
    if include_body:
        fields.update({"body", "raw"})
    return {k: item.get(k) for k in fields}


def list_skills(include_disabled: bool = False) -> list[dict[str, Any]]:
    items = []
    for item in _effective_map().values():
        if not include_disabled and not item.get("enabled", True):
            continue
        # Agent-facing listing omits invalid skills, while the admin API can
        # still request them with include_disabled=True and repair them.
        if not include_disabled and not item.get("valid", False):
            continue
        items.append(_public(item))
    return items


def read_skill(name: str, include_disabled: bool = False) -> dict[str, Any]:
    name = _validate_name(name)
    item = _effective_map().get(name)
    if not item:
        raise KeyError(name)
    if (not include_disabled) and (not item.get("enabled", True) or not item.get("valid", False)):
        raise KeyError(name)
    return _public(item, include_body=True)


def _snapshot(item: dict[str, Any], reason: str) -> None:
    name = _validate_name(str(item["name"]))
    version = max(1, int(item.get("version") or 1))
    directory = _history_dir(name)
    path = directory / f"{version:06d}.json"
    if path.exists():
        return
    payload = {
        "name": name,
        "version": version,
        "enabled": bool(item.get("enabled", True)),
        "source": item.get("source") or item.get("storage") or "unknown",
        "description": item.get("description") or "",
        "raw": item.get("raw") or "",
        "saved_at": _now(),
        "reason": reason,
    }
    _atomic_write_json(path, payload)


def create_skill(name: str, description: str, body: str, enabled: bool = True) -> dict[str, Any]:
    _ensure_user_storage()
    name = _validate_name(name)
    if name in _effective_map():
        raise FileExistsError(name)
    raw = compose_skill(name, description, body)
    _atomic_write_text(_user_path(name), raw)
    _save_meta(name, enabled=enabled, version=1)
    return read_skill(name, include_disabled=True)


def update_skill(name: str, description: str, body: str, enabled: bool | None = None) -> dict[str, Any]:
    _ensure_user_storage()
    name = _validate_name(name)
    current = read_skill(name, include_disabled=True)
    raw = compose_skill(name, description, body)
    _snapshot(current, "before_update")
    _atomic_write_text(_user_path(name), raw)
    new_enabled = bool(current.get("enabled", True) if enabled is None else enabled)
    _save_meta(name, enabled=new_enabled, version=int(current.get("version") or 1) + 1)
    return read_skill(name, include_disabled=True)


def set_skill_enabled(name: str, enabled: bool) -> dict[str, Any]:
    _ensure_user_storage()
    name = _validate_name(name)
    current = read_skill(name, include_disabled=True)
    _save_meta(name, enabled=bool(enabled), version=int(current.get("version") or 1))
    return read_skill(name, include_disabled=True)


def delete_skill(name: str) -> dict[str, Any]:
    _ensure_user_storage()
    name = _validate_name(name)
    current = read_skill(name, include_disabled=True)
    user_path = _user_path(name)
    if not user_path.exists() and not user_path.is_symlink():
        raise PermissionError("Built-in skills cannot be deleted; disable the skill or edit it as an override")
    _snapshot(current, "before_delete")
    try:
        user_path.unlink()
    except OSError as exc:
        raise RuntimeError("Cannot remove user skill file") from exc
    builtins = _load_root(_builtin_root(), "builtin")
    if name in builtins:
        # Removing an override restores the read-only built-in while retaining
        # the user's enable/disable state and a monotonically increasing version.
        _save_meta(name, enabled=bool(current.get("enabled", True)), version=int(current.get("version") or 1) + 1)
        restored = read_skill(name, include_disabled=True)
        return {"ok": True, "deleted": "override", "restored_builtin": True, "skill": restored}
    try:
        _meta_path(name).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "deleted": "user", "restored_builtin": False, "name": name}


def list_skill_versions(name: str) -> list[dict[str, Any]]:
    name = _validate_name(name)
    directory = _history_dir(name)
    rows: list[dict[str, Any]] = []
    if directory.exists():
        for path in sorted(directory.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            rows.append({
                "version": int(data.get("version") or 0),
                "enabled": bool(data.get("enabled", True)),
                "source": str(data.get("source") or ""),
                "description": str(data.get("description") or ""),
                "saved_at": str(data.get("saved_at") or ""),
                "reason": str(data.get("reason") or ""),
            })
    try:
        current = read_skill(name, include_disabled=True)
    except KeyError:
        current = None
    if current:
        rows.insert(0, {
            "version": int(current.get("version") or 1),
            "enabled": bool(current.get("enabled", True)),
            "source": str(current.get("source") or ""),
            "description": str(current.get("description") or ""),
            "saved_at": str(current.get("updated_at") or ""),
            "reason": "current",
            "current": True,
        })
    return rows


def rollback_skill(name: str, version: int) -> dict[str, Any]:
    _ensure_user_storage()
    name = _validate_name(name)
    version = int(version)
    if version < 1:
        raise ValueError("Version must be >= 1")
    path = _history_dir(name) / f"{version:06d}.json"
    if not path.exists():
        raise KeyError(version)
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Stored skill version is unreadable") from exc
    raw = str(snapshot.get("raw") or "")
    checked = validate_skill_content(raw, expected_name=name)
    if not checked["ok"]:
        raise ValueError("Stored skill version is invalid: " + "; ".join(checked["errors"]))
    try:
        current = read_skill(name, include_disabled=True)
    except KeyError:
        current = None
    if current:
        _snapshot(current, "before_rollback")
        next_version = int(current.get("version") or 1) + 1
    else:
        historical = [x.get("version", 0) for x in list_skill_versions(name)]
        next_version = max([int(x) for x in historical if int(x) > 0] or [version]) + 1
    _atomic_write_text(_user_path(name), raw)
    _save_meta(name, enabled=bool(snapshot.get("enabled", True)), version=next_version)
    result = read_skill(name, include_disabled=True)
    result["rolled_back_from"] = version
    return result


def test_skill(name: str) -> dict[str, Any]:
    current = read_skill(name, include_disabled=True)
    validation = validate_skill_content(str(current.get("raw") or ""), expected_name=name)
    body = str(current.get("body") or "")
    headings = re.findall(r"^#{1,3}\s+(.+)$", body, re.MULTILINE)
    checks = {
        "frontmatter": validation["ok"] or not any("frontmatter" in e.lower() for e in validation["errors"]),
        "name_matches": validation.get("name") == name,
        "has_description": bool(validation.get("description")),
        "has_body": bool(body.strip()),
        "has_structure": bool(headings),
        "enabled": bool(current.get("enabled", True)),
    }
    return {
        "ok": bool(validation["ok"]),
        "name": name,
        "version": current.get("version"),
        "source": current.get("source"),
        "enabled": current.get("enabled"),
        "checks": checks,
        "headings": headings[:20],
        "errors": validation["errors"],
        "warnings": validation["warnings"],
        "bytes": validation["bytes"],
    }
