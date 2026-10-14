"""Bridge Zalo personal-account image messages and HassMind's durable notes.

The companion delivers webhooks and fetches short-lived signed image URLs.
No image URL from a webhook is allowed to reach private/internal services.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import re
import socket
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from . import notes

# The Zalo personal-account photo CDNs and the official OA photo CDNs.
# Deliberately do not accept arbitrary webhook-supplied URLs (SSRF).
IMAGE_HOST_SUFFIXES = ("zdn.vn", "zadn.vn", "zalo.me", "zaloapp.com", "zapps.me")
PENDING_SECONDS = 600
FOLLOWUP_SECONDS = 180
MAX_PENDING_SESSIONS = 32
MAX_PENDING_BYTES = 40 * 1024 * 1024
SIGNED_URL_SECONDS = 600

_pending: OrderedDict[str, tuple[float, list[tuple[bytes, str]]]] = OrderedDict()
_followup: dict[str, tuple[float, str]] = {}
_seen_events: OrderedDict[str, float] = OrderedDict()
_pending_lock = asyncio.Lock()


def image_urls_from_webhook(payload: dict[str, Any]) -> list[str]:
    """Read known personal-Zalo / OA photo shapes, never arbitrary URLs or links."""
    found: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip() and value.strip() not in found:
            found.append(value.strip())

    def inspect(obj: Any, *, depth: int = 0, image_context: bool = False) -> None:
        if depth > 5:
            return
        if isinstance(obj, list):
            for item in obj[:notes.MAX_IMAGES]:
                inspect(item, depth=depth + 1, image_context=image_context)
            return
        if not isinstance(obj, dict):
            return
        marker = str(obj.get('type') or obj.get('msgType') or obj.get('media_type') or '').lower()
        is_photo = image_context or any(t in marker for t in ('image', 'photo', 'picture', 'chat.photo'))
        if isinstance(obj.get('photo'), str):
            add(obj['photo'])
        if isinstance(obj.get('image_url'), str):
            add(obj['image_url'])
        if is_photo:
            for key in ('href', 'url', 'oriUrl', 'hdUrl', 'normalUrl', 'photoUrl'):
                add(obj.get(key))
        # zca-js content object has an image href and thumbnail even when msgType is on its parent.
        if isinstance(obj.get('href'), str) and ('thumb' in obj or 'width' in obj) and not marker.startswith('link'):
            add(obj['href'])
        for key in ('attachments', 'attachment', 'payload', 'message', 'data', 'content'):
            if key == 'content' and marker and not is_photo and any(t in marker for t in ('sticker', 'link')):
                continue
            child = obj.get(key)
            if isinstance(child, (dict, list)):
                inspect(child, depth=depth + 1, image_context=is_photo if key in ('payload', 'content') else False)

    inspect(payload)
    return found[:notes.MAX_IMAGES]


def allowed_photo_url(value: str) -> str:
    """Enforce recognized external image hosts; never fetch private network IPs."""
    try:
        if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError
        url = urlsplit(value)
        host = (url.hostname or '').lower().rstrip('.')
        if url.username or url.password or url.port not in (None, 80, 443):
            raise ValueError
        if url.scheme not in ('http', 'https') or not host or len(value) > 4096:
            raise ValueError
        if not any(host == suffix or host.endswith('.' + suffix) for suffix in IMAGE_HOST_SUFFIXES):
            raise ValueError
        if not re.fullmatch(r'[a-z0-9.-]+', host):
            raise ValueError
        # Some Zalo webhook URLs use http; request HTTPS even when HTTP was advertised.
        return urlunsplit(('https', url.netloc.split(':')[0], url.path, url.query, ''))
    except (ValueError, TypeError) as exc:
        raise ValueError('URL ảnh Zalo không được phép truy cập.') from exc


def _public_dns_only(host: str) -> None:
    """DNS check complements the strict CDN allowlist and disabled redirects."""
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError('Không phân giải được tên miền ảnh Zalo.') from exc
    if not addresses:
        raise ValueError('Không tìm thấy địa chỉ ảnh Zalo.')
    for item in addresses:
        try:
            ip = ipaddress.ip_address(item[4][0])
        except ValueError as exc:
            raise ValueError('Địa chỉ ảnh không hợp lệ.') from exc
        if not ip.is_global:
            raise ValueError('Từ chối tải ảnh từ địa chỉ nội bộ.')


async def download_photo(url: str) -> tuple[bytes, str]:
    safe_url = allowed_photo_url(url)
    await asyncio.to_thread(_public_dns_only, urlsplit(safe_url).hostname or '')
    async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), follow_redirects=False, trust_env=False) as client:
        async with client.stream('GET', safe_url, headers={'Accept': 'image/jpeg,image/png,image/webp,image/gif'}) as response:
            response.raise_for_status()
            mime = response.headers.get('content-type', '').split(';', 1)[0].lower()
            if mime not in ('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/octet-stream'):
                raise ValueError('Zalo không trả về nội dung ảnh hợp lệ.')
            if int(response.headers.get('content-length', '0') or 0) > notes.MAX_IMAGE_BYTES:
                raise ValueError('Ảnh Zalo vượt giới hạn 5 MB.')
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > notes.MAX_IMAGE_BYTES:
                    raise ValueError('Ảnh Zalo vượt giới hạn 5 MB.')
                chunks.append(chunk)
    raw = b''.join(chunks)
    # Decode and re-encode immediately, stripping EXIF/malicious ancillary data.
    ext, normalized, _ = notes.encode_image(raw, 'zalo-photo')
    return normalized, 'zalo-photo' + ext


def _prune(now: float) -> None:
    for key, at in list(_seen_events.items()):
        if now - at > PENDING_SECONDS:
            _seen_events.pop(key, None)
    for key, (at, _) in list(_pending.items()):
        if now - at > PENDING_SECONDS:
            _pending.pop(key, None)
    for key, (at, _) in list(_followup.items()):
        if now - at > FOLLOWUP_SECONDS:
            _followup.pop(key, None)


async def buffer_photos(session: str, photos: list[tuple[bytes, str]]) -> int:
    async with _pending_lock:
        now = time.monotonic()
        _prune(now)
        old = _pending.pop(session, (now, []))[1]
        merged = (old + photos)[-notes.MAX_IMAGES:]
        _pending[session] = (now, merged)
        while len(_pending) > MAX_PENDING_SESSIONS or sum(sum(len(b) for b, _ in p) for _, p in _pending.values()) > MAX_PENDING_BYTES:
            _pending.popitem(last=False)
        return len(merged)


async def take_photos(session: str, incoming: list[tuple[bytes, str]]) -> list[tuple[bytes, str]]:
    async with _pending_lock:
        _prune(time.monotonic())
        buffered = _pending.pop(session, (0, []))[1]
        merged = buffered + incoming
        if len(merged) > notes.MAX_IMAGES:
            # Do not quietly drop image attachments from notes.
            _pending[session] = (time.monotonic(), buffered)
            raise ValueError('Một ghi chú chỉ chứa tối đa 5 ảnh. Hãy chia thành nhiều ghi chú.')
        return merged


async def register_followup(session: str, note_id: str) -> None:
    async with _pending_lock:
        _prune(time.monotonic())
        _followup[session] = (time.monotonic(), note_id)


async def append_followup(session: str, images: list[tuple[bytes, str]]) -> dict | None:
    async with _pending_lock:
        _prune(time.monotonic())
        item = _followup.get(session)
        if not item:
            return None
        # Keep the lock through the append to avoid concurrent duplicate attachments.
        note = notes.append_images(item[1], images)
        if note and len(note['images']) >= notes.MAX_IMAGES:
            _followup.pop(session, None)
        return note


def _message_id(payload: dict[str, Any]) -> str:
    for source in (payload, payload.get('message'), payload.get('data'),
                   (payload.get('message') or {}).get('data') if isinstance(payload.get('message'), dict) else None):
        if isinstance(source, dict):
            for key in ('msgId', 'msg_id', 'message_id', 'cliMsgId'):
                value = source.get(key)
                if isinstance(value, (str, int)) and value:
                    return str(value)[:150]
    return ''


async def claim_event(session: str, payload: dict[str, Any]) -> bool:
    """Ignore redelivery of the same Zalo message so notes aren't duplicated."""
    msg_id = _message_id(payload)
    if not msg_id:
        return True
    key = session + ':' + msg_id
    async with _pending_lock:
        _prune(time.monotonic())
        if key in _seen_events:
            return False
        _seen_events[key] = time.monotonic()
        while len(_seen_events) > 3000:
            _seen_events.popitem(last=False)
        return True


