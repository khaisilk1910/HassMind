import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import knowledge_governance as kg, rag
from app.db import conn, init_db
from app.settings import settings


class KnowledgeGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: getattr(settings, k) for k in ('db_path', 'knowledge_dir', 'knowledge_notify_enabled')}
        settings.db_path = str(Path(self.tmp.name)/'data'/'test.db')
        settings.knowledge_dir = str(Path(self.tmp.name)/'knowledge')
        settings.knowledge_notify_enabled = True
        self.root = Path(settings.knowledge_dir)
        self.root.mkdir()
        init_db()
        kg.ensure_schema()
        self.write('devices.yaml', 'entities:\n  - entity_id: light.bedroom\n    name: Đèn ngủ\n    aliases: [đèn ngủ]\n    area: Phòng ngủ\n    domain: light\n')
        rag.reindex_knowledge()

    def tearDown(self):
        for k,v in self.old.items():
            setattr(settings,k,v)
        self.tmp.cleanup()

    def write(self, name, text):
        (self.root/name).write_bytes(text.encode('utf-8'))

    def draft(self, text='New reference\n', path='reference.md'):
        return kg.create_proposal([{'path':path,'new_content':text}], 'Reviewed correction')

    def test_draft_and_dry_run_do_not_mutate(self):
        p=self.draft()
        self.assertEqual(p['status'],'pending')
        self.assertIn('+New reference',p['changes'][0]['diff'])
        self.assertTrue(kg.dry_run(p['id'])['valid'])
        self.assertFalse((self.root/'reference.md').exists())

    def test_approve_apply_backup_rollback_and_audit(self):
        old=(self.root/'devices.yaml').read_bytes()
        p=self.draft('entities:\n  - entity_id: light.bedroom\n    name: Bedroom lamp\n','devices.yaml')
        self.assertEqual(kg.approve(p['id'],'admin')['status'],'applied')
        self.assertIn('Bedroom lamp',(self.root/'devices.yaml').read_text())
        self.assertEqual(kg.rollback(p['id'],'admin')['status'],'rolled_back')
        self.assertEqual(old,(self.root/'devices.yaml').read_bytes())
        self.assertTrue({'proposal_created','applied','rolled_back'} <= {r['action'] for r in kg.audit_log()})

    def test_reject_and_repeated_decision(self):
        p=self.draft()
        self.assertEqual(kg.reject(p['id'],'admin')['status'],'rejected')
        with self.assertRaises(ValueError): kg.approve(p['id'],'admin')
        with self.assertRaises(ValueError): kg.reject(p['id'],'admin')

    def test_stale_proposal_is_blocked_even_unrelated_file_changed(self):
        p=self.draft()
        self.write('other.txt','external edit')
        self.assertFalse(kg.dry_run(p['id'])['valid'])
        with self.assertRaises(ValueError): kg.approve(p['id'],'admin')
        self.assertFalse((self.root/'reference.md').exists())

    def test_stale_rollback_preserves_newer_edit(self):
        p=self.draft()
        kg.approve(p['id'],'admin')
        self.write('reference.md','Changed externally')
        with self.assertRaises(ValueError): kg.rollback(p['id'],'admin')
        self.assertEqual((self.root/'reference.md').read_text(),'Changed externally')

    def test_invalid_yaml_dry_run(self):
        p=self.draft('entities: [','bad.yaml')
        self.assertFalse(kg.dry_run(p['id'])['valid'])
        with self.assertRaises(ValueError): kg.approve(p['id'],'admin')

    def test_duplicate_paths_and_traversal_rejected(self):
        with self.assertRaises(ValueError): self.draft('x','../escape.md')
        with self.assertRaises(ValueError): kg.create_proposal([{'path':'a.md','new_content':'a'},{'path':'a.md','new_content':'b'}],'bad')

    def test_delete_with_rollback_preserves_exact_bytes(self):
        original=b'hello\r\n'
        (self.root/'old.txt').write_bytes(original)
        p=kg.create_proposal([{'path':'old.txt','operation':'delete'}],'remove old document')
        kg.approve(p['id'],'admin')
        self.assertFalse((self.root/'old.txt').exists())
        kg.rollback(p['id'],'admin')
        self.assertEqual((self.root/'old.txt').read_bytes(),original)

    def test_partial_apply_failure_restores_written_files(self):
        p=kg.create_proposal([{'path':'a.md','new_content':'a'},{'path':'b.md','new_content':'b'}],'two file correction')
        original=kg._write
        def fail_b(path,data):
            if path=='b.md' and data is not None: raise OSError('simulated read-only mount')
            return original(path,data)
        with patch.object(kg,'_write',side_effect=fail_b):
            with self.assertRaises(OSError): kg.approve(p['id'],'admin')
        self.assertFalse((self.root/'a.md').exists())
        self.assertFalse((self.root/'b.md').exists())
        self.assertEqual(kg.get_proposal(p['id'])['status'],'failed')

    def test_failed_reindex_restores_content(self):
        p=self.draft()
        with patch.object(rag,'reindex_knowledge',side_effect=[RuntimeError('index failed'),{}]):
            with self.assertRaises(RuntimeError): kg.approve(p['id'],'admin')
        self.assertFalse((self.root/'reference.md').exists())

    def test_config_persist_and_bounds(self):
        cfg=kg.save_monitor_config({'enabled':False,'scan_interval_seconds':60},'admin')
        self.assertEqual(cfg,kg.monitor_config())
        with self.assertRaises(ValueError): kg.save_monitor_config({'scan_interval_seconds':1},'admin')

    def test_scan_changes_and_no_automatic_content_apply(self):
        first=asyncio.run(kg.scan_knowledge())
        self.assertIn('devices.yaml',first['changes']['added'])
        self.write('devices.yaml','entities:\n  - entity_id: light.bedroom\n    state: on\n    domain: switch\n')
        second=asyncio.run(kg.scan_knowledge())
        self.assertIn('devices.yaml',second['changes']['modified'])
        content=[p for p in second['proposals'] if p['kind']=='content']
        self.assertTrue(content)
        self.assertIn('state: on',(self.root/'devices.yaml').read_text())
        self.assertNotIn('state:',kg.get_proposal(content[0]['id'])['changes'][0]['new_content'])
        (self.root/'devices.yaml').unlink()
        third=asyncio.run(kg.scan_knowledge())
        self.assertIn('devices.yaml',third['changes']['deleted'])

    def test_reindex_warning_conflicts_are_detailed_but_do_not_block_approval(self):
        self.write('conflict.yaml', '''entities:\n  - entity_id: light.same\n    name: Đèn một\n    area: Phòng ngủ\n  - entity_id: light.same\n    name: Đèn hai\n    area: Phòng khách\n''')
        scan=asyncio.run(kg.scan_knowledge())
        proposal=next(p for p in scan['proposals'] if p['kind']=='reindex')
        dry=kg.dry_run(proposal['id'])
        self.assertTrue(dry['valid'])
        conflict=next(i for i in dry['issues'] if i['code']=='entity_conflict')
        self.assertFalse(conflict['blocking'])
        self.assertEqual(conflict['entity_id'],'light.same')
        self.assertEqual({d['location'] for d in conflict['definitions']},{'entities[0]','entities[1]'})
        applied=kg.approve(proposal['id'],'admin')
        self.assertEqual(applied['status'],'applied')
        self.assertTrue(any(w['code']=='entity_conflict' for w in applied['index']['warnings']))

    def test_content_conflict_blocks_only_when_changed_file_participates(self):
        self.write('conflict.yaml', '''entities:\n  - entity_id: light.same\n    name: Đèn một\n  - entity_id: light.same\n    name: Đèn hai\n''')
        rag.reindex_knowledge()
        unrelated=kg.create_proposal([{'path':'reference.md','new_content':'safe text\n'}],'unrelated correction')
        dry=kg.dry_run(unrelated['id'])
        self.assertTrue(dry['valid'])
        self.assertTrue(any(i['code']=='entity_conflict' and not i['blocking'] for i in dry['issues']))
        kg.approve(unrelated['id'],'admin')
        changed=kg.create_proposal([{'path':'conflict.yaml','new_content':'''entities:\n  - entity_id: light.same\n    name: Đèn một\n  - entity_id: light.same\n    name: Đèn ba\n'''}],'conflicting correction')
        blocked=kg.dry_run(changed['id'])
        self.assertFalse(blocked['valid'])
        self.assertTrue(any(i['code']=='entity_conflict' and i['blocking'] for i in blocked['issues']))

    def test_rejected_automatic_draft_not_recreated(self):
        p=self.draft()
        kg.reject(p['id'],'admin')
        duplicate=self.draft()
        self.assertEqual(duplicate['id'],p['id'])
        self.assertEqual(duplicate['status'],'rejected')

    def test_schema_errors_make_manual_review_proposal(self):
        self.write('bad.yaml','entities: [')
        result=asyncio.run(kg.scan_knowledge())
        p=next(p for p in result['proposals'] if p['kind']=='review')
        self.assertFalse(kg.dry_run(p['id'])['valid'])

    def test_scan_marks_old_draft_stale_and_lists_summaries(self):
        p=self.draft()
        self.assertNotIn('new_content',kg.list_proposals()[0]['changes'][0])
        self.assertIn('new_content',kg.get_proposal(p['id'])['changes'][0])
        self.write('other.txt','changed')
        asyncio.run(kg.scan_knowledge())
        self.assertEqual(kg.get_proposal(p['id'])['status'],'stale')
        self.assertFalse(kg.dry_run(p['id'])['valid'])

    def test_oversize_existing_file_cannot_be_read_into_proposal(self):
        with patch.object(settings,'knowledge_max_file_bytes',1024):
            self.write('huge.md','x'*1025)
            with self.assertRaises(ValueError): self.draft('new','huge.md')

    def test_external_file_growth_blocks_dry_run(self):
        p=self.draft()
        with patch.object(settings,'knowledge_max_file_bytes',1024):
            self.write('reference.md','x'*1025)
            self.assertFalse(kg.dry_run(p['id'])['valid'])

    def test_ha_registry_check_and_notification_dedup(self):
        class HA:
            def __init__(self): self.notifications=[]
            async def entity_registry(self): return [{'entity_id':'light.other'}]
            async def ws_command(self,cmd): return []
            async def notify(self,text,title): self.notifications.append(text)
        async def run():
            ha=HA()
            first=await kg.scan_knowledge(ha)
            second=await kg.scan_knowledge(ha)
            self.assertTrue(first['ha_checked'])
            self.assertTrue(any(i['code']=='unresolved_entity' for i in first['issues']))
            self.assertEqual(len(ha.notifications),1)
            self.assertFalse(second['new_findings'])
        asyncio.run(run())

    def test_ha_outage_deferred_not_marked_unresolved(self):
        class HA:
            async def entity_registry(self): raise ConnectionError('offline')
            async def ws_command(self,cmd): return []
        result=asyncio.run(kg.scan_knowledge(HA()))
        self.assertFalse(result['ha_checked'])
        self.assertTrue(result['ha_error'])
        self.assertFalse(any(i['code']=='unresolved_entity' for i in result['issues']))

    def test_cross_file_invalid_prospective_catalog_blocks_apply(self):
        p=self.draft('entities:\n  - entity_id: light.bedroom\n    name: Conflicting name\n    domain: switch\n','other.yaml')
        self.assertFalse(kg.dry_run(p['id'])['valid'])

    def test_crash_journal_recovers_without_overwriting_external_edits(self):
        p=self.draft()
        backup=[{'path':'reference.md','content':None,'before_hash':None,'after_hash':kg._hash(b'New reference\n')}]
        self.write('reference.md','New reference\n')
        with conn() as c: c.execute("UPDATE knowledge_proposals SET status='applying',backup=? WHERE id=?",(json.dumps(backup),p['id']))
        kg.recover_interrupted()
        self.assertFalse((self.root/'reference.md').exists())
        self.assertEqual(kg.get_proposal(p['id'])['status'],'rolled_back')


if __name__=='__main__': unittest.main()
