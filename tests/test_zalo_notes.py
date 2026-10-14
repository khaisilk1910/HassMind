"""Zalo photo note input, signed transport, URL security and note attachment recall."""
import asyncio
import time
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from app import db, notes, zalo_notes, zalo_note_drafts
from app.settings import settings
from app.integrations.zalo import ZaloClient


@pytest.fixture(autouse=True)
def empty_ephemeral_zalo_buffers():
    zalo_notes._pending.clear()
    zalo_notes._followup.clear()
    yield
    zalo_notes._pending.clear()
    zalo_notes._followup.clear()


def photo():
    result = BytesIO()
    Image.new('RGB', (24, 22), (5, 10, 30)).save(result, format='PNG')
    return result.getvalue()


def test_zalo_photo_webhook_common_shapes():
    base = 'https://f6.photo.talk.zdn.vn/photo.jpg'
    for event in [
        {'message': {'msg': 'Ghi chú: Hoá đơn', 'attachments': [{'type': 'image', 'payload': {'url': base}}]}},
        {'data': {'content': {'href': base, 'thumb': base + '?thumb=1'}}},
        {'data': {'msgType': 'chat.photo', 'content': {'href': base}}},
        {'message': {'photo': base, 'caption': 'Ghi chú: Điện'}},
    ]:
        assert zalo_notes.image_urls_from_webhook(event) == [base]
    assert zalo_notes.image_urls_from_webhook({'message': {'text': 'Xem ghi chú', 'attachments': [{'type': 'sticker', 'payload': {'url': base}}]}}) == []
    assert zalo_notes.image_urls_from_webhook({'message': 'Hello'}) == []


@pytest.mark.parametrize('url', [
    'http://127.0.0.1:8090/image.png',
    'https://localhost/photo.jpg',
    'https://zdn.vn.attacker.com/file.jpg',
    'https://evil.com@localhost/pic.jpg',
    'file:///etc/shadow',
    'https://zdn.vn:8080/private',
    'http://169.254.169.254/latest/meta-data/',
    'https://zdn.vn/\r\nHost: localhost',
])
def test_reject_webhook_supplied_ssrf_urls(url):
    with pytest.raises(ValueError):
        zalo_notes.allowed_photo_url(url)


def test_public_photo_url_is_forced_https():
    assert zalo_notes.allowed_photo_url('http://f6.photo.talk.zdn.vn/a.jpg?q=1') == 'https://f6.photo.talk.zdn.vn/a.jpg?q=1'


