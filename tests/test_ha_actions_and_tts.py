import unittest

from app.ha import HomeAssistantClient
from app.ha_integrations import HAIntegrationBridge
from app.settings import settings


class HomeAssistantActionPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_token = settings.ha_token
        settings.ha_token = "unit-test-token"
        self.ha = HomeAssistantClient()
        self.posts = []

        async def fake_post(path, data=None, params=None):
            self.posts.append((path, data, params))
            return {"ok": True}

        self.ha._post = fake_post

    async def asyncTearDown(self):
        await self.ha.close()
        settings.ha_token = self.old_token

    async def test_action_target_is_flattened_only_at_rest_boundary(self):
        await self.ha.call_service_raw(
            "tts",
            "speak",
            {"media_player_entity_id": "media_player.bedroom", "message": "Hello"},
            target={"entity_id": "tts.piper"},
        )
        path, payload, params = self.posts[-1]
        self.assertEqual(path, "/api/services/tts/speak")
        self.assertEqual(payload["entity_id"], "tts.piper")
        self.assertEqual(payload["media_player_entity_id"], "media_player.bedroom")
        self.assertEqual(payload["message"], "Hello")
        self.assertIsNone(params)

    async def test_conflicting_target_and_data_is_rejected(self):
        with self.assertRaises(ValueError):
            await self.ha.call_service_raw(
                "light",
                "turn_on",
                {"entity_id": "light.one"},
                target={"entity_id": "light.two"},
            )

    async def test_unknown_target_key_is_rejected(self):
        with self.assertRaises(ValueError):
            await self.ha.call_service_raw(
                "light", "turn_on", {}, target={"not_a_target": "x"}
            )

    async def test_websocket_frame_ceiling_is_above_library_default_and_bounded(self):
        old_size = settings.ha_ws_max_size
        try:
            settings.ha_ws_max_size = 16 * 1024 * 1024
            self.assertEqual(self.ha._ws_max_size(), 16 * 1024 * 1024)
            settings.ha_ws_max_size = 128 * 1024 * 1024
            self.assertEqual(self.ha._ws_max_size(), 64 * 1024 * 1024)
            settings.ha_ws_max_size = 128
            self.assertEqual(self.ha._ws_max_size(), 1024 * 1024)
        finally:
            settings.ha_ws_max_size = old_size


class FakeTTSHA:
    def __init__(self, states=None, registry=None):
        self._states = states or []
        self._registry = registry or []
        self.registry_calls = 0
        self.state_calls = 0
        self.calls = []

    async def states(self):
        self.state_calls += 1
        return self._states

    async def entity_registry(self):
        self.registry_calls += 1
        return self._registry

    async def call_service_raw(self, domain, service, data=None, *, target=None, return_response=False):
        self.calls.append({
            "domain": domain,
            "service": service,
            "data": data or {},
            "target": target,
            "return_response": return_response,
        })
        return {"ok": True}


class TTSActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_allow = settings.wyoming_allow_tts
        self.old_entity = settings.wyoming_tts_entity_id
        settings.wyoming_allow_tts = True
        settings.wyoming_tts_entity_id = ""

    async def asyncTearDown(self):
        settings.wyoming_allow_tts = self.old_allow
        settings.wyoming_tts_entity_id = self.old_entity

    async def test_single_tts_state_avoids_entity_registry_websocket(self):
        ha = FakeTTSHA(states=[{"entity_id": "tts.piper", "state": "2026-10-04T00:00:00+00:00"}])
        bridge = HAIntegrationBridge(ha)
        result = await bridge.tts_speak(
            "media_player.phong_ngu_speaker", "Dậy đi chíp hôi", cache=False
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(ha.registry_calls, 0)
        call = ha.calls[-1]
        self.assertEqual(call["domain"], "tts")
        self.assertEqual(call["service"], "speak")
        self.assertEqual(call["target"], {"entity_id": "tts.piper"})
        self.assertNotIn("entity_id", call["data"])
        self.assertEqual(call["data"]["media_player_entity_id"], "media_player.phong_ngu_speaker")
        self.assertEqual(call["data"]["message"], "Dậy đi chíp hôi")
        self.assertFalse(call["data"]["cache"])

    async def test_configured_tts_entity_skips_discovery_entirely(self):
        settings.wyoming_tts_entity_id = "tts.wyoming_vi"
        ha = FakeTTSHA()
        bridge = HAIntegrationBridge(ha)
        await bridge.tts_speak("media_player.bedroom", "Xin chào")
        self.assertEqual(ha.state_calls, 0)
        self.assertEqual(ha.registry_calls, 0)
        self.assertEqual(ha.calls[-1]["target"], {"entity_id": "tts.wyoming_vi"})

    async def test_multiple_tts_entities_use_registry_only_as_bounded_fallback(self):
        ha = FakeTTSHA(
            states=[
                {"entity_id": "tts.cloud", "state": "x"},
                {"entity_id": "tts.piper", "state": "x"},
            ],
            registry=[
                {"entity_id": "tts.cloud", "platform": "cloud"},
                {"entity_id": "tts.piper", "platform": "wyoming"},
            ],
        )
        bridge = HAIntegrationBridge(ha)
        await bridge.tts_speak("media_player.bedroom", "Xin chào")
        self.assertEqual(ha.registry_calls, 1)
        self.assertEqual(ha.calls[-1]["target"], {"entity_id": "tts.piper"})

    async def test_invalid_media_player_is_rejected_before_action(self):
        settings.wyoming_tts_entity_id = "tts.piper"
        ha = FakeTTSHA()
        bridge = HAIntegrationBridge(ha)
        with self.assertRaises(ValueError):
            await bridge.tts_speak("speaker.bedroom", "Xin chào")
        self.assertEqual(ha.calls, [])


if __name__ == "__main__":
    unittest.main()
