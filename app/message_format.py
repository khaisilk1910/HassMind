from __future__ import annotations

import html
import re
from typing import Any

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
_INLINE_TAG_RE = re.compile(r"\{(red|orange|yellow|green|big|small)\}", re.IGNORECASE)
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", re.IGNORECASE)

_AUTO_LABEL_RE = re.compile(r"^([^:\n]{1,42}:)(?:\s+|$)")
_COLOR_STYLE_PREFIX = "c_"
_AUTO_STATUS_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\w)(?:đang có người|đang đóng|đã đóng|bật|online|sẵn sàng|hoạt động bình thường|bình thường|thành công|rất tốt|tốt)(?!\w)", re.IGNORECASE), "c_15a85f"),
    (re.compile(r"(?<!\w)(?:đang mở|mở|unavailable|không khả dụng|mất kết nối|cần chú ý|nhiệt độ cao|độ ẩm cao)(?!\w)", re.IGNORECASE), "c_f27806"),
    (re.compile(r"(?<!\w)(?:cảnh báo|lỗi|nguy hiểm|thất bại|critical|alarm)(?!\w)", re.IGNORECASE), "c_db342e"),
)

# zca-js TextStyle values. Keep these strings in one place so transport code
# does not need to know anything about the markup syntax used by the model.
_ZALO_TAG_STYLES = {
    "red": "c_db342e",
    "orange": "c_f27806",
    "yellow": "c_f7b503",
    "green": "c_15a85f",
    "big": "f_18",
    "small": "f_13",
}


def _followup_to_text(match: re.Match[str]) -> str:
    attrs = {m.group(1).lower(): html.unescape(m.group(3)).strip() for m in _ATTR_RE.finditer(match.group("attrs") or "")}
    label = attrs.get("label", "").strip()
    if not label:
        return ""
    return f"\n\n{{green}}**\U0001f4a1 Gợi ý:**{{/green}} {label}\n"