def test_signed_photo_url_expiry_and_tamper(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    db.init_db()
    note = notes.create_note('Tờ hóa đơn', 'Điện tháng mười', images=[(photo(), 'bill.png')])
    photo_id = note['images'][0]['id']
    url = zalo_notes.signed_image_url(photo_id, base='http://hassmind:8090', secret='unique-super-secret')
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    expires = int(query['expires'][0])
    sig = query['sig'][0]
    assert parts.path == f'/media/zalo-note-images/{photo_id}'
    assert zalo_notes.check_image_signature(photo_id, expires, sig, 'unique-super-secret')
    assert not zalo_notes.check_image_signature(photo_id, expires, '0'*64, 'unique-super-secret')
    assert not zalo_notes.check_image_signature('0'*16, expires, sig, 'unique-super-secret')
    assert not zalo_notes.check_image_signature(photo_id, int(time.time()) - 1, sig, 'unique-super-secret')
    assert not zalo_notes.check_image_signature(photo_id, expires + 1500, sig, 'unique-super-secret')
    assert notes.image_info(photo_id)[0].is_file()


@pytest.mark.asyncio
async def test_image_first_then_text_creates_durable_note(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    db.init_db()
    session = 'zalo:account:123'
    await zalo_notes.buffer_photos(session, [(photo(), 'zalo-photo.png')])
    images = await zalo_notes.take_photos(session, [])
    saved = notes.respond_to_note_command('Ghi chú: Hóa đơn điện tháng 10', images)['notes'][0]
    assert len(saved['images']) == 1
    assert saved['id'] == notes.search_notes('hóa đơn điện')[0]['id']
    assert len(await zalo_notes.take_photos(session, [])) == 0


@pytest.mark.asyncio
async def test_text_first_then_image_attaches_to_recent_note(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    db.init_db()
    note = notes.respond_to_note_command('Ghi chú: Ảnh thẻ thành viên')['notes'][0]
    session = 'zalo:account:245'
    await zalo_notes.register_followup(session, note['id'])
    updated = await zalo_notes.append_followup(session, [(photo(), 'user_photo.png')])
    assert updated['id'] == note['id']
    assert len(updated['images']) == 1
    assert len(notes.respond_to_note_command('Tìm ghi chú ảnh thẻ')['notes'][0]['images']) == 1


@pytest.mark.asyncio
async def test_image_buffer_isolated_by_thread():
    await zalo_notes.buffer_photos('zalo:acc:one', [(photo(), 'a.png')])
    assert await zalo_notes.take_photos('zalo:acc:two', []) == []
    assert len(await zalo_notes.take_photos('zalo:acc:one', [])) == 1


@pytest.mark.asyncio
async def test_buffer_expiration():
    await zalo_notes.buffer_photos('zalo:acc:one', [(photo(), 'a.png')])
    old, images = zalo_notes._pending['zalo:acc:one']
    zalo_notes._pending['zalo:acc:one'] = old - zalo_notes.PENDING_SECONDS - 1, images
    assert await zalo_notes.take_photos('zalo:acc:one', []) == []


class FakeZalo(ZaloClient):
    def __init__(self):
        self.recorded = None

    async def ensure_login(self):
        pass

    async def _select_account(self, requested=''):
        return requested or 'a'

    async def request(self, method, path, **kwargs):
        self.recorded = (method, path, kwargs['json'])
        return {'success': True}


@pytest.mark.asyncio
async def test_companion_image_attachment_transport_contract():
    client = FakeZalo()
    await client.send_image(thread_id='23', message='📷 Hóa đơn điện', thread_type=0,
                            image_url='http://hassmind:8090/media/zalo-note-images/abc?expires=1&sig=x')
    method, path, body = client.recorded
    assert method == 'POST'
    assert path == '/api/sendImageByAccount'
    assert body['imagePath'].startswith('http://hassmind:8090/media/')
    assert body['threadId'] == '23'


def build_chat_handler():
    """Exercise exact production Zalo handler even without optional OpenAI/MCP packages."""
    import ast
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace
    from app.message_format import split_zalo_message

    tree = ast.parse((Path(__file__).parent.parent / 'app' / 'main.py').read_text(encoding='utf-8'))
    names = ('_extract_zalo_text', '_process_zalo_message')
    nodes = [item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in names]
    stub = SimpleNamespace(sent=[])

    async def send_message(**data):
        stub.sent.append(data)
        return {'success': True}

    stub.send_message = send_message
    async def send_image(**data):
        stub.sent.append({'_is_image': True, **data})
        return {'success': True, 'deliveryStatus': 'accepted'}
    async def download_incoming_image(token):
        return photo()
    stub.send_image = send_image
    async def send_images(**data):
        stub.sent.append({'_is_images': True, **data})
        return {'success': True, 'deliveryStatus': 'accepted'}
    stub.send_images = send_images
    stub.download_incoming_image = download_incoming_image
    scope = {
        'Any': __import__('typing').Any,
        'notes': notes, 'zalo_notes': zalo_notes, 'zalo_note_drafts': zalo_note_drafts, 'settings': settings,
        'time': time,
        'integrations': SimpleNamespace(zalo=stub),
        'agent': None, 'warning': lambda *a, **k: None,
        'info': lambda *a, **k: None,
        'exception': lambda *a, **k: print('EXCEPTION', a, k),
        'log_context': lambda **k: nullcontext(),
        'split_zalo_message': split_zalo_message,
        'add_event': lambda *a, **k: None,
        'logger': None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename='app/main.py', mode='exec'), scope)
    return scope['_process_zalo_message'], stub


@pytest.mark.asyncio
async def test_production_text_first_photo_and_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '123')
    monkeypatch.setattr(settings, 'zalo_media_base_url', 'http://hassmind:8090')
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'secret-from-a-test')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    monkeypatch.setattr(settings, 'runtime_secret_dir', str(tmp_path / 'secrets'))
    db.init_db()
    handle, zalo = build_chat_handler()
    await handle({'threadId': '123', 'msgId': 'text-1', 'message': 'Ghi chú: Hóa đơn điện tháng 10'})
    assert '60 giây' in zalo.sent[-1]['message']
    assert notes.list_notes()['total'] == 0
    assert zalo_note_drafts.get_draft('zalo:default:123')
    await handle({'threadId': '123', 'msgId': 'photo-1', '_hassmindImages': [{'token': 'a'*48}],
                  'data': {'msgType': 'chat.photo', 'content': '{}'}})
    note = notes.search_notes('hóa đơn điện')[0]
    assert len(note['images']) == 1
    await handle({'threadId': '123', 'msgId': 'done-1', 'message': 'Xong'})
    assert 'Đã lưu ghi chú' in zalo.sent[-1]['message']
    assert zalo_note_drafts.get_draft('zalo:default:123') is None
    await handle({'threadId': '123', 'msgId': 'query-1', 'message': 'Tìm ghi chú hóa đơn điện'})
    images = [message for message in zalo.sent if message.get('_is_image')]
    assert len(images) == 1
    params = parse_qs(urlsplit(images[0]['image_url']).query)
    assert zalo_notes.check_image_signature(note['images'][0]['id'], int(params['expires'][0]), params['sig'][0], settings.read_zalo_webhook_secret())


