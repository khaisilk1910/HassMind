import unittest

from app.ha import HomeAssistantClient
from app.settings import settings


class HomeAssistantStateCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_token = settings.ha_token
        self.old_ttl = settings.ha_state_cache_ttl
        settings.ha_token = "unit-test-token"
        settings.ha_state_cache_ttl = 5.0
        self.ha = HomeAssistantClient()
        self.calls = 0

        async def fake_get(path, params=None):
            self.calls += 1
            if path == "/api/states":
                return [{
                    "entity_id": "sensor.room_temperature",
                    "state": "27.8",
                    "attributes": {"friendly_name": "Room temperature"},
                }]
            raise AssertionError(path)

        self.ha._get = fake_get

    async def asyncTearDown(self):
        await self.ha.close()
        settings.ha_token = self.old_token
        settings.ha_state_cache_ttl = self.old_ttl

    async def test_snapshot_reused_and_event_updates_in_memory(self):
        first = await self.ha.states()
        second = await self.ha.states()
        self.assertEqual(self.calls, 1)
        self.assertEqual(first[0]["state"], "27.8")
        self.assertEqual(second[0]["state"], "27.8")

        self.ha._event_stream_live = True
        self.ha._cache_state({
            "entity_id": "sensor.room_temperature",
            "state": "28.1",
            "attributes": {"friendly_name": "Room temperature"},
        })
        current = await self.ha.state("sensor.room_temperature")
        self.assertEqual(current["state"], "28.1")
        self.assertEqual(self.calls, 1)

    async def test_invalidation_forces_refresh(self):
        await self.ha.states()
        self.ha.invalidate_state_cache()
        await self.ha.states()
        self.assertEqual(self.calls, 2)


if __name__ == "__main__":
    unittest.main()