def _sanitize_inline(text: str, *, strip: bool = True) -> str:
    # The Zalo dialect allows one pair of backticks. Normalize accidental
    # Markdown double/multiple backticks before the rich-text compiler runs.
    text = re.sub(r"`{2,}([^`\n]+?)`{2,}", r"`\1`", text)
    text = re.sub(r"\\([#*`_~>+\-])", r"\1", text)
    text = _RAW_HTML_RE.sub("", text)
    return text.strip() if strip else text


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
    """Normalize model output to the supported Zalo rich-text dialect.

    This function deliberately keeps supported markup. `build_zalo_message_content`
    then compiles that markup into zca-js `msg` + `styles[]`, so Zalo never needs
    to understand Markdown itself.
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

        output.append(_sanitize_inline(line, strip=False))

    result = "\n".join(output)
    result = re.sub(r"</?FollowUp\b[^>]*>", "", result, flags=re.IGNORECASE | re.DOTALL)

    # Remove unknown brace-style pseudo tags while preserving the six tags that
    # the user's Zalo Server / zca-js formatting contract supports.
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
    return result.strip("\n")


def _parse_inline_markup(value: str) -> tuple[str, list[dict[str, Any]]]:
    """Compile supported inline markup to plain text + char-index style spans.

    Span offsets returned here are Python character offsets. They are converted
    to UTF-16 code-unit offsets only after the complete message has been built.
    """
    pieces: list[str] = []
    spans: list[dict[str, Any]] = []
    char_pos = 0

    def append_plain(text: str) -> tuple[int, int]:
        nonlocal char_pos
        if not text:
            return char_pos, char_pos
        start = char_pos
        pieces.append(text)
        char_pos += len(text)
        return start, char_pos

    def append_parsed(inner_plain: str, inner_spans: list[dict[str, Any]], extra_styles: tuple[str, ...] = ()) -> None:
        nonlocal char_pos
        base = char_pos
        pieces.append(inner_plain)
        char_pos += len(inner_plain)
        for span in inner_spans:
            shifted = dict(span)
            shifted["start"] = base + int(span["start"])
            shifted["end"] = base + int(span["end"])
            spans.append(shifted)
        if inner_plain:
            for style in extra_styles:
                spans.append({"start": base, "end": char_pos, "st": style})

    i = 0
    while i < len(value):
        # Backslash escape: retain the escaped character but drop the slash.
        if value[i] == "\\" and i + 1 < len(value) and value[i + 1] in "#*`_~>+-{}[]":
            append_plain(value[i + 1])
            i += 2
            continue

        # {green}...{/green}, {big}...{/big}, etc. Nested different tags are
        # naturally supported by the recursive parse of the inner content.
        tag_match = _INLINE_TAG_RE.match(value, i)
        if tag_match:
            name = tag_match.group(1).lower()
            close_tag = f"{{/{name}}}"
            close_at = value.lower().find(close_tag, tag_match.end())
            if close_at >= 0:
                inner_plain, inner_spans = _parse_inline_markup(value[tag_match.end():close_at])
                append_parsed(inner_plain, inner_spans, (_ZALO_TAG_STYLES[name],))
                i = close_at + len(close_tag)
                continue

        # Bold + italic before bold/single-italic detection.
        if value.startswith("***", i):
            close_at = value.find("***", i + 3)
            if close_at >= 0:
                inner_plain, inner_spans = _parse_inline_markup(value[i + 3:close_at])
                append_parsed(inner_plain, inner_spans, ("b", "i"))
                i = close_at + 3
                continue

        if value.startswith("**", i):
            close_at = value.find("**", i + 2)
            if close_at >= 0:
                inner_plain, inner_spans = _parse_inline_markup(value[i + 2:close_at])
                append_parsed(inner_plain, inner_spans, ("b",))
                i = close_at + 2
                continue

        if value.startswith("__", i):
            close_at = value.find("__", i + 2)
            if close_at >= 0:
                inner_plain, inner_spans = _parse_inline_markup(value[i + 2:close_at])
                append_parsed(inner_plain, inner_spans, ("u",))
                i = close_at + 2
                continue

        if value.startswith("~~", i):
            close_at = value.find("~~", i + 2)
            if close_at >= 0:
                inner_plain, inner_spans = _parse_inline_markup(value[i + 2:close_at])
                append_parsed(inner_plain, inner_spans, ("s",))
                i = close_at + 2
                continue

        # Legacy Zalo behavior: single-backtick content is italic and is not
        # parsed recursively for Markdown inside the code span.
        if value[i] == "`":
            close_at = value.find("`", i + 1)
            if close_at >= 0:
                raw = value[i + 1:close_at]
                start, end = append_plain(raw)
                if end > start:
                    spans.append({"start": start, "end": end, "st": "i"})
                i = close_at + 1
                continue

        link_match = _LINK_RE.match(value, i)
        if link_match:
            # Compatibility contract supplied by the Zalo Server: the label is
            # replaced by the URL in the outgoing text.
            append_plain(link_match.group(2))
            i = link_match.end()
            continue

        # Single-star italic. Do not consume a star that belongs to ** or ***.
        if value[i] == "*" and not value.startswith("**", i):
            close_at = value.find("*", i + 1)
            if close_at >= 0:
                inner_plain, inner_spans = _parse_inline_markup(value[i + 1:close_at])
                append_parsed(inner_plain, inner_spans, ("i",))
                i = close_at + 1
                continue

        append_plain(value[i])
        i += 1

    return "".join(pieces), spans


def _span_overlaps(span: dict[str, Any], start: int, end: int, *, style: str | None = None, style_prefix: str | None = None) -> bool:
    span_start = int(span.get("start", 0))
    span_end = int(span.get("end", 0))
    if span_end <= start or span_start >= end:
        return False
    code = str(span.get("st") or "")
    if style is not None and code != style:
        return False
    if style_prefix is not None and not code.startswith(style_prefix):
        return False
    return True


def _auto_enhance_line_styles(
    plain: str,
    spans: list[dict[str, Any]],
    *,
    is_list: bool,
    is_heading: bool,
) -> list[dict[str, Any]]:
    """Add conservative mobile-friendly emphasis when the model omitted it.

    Explicit model styles always win. We only bold short list labels and color
    well-known status/value phrases after a colon. This keeps rich Zalo output
    readable without guessing the meaning of arbitrary prose.
    """
    if not plain or is_heading:
        return spans

    result = [dict(item) for item in spans]
    label = _AUTO_LABEL_RE.match(plain)
    value_start = 0
    if label:
        label_start, label_end = label.span(1)
        value_start = label.end()
        # Automatically emphasize labels mainly in list items. For non-list
        # prose, only very short labels are treated as labels to avoid bolding
        # sentences such as "Ngày ... tương ứng với:".
        should_bold = is_list or label_end <= 24
        if should_bold and not any(_span_overlaps(x, label_start, label_end, style="b") for x in result):
            result.append({"start": label_start, "end": label_end, "st": "b"})
    else:
        # Whole-line coloring is intentionally limited to short standalone
        # status lines. Long explanatory prose is left neutral.
        if len(plain.strip()) > 36:
            return result

    search_start = value_start if label else 0
    if search_start >= len(plain):
        return result

    for pattern, color in _AUTO_STATUS_RULES:
        for match in pattern.finditer(plain, search_start):
            start, end = match.span()
            # Do not overwrite an explicit inline color from the model.
            if any(_span_overlaps(x, start, end, style_prefix=_COLOR_STYLE_PREFIX) for x in result):
                continue
            result.append({"start": start, "end": end, "st": color})
    return result


def _merge_char_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate/overlapping identical spans to keep Zalo payload small."""
    ordered = sorted(
        (dict(item) for item in spans),
        key=lambda item: (str(item.get("st") or ""), int(item.get("indentSize") or 0), int(item.get("start") or 0), int(item.get("end") or 0)),
    )
    merged: list[dict[str, Any]] = []
    for item in ordered:
        start = int(item.get("start") or 0)
        end = int(item.get("end") or 0)
        if end <= start:
            continue
        if merged:
            last = merged[-1]
            if (
                str(last.get("st") or "") == str(item.get("st") or "")
                and int(last.get("indentSize") or 0) == int(item.get("indentSize") or 0)
                and start <= int(last.get("end") or 0)
            ):
                last["end"] = max(int(last.get("end") or 0), end)
                continue
        merged.append(item)
    return merged