@pytest.mark.asyncio
async def test_caption_with_image_starts_draft_and_attaches(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '456')
    db.init_db()

    async def fake_download(url):
        return photo(), 'image.png'

    monkeypatch.setattr(zalo_notes, 'download_photo', fake_download)
    handle, zalo = build_chat_handler()
    await handle({'threadId': '456', 'msgId': 'caption-1',
                  'message': {'caption': 'Ghi chú: Thẻ bảo hành máy giặt', 'photo': 'https://f6.photo.talk.zdn.vn/test.jpg'}})
    assert len(notes.search_notes('thẻ bảo hành')[0]['images']) == 1
    assert '60 giây' in zalo.sent[0]['message']


@pytest.mark.asyncio
async def test_production_handler_rejects_untrusted_threads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '456')
    db.init_db()
    handle, zalo = build_chat_handler()
    await handle({'threadId': '999', 'message': {'text': 'Ghi chú: Đừng lưu'}})
    assert zalo.sent == []
    assert notes.list_notes()['total'] == 0


@pytest.mark.asyncio
async def test_zalo_webhook_redelivery_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '23')
    db.init_db()
    handle, zalo = build_chat_handler()
    event = {'threadId': '23', 'msgId': 'unique-msg-a21', 'message': 'Ghi chú: Nhắc bảo dưỡng máy lọc nước'}
    await handle(event)
    await handle(event)
    assert notes.list_notes()['total'] == 0
    assert zalo_note_drafts.get_draft('zalo:default:23')
    assert len(zalo.sent) == 1


@pytest.mark.asyncio
async def test_failed_image_keeps_draft_until_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '701')
    db.init_db()
    handler, zalo = build_chat_handler()
    await handler({'threadId': '701', 'message': 'Ghi chú: Hóa đơn không có ảnh'})
    await handler({'threadId': '701', '_hassmindPhoto': True, '_hassmindPhotoError': 'http_403',
                   'data': {'msgType': 'chat.photo', 'content': '{}'}})
    assert 'HTTP 403' in zalo.sent[-1]['message']
    assert zalo_note_drafts.get_draft('zalo:default:701')
    draft = zalo_note_drafts.get_draft('zalo:default:701')
    assert notes.list_notes()['total'] == 0
    assert 'zalo:default:701' in zalo_note_drafts.due_sessions(now=draft['deadline'] + 1)
    note, _ = zalo_note_drafts.finish_draft('zalo:default:701', now=draft['deadline'] + 1)
    assert note['images'] == []
    assert notes.search_notes('hóa đơn không có ảnh')[0]['id'] == note['id']


