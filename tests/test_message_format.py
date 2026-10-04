import unittest

from app.message_format import build_zalo_message_content, format_zalo_message, split_zalo_message


class ZaloMessageFormatTests(unittest.TestCase):
    def test_supported_zalo_markup_is_preserved_before_transport_compile(self):
        raw = '''# \U0001f3e0 Trang thai Phong Ngu\n\n---\n### 1. Phong chinh\n- **Trang thai:** {green}**Dang co nguoi**{/green} (`binary_sensor.presence_room` = `on`).\n  - *Quat:* (``switch.room_fan``) dang **Bat**.\n> Ghi chu\n<FollowUp label="Ban co muon bat dieu hoa khong?" query="Bat dieu hoa 26 do"/>'''
        out = format_zalo_message(raw)
        self.assertIn("# \U0001f3e0 Trang thai Phong Ngu", out)
        self.assertIn("### 1. Phong chinh", out)
        self.assertIn("- **Trang thai:** {green}**Dang co nguoi**{/green}", out)
        self.assertIn("  - *Quat:*", out)
        self.assertIn("`binary_sensor.presence_room`", out)
        self.assertIn("`switch.room_fan`", out)
        self.assertIn("> Ghi chu", out)
        self.assertIn("{green}**\U0001f4a1 Gợi ý:**{/green}", out)
        self.assertNotIn("<FollowUp", out)
        self.assertIn("\u2500" * 12, out)

    def test_transport_compiler_removes_visible_markup_and_emits_zca_styles(self):
        raw = '''# TRUY XUẤT NGÀY ÂM LỊCH\n\nNgày **24 tháng 9 năm 2026 Âm lịch** tương ứng với:\n\n- **Dương lịch:** **Thứ Hai, ngày 02 tháng 11 năm 2026**\n- **Thông tin Can Chi & Tiết khí:**\n  - Ngày Canh Thìn, tháng Mậu Tuất, năm Bính Ngọ\n  - Tiết khí: Sương Giáng'''
        content = build_zalo_message_content(raw)
        msg = content["msg"]
        styles = content["styles"]

        self.assertTrue(msg.startswith("TRUY XUẤT NGÀY ÂM LỊCH"))
        self.assertNotIn("# ", msg)
        self.assertNotIn("**", msg)
        self.assertNotIn("- **", msg)
        self.assertTrue(any(x["st"] == "f_18" and x["start"] == 0 for x in styles))
        self.assertTrue(any(x["st"] == "b" and x["start"] == 0 for x in styles))
        self.assertTrue(any(x["st"] == "lst_1" for x in styles))
        self.assertTrue(any(x["st"] == "ind_$" and x.get("indentSize") == 2 for x in styles))

    def test_nested_color_bold_italic_becomes_multiple_style_ranges(self):
        content = build_zalo_message_content("{green}***Hệ thống tốt***{/green}")
        self.assertEqual(content["msg"], "Hệ thống tốt")
        codes = {item["st"] for item in content["styles"]}
        self.assertTrue({"c_15a85f", "b", "i"}.issubset(codes))

    def test_utf16_offsets_are_correct_after_emoji(self):
        content = build_zalo_message_content("🛏️ **Phòng**")
        self.assertEqual(content["msg"], "🛏️ Phòng")
        bold = next(item for item in content["styles"] if item["st"] == "b")
        # JavaScript/Zalo offsets are UTF-16 code units: 🛏 is a surrogate pair,
        # U+FE0F is one unit and the following space is one unit => 4.
        self.assertEqual(bold["start"], 4)
        self.assertEqual(bold["len"], 5)

    def test_all_documented_inline_styles_compile(self):
        raw = "**B** *I* ***BI*** __U__ ~~S~~ `C` {red}R{/red} {orange}O{/orange} {yellow}Y{/yellow} {green}G{/green} {big}BIG{/big} {small}SM{/small}"
        content = build_zalo_message_content(raw)
        self.assertNotRegex(content["msg"], r"\*\*|__|~~|\{/?(?:red|orange|yellow|green|big|small)\}|`")
        codes = {item["st"] for item in content["styles"]}
        self.assertTrue({"b", "i", "u", "s", "c_db342e", "c_f27806", "c_f7b503", "c_15a85f", "f_18", "f_13"}.issubset(codes))

    def test_markdown_link_is_replaced_by_url(self):
        content = build_zalo_message_content("Xem [trang này](https://example.com/a)")
        self.assertEqual(content["msg"], "Xem https://example.com/a")

    def test_plain_leading_spaces_become_indent_style(self):
        content = build_zalo_message_content("  Dòng thụt lề")
        self.assertEqual(content["msg"], "Dòng thụt lề")
        indent = next(item for item in content["styles"] if item["st"] == "ind_$")
        self.assertEqual(indent["indentSize"], 2)

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


    def test_plain_list_label_gets_bold_automatically(self):
        content = build_zalo_message_content("- Dương lịch: Thứ Hai, ngày 02 tháng 11 năm 2026")
        self.assertEqual(content["msg"], "Dương lịch: Thứ Hai, ngày 02 tháng 11 năm 2026")
        bold = [x for x in content["styles"] if x["st"] == "b"]
        self.assertTrue(bold)
        self.assertEqual(bold[0]["start"], 0)
        self.assertEqual(bold[0]["len"], len("Dương lịch:"))

    def test_status_value_gets_conservative_auto_color(self):
        content = build_zalo_message_content("- Cửa phòng: Đang mở")
        orange = next(x for x in content["styles"] if x["st"] == "c_f27806")
        self.assertEqual(content["msg"][orange["start"]:orange["start"] + orange["len"]], "Đang mở")

        content = build_zalo_message_content("- Quạt: Bật")
        green = next(x for x in content["styles"] if x["st"] == "c_15a85f")
        self.assertEqual(content["msg"][green["start"]:green["start"] + green["len"]], "Bật")

        content = build_zalo_message_content("- Kết nối: Lỗi")
        red = next(x for x in content["styles"] if x["st"] == "c_db342e")
        self.assertEqual(content["msg"][red["start"]:red["start"] + red["len"]], "Lỗi")

    def test_explicit_color_is_not_overridden_by_auto_color(self):
        content = build_zalo_message_content("- Cửa: {red}Đang mở{/red}")
        codes = [x["st"] for x in content["styles"] if x["st"].startswith("c_")]
        self.assertIn("c_db342e", codes)
        self.assertNotIn("c_f27806", codes)

    def test_long_non_list_sentence_before_colon_is_not_auto_bolded(self):
        content = build_zalo_message_content("Ngày 24 tháng 9 năm 2026 Âm lịch tương ứng với:")
        self.assertFalse(any(x["st"] == "b" for x in content["styles"]))

    def test_duplicate_bold_spans_are_merged(self):
        content = build_zalo_message_content("- **Trạng thái:** Bật")
        bold = [x for x in content["styles"] if x["st"] == "b"]
        self.assertEqual(len(bold), 1)

    def test_long_message_splits_on_boundaries(self):
        raw = "\n\n".join(f"### Muc {i}\n- **Trang thai:** `on`" for i in range(60))
        chunks = split_zalo_message(raw, limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 500 for chunk in chunks))
        self.assertTrue(all("###" in chunk for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
