import tempfile
import unittest
from pathlib import Path

from app.settings import settings
from app.skills import (
    compose_skill,
    create_skill,
    delete_skill,
    list_skill_versions,
    list_skills,
    read_skill,
    rollback_skill,
    set_skill_enabled,
    test_skill,
    update_skill,
    validate_skill_content,
)


class SkillManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_builtin = settings.skills_dir
        self.old_user = settings.user_skills_dir
        self.builtin = Path(self.tmp.name) / "builtin"
        self.user = Path(self.tmp.name) / "data" / "skills"
        self.builtin.mkdir(parents=True)
        settings.skills_dir = str(self.builtin)
        settings.user_skills_dir = str(self.user)
        (self.builtin / "lighting-optimizer.md").write_text(
            compose_skill(
                "lighting-optimizer",
                "Tối ưu ánh sáng theo trạng thái và ngữ cảnh Home Assistant.",
                "# Objective\nGiữ ánh sáng phù hợp.\n\n# Workflow\n1. Đọc state.\n2. Chỉ action khi cần.\n\n# Safety rules\nKhông sửa automation trực tiếp.",
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        settings.skills_dir = self.old_builtin
        settings.user_skills_dir = self.old_user
        self.tmp.cleanup()

    def test_builtin_edit_creates_versioned_override_and_delete_restores_default(self):
        base = read_skill("lighting-optimizer", include_disabled=True)
        self.assertEqual(base["source"], "builtin")
        self.assertEqual(base["version"], 1)
        updated = update_skill(
            "lighting-optimizer",
            "Tối ưu ánh sáng có kiểm tra lux, presence và trạng thái hiện tại.",
            "# Objective\nTối ưu ánh sáng.\n\n# Workflow\n1. Đọc lux.\n2. Đọc presence.\n3. Điều khiển idempotent.\n\n# Safety rules\nKhông action khi dữ liệu mơ hồ.",
            True,
        )
        self.assertEqual(updated["source"], "user")
        self.assertTrue(updated["override"])
        self.assertEqual(updated["version"], 2)
        self.assertTrue((self.user / "lighting-optimizer.md").exists())
        versions = list_skill_versions("lighting-optimizer")
        self.assertEqual(versions[0]["version"], 2)
        self.assertTrue(any(x["version"] == 1 for x in versions))

        rolled = rollback_skill("lighting-optimizer", 1)
        self.assertEqual(rolled["version"], 3)
        self.assertIn("Giữ ánh sáng phù hợp", rolled["body"])

        result = delete_skill("lighting-optimizer")
        self.assertTrue(result["restored_builtin"])
        restored = read_skill("lighting-optimizer", include_disabled=True)
        self.assertEqual(restored["source"], "builtin")
        self.assertIn("Giữ ánh sáng phù hợp", restored["body"])

    def test_user_skill_create_toggle_and_agent_listing(self):
        created = create_skill(
            "presence-aware-control",
            "Điều khiển thiết bị theo presence và occupancy của từng khu vực.",
            "# Objective\nĐiều khiển theo hiện diện.\n\n# Workflow\n1. Đọc sensor.\n2. Đọc device state.\n\n# Safety rules\nKhông tắt khi sensor unavailable.",
            True,
        )
        self.assertEqual(created["source"], "user")
        names = {x["name"] for x in list_skills()}
        self.assertIn("presence-aware-control", names)
        set_skill_enabled("presence-aware-control", False)
        self.assertNotIn("presence-aware-control", {x["name"] for x in list_skills()})
        admin = {x["name"]: x for x in list_skills(include_disabled=True)}
        self.assertFalse(admin["presence-aware-control"]["enabled"])
        with self.assertRaises(KeyError):
            read_skill("presence-aware-control")
        self.assertEqual(read_skill("presence-aware-control", include_disabled=True)["name"], "presence-aware-control")

    def test_invalid_manual_skill_is_visible_to_admin_but_not_agent(self):
        self.user.mkdir(parents=True)
        (self.user / "broken.md").write_text("# no frontmatter\nunsafe draft", encoding="utf-8")
        admin = {x["name"]: x for x in list_skills(include_disabled=True)}
        self.assertIn("broken", admin)
        self.assertFalse(admin["broken"]["valid"])
        self.assertNotIn("broken", {x["name"] for x in list_skills()})

    def test_validation_and_test_report(self):
        raw = compose_skill(
            "device-health-monitor",
            "Chẩn đoán entity unavailable, unknown và thiết bị Home Assistant bất thường.",
            "# Objective\nTìm lỗi thiết bị.\n\n# Workflow\n1. Đọc state.\n2. Kiểm tra event khi cần.\n\n# Safety rules\nKhông restart thiết bị tự động.",
        )
        checked = validate_skill_content(raw, expected_name="device-health-monitor")
        self.assertTrue(checked["ok"])
        create_skill(
            "device-health-monitor",
            checked["description"],
            checked["body"],
        )
        report = test_skill("device-health-monitor")
        self.assertTrue(report["ok"])
        self.assertTrue(report["checks"]["name_matches"])
        self.assertTrue(report["checks"]["has_structure"])

    def test_name_validation_blocks_path_traversal(self):
        with self.assertRaises(ValueError):
            create_skill("../escape", "Mô tả đủ dài để kiểm tra validation.", "# Workflow\nNội dung đủ dài để kiểm tra an toàn đường dẫn.")

    def test_symlink_skill_is_rejected_without_reading_target(self):
        self.user.mkdir(parents=True, exist_ok=True)
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("TOP-SECRET-SHOULD-NOT-BE-READ", encoding="utf-8")
        (self.user / "leak.md").symlink_to(outside)

        admin = {x["name"]: x for x in list_skills(include_disabled=True)}
        self.assertIn("leak", admin)
        self.assertFalse(admin["leak"]["valid"])
        self.assertIn("Symbolic-link skill files are not allowed", admin["leak"]["validation_errors"])
        self.assertNotIn("leak", {x["name"] for x in list_skills()})

    def test_invalid_manual_filename_does_not_break_admin_listing(self):
        self.user.mkdir(parents=True, exist_ok=True)
        (self.user / "Bad Name.md").write_text("# malformed manual skill", encoding="utf-8")
        rows = {x["name"]: x for x in list_skills(include_disabled=True)}
        self.assertIn("Bad Name", rows)
        self.assertFalse(rows["Bad Name"]["valid"])
        self.assertFalse(rows["Bad Name"]["manageable"])


if __name__ == "__main__":
    unittest.main()