@pytest.mark.asyncio
async def test_no_early_photo_download_before_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '700')
    db.init_db()
    handler, zalo = build_chat_handler()
    async def impossible(*args):
        raise AssertionError('Photo must not be downloaded before the user creates a note')
    zalo.download_incoming_image = impossible
    await handler({'threadId': '700', '_hassmindImages': [{'token': 'a'*48}],
                   'data': {'msgType': 'chat.photo', 'content': '{}'}})
    assert 'Ghi chú: nội dung' in zalo.sent[-1]['message']
    assert notes.list_notes()['total'] == 0


@pytest.mark.asyncio
async def test_photo_relay_attaches_to_active_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '700')
    db.init_db()
    handler, zalo = build_chat_handler()
    await handler({'threadId': '700', 'message': 'Ghi chú: Ảnh gia đình họ tộc'})
    await handler({'threadId': '700', '_hassmindImages': [{'token': 'a'*48}],
                   'data': {'msgType': 'chat.photo', 'content': '{}'}})
    assert len(notes.search_notes('gia đình họ tộc')[0]['images']) == 1
    assert 'Đã nhận 1 ảnh' in zalo.sent[-1]['message']


@pytest.mark.asyncio
async def test_parallel_photo_and_finish_wait_for_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '800')
    db.init_db()
    handler, zalo = build_chat_handler()
    await handler({'threadId': '800', 'message': 'Ghi chú: Ảnh trên Zalo'})
    started = asyncio.Event()
    resume = asyncio.Event()
    async def late_photo(token):
        started.set()
        await resume.wait()
        return photo()
    zalo.download_incoming_image = late_photo
    first = asyncio.create_task(handler({'threadId': '800', '_hassmindImages': [{'token': 'b'*48}],
                                         'data': {'msgType': 'chat.photo', 'content': '{}'}}))
    await started.wait()
    second = asyncio.create_task(handler({'threadId': '800', 'message': 'Xong'}))
    await asyncio.sleep(0.01)
    assert notes.list_notes()['total'] == 0
    resume.set()
    await asyncio.gather(first, second)
    note = notes.search_notes('Ảnh trên Zalo')[0]
    assert len(note['images']) == 1
    assert zalo_note_drafts.get_draft('zalo:default:800') is None


def test_drafts_are_durable_across_reload_and_60_second_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    db.init_db()
    draft = zalo_note_drafts.start_draft('zalo:acc:thread', 'Tài liệu quan trọng', 'acc', 'thread', 0, now=1000)
    assert draft['deadline'] == 1060
    assert zalo_note_drafts.get_draft('zalo:acc:thread')['content'] == 'Tài liệu quan trọng'
    assert zalo_note_drafts.finish_draft('zalo:acc:thread', now=1059) is None
    note, _ = zalo_note_drafts.finish_draft('zalo:acc:thread', now=1060)
    assert note['content'] == 'Tài liệu quan trọng'
    assert note['images'] == []
    assert zalo_note_drafts.finish_draft('zalo:acc:thread', now=1061) is None


@pytest.mark.asyncio
async def test_max_5_photos_and_multiple_threads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    db.init_db()
    zalo_note_drafts.start_draft('s1', 'Ảnh 1', 'a', '1', 0)
    zalo_note_drafts.start_draft('s2', 'Ảnh 2', 'a', '2', 0)
    assert zalo_note_drafts.attach_draft_photos('s1', [(photo(), '1.png')] * 3)['images']
    assert len(zalo_note_drafts.attach_draft_photos('s1', [(photo(), '4.png')] * 2)['images']) == 5
    with pytest.raises(ValueError, match='5 ảnh'):
        zalo_note_drafts.attach_draft_photos('s1', [(photo(), 'extra.png')])
    assert notes.list_notes()['total'] == 1
    assert zalo_note_drafts.get_draft('s2') is not None

@pytest.mark.asyncio
async def test_empty_image_attachment_result_is_reported_not_ignored():
    from app.integrations.base import IntegrationError
    client = FakeZalo()

    async def empty_response(method, path, **kwargs):
        return {'success': True, 'data': {'message': None, 'attachment': []}}

    client.request = empty_response
    with pytest.raises(IntegrationError, match='empty attachment receipt'):
        await client.send_image(thread_id='23', message='Ảnh ghi chú', thread_type=0,
                                image_url='https://example.org/signed')


