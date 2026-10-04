import unittest

from app.message_format import format_zalo_message, split_zalo_message


class ZaloMessageFormatTests(unittest.TestCase):
    def test_supported_zalo_markup_is_preserved(self):
        raw = '''# \U0001f3e0 Trang thai Phong Ngu\n\n---\n### 1. Phong chinh\n- **Trang thai:** {green}**Dang co nguoi**{/green} (`binary_sensor.presence_room` = `on`).\n  - *Quat:* (``switch.room_fan``) dang **Bat**.\n> Ghi chu\n<FollowUp label="Ban co muon bat dieu hoa khong?" query="Bat dieu hoa 26 do"/>'''
        out = format_zalo_message(raw)
        self.assertIn("# \U0001f3e0 Trang thai Phong Ngu", out)
        self.assertIn("### 1. Phong chinh", out)
        self.assertIn("- **Trang thai:** {green}**Dang co nguoi**{/green}", out)
        self.assertIn("  - *Quat:*", out)
        self.assertIn("`binary_sensor.presence_room`", out)
        self.assertIn("`switch.room_fan`", out)
        self.assertIn("> Ghi chu", out)
        self.assertIn("{green}**\U0001f4a1 G\u1ee3i \u00fd:**{/green}", out)
        self.assertNotIn("<FollowUp", out)
        self.assertIn("\u2500" * 12, out)

    def test_tables_become_bullets_instead_of_raw_table_markup(self):
        raw = "| Name | State |\n| --- | --- |\n| Fan | on |\n| AC | off |"
        out = format_zalo_message(raw)
        self.assertIn("- **Name:** Fan | **State:** on", out)
        self.assertIn("- **Name:** AC | **State:** off", out)
        self.assertNotIn("| --- |", out)

    def test_unknown_html_and_pseudo_tags_are_removed(self):
        raw = "<b>hello</b> {blue}x{/blue} {red}warning{/red}"
        out = format_zalo_message(raw)
        self.assertEqual(out, "hello x {red}warning{/red}")

    def test_long_message_splits_on_boundaries(self):
        raw = "\n\n".join(f"### Muc {i}\n- **Trang thai:** `on`" for i in range(60))
        chunks = split_zalo_message(raw, limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 500 for chunk in chunks))
        self.assertTrue(all("###" in chunk for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