async def clear_followup(session: str) -> None:
    async with _pending_lock:
        _followup.pop(session, None)


def image_signature(image_id: str, expires: int, secret: str) -> str:
    return hmac.new(secret.encode('utf-8'), f'{image_id}:{expires}'.encode('ascii'), hashlib.sha256).hexdigest()


def check_image_signature(image_id: str, expires: int, signature: str, secret: str) -> bool:
    if not re.fullmatch(r'[0-9a-f]{16}', image_id):
        return False
    now = int(time.time())
    if not secret or expires < now or expires > now + SIGNED_URL_SECONDS or not re.fullmatch(r'[0-9a-f]{64}', signature):
        return False
    return hmac.compare_digest(image_signature(image_id, expires, secret), signature)


def signed_image_url(image_id: str, *, base: str, secret: str) -> str:
    if not secret:
        raise ValueError('Chưa cấu hình Zalo webhook secret để ký URL ảnh.')
    parsed = urlsplit(base.strip().rstrip('/'))
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Cần cấu hình ZALO_MEDIA_BASE_URL hợp lệ.')
    expires = int(time.time()) + SIGNED_URL_SECONDS
    sig = image_signature(image_id, expires, secret)
    return f'{base.strip().rstrip("/")}/media/zalo-note-images/{quote(image_id)}?expires={expires}&sig={sig}'