def test_zalo_photo_content_as_json_string_not_text():
    from json import dumps
    base = 'https://f6.photo.talk.zdn.vn/photo.jpg'
    payload = {'data': {'msgType': 'chat.photo', 'content': dumps({'href': base, 'thumb': base + '?low'})}}
    assert zalo_notes.image_urls_from_webhook(payload) == [base, base + '?low']
    from pathlib import Path
    import ast
    node = next(n for n in ast.parse((Path(__file__).parent.parent/'app'/'main.py').read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_extract_zalo_text')
    scope = {'Any': __import__('typing').Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
    assert scope['_extract_zalo_text'](payload) == ''


@pytest.mark.asyncio
async def test_background_timeout_persists_note_and_notifies_zalo(tmp_path, monkeypatch):
    import ast
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace

    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    db.init_db()
    context = zalo_note_drafts.start_draft('zalo:acc:922', 'Nội dung chờ tự lưu', 'acc', '922', 0)
    from app.db import conn
    with conn() as c:
        c.execute('UPDATE zalo_note_drafts SET deadline=? WHERE session_id=?',
                  (time.time() - 1, 'zalo:acc:922'))
    stop = asyncio.Event()
    messages = []
    async def send_message(**kwargs):
        messages.append(kwargs)
        stop.set()
    tree = ast.parse((Path(__file__).parent.parent / 'app' / 'main.py').read_text(encoding='utf-8'))
    node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == '_zalo_draft_expiry_loop')
    scope = {
        'asyncio': asyncio, 'stop_event': stop, 'zalo_note_drafts': zalo_note_drafts,
        'zalo_notes': zalo_notes, 'notes': notes, 'settings': settings,
        'integrations': SimpleNamespace(zalo=SimpleNamespace(send_message=send_message)),
        'exception': lambda *a, **k: None, 'logger': None,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
    await asyncio.wait_for(scope['_zalo_draft_expiry_loop'](), timeout=1)
    assert len(messages) == 1
    assert messages[0]['thread_id'] == '922'
    assert messages[0]['account_selection'] == 'acc'
    assert 'sau 60 giây' in messages[0]['message']
    assert notes.list_notes()['items'][0]['images'] == []
    assert zalo_note_drafts.get_draft('zalo:acc:922') is None


def color_photo(rgb: tuple[int, int, int]) -> bytes:
    result = BytesIO()
    Image.new('RGB', (96, 68), rgb).save(result, 'PNG')
    return result.getvalue()


@pytest.mark.parametrize('count', [2, 3, 4, 5])
@pytest.mark.asyncio
async def test_multi_photo_recall_uses_each_stored_file_not_collage(tmp_path, monkeypatch, count):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '123')
    monkeypatch.setattr(settings, 'zalo_media_base_url', 'http://hassmind:8090')
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'secure-test-secret')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    db.init_db()
    colors = [(220, 20, 20), (10, 200, 15), (15, 25, 220), (225, 220, 30), (200, 20, 220)]
    note = notes.create_note('Nhà thờ tổ', 'Ảnh nhà thờ tổ họ tộc #giadinh',
                             images=[(color_photo(color), f'{i}.png') for i, color in enumerate(colors[:count])])
    handle, zalo = build_chat_handler()
    await handle({'threadId': '123', 'msgId': f'query-original-album-{count}', 'message': 'Tìm ghi chú nhà thờ tổ'})
    assert len(zalo.sent) == 1, zalo.sent
    sent = zalo.sent[0]
    assert sent.get('_is_images') is True
    assert sent['thread_type'] == 0
    assert sent['message'] == note['content']
    urls = sent['image_urls']
    assert len(urls) == count
    for url, item in zip(urls, note['images']):
        parts = urlsplit(url)
        assert parts.path == f'/media/zalo-note-images/{item["id"]}'
        params = parse_qs(parts.query)
        assert zalo_notes.check_image_signature(item['id'], int(params['expires'][0]),
                                                params['sig'][0], 'secure-test-secret')
        saved_bytes = notes.image_info(item['id'])[0].read_bytes()
        with Image.open(BytesIO(saved_bytes)) as im:
            assert im.size == (96, 68)  # Never rendered into contact-sheet thumbnails.
    assert not any('zalo-note-albums' in url for url in urls)


@pytest.mark.asyncio
async def test_multi_album_missing_photo_does_not_send_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '123')
    monkeypatch.setattr(settings, 'zalo_media_base_url', 'http://hassmind:8090')
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'secure-test-secret')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    db.init_db()
    note = notes.create_note('Nhà thờ', 'Ảnh nhà thờ tổ họ tộc', images=[(photo(), 'a.png'), (photo(), 'b.png')])
    notes.image_info(note['images'][1]['id'])[0].unlink()
    handle, zalo = build_chat_handler()
    await handle({'threadId': '123', 'msgId': 'query-missing', 'message': 'Tìm ghi chú nhà thờ tổ'})
    assert len(zalo.sent) == 1
    assert '_is_images' not in zalo.sent[0]
    assert 'Không gửi được' in zalo.sent[0]['message']


