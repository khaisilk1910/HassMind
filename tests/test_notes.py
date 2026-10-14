"""Durable notes, Vietnamese chat intent, safe multimodal attachment handling."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from app import db, notes
from app.settings import settings


@pytest.fixture
def note_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'data' / 'hassmind.db'))
    db.init_db()
    return tmp_path


def photo_bytes(fmt='PNG'):
    buf = BytesIO()
    Image.new('RGB', (35, 25), (120, 35, 30)).save(buf, format=fmt)
    return buf.getvalue()


def test_create_note_image_recall_and_chat_retention(note_db, monkeypatch):
    recorded = notes.respond_to_note_command('Ghi chú: Hóa đơn điện phòng khách tháng 10 #giadinh',
                                             [(photo_bytes(), '../../bad.png')])
    note = recorded['notes'][0]
    assert note['tags'] == ['giadinh']
    assert note['images'][0]['url'].startswith('/api/notes/images/')
    assert '../' not in notes.image_info(note['images'][0]['id'])[0].name
    with Image.open(notes.image_info(note['images'][0]['id'])[0]) as img:
        assert img.format == 'JPEG'
    by_text = notes.respond_to_note_command('Tìm ghi chú về hóa đơn điện')
    assert by_text['notes'][0]['id'] == note['id']
    assert by_text['notes'][0]['images'] == note['images']
    db.add_message('s', 'user', 'Tìm ghi chú về hóa đơn điện', 'web')
    db.add_message('s', 'assistant', by_text['answer'], 'web', note_ids=[note['id']])
    assert db.get_messages('s', include_created_at=True)[-1]['note_ids'] == [note['id']]
    tz = ZoneInfo('Asia/Ho_Chi_Minh')
    monkeypatch.setattr(db, 'local_now', lambda: datetime(2026, 10, 15, 0, 1, tzinfo=tz))
    db.cleanup_chat_history()
    assert db.get_messages('s', include_created_at=True) == []
    assert notes.get_note(note['id']) is not None
    assert notes.image_info(note['images'][0]['id']) is not None


def test_search_is_not_accidental_creation(note_db):
    for text in ('Ghi chú về wifi', 'Ghi chú về máy lạnh?', 'Tìm ghi chú về máy lạnh'):
        assert notes.parse_note_command(text)[0] == 'search'
    assert notes.respond_to_note_command('Ghi chú về máy lạnh')['notes'] == []
    assert notes.list_notes()['total'] == 0
    assert notes.respond_to_note_command('Bật đèn phòng khách') is None
    assert notes.respond_to_note_command('Ảnh này là gì?', [(photo_bytes(), 'a.png')])['notes'] == []
    assert notes.list_notes()['total'] == 0


def test_text_chat_recall_original_and_update(note_db):
    original = notes.respond_to_note_command('Ghi chú: Mã wifi phòng khách là 123Abc #wifi')['notes'][0]
    retrieved = notes.respond_to_note_command('Mã wifi phòng khách là gì?')
    assert retrieved and retrieved['notes'][0]['id'] == original['id']
    assert '123Abc' in retrieved['answer']
    changed = notes.update_note(original['id'], title='Thông tin wifi',
                                content='Mã wifi phòng khách là XYZ', tags='wifi, nhà', pinned=True)
    assert changed['pinned'] is True and changed['tags'] == ['wifi', 'nhà']
    assert 'XYZ' in notes.respond_to_note_command('tìm ghi chú về wifi')['answer']
    assert notes.delete_note(original['id']) is True
    assert notes.delete_note(original['id']) is False
    assert not notes.search_notes('wifi')


def test_image_validation_and_deletion(note_db):
    with pytest.raises(ValueError):
        notes.create_note('Bad', 'Bad', images=[(b'<svg onload="alert(1)"></svg>', 'x.png')])
    with pytest.raises(ValueError):
        notes.create_note('Bad', 'Bad', images=[(b'X' * (notes.MAX_IMAGE_BYTES + 1), 'oversized')])
    assert notes.list_notes()['total'] == 0
    note = notes.create_note('Y', 'Valid', images=[(photo_bytes(), 'ok.png')])
    photo = note['images'][0]
    assert notes.remove_image(note['id'], 'notfound') is False
    assert notes.remove_image(note['id'], photo['id']) is True
    assert notes.image_info(photo['id']) is None
    note = notes.append_images(note['id'], [(photo_bytes(), 'other.png')])
    path = notes.image_info(note['images'][0]['id'])[0]
    assert path.is_file()
    assert notes.delete_note(note['id'])
    assert not path.exists()


def test_tags_search_accents_and_list(note_db):
    one = notes.create_note('Lịch bảo dưỡng điều hòa', 'Kiểm tra bộ lọc ngày 20', ['BaoTri'])
    two = notes.create_note('Quà sinh nhật', 'Tặng sách', ['gia_dinh'])
    assert notes.search_notes('bao duong dieu hoa')[0]['id'] == one['id']
    assert notes.search_notes('baoTri')[0]['id'] == one['id']
    listed = notes.respond_to_note_command('Liệt kê ghi chú')
    assert len(listed['notes']) == 2
    assert notes.respond_to_note_command('Xem ghi chú #'+two['id'])['notes'][0]['id'] == two['id']


def test_chat_edit_pin_append_delete_requires_explicit_confirmation(note_db):
    note = notes.respond_to_note_command('Ghi chú: Công việc cần kiểm tra #job')['notes'][0]
    key = note['id']
    assert notes.respond_to_note_command(f'Ghim ghi chú #{key}')['notes'][0]['pinned'] is True
    assert 'Ngày mai' in notes.respond_to_note_command(f'Thêm vào ghi chú #{key}: Ngày mai')['answer']
    assert 'Mới hoàn toàn' in notes.respond_to_note_command(f'Sửa ghi chú #{key}: Mới hoàn toàn')['answer']
    assert 'Ngày mai' not in notes.get_note(key)['content']
    assert notes.respond_to_note_command(f'Bỏ ghim ghi chú #{key}')['notes'][0]['pinned'] is False
    request = notes.respond_to_note_command(f'Xóa ghi chú #{key}')
    assert 'xác nhận' in request['answer'] and notes.get_note(key) is not None
    assert notes.respond_to_note_command(f'Xóa ghi chú #{key} xác nhận')['notes'] == []
    assert notes.get_note(key) is None


def test_chat_append_photo_to_existing_note(note_db):
    note = notes.create_note('Lưu chứng từ', 'Bản gốc')
    answer = notes.respond_to_note_command(f'Thêm ảnh vào ghi chú #{note["id"]}: ảnh mặt sau',
                                           [(photo_bytes(), 'receipt.png')])
    assert len(answer['notes'][0]['images']) == 1
    assert 'ảnh mặt sau' in notes.get_note(note['id'])['content']
    assert notes.respond_to_note_command(f'Thêm ảnh vào ghi chú #{note["id"]}')['notes'][0]['images']
    assert len(notes.list_notes()['items']) == 1


def test_precise_vietnamese_note_search_does_not_return_unrelated_photos(note_db):
    """Regression: Zalo used to send every stored photo for 'thuốc an thần'."""
    pain = notes.create_note('mẫu thuốc giảm đau', 'mẫu thuốc giảm đau',
                             images=[(photo_bytes(), 'pain.png')])
    sleep = notes.create_note('mẫu thuốc an thần', 'mẫu thuốc an thần',
                              images=[(photo_bytes(), 'sleep.png')])
    church = notes.create_note('Ảnh nhà thờ tổ', 'Ảnh nhà thờ tổ họ tiên',
                               tags=['gia', 'dinh'], images=[(photo_bytes(), 'church.png')])

    for query in ('tìm ghi chú thuốc an thần', 'Tìm ghi chú về thuốc an thần',
                  'TIM GHI CHU THUOC AN THAN', 'tìm ghi chú mẫu thuốc an thần',
                  'tìm ghi chú thuốc an thần của tôi'):
        # The chat parser supports accented and unaccented retrieval intents.
        matches = notes.respond_to_note_command(query)['notes']
        assert [x['id'] for x in matches] == [sleep['id']], query
        assert [img['id'] for img in matches[0]['images']] == [sleep['images'][0]['id']]

    assert [x['id'] for x in notes.respond_to_note_command('tìm ghi chú thuốc giảm đau')['notes']] == [pain['id']]
    assert [x['id'] for x in notes.respond_to_note_command('tìm ghi chú nhà thờ tổ')['notes']] == [church['id']]
    assert {x['id'] for x in notes.respond_to_note_command('tìm ghi chú thuốc')['notes']} == {pain['id'], sleep['id']}
    assert {x['id'] for x in notes.respond_to_note_command('danh sách ghi chú')['notes']} == {pain['id'], sleep['id'], church['id']}
    assert notes.respond_to_note_command('tìm ghi chú thuốc cảm lạnh')['notes'] == []


def test_search_requires_complete_words_and_prefers_exact_phrases(note_db):
    exact = notes.create_note('Danh mục thuốc an thần', 'Thông tin chính')
    # All words match, but not the phrase, so it must not beat the exact note.
    scattered = notes.create_note('Thuốc cần nhớ', 'Thông tin về an toàn khi dùng thuốc thần kinh')
    substring = notes.create_note('Thuốc giảm đau', 'Gửi anh Thành xem trước')
    assert [n['id'] for n in notes.search_notes('thuốc an thần')] == [exact['id']]
    assert [n['id'] for n in notes.search_notes('thuốc an')] == [exact['id']]
    assert notes.search_notes('thuốc ngủ sai tên') == []
    assert notes.search_notes('thuốc không tồn tại') == []
    assert substring['id'] not in {n['id'] for n in notes.search_notes('an')}
    # A full-token match remains possible if there is no contiguous phrase.
    assert [n['id'] for n in notes.search_notes('nhớ thông tin')] == [scattered['id']]


def test_exact_search_fallback_when_sqlite_fts_unavailable(note_db):
    target = notes.create_note('Mẫu thuốc an thần', 'Thông tin ảnh')
    notes.create_note('Thuốc giảm đau', 'Nội dung không liên quan')
    notes.create_note('Ảnh nhà thờ tổ', 'Gia đình')
    with db.conn() as c:
        c.execute('DROP TABLE IF EXISTS notes_fts')
    assert [n['id'] for n in notes.search_notes('thuoc an than')] == [target['id']]
    assert notes.search_notes('thuoc an nghi') == []
