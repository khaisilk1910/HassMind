import unittest

from app.message_format import format_zalo_message, split_zalo_message


class ZaloMessageFormatTests(unittest.TestCase):
    def test_markdown_and_followup_are_plain_text(self):
        raw = '''### 🛏️ Trạng thái Phòng Ngủ\n\n---\n#### 1. Phòng chính\n* **Trạng thái:** **Đang có người** (`binary_sensor.presence_room` = `on`).\n  * **Quạt:** (``switch.room_fan``) đang **Bật**.\n<FollowUp label="Bạn có muốn bật điều hòa không?" query="Bật điều hòa 26 độ"/>'''
        out = format_zalo_message(raw)
        for marker in ("###", "####", "**", "`", "<FollowUp"):
            self.assertNotIn(marker, out)
        self.assertIn("• Trạng thái: Đang có người", out)
        self.assertIn("◦ Quạt:", out)
        self.assertIn("binary_sensor.presence_room", out)
        self.assertIn("switch.room_fan", out)
        self.assertIn("💡 Gợi ý: Bạn có muốn bật điều hòa không?", out)

    def test_entity_underscores_are_preserved(self):
        eid = "sensor.espresence_phone_khai_turbo_4_pro_2"
        self.assertIn(eid, format_zalo_message(f"**Thiết bị:** `{eid}`"))

    def test_long_message_splits_on_boundaries(self):
        raw = "\n\n".join(f"### Mục {i}\n* **Trạng thái:** `on`" for i in range(60))
        chunks = split_zalo_message(raw, limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 500 for chunk in chunks))
        self.assertTrue(all("###" not in chunk and "**" not in chunk and "`" not in chunk for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
