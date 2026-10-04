from __future__ import annotations

import html
import re

_FOLLOWUP_RE = re.compile(r"<FollowUp\b(?P<attrs>[^>]*)/?>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:[A-Za-z0-9_+.-]+)?\s*\n?(.*?)```", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_HRULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_UNORDERED_RE = re.compile(r"^(\s*)[*+-]\s+(.+)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.+)$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")


def _followup_to_text(match: re.Match[str]) -> str:
    attrs = {m.group(1).lower(): html.unescape(m.group(3)).strip() for m in _ATTR_RE.finditer(match.group("attrs") or "")}
    label = attrs.get("label", "").strip()
    if not label:
        return ""
    return f"\n\n💡 Gợi ý: {label}\n"


def _strip_inline_markdown(text: str) -> str:
    # Preserve entity IDs and values literally; only strip unambiguous Markdown delimiters.
    text = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = re.sub(r"`+([^`\n]+?)`+", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    # Paired asterisk italics only. This deliberately does not treat '_' as emphasis,
    # because Home Assistant entity_ids contain underscores extensively.
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"\\([#*`_~>+\-])", r"\1", text)
    return text


def format_zalo_message(value: str) -> str:
    """Convert model Markdown/UI markup to readable Zalo-safe plain text.

    Zalo's regular message surface does not render Markdown.  This function keeps
    hierarchy using Unicode bullets, whitespace and a text separator while
    preserving Home Assistant entity IDs exactly.
    """
    text = html.unescape(str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FOLLOWUP_RE.sub(_followup_to_text, text)
    text = _FENCE_RE.sub(lambda m: m.group(1).strip("\n"), text)

    output: list[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            output.append("")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            output.append(_strip_inline_markdown(heading.group(1).strip()))
            continue

        if _HRULE_RE.match(line):
            output.append("────────────")
            continue

        unordered = _UNORDERED_RE.match(line)
        if unordered:
            spaces = len(unordered.group(1).replace("\t", "    "))
            depth = max(0, spaces // 2)
            bullet = "•" if depth == 0 else "◦"
            output.append(f"{'  ' * depth}{bullet} {_strip_inline_markdown(unordered.group(2).strip())}")
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            spaces = len(ordered.group(1).replace("\t", "    "))
            depth = max(0, spaces // 2)
            output.append(f"{'  ' * depth}{ordered.group(2)}. {_strip_inline_markdown(ordered.group(3).strip())}")
            continue

        quote = _BLOCKQUOTE_RE.match(line)
        if quote:
            output.append(f"› {_strip_inline_markdown(quote.group(1).strip())}")
            continue

        output.append(_strip_inline_markdown(line))

    # Remove unsupported residual FollowUp closing tags if a model emitted a
    # non-self-closing variant, then normalize whitespace for a mobile chat bubble.
    result = "\n".join(output)
    result = re.sub(r"</?FollowUp\b[^>]*>", "", result, flags=re.IGNORECASE | re.DOTALL)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def split_zalo_message(value: str, limit: int = 3900) -> list[str]:
    """Format and split a long answer on readable boundaries for Zalo."""
    text = format_zalo_message(value)
    limit = max(200, int(limit))
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[: limit + 1]
        minimum = int(limit * 0.55)
        cuts = [window.rfind("\n\n", minimum), window.rfind("\n", minimum), window.rfind(" ", minimum)]
        cut = max(cuts)
        if cut < minimum:
            cut = limit
        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
