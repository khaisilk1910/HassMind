from pathlib import Path
from .settings import settings


def _parse(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    name = path.stem
    description = ""
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            meta = parts[1]
            body = parts[2].strip()
            for line in meta.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
    return {"name": name, "description": description, "body": body, "path": str(path)}


def list_skills() -> list[dict]:
    root = Path(settings.skills_dir)
    if not root.exists():
        return []
    return [{k: v for k, v in _parse(p).items() if k != "body"} for p in sorted(root.glob("*.md"))]


def read_skill(name: str) -> dict:
    root = Path(settings.skills_dir)
    for p in root.glob("*.md"):
        s = _parse(p)
        if s["name"] == name or p.stem == name:
            return s
    raise KeyError(name)