def _utf16_offsets(text: str) -> list[int]:
    """Map Python character boundaries to JavaScript UTF-16 code-unit offsets."""
    offsets = [0]
    total = 0
    for char in text:
        total += 2 if ord(char) > 0xFFFF else 1
        offsets.append(total)
    return offsets


def build_zalo_message_content(value: str) -> dict[str, Any]:
    """Return a zca-js MessageContent-compatible `{msg, styles}` object.

    The model may produce the supported Zalo markup syntax, but this compiler
    removes all visible markup delimiters and expresses formatting as zca-js
    style ranges. This is robust even when the companion Zalo Server endpoint
    does *not* perform Markdown parsing itself.
    """
    markup = format_zalo_message(value)
    lines = markup.split("\n") if markup else []
    plain_parts: list[str] = []
    char_spans: list[dict[str, Any]] = []
    char_offset = 0

    for index, raw in enumerate(lines):
        line = raw
        block_styles: list[str] = []
        indent_size = 0
        is_list = False
        is_heading = False

        heading = _HEADING_RE.match(line)
        if heading:
            is_heading = True
            level = min(len(heading.group(1)), 6)
            line = heading.group(2)
            if level <= 2:
                block_styles.extend(("f_18", "b"))
            elif level == 3:
                block_styles.append("b")
            else:
                block_styles.append("f_13")
        else:
            unordered = _UNORDERED_RE.match(line)
            ordered = _ORDERED_RE.match(line)
            quote = _BLOCKQUOTE_RE.match(line)
            if unordered:
                is_list = True
                indent_size = min(8, len(unordered.group(1).replace("\t", "    ")))
                line = unordered.group(2)
                block_styles.append("lst_1")
            elif ordered:
                is_list = True
                indent_size = min(8, len(ordered.group(1).replace("\t", "    ")))
                line = ordered.group(3)
                block_styles.append("lst_2")
            elif quote:
                indent_size = min(8, len(quote.group(1).replace("\t", "    ")))
                line = quote.group(2)
                block_styles.append("i")
            else:
                leading = len(line) - len(line.lstrip(" \t"))
                if leading:
                    prefix = line[:leading].replace("\t", "    ")
                    indent_size = min(8, len(prefix))
                    line = line[leading:]

        line_plain, inline_spans = _parse_inline_markup(line)
        inline_spans = _auto_enhance_line_styles(
            line_plain, inline_spans, is_list=is_list, is_heading=is_heading
        )
        line_start = char_offset
        plain_parts.append(line_plain)
        char_offset += len(line_plain)
        line_end = char_offset

        for span in inline_spans:
            shifted = dict(span)
            shifted["start"] = line_start + int(span["start"])
            shifted["end"] = line_start + int(span["end"])
            char_spans.append(shifted)

        if line_end > line_start:
            for style in block_styles:
                char_spans.append({"start": line_start, "end": line_end, "st": style})
            if indent_size:
                char_spans.append({
                    "start": line_start,
                    "end": line_end,
                    "st": "ind_$",
                    "indentSize": indent_size,
                })

        if index < len(lines) - 1:
            plain_parts.append("\n")
            char_offset += 1

    plain = "".join(plain_parts)
    char_spans = _merge_char_spans(char_spans)
    offsets = _utf16_offsets(plain)
    styles: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for span in char_spans:
        start_char = max(0, min(len(plain), int(span["start"])))
        end_char = max(start_char, min(len(plain), int(span["end"])))
        if end_char <= start_char:
            continue
        item: dict[str, Any] = {
            "start": offsets[start_char],
            "len": offsets[end_char] - offsets[start_char],
            "st": str(span["st"]),
        }
        if item["st"] == "ind_$":
            item["indentSize"] = max(1, min(8, int(span.get("indentSize") or 1)))
        key = (item["start"], item["len"], item["st"], item.get("indentSize"))
        if key in seen:
            continue
        seen.add(key)
        styles.append(item)

    styles.sort(key=lambda item: (int(item["start"]), -int(item["len"]), str(item["st"])))
    return {"msg": plain, "styles": styles}