@pytest.mark.asyncio
async def test_multi_album_client_contract_receipts():
    class AlbumZalo(FakeZalo):
        def __init__(self, confirmed):
            super().__init__()
            self.confirmed = confirmed
        async def request(self, method, path, **kwargs):
            self.recorded = (method, path, kwargs['json'])
            return {'success': True, 'deliveryStatus': 'accepted',
                    'data': {'attachment': [{'msgId': f'x{i}'} for i in range(self.confirmed)]}}
    client = AlbumZalo(3)
    urls = [f'http://hassmind:8090/media/zalo-note-images/{n}' for n in ('a', 'b', 'c')]
    await client.send_images(thread_id='zalo:123', thread_type=1, image_urls=urls,
                             message='Ảnh nhà thờ tổ')
    method, path, body = client.recorded
    assert (method, path) == ('POST', '/api/sendImagesByAccount')
    assert body['imagePaths'] == urls and body['message'] == 'Ảnh nhà thờ tổ'
    assert body['threadId'] == '123' and body['type'] == 1
    bad = AlbumZalo(1)
    from app.integrations.base import IntegrationError
    with pytest.raises(IntegrationError, match='not fully confirmed'):
        await bad.send_images(thread_id='123', thread_type=0, image_urls=urls, message='Album')
    for invalid in ([], [urls[0]], urls * 2):
        with pytest.raises(IntegrationError):
            await client.send_images(thread_id='123', thread_type=0, image_urls=invalid)


@pytest.mark.asyncio
async def test_photo_recall_single_still_has_full_note_caption(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '999')
    monkeypatch.setattr(settings, 'zalo_media_base_url', 'http://hassmind:8090')
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'secret-v1515')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    db.init_db()
    note = notes.create_note('Sổ đỏ', 'Ảnh giấy tờ nhà tháng 10', images=[(photo(), 'paper.png')])
    handle, zalo = build_chat_handler()
    await handle({'threadId': '999', 'msgId': 'query-single-1', 'message': f'Xem ghi chú #{note["id"]}'})
    assert len(zalo.sent) == 1
    assert zalo.sent[0]['message'] == note['content']
    assert f'/media/zalo-note-images/{note["images"][0]["id"]}' in zalo.sent[0]['image_url']


