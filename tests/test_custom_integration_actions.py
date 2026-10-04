import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.custom_integrations import create_custom_integration, custom_action_tool_specs
from app.db import init_db
from app.integrations.generic import GenericHTTPIntegrationClient
from app.settings import settings


class CustomIntegrationActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = settings.db_path
        self.old_secret_dir = settings.runtime_secret_dir
        settings.db_path = str(Path(self.temp.name) / "hassmind.db")
        settings.runtime_secret_dir = str(Path(self.temp.name) / "secrets")
        init_db()

    def tearDown(self):
        settings.db_path = self.old_db
        settings.runtime_secret_dir = self.old_secret_dir
        self.temp.cleanup()

    def test_action_becomes_typed_agent_tool_only_when_opted_in(self):
        item = create_custom_integration({
            "name": "Demo API",
            "id": "demo-api",
            "base_url": "http://127.0.0.1:9999",
            "health_path": "/health",
            "auth_type": "none",
            "enabled": True,
            "actions": [{
                "id": "device-status",
                "name": "Device status",
                "description": "Read one device",
                "enabled": True,
                "agent_enabled": True,
                "method": "GET",
                "path": "/api/devices/{device_id}",
                "mode": "read",
                "request_target": "auto",
                "input_schema": {
                    "type": "object",
                    "properties": {"device_id": {"type": "string"}, "detail": {"type": "string"}},
                    "required": ["device_id"],
                    "additionalProperties": False,
                },
            }],
        })
        self.assertEqual(item["action_count"], 1)
        self.assertEqual(item["agent_action_count"], 1)
        specs = custom_action_tool_specs()
        self.assertEqual(len(specs), 1)
        self.assertTrue(specs[0]["tool_name"].startswith("ci_demo_api_device_status_"))
        self.assertEqual(specs[0]["action"]["input_schema"]["required"], ["device_id"])

    def test_path_parameter_must_be_declared(self):
        with self.assertRaises(ValueError):
            create_custom_integration({
                "name": "Bad API", "id": "bad-api", "base_url": "http://127.0.0.1:9999",
                "actions": [{
                    "id": "read-one", "name": "Read one", "enabled": True, "agent_enabled": True,
                    "method": "GET", "path": "/api/{missing}", "mode": "read",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                }],
            })


class GenericHTTPActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = None
            if request.content:
                body = json.loads(request.content.decode())
            self.requests.append((request.method, request.url.path, dict(request.url.params), body))
            return httpx.Response(200, json={"ok": True})

        self.client = GenericHTTPIntegrationClient("http://example.test")
        await self.client.client.aclose()
        self.client.client = httpx.AsyncClient(base_url="http://example.test", transport=httpx.MockTransport(handler))

    async def asyncTearDown(self):
        await self.client.close()

    async def test_get_uses_fixed_path_and_query(self):
        action = {"method": "GET", "path": "/api/devices/{device_id}", "request_target": "auto", "input_schema": {"type": "object", "properties": {"device_id": {"type": "string"}, "detail": {"type": "string"}}, "required": ["device_id"], "additionalProperties": False}}
        result = await self.client.call_action(action, {"device_id": "living room", "detail": "full"})
        self.assertTrue(result["ok"])
        method, path, query, body = self.requests[-1]
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/api/devices/living room")
        self.assertEqual(query, {"detail": "full"})
        self.assertIsNone(body)

    async def test_post_uses_json_body(self):
        action = {"method": "POST", "path": "/api/set/{device_id}", "request_target": "auto", "input_schema": {"type": "object", "properties": {"device_id": {"type": "string"}, "speed": {"type": "integer"}}, "required": ["device_id", "speed"], "additionalProperties": False}}
        await self.client.call_action(action, {"device_id": "fan-1", "speed": 3})
        method, path, query, body = self.requests[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/set/fan-1")
        self.assertEqual(query, {})
        self.assertEqual(body, {"speed": 3})


if __name__ == "__main__":
    unittest.main()
