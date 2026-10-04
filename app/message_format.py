from __future__ import annotations

import html
import re

_FOLLOWUP_RE = re.compile(r"<FollowUp\b(?P<attrs>[^>]*)/?>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:[A-Za-z0-9_+.-]+)?\s*\n?(.*?)```", re.DOTALL)
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")
_HRULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_UNORDERED_RE = re.compile(r"^(\s*)[*+-]\s+(.+)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.+)$")
_BLOCKQUOTE_RE = re.compile(r"^(\s*)>\s?(.*)$")
_RAW_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>")
_COLOR_SIZE_TAG_RE = re.compile(r"\{/?(?:red|orange|yellow|green|big|small)\}", re.IGNORECASE)
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _followup_to_text(match: re.Match[str]) -> str:
    attrs = {m.group(1).lower(): html.unescape(m.group(3)).strip() for m in _ATTR_RE.finditer(match.group("attrs") or "")}
    label = attrs.get("label", "").strip()
    if not label:
        return ""
    return f"\n\n{{green}}**\U0001f4a1 G\u1ee3i \u00fd:**{{/green}} {label}\n"


def _sanitize_inline(text: str) -> str:
    # The Zalo server supports the delimiters below. Keep them, but normalize
    # malformed legacy double/multiple backticks and remove unsupported HTML.
    text = re.sub(r"`{2,}([^`\n]+?)`{2,}", r"`\1`", text)
    text = re.sub(r"\\([#*`_~>+\-])", r"\1", text)
    text = _RAW_HTML_RE.sub("", text)
    return text.strip()


def _split_table_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def _convert_tables(lines: list[str]) -> list[str]:
    """Convert unsupported Markdown tables to readable Zalo bullets."""
    output: list[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines) and "|" in lines[i] and _TABLE_SEPARATOR_RE.match(lines[i + 1]):
            headers = _split_table_row(lines[i])
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                cells = _split_table_row(lines[i])
                pairs = []
                for index, cell in enumerate(cells):
                    if not cell:
                        continue
                    key = headers[index] if index < len(headers) and headers[index] else f"C{index + 1}"
                    pairs.append(f"**{_sanitize_inline(key)}:** {_sanitize_inline(cell)}")
                if pairs:
                    output.append("- " + " | ".join(pairs))
                i += 1
            continue
        output.append(lines[i])
        i += 1
    return output


def format_zalo_message(value: str) -> str:
    """Normalize model output to the rich-text dialect supported by Zalo Server.

    Supported syntax is intentionally preserved: headings, bold/italic,
    underline/strike, inline backticks, links, color/size tags, bullets,
    numbered lists, blockquotes and indentation. Unsupported constructs such as
    fenced code, Markdown tables, horizontal rules and UI tags are converted to
    safe readable equivalents.
    """
    text = html.unescape(str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FOLLOWUP_RE.sub(_followup_to_text, text)
    text = _FENCE_RE.sub(lambda m: m.group(1).strip("\n"), text)
    lines = _convert_tables(text.split("\n"))

    output: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            output.append("")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 6)
            content = _sanitize_inline(heading.group(2))
            output.append(f"{'#' * level} {content}")
            continue

        if _HRULE_RE.match(line):
            output.append("\u2500" * 12)
            continue

        unordered = _UNORDERED_RE.match(line)
        if unordered:
            indent = unordered.group(1).replace("\t", "    ")[:8]
            output.append(f"{indent}- {_sanitize_inline(unordered.group(2))}")
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            indent = ordered.group(1).replace("\t", "    ")[:8]
            output.append(f"{indent}{ordered.group(2)}. {_sanitize_inline(ordered.group(3))}")
            continue

        quote = _BLOCKQUOTE_RE.match(line)
        if quote:
            indent = quote.group(1).replace("\t", "    ")[:8]
            output.append(f"{indent}> {_sanitize_inline(quote.group(2))}")
            continue

        output.append(_sanitize_inline(line))

    result = "\n".join(output)
    result = re.sub(r"</?FollowUp\b[^>]*>", "", result, flags=re.IGNORECASE | re.DOTALL)
    # Remove unknown brace-style pseudo tags while preserving the six tags that
    # Zalo Server explicitly supports.
    placeholders: list[str] = []

    def keep_tag(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x00ZT{len(placeholders) - 1}\x00"

    result = _COLOR_SIZE_TAG_RE.sub(keep_tag, result)
    result = re.sub(r"\{/?[A-Za-z][A-Za-z0-9_-]*\}", "", result)
    for index, tag in enumerate(placeholders):
        result = result.replace(f"\x00ZT{index}\x00", tag)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def split_zalo_message(value: str, limit: int = 3900) -> list[str]:
    """Format and split a long answer, preferring whole Zalo sections."""
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
