"""Deterministic file-race regressions for proposal journals and compensation."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from app import knowledge_governance as kg, rag
from app.db import conn, init_db
from app.settings import settings


class KnowledgeTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {key: getattr(settings, key) for key in ("db_path", "knowledge_dir")}
        settings.db_path = str(Path(self.tmp.name) / "db" / "test.db")
        settings.knowledge_dir = str(Path(self.tmp.name) / "knowledge")
        self.root = Path(settings.knowledge_dir)
        self.root.mkdir()
        init_db()
        kg.ensure_schema()
        self.before = {"a.md": b"Original A\r\n", "b.md": b"Original B\r\n"}
        self.after = {"a.md": b"Reviewed A\n", "b.md": b"Reviewed B\n"}
        for name, content in self.before.items():
            self.write(name, content)
        rag.reindex_knowledge()

    def tearDown(self):
        for key, value in self.old.items():
            setattr(settings, key, value)
        self.tmp.cleanup()

    def write(self, name, content):
        # Bytes matter: TextIO's Windows newline conversion must not disguise a
        # changed file or weaken the expected-hash assertions.
        (self.root / name).write_bytes(content)

    def read(self, name):
        return (self.root / name).read_bytes()

    def draft(self):
        return kg.create_proposal(
            [{"path": name, "new_content": content.decode("utf-8")} for name, content in self.after.items()],
            "Reviewed two-file correction", actor="test-admin",
        )

    def journal(self, *, status="applying", paths=None):
        proposal = self.draft()
        paths = paths or list(self.before)
        backup = [{"path": name, "content": base64.b64encode(self.before[name]).decode("ascii"),
                   "before_hash": kg._hash(self.before[name]), "after_hash": kg._hash(self.after[name])}
                  for name in paths]
        for name in paths:
            self.write(name, self.after[name])
        with conn() as connection:
            connection.execute("UPDATE knowledge_proposals SET status=?,backup=? WHERE id=?",
                               (status, json.dumps(backup), proposal["id"]))
        return proposal

    def test_partial_apply_external_second_file_is_preserved_and_first_restored(self):
        proposal = self.draft()
        original_write = kg._write

        def mutate_next_file(path, data):
            original_write(path, data)
            if path == "a.md" and data == self.after["a.md"]:
                self.write("b.md", b"Operator B\r\n")

        with patch.object(kg, "_write", side_effect=mutate_next_file):
            with self.assertRaisesRegex(ValueError, "changed during apply"):
                kg.approve(proposal["id"], "admin")
        self.assertEqual(self.read("a.md"), self.before["a.md"])
        self.assertEqual(self.read("b.md"), b"Operator B\r\n")
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "failed")

    def test_apply_failed_index_preserves_operator_edit_and_requires_recovery(self):
        proposal = self.draft()

        def fail_after_external_edit():
            self.write("a.md", b"Operator A after apply\r\n")
            raise RuntimeError("index unavailable")

        with patch.object(rag, "reindex_knowledge", side_effect=fail_after_external_edit):
            with self.assertRaisesRegex(RuntimeError, "index unavailable"):
                kg.approve(proposal["id"], "admin")
        self.assertEqual(self.read("a.md"), b"Operator A after apply\r\n")
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_apply_compensation_checks_each_file_again(self):
        proposal = self.draft()
        original_write = kg._write

        def race_during_compensation(path, data):
            original_write(path, data)
            if path == "b.md" and data == self.before["b.md"]:
                self.write("a.md", b"Operator A during compensation\r\n")

        with patch.object(kg, "_write", side_effect=race_during_compensation), patch.object(
            rag, "reindex_knowledge", side_effect=RuntimeError("index unavailable")
        ):
            with self.assertRaises(RuntimeError):
                kg.approve(proposal["id"], "admin")
        self.assertEqual(self.read("a.md"), b"Operator A during compensation\r\n")
        self.assertEqual(self.read("b.md"), self.before["b.md"])
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_two_index_failures_mark_apply_recovery_required_after_byte_restore(self):
        proposal = self.draft()
        with patch.object(rag, "reindex_knowledge", return_value={"retained_previous": True, "errors": []}):
            with self.assertRaises(RuntimeError):
                kg.approve(proposal["id"], "admin")
        self.assertEqual({name: self.read(name) for name in self.before}, self.before)
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_mid_rollback_edit_is_preserved_and_restored_file_is_compensated(self):
        proposal = self.draft()
        kg.approve(proposal["id"], "admin")
        original_write = kg._write

        def mutate_next_restore(path, data):
            original_write(path, data)
            if path == "b.md" and data == self.before["b.md"]:
                self.write("a.md", b"Operator A during rollback\r\n")

        with patch.object(kg, "_write", side_effect=mutate_next_restore):
            with self.assertRaisesRegex(RuntimeError, "Concurrent edit prevents restore"):
                kg.rollback(proposal["id"], "admin")
        self.assertEqual(self.read("a.md"), b"Operator A during rollback\r\n")
        self.assertEqual(self.read("b.md"), self.after["b.md"])
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "applied")
        self.assertIn("rollback_failed", {row["action"] for row in kg.audit_log()})

    def test_failed_rollback_compensation_does_not_overwrite_operator_edit(self):
        proposal = self.draft()
        kg.approve(proposal["id"], "admin")

        def fail_after_external_edit():
            self.write("b.md", b"Operator B during rollback indexing\r\n")
            raise RuntimeError("rollback index unavailable")

        with patch.object(rag, "reindex_knowledge", side_effect=fail_after_external_edit):
            with self.assertRaises(RuntimeError):
                kg.rollback(proposal["id"], "admin")
        self.assertEqual(self.read("b.md"), b"Operator B during rollback indexing\r\n")
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_compensation_race_after_first_file_is_detected(self):
        proposal = self.draft()
        kg.approve(proposal["id"], "admin")
        original_write = kg._write

        def race_during_compensation(path, data):
            original_write(path, data)
            if path == "b.md" and data == self.after["b.md"]:
                self.write("a.md", b"Operator A during rollback compensation\r\n")

        with patch.object(kg, "_write", side_effect=race_during_compensation), patch.object(
            rag, "reindex_knowledge", side_effect=RuntimeError("index unavailable")
        ):
            with self.assertRaises(RuntimeError):
                kg.rollback(proposal["id"], "admin")
        self.assertEqual(self.read("a.md"), b"Operator A during rollback compensation\r\n")
        self.assertEqual(self.read("b.md"), self.after["b.md"])
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_crash_recovery_does_not_recapture_an_unvalidated_external_hash(self):
        proposal = self.journal(paths=["a.md"])
        original_hash = kg._current_hash
        calls = 0

        def edit_after_first_validation(path):
            nonlocal calls
            if path == "a.md":
                calls += 1
                if calls == 2:
                    self.write("a.md", b"Operator A after crash validation\r\n")
            return original_hash(path)

        with patch.object(kg, "_current_hash", side_effect=edit_after_first_validation):
            kg.recover_interrupted()
        self.assertEqual(self.read("a.md"), b"Operator A after crash validation\r\n")
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_crash_recovery_checks_each_file_before_restoring(self):
        proposal = self.journal()
        original_write = kg._write

        def edit_next_recovery_file(path, data):
            original_write(path, data)
            if path == "b.md":
                self.write("a.md", b"Operator A during recovery\r\n")

        with patch.object(kg, "_write", side_effect=edit_next_recovery_file):
            kg.recover_interrupted()
        self.assertEqual(self.read("a.md"), b"Operator A during recovery\r\n")
        self.assertEqual(self.read("b.md"), self.before["b.md"])
        self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_crash_index_failure_requires_recovery_despite_restored_bytes(self):
        for status in ("applying", "rolling_back"):
            with self.subTest(status=status):
                proposal = self.journal(status=status)
                with patch.object(rag, "reindex_knowledge", return_value={"errors": ["index failed"], "retained_previous": True}):
                    kg.recover_interrupted()
                self.assertEqual({name: self.read(name) for name in self.before}, self.before)
                self.assertEqual(kg.get_proposal(proposal["id"])["status"], "recovery_required")

    def test_cleanup_preserves_desired_scene_parameters_and_entity_actions(self):
        text = """scenes:
  - entity_id: scene.good_night
    name: Good night
    state: '2026-10-04T00:00:00Z'
    entities:
      climate.bedroom:
        temperature: 26
      light.bedroom:
        state: 'on'
        brightness: 120