def format_mobile_notification(value: str) -> str:
    """Convert model/Markdown-like output into readable plain mobile text.

    Home Assistant mobile notifications do not consistently render Markdown.
    Preserve structure with Unicode bullets/emojis while removing formatting
    delimiters so users never see raw `**`, `#`, backticks or pseudo tags.
    """
    markup = format_zalo_message(value)
    if not markup:
        return ""
    output: list[str] = []
    for raw in markup.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            output.append("")
            continue
        if line and set(line.strip()) <= {"─", "-", "_", "*"}:
            continue
        prefix = ""
        heading = _HEADING_RE.match(line)
        unordered = _UNORDERED_RE.match(line)
        ordered = _ORDERED_RE.match(line)
        quote = _BLOCKQUOTE_RE.match(line)
        if heading:
            prefix = "📌 "
        elif unordered:
            prefix = "• "
        elif ordered:
            prefix = f"{ordered.group(2)}. "
        elif quote:
            prefix = "💡 "
        plain = build_zalo_message_content(line).get("msg", "").strip()
        if plain:
            output.append(prefix + plain)
    result = "\n".join(output)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def format_mobile_notification_title(value: str) -> str:
    plain = build_zalo_message_content(str(value or "HassMind")).get("msg", "").strip() or "HassMind"
    return plain if plain.startswith("🤖") else f"🤖 {plain}"


def split_zalo_message(value: str, limit: int = 3900) -> list[str]:
    """Format and split a long answer, preferring whole Zalo sections.

    The returned chunks are still markup. Each chunk is compiled independently
    to `msg + styles[]` immediately before it is sent to Zalo Server.
    """
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
