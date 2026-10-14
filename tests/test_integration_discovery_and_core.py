"""Regression coverage for web-managed connections and read-only action discovery."""
import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from app.db import init_db
from app.integration_config import (integration_config_view, load_runtime_integration_overrides,
                                    reset_integration_config, save_integration_config)
from app.integration_discovery import _spec_path, parse_openapi
from app.integrations.generic import GenericHTTPIntegrationClient
from app.custom_integrations import _normalize_actions
from app.mcp_connections import list_mcp_connections, save_mcp_connection, delete_mcp_connection, mcp_servers_runtime
from app.settings import settings


DOC = {
    'openapi': '3.1.0',
    'paths': {
        '/api/devices/{device_id}': {
            'get': {'summary': 'Read device', 'parameters': [
                {'in': 'path', 'name': 'device_id', 'required': True,
                 'schema': {'type': 'string'}},
                {'in': 'query', 'name': 'details', 'schema': {'type': 'boolean'}}]},
            'patch': {'summary': 'Update device', 'parameters': [
                {'in': 'path', 'name': 'device_id', 'required': True,
                 'schema': {'type': 'string'}},
                {'in': 'query', 'name': 'dry_run', 'schema': {'type': 'boolean'}}],
                'requestBody': {'content': {'application/json': {
                    'schema': {'type': 'object', 'properties': {'level': {'type': 'integer'}},
                               'required': ['level']}}}}},
        }
    },
}


class CoreIntegrationsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.original = {name: getattr(settings, name) for name in
                         ('db_path', 'runtime_secret_dir', 'ha_url', 'ha_notify_service',
                          'openai_base_url', 'openai_model', 'searxng_url')}
        settings.db_path = str(Path(self.dir.name) / 'db.sqlite3')
        settings.runtime_secret_dir = str(Path(self.dir.name) / 'secrets')
        init_db()

    def tearDown(self):
        for name, value in self.original.items():
            setattr(settings, name, value)
        self.dir.cleanup()

    def test_core_configs_use_web_override_and_keep_secrets_private(self):
        save_integration_config('home_assistant', {
            'url': 'http://127.0.0.1:8123', 'notify_service': 'notify.mobile_app_test',
            'token': 'web_token_ha_1234',
        })
        save_integration_config('openai', {
            'base_url': 'http://127.0.0.1:8000/v1', 'model': 'gemini-auto',
            'api_key': 'web_key_llm_9876',
        })
        save_integration_config('searxng', {'url': 'http://search:8080'})
        settings.ha_url = 'http://wrong:8123'
        settings.openai_model = 'wrong'
        load_runtime_integration_overrides()
        self.assertEqual(settings.ha_url, 'http://127.0.0.1:8123')
        self.assertEqual(settings.openai_model, 'gemini-auto')
        self.assertEqual(settings.read_ha_token(), 'web_token_ha_1234')
        self.assertEqual(settings.read_openai_key(), 'web_key_llm_9876')
        view = integration_config_view()
        for item in view['integrations']:
            for f in item['fields']:
                if f['type'] == 'secret':
                    self.assertEqual(f['value'], '')
        self.assertEqual(next(i for i in view['integrations'] if i['id'] == 'searxng')['source'], 'web_admin')
        reset_integration_config('home_assistant')
        self.assertFalse((Path(settings.runtime_secret_dir) / 'integration_home_assistant_token').exists())

    def test_mcp_connections_require_explicit_approved_tool(self):
        item = save_mcp_connection({
            'id': 'weather-mcp', 'name': 'Weather MCP', 'url': 'http://127.0.0.1:3000/mcp',
            'enabled': True, 'auth_type': 'bearer', 'secret': 'test_mcp_key_123',
            'allowed_tools': [],
        })
        self.assertFalse(item['allowed_tools'])
        self.assertTrue(item['secret_configured'])
        self.assertNotIn('secret', item)
        live = mcp_servers_runtime()
        self.assertEqual(live['weather-mcp']['allowed_tools'], [])
        self.assertEqual(live['weather-mcp']['headers']['Authorization'], 'Bearer test_mcp_key_123')
        save_mcp_connection({'name': 'Weather MCP', 'url': 'http://127.0.0.1:3000/mcp',
                             'auth_type': 'bearer', 'allowed_tools': ['get_forecast']}, existing='weather-mcp')
        self.assertEqual(list_mcp_connections()[0]['allowed_tools'], ['get_forecast'])
        delete_mcp_connection('weather-mcp')
        self.assertFalse(list_mcp_connections())
        self.assertFalse((Path(settings.runtime_secret_dir) / 'integration_mcp_weather-mcp_secret').exists())


class OpenAPIDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_openapi_defaults_agent_disabled_and_handles_both_request_locations(self):
        actions = parse_openapi(DOC)['actions']
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(not a['agent_enabled'] for a in actions))
        patch = next(a for a in actions if a['method'] == 'PATCH')
        self.assertEqual(patch['input_schema']['required'], ['device_id', 'level'])
        self.assertEqual(patch['parameter_locations'], {'dry_run': 'query', 'level': 'json'})
        self.assertEqual(_normalize_actions([patch])[0]['parameter_locations'], patch['parameter_locations'])

    def test_invalid_spec_path_is_rejected(self):
        for value in ('/api/../secret', 'http://external.com', '//other/path', '/file?token=abc'):
            with self.assertRaises(ValueError):
                _spec_path(value)

    def test_untrusted_external_refs_are_never_fetched(self):
        spec = {'openapi': '3.0', 'paths': {'/x': {'post': {'parameters': [{'$ref': 'https://example.org/schema'}]}}}}
        result = parse_openapi(spec)
        self.assertEqual(result['actions'], [])
        self.assertTrue(result['warnings'])

    async def test_http_client_places_discovered_query_and_body_correctly(self):
        seen = []
        async def handler(req):
            seen.append(req)
            return httpx.Response(200, json={'ok': True})
        client = GenericHTTPIntegrationClient('http://example.test')
        await client.client.aclose()
        client.client = httpx.AsyncClient(base_url='http://example.test', transport=httpx.MockTransport(handler))
        try:
            patch = next(a for a in parse_openapi(DOC)['actions'] if a['method'] == 'PATCH')
            result = await client.call_action(patch, {'device_id': 'box1', 'dry_run': True, 'level': 3})
            self.assertTrue(result['ok'])
            self.assertEqual(seen[0].url.path, '/api/devices/box1')
            self.assertEqual(seen[0].url.params['dry_run'], 'true')
            self.assertEqual(seen[0].content, b'{"level":3}')
        finally:
            await client.close()
