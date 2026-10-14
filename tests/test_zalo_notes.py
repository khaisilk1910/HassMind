"""Zalo photo note input, signed transport, URL security and note attachment recall."""
import asyncio
import time
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from app import db, notes, zalo_notes
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
    stub.download_incoming_image = download_incoming_image
    scope = {
        'Any': __import__('typing').Any,
        'notes': notes, 'zalo_notes': zalo_notes, 'settings': settings,
        'integrations': SimpleNamespace(zalo=stub),
        'agent': None, 'warning': lambda *a, **k: None,
        'info': lambda *a, **k: None,
        'exception': lambda *a, **k: None,
        'log_context': lambda **k: nullcontext(),
        'split_zalo_message': split_zalo_message,
        'add_event': lambda *a, **k: None,
        'logger': None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename='app/main.py', mode='exec'), scope)
    return scope['_process_zalo_message'], stub


@pytest.mark.asyncio
async def test_production_handler_zalo_photo_first_then_note_and_photo_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '123')
    monkeypatch.setattr(settings, 'zalo_media_base_url', 'http://hassmind:8090')
    monkeypatch.setattr(settings, 'zalo_webhook_secret', 'secret-from-a-test')
    monkeypatch.setattr(settings, 'zalo_webhook_secret_file', '')
    monkeypatch.setattr(settings, 'runtime_secret_dir', str(tmp_path / 'secrets'))
    db.init_db()
    normalized = notes.encode_image(photo(), 'original.png')[1]

    async def fake_download(url):
        assert url.startswith('https://f6.photo.talk.zdn.vn')
        return normalized, 'photo.jpg'

    monkeypatch.setattr(zalo_notes, 'download_photo', fake_download)
    handle, zalo = build_chat_handler()
    await handle({'threadId': '123', 'message': {'attachments': [{'type': 'image', 'payload': {'url': 'https://f6.photo.talk.zdn.vn/unique.jpg'}}]}})
    assert 'Đã nhận' in zalo.sent[-1]['message']
    await handle({'threadId': '123', 'message': {'text': 'Ghi chú: Hóa đơn điện tháng 10'}})
    note = notes.search_notes('hóa đơn điện')[0]
    assert len(note['images']) == 1
    await handle({'threadId': '123', 'message': {'text': 'Tìm ghi chú hóa đơn điện'}})
    assert len(zalo.sent) >= 4
    assert any('Hóa đơn điện' in message['message'] for message in zalo.sent)
    images = [message for message in zalo.sent if message.get('_is_image')]
    assert len(images) == 1
    photo_url = images[0]['image_url']
    params = parse_qs(urlsplit(photo_url).query)
    assert zalo_notes.check_image_signature(note['images'][0]['id'], int(params['expires'][0]), params['sig'][0], settings.read_zalo_webhook_secret())


@pytest.mark.asyncio
async def test_production_handler_zalo_caption_plus_image(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '456')
    db.init_db()

    async def fake_download(url):
        return photo(), 'image.png'

    monkeypatch.setattr(zalo_notes, 'download_photo', fake_download)
    handle, zalo = build_chat_handler()
    await handle({'threadId': '456', 'message': {'caption': 'Ghi chú: Thẻ bảo hành máy giặt', 'photo': 'https://f6.photo.talk.zdn.vn/test.jpg'}})
    assert notes.search_notes('thẻ bảo hành')[0]['images']
    assert 'Đã lưu ghi chú' in zalo.sent[0]['message']


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
    assert notes.list_notes()['total'] == 1
    assert len(zalo.sent) == 1

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
    assert zalo_notes.image_urls_from_webhook(payload) == [base]
    from pathlib import Path
    import ast
    node = next(n for n in ast.parse((Path(__file__).parent.parent/'app'/'main.py').read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_extract_zalo_text')
    scope = {'Any': __import__('typing').Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
    assert scope['_extract_zalo_text'](payload) == ''

@pytest.mark.asyncio
async def test_cached_zalo_photo_reaches_note_without_public_cdn(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '700')
    db.init_db()
    handler, zalo = build_chat_handler()
    # No reachable external URL; media is received through the authenticated server.
    await handler({'threadId': '700', '_hassmindImages': [{'token': 'a'*48}],
                   'data': {'msgType': 'chat.photo', 'content': '{}'}})
    assert 'Đã nhận 1 ảnh' in zalo.sent[-1]['message']
    await handler({'threadId': '700', 'message': 'Ghi chú: Ảnh gia đình họ tộc'})
    assert len(notes.search_notes('gia đình họ tộc')[0]['images']) == 1

@pytest.mark.asyncio
async def test_bad_cached_token_does_not_access_remote_url(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '700')
    db.init_db()
    handler, zalo = build_chat_handler()
    await handler({'threadId': '700', '_hassmindImages': [{'token': 'a'*48}],
                   'data': {'msgType': 'chat.photo', 'content': '{}'}})
    assert 'Đã nhận' in zalo.sent[-1]['message']

@pytest.mark.asyncio
async def test_fast_followup_command_waits_until_photo_is_buffered(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    monkeypatch.setattr(settings, 'zalo_agent_reply_enabled', True)
    monkeypatch.setattr(settings, 'zalo_allow_send', True)
    monkeypatch.setattr(settings, 'zalo_agent_allowed_thread_ids', '800')
    db.init_db()
    handler, zalo = build_chat_handler()
    start = asyncio.Event()
    finish = asyncio.Event()

    async def late_photo(token):
        start.set()
        await finish.wait()
        return photo()

    zalo.download_incoming_image = late_photo
    first = asyncio.create_task(handler({'threadId': '800', '_hassmindImages': [{'token': 'b'*48}],
                                         'data': {'msgType': 'chat.photo', 'content': '{}'}}))
    await start.wait()
    second = asyncio.create_task(handler({'threadId': '800', 'message': 'Ghi chú: Ảnh trên Zalo'}))
    await asyncio.sleep(0.01)
    assert notes.list_notes()['total'] == 0
    finish.set()
    await asyncio.gather(first, second)
    note = notes.search_notes('Ảnh trên Zalo')[0]
    assert len(note['images']) == 1
