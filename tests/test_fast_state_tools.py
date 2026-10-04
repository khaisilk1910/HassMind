import unittest

from app.state_query import compact_state, search_states


STATES = [
    {
        "entity_id": "binary_sensor.presence_phong_ngu",
        "state": "on",
        "last_changed": "2026-10-04T02:00:00+00:00",
        "attributes": {"friendly_name": "Hiện diện Phòng Ngủ", "device_class": "occupancy", "target_count": 1.0},
    },
    {
        "entity_id": "sensor.nhiet_do_phong_ngu",
        "state": "27.8",
        "last_changed": "2026-10-04T02:00:00+00:00",
        "attributes": {"friendly_name": "Nhiệt độ Phòng Ngủ", "unit_of_measurement": "°C"},
    },
    {
        "entity_id": "light.phong_khach",
        "state": "off",
        "last_changed": "2026-10-04T02:00:00+00:00",
        "attributes": {"friendly_name": "Đèn Phòng Khách"},
    },
]


class FastStateQueryTests(unittest.TestCase):
    def test_accent_insensitive_room_search(self):
        result = search_states(STATES, query="phong ngu", include_attributes=True)
        self.assertEqual(result["total_matches"], 2)
        self.assertEqual({x["entity_id"] for x in result["states"]}, {
            "binary_sensor.presence_phong_ngu", "sensor.nhiet_do_phong_ngu"
        })
        presence = next(x for x in result["states"] if x["entity_id"].startswith("binary_sensor."))
        self.assertEqual(presence["attributes"]["target_count"], 1.0)

    def test_domain_and_state_filter(self):
        result = search_states(STATES, query="phong", domains=["light"], state_filter="off")
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["states"][0]["entity_id"], "light.phong_khach")

    def test_compact_state_preserves_small_custom_measurements(self):
        item = dict(STATES[0])
        item["attributes"] = dict(item["attributes"], custom_power_w=3.2, huge="x" * 500)
        compact = compact_state(item)
        self.assertEqual(compact["attributes"]["custom_power_w"], 3.2)
        self.assertNotIn("huge", compact["attributes"])


if __name__ == "__main__":
    unittest.main()
