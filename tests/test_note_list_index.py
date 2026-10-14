"""Compact catalogue must never be sent as a photo-gallery response."""
from io import BytesIO

import pytest
from PIL import Image

from app import db, notes
from app.settings import settings


@pytest.fixture
def isolated_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'db_path', str(tmp_path / 'hassmind.db'))
    db.init_db()


def photo():
    buf = BytesIO()
    Image.new('RGB', (24, 24), (90, 40, 210)).save(buf, 'PNG')
    return buf.getvalue()


@pytest.mark.parametrize('query', [
    'danh s\u00e1ch ghi ch\u00fa',
    'li\u1ec7t k\u00ea ghi ch\u00fa',
    'li\u1ec7t k\u00ea t\u1ea5t c\u1ea3 ghi ch\u00fa',
    'xem danh s\u00e1ch ghi ch\u00fa',
    'cho t\u00f4i xem danh s\u00e1ch ghi ch\u00fa',
    'danh sach cac ghi chu',
    'liet ke tat ca cac ghi chu',
    'hay liet ke ghi chu',
    'cho toi danh sach ghi chu',
    'cho minh xem danh sach cac ghi chu',
    'toan bo ghi chu',
    'xem ghi chu',
])
def test_index_variations(query, isolated_notes):
    # The unqualified "xem ghi chu" is a search prompt, not an index command.
    if query == 'xem ghi chu':
        assert notes.parse_note_command(query)[0] == 'search'
    else:
        assert notes.parse_note_command(query)[0] == 'list'


def test_empty_index(isolated_notes):
    result = notes.respond_to_note_command('danh sach ghi chu')
    assert result['mode'] == 'list'
    assert result['notes'] == []
    assert result['total'] == 0
    assert 'Ch\u01b0a c\u00f3 ghi ch\u00fa' in result['answer']


def test_index_only_counts_attachments_without_leaking_content(isolated_notes):
    one = notes.create_note('M\u1eabu thu\u1ed1c gi\u1ea3m \u0111au', 'secret pain note', images=[(photo(), 'one.png')])
    two = notes.create_note('M\u1eabu thu\u1ed1c an th\u1ea7n', 'secret sleep note', images=[(photo(), 'a.png'), (photo(), 'b.png')])
    three = notes.create_note('\u1ea2nh nh\u00e0 th\u1edd t\u1ed5', 'secret family note')
    response = notes.respond_to_note_command('li\u1ec7t k\u00ea ghi ch\u00fa')
    text = response['answer']
    assert response['total'] == 3
    assert response['notes'] == []
    for note in (one, two, three):
        assert note['id'] in text
        assert note['title'] in text
        assert note['content'] not in text
        assert all(image['id'] not in text for image in note['images'])
    assert text.count('1 \u1ea3nh') == 1
    assert text.count('2 \u1ea3nh') == 1
    assert text.count('\U0001f4f7') == 2
    search = notes.respond_to_note_command('t\u00ecm ghi ch\u00fa thu\u1ed1c an th\u1ea7n')
    assert search['notes'][0]['id'] == two['id']
    assert len(search['notes'][0]['images']) == 2
    detail = notes.respond_to_note_command(f'Xem ghi ch\u00fa #{one["id"]}')
    assert len(detail['notes'][0]['images']) == 1


def test_index_contains_all_notes_beyond_old_20_and_5_item_caps(isolated_notes):
    for index in range(117):
        notes.create_note(f'Unique item {index:03}', f'secret data {index:03}')
    result = notes.respond_to_note_command('danh sach ghi chu')
    assert result['total'] == 117
    assert result['notes'] == []
    assert result['answer'].count('Unique item') == 117
    assert 'Unique item 000' in result['answer']
    assert 'Unique item 116' in result['answer']
    assert 'secret data' not in result['answer']


def test_blank_search_does_not_fetch_entire_photo_collection(isolated_notes):
    notes.create_note('abc', 'abc', images=[(photo(), 'x.png')])
    result = notes.respond_to_note_command('t\u00ecm ghi ch\u00fa')
    assert result['notes'] == []
    assert 'Danh s\u00e1ch ghi ch\u00fa' in result['answer']
