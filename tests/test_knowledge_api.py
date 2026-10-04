import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.settings import settings
from app.db import init_db
from app.auth import ensure_bootstrap_admin
from app import knowledge_governance as kg, rag


class KnowledgeAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_log = settings.log_file_enabled
        settings.log_file_enabled = False
        from app import main
        cls.main = main

    @classmethod
    def tearDownClass(cls):
        settings.log_file_enabled = cls.old_log

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        keys=('db_path','knowledge_dir','runtime_secret_dir','api_token','admin_bootstrap_password','admin_bootstrap_password_file','admin_allowed_networks','knowledge_monitor_enabled')
        self.old={k:getattr(settings,k) for k in keys}
        settings.db_path=str(Path(self.tmp.name)/'data'/'app.db')
        settings.knowledge_dir=str(Path(self.tmp.name)/'knowledge')
        settings.runtime_secret_dir=str(Path(self.tmp.name)/'secrets')
        settings.api_token='test-api-token-'+'a'*40
        settings.admin_bootstrap_password='Knowledge-test-password-294!'
        settings.admin_bootstrap_password_file=''
        settings.admin_allowed_networks=''
        settings.knowledge_monitor_enabled=False
        self.root=Path(settings.knowledge_dir)
        self.root.mkdir()
        (self.root/'entities.yaml').write_bytes('entities:\n  - entity_id: light.test\n    name: Đèn thử\n    aliases: [đèn thử]\n    area: Phòng ngủ\n'.encode('utf-8'))
        init_db()
        ensure_bootstrap_admin()
        kg.ensure_schema()
        rag.reindex_knowledge()
        self.client=TestClient(self.main.app, client=('127.0.0.1',50000))
        self.token={'X-HassMind-Token':settings.api_token}
        self.csrf={}
        self.old_ha=self.main.ha
        self.main.ha=None

    def tearDown(self):
        self.client.close()
        self.main.ha=self.old_ha
        for k,v in self.old.items(): setattr(settings,k,v)
        self.tmp.cleanup()

    def login(self):
        r=self.client.post('/api/auth/login',json={'username':'admin','password':settings.admin_bootstrap_password})
        self.assertEqual(r.status_code,200,r.text)
        self.csrf={'X-CSRF-Token':r.json()['csrf_token']}

    def test_search_backward_compatible_list_and_metadata_filters(self):
        r=self.client.get('/api/knowledge/search',params={'q':'đèn thử','domain':'light','type':'entity'},headers=self.token)
        self.assertEqual(r.status_code,200,r.text)
        rows=r.json()
        self.assertIsInstance(rows,list)
        self.assertEqual(rows[0]['entity_id'],'light.test')
        self.assertTrue({'path','text','score','confidence','domain','source'} <= rows[0].keys())

    def test_auth_required_for_reads(self):
        self.assertEqual(self.client.get('/api/knowledge/status').status_code,401)

    def test_token_cannot_approve_reject_rollback_config_or_draft(self):
        p=kg.create_proposal([{'path':'note.md','new_content':'hello'}],'test')
        for action in ('approve','reject','rollback'):
            self.assertEqual(self.client.post(f'/api/knowledge/proposals/{p["id"]}/{action}',json={},headers=self.token).status_code,401)
        self.assertEqual(self.client.patch('/api/knowledge/config',json={'enabled':False},headers=self.token).status_code,401)
        self.assertEqual(self.client.post('/api/knowledge/proposals',json={'reason':'test','changes':[{'path':'a.md','new_content':'a'}]},headers=self.token).status_code,401)
        self.assertFalse((self.root/'note.md').exists())

    def test_csrf_and_approve_rollback_flow(self):
        self.login()
        draft=self.client.post('/api/knowledge/proposals',json={'reason':'test','changes':[{'path':'a.md','new_content':'a'}]},headers=self.csrf)
        self.assertEqual(draft.status_code,200,draft.text)
        pid=draft.json()['id']
        self.assertEqual(self.client.post(f'/api/knowledge/proposals/{pid}/approve',json={}).status_code,403)
        self.assertTrue(self.client.post(f'/api/knowledge/proposals/{pid}/dry-run',json={},headers=self.csrf).json()['valid'])
        r=self.client.post(f'/api/knowledge/proposals/{pid}/approve',json={},headers=self.csrf)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['status'],'applied')
        r=self.client.post(f'/api/knowledge/proposals/{pid}/rollback',json={},headers=self.csrf)
        self.assertEqual(r.status_code,200,r.text)
        self.assertFalse((self.root/'a.md').exists())

    def test_stale_api_409_and_invalid_schema(self):
        self.login()
        p=kg.create_proposal([{'path':'a.md','new_content':'a'}],'test')
        (self.root/'external.txt').write_text('external')
        r=self.client.post(f'/api/knowledge/proposals/{p["id"]}/approve',json={},headers=self.csrf)
        self.assertEqual(r.status_code,409,r.text)
        self.assertFalse((self.root/'a.md').exists())
        r=self.client.patch('/api/knowledge/config',json={'scan_interval_seconds':1},headers=self.csrf)
        self.assertEqual(r.status_code,422)

    def test_missing_proposal_404_and_draft_path_block(self):
        self.assertEqual(self.client.get('/api/knowledge/proposals/missing',headers=self.token).status_code,404)
        self.login()
        r=self.client.post('/api/knowledge/proposals',json={'reason':'test','changes':[{'path':'../bad.md','new_content':'bad'}]},headers=self.csrf)
        self.assertEqual(r.status_code,409)

    def test_manual_scan_status_audit_and_file_editor(self):
        r=self.client.post('/api/knowledge/scan',json={},headers=self.token)
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn('proposals',r.json())
        status=self.client.get('/api/knowledge/status',headers=self.token).json()
        self.assertIn('latest_scan',status)
        self.assertGreater(status['pending_count'],0)
        self.assertTrue(self.client.get('/api/knowledge/audit',headers=self.token).json())
        self.login()
        file=self.client.get('/api/knowledge/file',params={'path':'entities.yaml'},headers=self.csrf)
        self.assertEqual(file.status_code,200,file.text)
        self.assertEqual(len(file.json()['sha256']),64)
        self.assertEqual(self.client.get('/api/knowledge/file',params={'path':'../escape.txt'},headers=self.csrf).status_code,409)

    def test_startup_shutdown_smoke_without_external_services(self):
        class HA:
            async def listen_events(self,callback,stop): await stop.wait()
            async def close(self): pass
        class Hub:
            zalo=None
            async def close(self): pass
        class Agent:
            def __init__(self,runtime): self.runtime=runtime
        async def background(stop,*args): await stop.wait()
        with patch.object(self.main,'HomeAssistantClient',HA),patch.object(self.main,'IntegrationHub',Hub),patch.object(self.main,'Agent',Agent),patch.object(self.main,'scheduler_loop',background),patch.object(self.main,'telegram_supervisor',background):
            with TestClient(self.main.app, client=('127.0.0.1',50000)) as client:
                self.assertEqual(client.get('/health').status_code,200)
                self.assertTrue(any(t.get_name()=='knowledge-monitor' for t in self.main.tasks))
                self.assertEqual(client.get('/api/knowledge/status',headers=self.token).status_code,200)
            self.assertTrue(all(t.done() for t in self.main.tasks))


if __name__=='__main__': unittest.main()
