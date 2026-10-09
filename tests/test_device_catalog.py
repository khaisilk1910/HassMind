"""Regression tests for Home Assistant Device-first Knowledge import."""
import tempfile
import unittest
from pathlib import Path

import yaml

from app import device_catalog, knowledge_governance as kg, rag
from app.db import init_db
from app.settings import settings


DEVICES = [
    {"id": "ha-bom-001", "name": "Original name", "name_by_user": "Ổ cắm Bơm Nước",
     "area_id": "kitchen", "manufacturer": "Tuya", "model": "TS011F_plug_1",
     "identifiers": [["z2m", "bom"]]},
    {"id": "ha-02", "name": "Quạt", "area_id": "bedroom", "manufacturer": "Tuya", "model": "Fan"},
]
ENTITIES = [
    {"device_id": "ha-bom-001", "entity_id": "switch.bom_nuoc", "name": "Bơm nước"},
    {"device_id": "ha-bom-001", "entity_id": "sensor.bom_power", "original_name": "Power",
     "original_device_class": "power"},
    {"device_id": "ha-bom-001", "entity_id": "select.bom_outage", "disabled_by": "user"},
    {"device_id": "ha-02", "entity_id": "fan.quat", "name": "Quạt"},
]
AREAS = [{"area_id": "kitchen", "name": "Bếp"}, {"area_id": "bedroom", "name": "Phòng ngủ"}]


class DeviceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: getattr(settings, k) for k in ('db_path', 'knowledge_dir')}
        settings.db_path = str(Path(self.tmp.name)/'data'/'app.db')
        settings.knowledge_dir = str(Path(self.tmp.name)/'knowledge')
        Path(settings.knowledge_dir).mkdir()
        init_db()
        kg.ensure_schema()
        rag.reindex_knowledge()

    def tearDown(self):
        for k, value in self.saved.items():
            setattr(settings, k, value)
        self.tmp.cleanup()

    def test_discover_groups_entities_by_device_registry_id(self):
        result = device_catalog.discover(DEVICES, ENTITIES, AREAS)
        pump = next(d for d in result if d['device_id'] == 'ha-bom-001')
        self.assertEqual(pump['name'], 'Ổ cắm Bơm Nước')
        self.assertEqual(pump['area'], 'Bếp')
        self.assertEqual(pump['entity_count'], 3)
        self.assertEqual(pump['active_count'], 2)
        self.assertTrue(any(e['device_class'] == 'power' for e in pump['entities']))
        self.assertFalse(pump['imported'])

    def test_import_requires_approval_and_keeps_entity_discovery_dynamic(self):
        devices = device_catalog.discover(DEVICES, ENTITIES, AREAS)
        proposal = device_catalog.create_import_proposal(devices, 'ha-bom-001', 'Ổ cắm Bơm Nước',
                                                         ['bơm nước', 'ổ điện bơm'], 'admin')
        path = Path(settings.knowledge_dir) / '21-devices.yaml'
        self.assertFalse(path.exists())
        self.assertTrue(kg.dry_run(proposal['id'])['valid'])
        kg.approve(proposal['id'], 'admin')
        content = yaml.safe_load(path.read_text('utf-8'))
        self.assertEqual(len(content['devices']), 1)
        row = content['devices'][0]
        self.assertEqual(row['match']['device_id'], 'ha-bom-001')
        self.assertEqual(row['entities']['mode'], 'auto')
        self.assertNotIn('sensor.bom_power', path.read_text('utf-8'))
        self.assertNotIn('state:', path.read_text('utf-8'))
        self.assertEqual(device_catalog.match_catalog_device('bơm nước')['status'], 'resolved')
        self.assertTrue(next(d for d in device_catalog.discover(DEVICES, ENTITIES, AREAS) if d['device_id'] == 'ha-bom-001')['imported'])
        matches = rag.search_knowledge('Ổ cắm Bơm Nước', kind='device')
        self.assertTrue(any(r['kind'] == 'device' for r in matches))
        self.assertEqual(rag.resolve_entity('Ổ cắm Bơm Nước')['status'], 'not_found')  # no unsafe guessing a service target
        with self.assertRaisesRegex(ValueError, 'already exists'):
            device_catalog.create_import_proposal(devices, 'ha-bom-001', 'Ổ cắm Bơm Nước', [], 'admin')

    def test_import_merges_and_rejects_stale_proposals(self):
        devices = device_catalog.discover(DEVICES, ENTITIES, AREAS)
        first = device_catalog.create_import_proposal(devices, 'ha-02', 'Quạt treo', [], 'admin')
        kg.approve(first['id'], 'admin')
        second = device_catalog.create_import_proposal(devices, 'ha-bom-001', 'Ổ cắm', [], 'admin')
        # An unrelated Knowledge edit after the draft invalidates the optimistic snapshot.
        (Path(settings.knowledge_dir)/'new.md').write_text('changed externally', encoding='utf-8')
        self.assertFalse(kg.dry_run(second['id'])['valid'])
        (Path(settings.knowledge_dir)/'new.md').unlink()
        third = device_catalog.create_import_proposal(devices, 'ha-bom-001', 'Ổ cắm', [], 'admin')
        kg.approve(third['id'], 'admin')
        document = yaml.safe_load((Path(settings.knowledge_dir)/'21-devices.yaml').read_text('utf-8'))
        self.assertEqual({r['match']['device_id'] for r in document['devices']}, {'ha-02', 'ha-bom-001'})

    def test_import_errors_missing_device_invalid_alias_and_existing_schema(self):
        devices = device_catalog.discover(DEVICES, ENTITIES, AREAS)
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            device_catalog.create_import_proposal(devices, 'fake', 'Name', [], 'admin')
        with self.assertRaises(ValueError):
            device_catalog.create_import_proposal(devices, 'ha-02', 'Fan', [123], 'admin')
        path = Path(settings.knowledge_dir)/'21-devices.yaml'
        path.write_text('entities: []\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'devices list'):
            device_catalog.create_import_proposal(devices, 'ha-02', 'Fan', [], 'admin')

    def test_migrates_legacy_template_without_losing_notes_or_permissions(self):
        path = Path(settings.knowledge_dir)/'21-devices.yaml'
        path.write_text(yaml.safe_dump({'schema_version': 1, 'kind': 'hassmind_device_catalog',
            'settings': {'source': 'home_assistant_device_registry'},
            'devices': [{'key': 'o_cam_bom_nuoc', 'name': 'Ổ cắm Bơm Nước',
                         'aliases': ['ổ điện bơm'], 'match': {'name': 'Ổ cắm Bơm Nước',
                         'manufacturer': 'Tuya', 'model': 'TS011F_plug_1'},
                         'entities': {'mode': 'auto'}, 'notes': 'Không tự động thay đổi countdown',
                         'permissions': {'read': True}}]}, allow_unicode=True), encoding='utf-8')
        devices = device_catalog.discover(DEVICES, ENTITIES, AREAS)
        proposal = device_catalog.create_import_proposal(devices, 'ha-bom-001', 'Ổ cắm Bơm Nước', ['bơm nước'], 'admin')
        self.assertTrue(kg.dry_run(proposal['id'])['valid'])
        kg.approve(proposal['id'], 'admin')
        record = yaml.safe_load(path.read_text('utf-8'))['devices'][0]
        self.assertEqual(record['match']['device_id'], 'ha-bom-001')
        self.assertEqual(record['permissions'], {'read': True})
        self.assertEqual(record['aliases'], ['ổ điện bơm', 'bơm nước'])
        self.assertIn('countdown', record['notes'])
        self.assertEqual(len(yaml.safe_load(path.read_text('utf-8'))['devices']), 1)

    def test_device_missing_from_registry_is_reported_in_scan(self):
        devices = device_catalog.discover(DEVICES, ENTITIES, AREAS)
        proposal = device_catalog.create_import_proposal(devices, 'ha-02', 'Quạt', [], 'admin')
        kg.approve(proposal['id'], 'admin')
        issues = kg._ha_issues(rag.load_catalog(), ENTITIES, AREAS, [DEVICES[0]])
        self.assertTrue(any(d['code'] == 'unresolved_device' for d in issues))


if __name__ == '__main__':
    unittest.main()