@pytest.mark.asyncio
async def test_signed_image_endpoint_returns_stored_file_without_reencoding(tmp_path, monkeypatch):
    import ast
    from pathlib import Path
    from fastapi import HTTPException, Query
    from fastapi.responses import FileResponse
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'test-image-secret')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    db.init_db()
    note = notes.create_note('Cổng nhà', 'Ảnh trước sau sửa chữa', images=[(photo(), 'a.png'), (photo(), 'b.png')])
    tree = ast.parse((Path(__file__).parent.parent / 'app/main.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'signed_zalo_note_image')
    node.decorator_list = []
    scope = {'settings': settings, 'zalo_notes': zalo_notes, 'notes': notes,
             'HTTPException': HTTPException, 'FileResponse': FileResponse, 'Query': Query}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app/main.py', 'exec'), scope)
    handler = scope['signed_zalo_note_image']
    item = note['images'][0]
    url = zalo_notes.signed_image_url(item['id'], base='http://hassmind:8090', secret='test-image-secret')
    query = parse_qs(urlsplit(url).query)
    expires, sig = int(query['expires'][0]), query['sig'][0]
    response = await handler(item['id'], expires, sig)
    assert isinstance(response, FileResponse)
    assert response.path == notes.image_info(item['id'])[0]
    assert response.headers['cache-control'] == 'private, no-store'
    with pytest.raises(HTTPException) as error:
        await handler(item['id'], expires, '0' * 64)
    assert error.value.status_code == 404


def test_zalo_photo_fallback_candidates_are_not_separate_attachments():
    original = 'https://f6.photo.talk.zdn.vn/original.jpg'
    preview = 'https://f6.photo.talk.zdn.vn/preview.jpg'
    result = zalo_notes.image_urls_from_webhook({'data': {'msgType': 'chat.photo', 'content': {
        'hdUrl': original, 'href': original, 'thumb': preview,
    }}})
    assert result == [original, preview]
    assert len(result) == 2  # distinct download candidates, not two note images


@pytest.mark.asyncio
async def test_zalo_precise_note_search_only_sends_matching_stored_photo(tmp_path, monkeypatch):
    """Zalo must never receive a gallery of unrelated note photos."""
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '123')
    monkeypatch.setattr(settings, 'zalo_media_base_url', 'http://hassmind:8090')
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'secret-from-a-test')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    monkeypatch.setattr(settings, 'runtime_secret_dir', str(tmp_path / 'secrets'))
    db.init_db()
    notes.create_note('mẫu thuốc giảm đau', 'mẫu thuốc giảm đau', images=[(photo(), 'pain.png')])
    target = notes.create_note('mẫu thuốc an thần', 'mẫu thuốc an thần', images=[(photo(), 'sleep.png')])
    notes.create_note('Ảnh nhà thờ tổ', 'Ảnh nhà thờ tổ họ tiên', images=[(photo(), 'church.png')])
    handle, zalo = build_chat_handler()
    await handle({'threadId': '123', 'msgId': 'precise-search-1', 'message': 'tìm ghi chú thuốc an thần'})
    image_sends = [item for item in zalo.sent if item.get('_is_image') or item.get('_is_images')]
    assert len(image_sends) == 1
    assert target['images'][0]['id'] in image_sends[0]['image_url']
    assert image_sends[0]['message'] == 'mẫu thuốc an thần'
    assert len(zalo.sent) == 1
    await handle({'threadId': '123', 'msgId': 'precise-search-2', 'message': 'tìm ghi chú thuốc cảm lạnh'})
    assert len(zalo.sent) == 2
    assert 'Không tìm thấy ghi chú' in zalo.sent[-1]['message']
    assert not zalo.sent[-1].get('_is_image')


@pytest.mark.asyncio
async def test_zalo_listing_sends_all_note_titles_and_counts_but_no_photos(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '123')
    monkeypatch.setattr(settings, 'zalo_media_base_url', 'http://hassmind:8090')
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'secret-for-list-test')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    db.init_db()
    pain = notes.create_note('Pain sample', 'private medicine detail', images=[(photo(), 'pain.png')])
    sleep = notes.create_note('Sleep sample', 'private prescription detail',
                              images=[(photo(), 'a.png'), (photo(), 'b.png')])
    church = notes.create_note('Family building', 'private family detail')
    handle, zalo = build_chat_handler()
    await handle({'threadId': '123', 'msgId': 'list-index-1',
                  'message': 'li\u1ec7t k\u00ea t\u1ea5t c\u1ea3 ghi ch\u00fa'})
    assert zalo.sent
    assert all(not s.get('_is_image') and not s.get('_is_images') for s in zalo.sent)
    all_text = '\n'.join(item['message'] for item in zalo.sent)
    for note in (pain, sleep, church):
        assert note['title'] in all_text
        assert note['content'] not in all_text
        assert note['id'] in all_text
    assert '2 \u1ea3nh' in all_text and '1 \u1ea3nh' in all_text
    assert '/media/zalo-note-images/' not in all_text
    assert len(zalo.sent) <= 3

    await handle({'threadId': '123', 'msgId': 'find-one-2',
                  'message': 't\u00ecm ghi ch\u00fa Sleep sample'})
    images = [item for item in zalo.sent if item.get('_is_image') or item.get('_is_images')]
    assert len(images) == 1
    assert images[0]['_is_images'] is True
    assert len(images[0]['image_urls']) == 2
