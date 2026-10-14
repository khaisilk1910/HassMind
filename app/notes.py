"""Durable, source-backed personal notes with private, validated image attachments.

Notes deliberately do not share the short-lived conversation-history lifecycle.
Commands are deterministic; original text is returned rather than LLM-generated guesses.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .db import conn, utcnow
from .settings import settings

MAX_IMAGES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_NOTE_CHARS = 12000
MAX_PIXELS = 16_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
STOPWORDS = set("""toi minh cua ban la gi ve voi cho xem tim lai da duoc mot nhung trong khi nay kia roi nay co khong ghi chu luu noi dung anh hinh xin hay giup nhe nao den dieu thong tin can biet hoi nhac nhung tu den va cac theo o duoi tren nhe no ma""".split())
IMAGE_DIR_NAME = 'note_images'


def image_dir() -> Path:
    root = Path(settings.db_path).resolve().parent / IMAGE_DIR_NAME
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError('Invalid image storage directory')
    return root


def fold(value: str) -> str:
    value = str(value or '').replace('đ', 'd').replace('Đ', 'D')
    plain = ''.join(ch for ch in unicodedata.normalize('NFD', value.casefold())
                    if unicodedata.category(ch) != 'Mn')
    # A small explicit vocabulary of common Vietnamese synonyms, not AI guesses.
    return re.sub(r'\bmay\s+lanh\b', 'dieu hoa', plain)


def terms(value: str) -> list[str]:
    words = re.findall(r'[a-z0-9]{2,}', fold(value))
    return list(dict.fromkeys(w for w in words if w not in STOPWORDS))[:20]


def normalize_tags(tags: list[str] | str | None) -> list[str]:
    if isinstance(tags, str):
        tags = re.split(r'[,\s]+', tags)
    if not isinstance(tags, list):
        return []
    result = []
    for tag in tags:
        label = str(tag).strip().lstrip('#')[:40]
        if re.fullmatch(r'[\w\-]{1,40}', label, flags=re.UNICODE) and label.casefold() not in {x.casefold() for x in result}:
            result.append(label)
        if len(result) >= 12:
            break
    return result


def init_notes_db(c) -> None:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS notes (
      id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
      tags_json TEXT NOT NULL DEFAULT '[]', search_text TEXT NOT NULL,
      pinned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(pinned DESC, updated_at DESC);
    CREATE TABLE IF NOT EXISTS note_images (
      id TEXT PRIMARY KEY, note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
      filename TEXT NOT NULL UNIQUE, mime TEXT NOT NULL, original_name TEXT NOT NULL,
      bytes INTEGER NOT NULL, position INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_note_images_note ON note_images(note_id, position);
    ''')
    try:
        c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(note_id UNINDEXED, searchable, tokenize="unicode61")')
    except Exception:  # Some SQLite builds omit FTS5; LIKE scoring still works.
        pass


def _search_text(title: str, content: str, tags: list[str]) -> str:
    return fold(' '.join([title, content, ' '.join(tags)]))


def _refresh_fts(c, note_id: str, searchable: str | None) -> None:
    try:
        c.execute('DELETE FROM notes_fts WHERE note_id=?', (note_id,))
        if searchable is not None:
            c.execute('INSERT INTO notes_fts(note_id,searchable) VALUES(?,?)', (note_id, searchable))
    except Exception:  # FTS is optional and never required for note integrity.
        pass


def _serialize(c, row, *, with_content=True) -> dict:
    result = dict(row)
    result['tags'] = json.loads(result.pop('tags_json'))
    result.pop('search_text', None)
    result['pinned'] = bool(result['pinned'])
    if not with_content:
        result['content'] = result['content'][:250]
    images = c.execute('SELECT id, original_name, bytes FROM note_images WHERE note_id=? ORDER BY position', (result['id'],)).fetchall()
    result['images'] = [{'id': item['id'], 'name': item['original_name'], 'bytes': item['bytes'],
                         'url': f'/api/notes/images/{item["id"]}'} for item in images]
    return result


def get_note(note_id: str) -> dict | None:
    with conn() as c:
        row = c.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
        return _serialize(c, row) if row else None


def list_notes(limit: int = 50, offset: int = 0) -> dict:
    with conn() as c:
        total = c.execute('SELECT count(*) FROM notes').fetchone()[0]
        rows = c.execute('SELECT * FROM notes ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?',
                         (min(100, max(1, limit)), max(0, offset))).fetchall()
        return {'total': total, 'items': [_serialize(c, row) for row in rows]}


def _words(value: str) -> list[str]:
    """Accented Vietnamese is folded, then matched on complete word boundaries.

    A substring check is unsafe here: e.g. 'an' (an thần) must not match
    'anh' (ảnh); 'thuốc' alone must not imply 'thuốc an thần'.
    """
    return re.findall(r'[a-z0-9]+', fold(value))


def _has_phrase(words: list[str], phrase: list[str]) -> bool:
    """Whether all words occur consecutively within ONE note field."""
    width = len(phrase)
    return bool(width) and any(words[i:i + width] == phrase for i in range(len(words) - width + 1))


def search_notes(query: str, limit: int = 10, *, include_all: bool = False) -> list[dict]:
    if not query.strip():
        return list_notes(limit)['items'] if include_all else []
    tokens = terms(query)
    if not tokens:
        return []

    # Strict intersection, not union: do not leak unrelated note images when a
    # query happens to share just 'thuốc', 'ảnh', or a short word like 'an'.
    # Full token matching below is authoritative; FTS/LIKE only select candidates.
    candidate_limit = 1000
    with conn() as c:
        rows = []
        try:
            expression = ' AND '.join(f'"{token}"' for token in tokens)
            rows = c.execute(
                'SELECT n.* FROM notes n JOIN notes_fts f ON f.note_id=n.id '
                'WHERE notes_fts MATCH ? LIMIT ?',
                (expression, candidate_limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # SQLite FTS5 is optional, and old installations may not have it.
            pass
        if not rows:
            # The cheap LIKE intersection is only a prefilter. Exact-token
            # checks below remove all substring false positives.
            clauses = ' AND '.join('search_text LIKE ?' for _ in tokens)
            rows = c.execute(
                f'SELECT * FROM notes WHERE {clauses} LIMIT ?',
                [*[f'%{token}%' for token in tokens], candidate_limit],
            ).fetchall()

        matches = []
        for row in rows:
            title_words = _words(row['title'])
            content_words = _words(row['content'])
            tag_words = _words(' '.join(json.loads(row['tags_json'])))
            title_set, content_set, tag_set = set(title_words), set(content_words), set(tag_words)
            if not set(tokens).issubset(title_set | content_set | tag_set):
                continue

            # A complete contiguous phrase is more trustworthy than the same
            # words scattered across a note. Prefer phrase results exclusively
            # when any are available; otherwise return full-token matches.
            title_phrase = _has_phrase(title_words, tokens)
            content_phrase = _has_phrase(content_words, tokens)
            tag_phrase = _has_phrase(tag_words, tokens)
            phrase = title_phrase or content_phrase or tag_phrase
            title_hits = sum(t in title_set for t in tokens)
            content_hits = sum(t in content_set for t in tokens)
            tag_hits = sum(t in tag_set for t in tokens)
            score = (100 if title_phrase else 65 if content_phrase else 55 if tag_phrase else 0)
            score += 12 * title_hits + 5 * tag_hits + 2 * content_hits
            matches.append((phrase, score, int(row['pinned']), row['updated_at'], row))

        if any(item[0] for item in matches):
            matches = [item for item in matches if item[0]]
        matches.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
        return [{**_serialize(c, row), '_matches': len(tokens), '_ratio': 1.0}
                for _, _, _, _, row in matches[:min(50, max(1, limit))]]


def image_info(image_id: str) -> tuple[Path, str] | None:
    with conn() as c:
        row = c.execute('SELECT filename,mime FROM note_images WHERE id=?', (image_id,)).fetchone()
    if not row or not re.fullmatch(r'[0-9a-f]{32}\.jpe?g|[0-9a-f]{32}\.png', row['filename']):
        return None
    path = image_dir() / row['filename']
    if not path.is_file() or path.is_symlink():
        return None
    return path, row['mime']


def encode_image(data: bytes, original_name: str, *, max_input_bytes: int = MAX_IMAGE_BYTES) -> tuple[str, bytes, str]:
    if not data or len(data) > max_input_bytes:
        raise ValueError(f'Mỗi ảnh phải nhỏ hơn hoặc bằng {max_input_bytes // (1024 * 1024)} MB.')
    if len(original_name or '') > 255:
        raise ValueError('Tên ảnh quá dài.')
    try:
        with Image.open(io.BytesIO(data)) as src:
            if src.format not in ('JPEG', 'PNG', 'WEBP', 'GIF'):
                raise ValueError('Chỉ hỗ trợ ảnh JPEG, PNG, WebP hoặc GIF.')
            if src.width < 1 or src.height < 1 or src.width * src.height > MAX_PIXELS:
                raise ValueError('Ảnh vượt giới hạn 16 megapixel.')
            src.seek(0)
            img = ImageOps.exif_transpose(src)
            img.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            # All uploads are decoded and rewritten to remove EXIF, SVG/HTML,
            # embedded scripts, ancillary chunks, and arbitrary user filenames.
            if 'A' in img.getbands():
                img.convert('RGBA').save(buf, format='PNG', optimize=True)
                extension, mime = '.png', 'image/png'
            else:
                img.convert('RGB').save(buf, format='JPEG', quality=85, optimize=True)
                extension, mime = '.jpg', 'image/jpeg'
            result = buf.getvalue()
            if len(result) > 7 * 1024 * 1024:
                raise ValueError('Ảnh sau xử lý vẫn quá lớn.')
            return extension, result, mime
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('File không phải ảnh hợp lệ hoặc ảnh quá lớn.') from exc


def create_note(title: str, content: str, tags: list[str] | str | None = None,
                *, pinned: bool = False, images: list[tuple[bytes, str]] | None = None,
                max_input_bytes: int = MAX_IMAGE_BYTES) -> dict:
    title, content = str(title).strip(), str(content).strip()
    if not content or not title or len(content) > MAX_NOTE_CHARS or len(title) > 160:
        raise ValueError('Tiêu đề và nội dung phải có dữ liệu (tối đa 160 / 12.000 ký tự).')
    images = images or []
    if len(images) > MAX_IMAGES:
        raise ValueError('Tối đa 5 ảnh cho mỗi ghi chú.')
    encoded = [(*encode_image(blob, name, max_input_bytes=max_input_bytes), str(name or 'Ảnh')[:120]) for blob, name in images]
    note_id = secrets.token_hex(8)
    now = utcnow()
    tags_clean = normalize_tags(tags)
    stored = []
    try:
        for position, (extension, blob, mime, original_name) in enumerate(encoded):
            filename = secrets.token_hex(16) + extension
            path = image_dir() / filename
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(blob)
            stored.append((secrets.token_hex(8), note_id, filename, mime, original_name, len(blob), position))
        searchable = _search_text(title, content, tags_clean)
        with conn() as c:
            c.execute('INSERT INTO notes(id,title,content,tags_json,search_text,pinned,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                      (note_id, title, content, json.dumps(tags_clean, ensure_ascii=False), searchable, int(pinned), now, now))
            for entry in stored:
                c.execute('INSERT INTO note_images(id,note_id,filename,mime,original_name,bytes,position) VALUES(?,?,?,?,?,?,?)', entry)
            _refresh_fts(c, note_id, searchable)
    except Exception:
        for entry in stored:
            (image_dir() / entry[2]).unlink(missing_ok=True)
        raise
    return get_note(note_id)


def update_note(note_id: str, *, title: str, content: str, tags: list[str] | str | None = None,
                pinned: bool = False) -> dict | None:
    title, content = str(title).strip(), str(content).strip()
    if not title or not content or len(title) > 160 or len(content) > MAX_NOTE_CHARS:
        raise ValueError('Tiêu đề hoặc nội dung không hợp lệ.')
    clean_tags = normalize_tags(tags)
    search = _search_text(title, content, clean_tags)
    with conn() as c:
        result = c.execute('UPDATE notes SET title=?,content=?,tags_json=?,search_text=?,pinned=?,updated_at=? WHERE id=?',
                           (title, content, json.dumps(clean_tags, ensure_ascii=False), search, int(pinned), utcnow(), note_id))
        if not result.rowcount:
            return None
        _refresh_fts(c, note_id, search)
    return get_note(note_id)


def append_images(note_id: str, images: list[tuple[bytes, str]],
                  *, max_input_bytes: int = MAX_IMAGE_BYTES) -> dict | None:
    if not get_note(note_id):
        return None
    with conn() as c:
        count = c.execute('SELECT count(*) FROM note_images WHERE note_id=?', (note_id,)).fetchone()[0]
    if count + len(images) > MAX_IMAGES:
        raise ValueError('Một ghi chú chỉ được có tối đa 5 ảnh.')
    encoded = [(*encode_image(blob, name, max_input_bytes=max_input_bytes), str(name or 'Ảnh')[:120]) for blob, name in images]
    stored = []
    try:
        for position, (ext, blob, mime, original_name) in enumerate(encoded, count):
            filename = secrets.token_hex(16) + ext
            descriptor = os.open(image_dir() / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(blob)
            stored.append((secrets.token_hex(8), note_id, filename, mime, original_name, len(blob), position))
        with conn() as c:
            for entry in stored:
                c.execute('INSERT INTO note_images(id,note_id,filename,mime,original_name,bytes,position) VALUES(?,?,?,?,?,?,?)', entry)
            c.execute('UPDATE notes SET updated_at=? WHERE id=?', (utcnow(), note_id))
    except Exception:
        for entry in stored:
            (image_dir() / entry[2]).unlink(missing_ok=True)
        raise
    return get_note(note_id)


def remove_image(note_id: str, image_id: str) -> bool:
    with conn() as c:
        row = c.execute('SELECT filename FROM note_images WHERE note_id=? AND id=?', (note_id, image_id)).fetchone()
        if not row:
            return False
        c.execute('DELETE FROM note_images WHERE id=? AND note_id=?', (image_id, note_id))
    (image_dir() / row['filename']).unlink(missing_ok=True)
    return True


def delete_note(note_id: str) -> bool:
    with conn() as c:
        rows = c.execute('SELECT filename FROM note_images WHERE note_id=?', (note_id,)).fetchall()
        changed = c.execute('DELETE FROM notes WHERE id=?', (note_id,)).rowcount
        if changed:
            _refresh_fts(c, note_id, None)
    if changed:
        for row in rows:
            (image_dir() / row['filename']).unlink(missing_ok=True)
    return bool(changed)


_CREATE = re.compile(r'^\s*(?:hãy\s+)?(?:ghi\s+chú|ghi\s+nhớ|lưu\s+(?:lại|ghi\s+chú|giúp\s+(?:tôi|mình))|tạo\s+ghi\s+chú|note\s*:|remember\s*:)(?:\s+(?:rằng|là|về|nội\s+dung|giúp\s+tôi))?\s*[:：,\-]?\s*(.*)$', re.I | re.S)
_SEARCH = re.compile(r'^\s*(?:tìm(?:\s+lại)?\s+ghi\s+chú|tra\s+(?:cứu\s+)?ghi\s+chú|xem(?:\s+lại)?\s+ghi\s+chú|cho\s+(?:tôi|mình)\s+xem\s+ghi\s+chú|ghi\s+chú\s+(?:về|liên\s+quan|nào)|tôi\s+(?:đã\s+)?ghi\s+chú\s+(?:gì|những\s+gì)\s+(?:về|liên\s+quan)|(?:hình|ảnh)\s+(?:của\s+)?ghi\s+chú|đọc\s+ghi\s+chú|nhắc\s+lại\s+ghi\s+chú)\s*[:：,\-]?\s*(.*)$', re.I | re.S)
# Search commands written without Vietnamese diacritics are common on Zalo.
# Apply this only to retrieval intentions; do not reinterpret "ghi chu: ..."
# as a create command and do not mutate the stored original content.
_SEARCH_PLAIN = re.compile(r'^\s*(?:tim(?:\s+lai)?\s+ghi\s+chu|tra(?:\s+cuu)?\s+ghi\s+chu|xem(?:\s+lai)?\s+ghi\s+chu|cho\s+(?:toi|minh)\s+xem\s+ghi\s+chu)\s*[:：,\-]?\s*(.*)$', re.I | re.S)
_LIST_PLAIN = re.compile(r'^\s*(?:danh\s+sach|liet\s+ke|tat\s+ca|toan\s+bo|xem\s+tat\s+ca)\s+(?:cac\s+)?ghi\s+chu\s*[?!.]*\s*$', re.I)
_LIST = re.compile(r'^\s*(?:danh\s+sách|liệt\s+kê|tất\s+cả|toàn\s+bộ|xem\s+tất\s+cả)\s+(?:các\s+)?ghi\s+chú\s*[?!.]*\s*$', re.I)
_ID = re.compile(r'^\s*(?:xem|mở|đọc|tìm)\s+ghi\s+chú\s*#?([a-f0-9]{16})\s*[?.!]*$', re.I)
_EDIT = re.compile(r'^\s*(?:sửa|cập\s+nhật)\s+ghi\s+chú\s*#([a-f0-9]{16})\s*[:：]\s*(.+)$', re.I | re.S)
_APPEND = re.compile(r'^\s*(?:thêm\s+vào|bổ\s+sung\s+vào)\s+ghi\s+chú\s*#([a-f0-9]{16})\s*[:：]\s*(.+)$', re.I | re.S)
_PIN = re.compile(r'^\s*(ghim|bỏ\s+ghim)\s+ghi\s+chú\s*#([a-f0-9]{16})\s*$', re.I)
_DELETE = re.compile(r'^\s*xóa\s+ghi\s+chú\s*#([a-f0-9]{16})(?:\s+(xác\s+nhận))?\s*$', re.I)
_ATTACH = re.compile(r'^\s*(?:thêm|gắn|đính\s+kèm)\s+ảnh\s+(?:vào|cho)\s+ghi\s+chú\s*#([a-f0-9]{16})(?:\s*[:：]\s*(.*))?$', re.I | re.S)



def parse_note_command(message: str) -> tuple[str, str] | None:
    s = str(message or '').strip()
    for pattern, action in ((_EDIT, 'edit'), (_APPEND, 'append'), (_PIN, 'pin'),
                            (_DELETE, 'delete'), (_ATTACH, 'attach')):
        match = pattern.match(s)
        if match:
            if action == 'pin':
                return 'pin' if fold(match.group(1)) == 'ghim' else 'unpin', match.group(2).lower()
            if action == 'delete':
                return ('delete' if match.group(2) else 'delete_confirm'), match.group(1).lower()
            if action == 'attach':
                return 'attach', match.group(1).lower() + ':' + (match.group(2) or '').strip()
            return action, match.group(1).lower() + ':' + match.group(2).strip()
    plain = fold(s)
    if _LIST.fullmatch(s) or _LIST_PLAIN.fullmatch(plain) or plain in ('ghi chu', 'cac ghi chu', 'notes'):
        return 'list', ''
    m = _ID.match(s)
    if m:
        return 'show', m.group(1).lower()
    # "Ghi chú về X?" asks for an existing note; it MUST NOT create one.
    m = _SEARCH.match(s)
    if m:
        return 'search', m.group(1).strip(' ?!.:')
    # Do this after the accented command so any original text is preserved.
    m = _SEARCH_PLAIN.match(plain)
    if m:
        return 'search', m.group(1).strip(' ?!.:')
    m = _CREATE.match(s)
    if m:
        return 'create', m.group(1).strip()
    if re.search(r'\bghi\s+chú\b', s, re.I) and ('?' in s or any(x in fold(s) for x in ('toi da', 'o dau', 'la gi'))):
        prefix = re.sub(r'(?i)\bghi\s+chú\b', '', s)
        return 'search', prefix.strip(' ?!.,:')
    return None


def clean_search_query(text: str) -> str:
    text = re.sub(r'^(?:về|liên quan đến|cho tôi|cho mình|của tôi|giúp tôi|lại|nội dung|ảnh|hình)\s+', '', text.strip(), flags=re.I)
    return text.strip(' ?!.,:')


def note_response(note: dict) -> str:
    tags = ' '.join('#' + x for x in note['tags'])
    return (f'**{note["title"]}**  ·  Mã `{note["id"]}`\n\n{note["content"]}'
            + (f'\n\n{tags}' if tags else '')
            + (f'\n\n📷 {len(note["images"])} ảnh đính kèm (hiển thị bên dưới).' if note['images'] else '')
            + f'\n\n_Lưu lúc: {note["created_at"]}_')


def respond_to_note_command(message: str, images: list[tuple[bytes, str]] | None = None, *, allow_generic=True) -> dict | None:
    command = parse_note_command(message)
    images = images or []
    if images and (not command or command[0] not in ('create', 'attach')):
        return {'answer': 'Để lưu ảnh, hãy bắt đầu bằng “Ghi chú: ...” hoặc “Thêm ảnh vào ghi chú #MÃ”. Ảnh chưa được lưu.', 'notes': []}
    if command:
        action, payload = command
        if action in ('edit', 'append', 'pin', 'unpin', 'delete', 'delete_confirm', 'attach'):
            note_id, separator, remainder = payload.partition(':')
            note = get_note(note_id)
            if not note:
                return {'answer': 'Không tìm thấy ghi chú có mã này.', 'notes': []}
            if action == 'delete_confirm':
                return {'answer': f'Để xóa vĩnh viễn ghi chú **{note["title"]}**, hãy gửi nguyên câu: `Xóa ghi chú #{note_id} xác nhận`.', 'notes': [note]}
            if action == 'delete':
                delete_note(note_id)
                return {'answer': f'🗑️ Đã xóa ghi chú `{note_id}` và các ảnh liên quan.', 'notes': []}
            if action == 'attach':
                if not images:
                    return {'answer': 'Hãy đính kèm ảnh khi gửi câu lệnh thêm ảnh.', 'notes': [note]}
                updated = append_images(note_id, images)
                if remainder.strip():
                    new_text = note['content'] + '\n' + remainder.strip()
                    if len(new_text) <= MAX_NOTE_CHARS:
                        updated = update_note(note_id, title=note['title'], content=new_text,
                                              tags=note['tags'], pinned=note['pinned'])
                return {'answer': '✅ Đã bổ sung ảnh vào ghi chú.\n\n' + note_response(updated), 'notes': [updated]}
            if action in ('edit', 'append'):
                content = remainder if action == 'edit' else note['content'] + '\n' + remainder
                if not remainder or len(content) > MAX_NOTE_CHARS:
                    return {'answer': 'Nội dung không hợp lệ hoặc vượt giới hạn 12.000 ký tự.', 'notes': [note]}
                updated = update_note(note_id, title=note['title'], content=content,
                                      tags=note['tags'], pinned=note['pinned'])
                return {'answer': '✅ Đã cập nhật ghi chú.\n\n' + note_response(updated), 'notes': [updated]}
            updated = update_note(note_id, title=note['title'], content=note['content'],
                                  tags=note['tags'], pinned=action == 'pin')
            return {'answer': ('📌 Đã ghim' if action == 'pin' else 'Đã bỏ ghim') + ' ghi chú.\n\n' + note_response(updated), 'notes': [updated]}
        if action == 'create':
            if not payload:
                return {'answer': 'Bạn hãy nhập nội dung sau “Ghi chú:”, có thể đính kèm tối đa 5 ảnh.', 'notes': []}
            if len(payload) > MAX_NOTE_CHARS:
                return {'answer': 'Ghi chú quá dài (tối đa 12.000 ký tự). Vui lòng rút gọn trước khi lưu.', 'notes': []}
            content = payload
            title = content.splitlines()[0].strip()[:110]
            note = create_note(title, content, re.findall(r'#([\w\-]+)', content), images=images)
            return {'answer': '✅ Đã lưu ghi chú lâu dài (không bị xóa cùng lịch sử chat).\n\n' + note_response(note), 'notes': [note]}
        if action == 'show':
            note = get_note(payload)
            return {'answer': note_response(note) if note else 'Không tìm thấy ghi chú có mã này.', 'notes': [note] if note else []}
        if action == 'list' or (action == 'search' and not clean_search_query(payload)):
            found = list_notes(20)['items']
        else:
            found = search_notes(clean_search_query(payload), 8)
        if not found:
            return {'answer': 'Không tìm thấy ghi chú phù hợp. Hãy thử dùng một từ khóa cụ thể hơn hoặc mở mục Ghi chú để tìm kiếm.', 'notes': []}
        # Return original content and original images: never fabricate answers.
        return {'answer': ('📚 **Ghi chú đã lưu:**\n\n' if len(found) > 1 else '')
                + '\n\n---\n\n'.join(note_response(n) for n in found[:5])
                + ('\n\n_Có thêm kết quả; mở mục Ghi chú để xem._' if len(found) > 5 else ''),
                'notes': found[:5]}
    current_state = bool(re.search(r'(?i)\b(?:hiện tại|bây giờ|lúc này|đang bật|đang tắt|trạng thái hiện|nhiệt độ hiện|độ ẩm hiện)\b', message))
    if allow_generic and not current_state and ('?' in message or re.search(r'(?i)^(?:mã|mat khau|mật khẩu|địa chỉ|số|ở đâu|bao nhiêu|tôi đã|nhắc lại|bạn nhớ)', message.strip())):
        found = search_notes(message, 3)
        if found and found[0]['_matches'] >= 2 and found[0]['_ratio'] >= 0.68:
            found = [found[0]]
            return {'answer': '🔎 Tôi tìm thấy ghi chú liên quan (trích nguyên văn để tránh suy đoán):\n\n' + note_response(found[0]), 'notes': found}
    return None