entities:
  - entity_id: light.bedroom
    name: Bedroom lamp
    state: 'on'
    attributes:
      brightness: 99
    preferred_actions:
      - service: light.turn_on
        data:
          brightness: 160
    capabilities:
      brightness: [0, 255]
    static_limits:
      temperature: [16, 30]
"""
        parsed = yaml.safe_load(text)
        self.assertTrue(kg._clean_catalog(parsed))
        scene, entity = parsed["scenes"][0], parsed["entities"][0]
        self.assertNotIn("state", scene)
        self.assertEqual(scene["entities"]["climate.bedroom"]["temperature"], 26)
        self.assertEqual(scene["entities"]["light.bedroom"], {"state": "on", "brightness": 120})
        self.assertNotIn("state", entity)
        self.assertNotIn("brightness", entity.get("attributes", {}))
        self.assertEqual(entity["preferred_actions"][0]["data"]["brightness"], 160)
        self.assertEqual(entity["capabilities"]["brightness"], [0, 255])
        self.assertEqual(entity["static_limits"]["temperature"], [16, 30])
        proposed = kg.create_proposal([{"path": "devices.yaml", "new_content": yaml.safe_dump(parsed)}], "Remove stale observations", actor="test-admin")
        self.assertTrue(kg.dry_run(proposed["id"])["valid"])
        kg.approve(proposed["id"], "admin")
        live_index = rag.search_knowledge("Good night", kind="scene")
        self.assertTrue(live_index)
        self.assertIn('"temperature": 26', live_index[0]["text"])


if __name__ == "__main__":
    unittest.main()
