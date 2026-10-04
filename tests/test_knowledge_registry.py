import json
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from app import rag
from app.db import conn
from app.settings import settings


class KnowledgeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "knowledge"
        self.root.mkdir()
        self.old_db, self.old_root = settings.db_path, settings.knowledge_dir
        settings.db_path = str(Path(self.tmp.name) / "test.sqlite")
        settings.knowledge_dir = str(self.root)

    def tearDown(self):
        settings.db_path, settings.knowledge_dir = self.old_db, self.old_root
        self.tmp.cleanup()

    def write(self, name, data):
        text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
        (self.root / name).write_text(text, encoding="utf-8")

    def registry(self, entities=None):
        return {"schema_version": 1, "areas": [{"id": "bedroom", "name": "Phòng ngủ", "aliases": ["PN"]},
                                                {"id": "living", "name": "Phòng khách", "aliases": ["PK"]}],
                "entities": entities or [{"entity_id": "light.bedroom", "name": "Đèn trần", "aliases": ["đèn ngủ"], "area_id": "bedroom"},
                                         {"entity_id": "light.living", "name": "Đèn khách", "aliases": ["đèn chính"], "area_id": "living"}]}

    def test_registry_all_kinds_and_legacy_formats(self):
        data = self.registry()
        data.update(scenes=[{"entity_id": "scene.night", "name": "Ban đêm"}],
                    scripts=[{"entity_id": "script.welcome", "name": "Chào nhà"}],
                    references=[{"id": "manual", "text": "Hướng dẫn bộ lọc"}],
                    rules=[{"id": "quiet", "text": "Yên lặng sau 22h"}],
                    procedures=[{"id": "reset", "steps": ["Tắt điện", "Bật điện"]}])
        self.write("catalog.json", data)
        self.write("manual.md", "# Thiết bị\nHướng dẫn vệ sinh máy lạnh")
        self.write("old.txt", "Thông tin bảo hành điều hòa")
        self.write("old.yaml", "house_name: Nhà Khai\n")
        self.write("other.yml", "- thông tin chung\n")
        result = rag.reindex_knowledge()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["files"], 5)
        self.assertEqual({r["kind"] for r in rag.load_catalog()}, rag.KINDS)
        hits = rag.search_knowledge("vệ sinh")
        self.assertTrue(any(h["path"] == "manual.md" for h in hits))
        self.assertTrue({"id", "path", "chunk_index", "text", "updated_at", "score", "kind", "source"}.issubset(hits[0]))

    def test_resolution_priority_exact_alias_name_area_domain(self):
        self.write("registry.json", self.registry())
        rag.reindex_knowledge()
        for query, match_type in [("light.bedroom", "entity_id"), ("den ngu", "alias"), ("den tran", "name"), ("đèn phòng ngủ", "area_domain")]:
            with self.subTest(query=query):
                result = rag.resolve_entity(query)
                self.assertEqual(result["entity_id"], "light.bedroom")
                self.assertEqual(result["match_type"], match_type)
                self.assertTrue(result["safe_for_control"])
        self.assertEqual(rag.resolve_entity("đèn PN")["match_type"], "area_domain")

    def test_alias_outranks_other_entity_name(self):
        self.write("registry.json", self.registry([
            {"entity_id": "light.one", "name": "Đèn một", "aliases": ["đèn chính"]},
            {"entity_id": "light.two", "name": "Đèn chính"}]))
        rag.reindex_knowledge()
        result = rag.resolve_entity("đèn chính")
        self.assertEqual(result["entity_id"], "light.one")
        self.assertEqual(result["match_type"], "alias")

    def test_ambiguous_alias_requires_area(self):
        data = self.registry()
        for entity in data["entities"]:
            entity["aliases"] = ["đèn chính"]
        self.write("registry.json", data)
        result = rag.reindex_knowledge()
        self.assertTrue(any(d["code"] == "alias_conflict" for d in result["warnings"]))
        ambiguous = rag.resolve_entity("đèn chính")
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertIsNone(ambiguous["entity_id"])
        self.assertFalse(ambiguous["safe_for_control"])
        exact = rag.resolve_entity("đèn chính", area="PN", domain="light")
        self.assertEqual(exact["entity_id"], "light.bedroom")
        self.assertTrue(exact["safe_for_control"])
        self.assertTrue(all(not h["safe_for_control"] for h in rag.search_knowledge("đèn chính")))

    def test_fuzzy_never_authorizes_control(self):
        self.write("registry.json", self.registry())
        rag.reindex_knowledge()
        result = rag.resolve_entity("đèn trầnn")
        self.assertEqual(result["match_type"], "fuzzy")
        self.assertLess(result["confidence"], 0.85)
        self.assertFalse(result["safe_for_control"])
        self.assertTrue(all(not h["safe_for_control"] for h in rag.search_knowledge("đèn trầnn")))

    def test_area_domain_never_drops_specific_device_words(self):
        self.write("registry.json", self.registry())
        rag.reindex_knowledge()
        result = rag.resolve_entity("đèn bàn phòng ngủ")
        self.assertNotEqual(result["match_type"], "area_domain")
        self.assertFalse(result["safe_for_control"])

    def test_live_fields_excluded_but_static_service_parameters_preserved(self):
        self.write("entities.json", {"entities": [{"entity_id": "climate.bedroom", "name": "Máy lạnh",
            "state": "cool", "attributes": {"current_temperature": 31.5, "min_temp": 16},
            "metadata": {"battery": 18}, "preferred_actions": [{"service": "climate.set_temperature", "data": {"temperature": 26}}]}],
            "scenes": [{"entity_id": "scene.cool", "name": "Mát", "state": "on", "service_data": {"temperature": 25, "brightness": 70}}]})
        result = rag.reindex_knowledge()
        self.assertEqual(result["status"], "ready")
        entity = next(r for r in rag.load_catalog() if r["kind"] == "entity")
        self.assertNotIn('"state"', entity["text"])
        self.assertNotIn("31.5", entity["text"])
        self.assertNotIn('"battery"', entity["text"])
        self.assertIn('"temperature": 26', entity["text"])
        self.assertIn('"min_temp": 16', entity["text"])
        scene = next(r for r in rag.load_catalog() if r["kind"] == "scene")
        self.assertIn('"brightness": 70', scene["text"])
        self.assertNotIn('"state"', scene["text"])
        self.assertTrue(any(d["code"] == "realtime_fields" for d in result["warnings"]))

    def test_domain_conflict_blocks_even_exact_resolution(self):
        self.write("registry.json", self.registry([{"entity_id": "light.bedroom", "name": "Đèn", "domain": "switch"}]))
        indexed = rag.reindex_knowledge()
        self.assertTrue(any(d["code"] == "domain_conflict" for d in indexed["warnings"]))
        result = rag.resolve_entity("light.bedroom")
        self.assertEqual(result["status"], "ambiguous")
        self.assertFalse(result["safe_for_control"])

    def test_duplicate_definitions_conflict_and_area_conflict(self):
        self.write("one.json", self.registry([{"entity_id": "light.bedroom", "name": "Đèn", "area_id": "bedroom", "area": "Phòng khách"}]))
        self.write("two.json", {"entities": [{"entity_id": "light.bedroom", "name": "Đèn khác", "area_id": "living"}]})
        result = rag.reindex_knowledge()
        codes = {d["code"] for d in result["warnings"]}
        self.assertTrue({"entity_conflict", "area_conflict"}.issubset(codes))
        conflict = next(d for d in result["warnings"] if d["code"] == "entity_conflict")
        self.assertEqual(conflict["entity_id"], "light.bedroom")
        self.assertTrue({"name", "area"}.issubset(conflict["conflict_fields"]))
        self.assertEqual({d["path"] for d in conflict["definitions"]}, {"one.json", "two.json"})
        self.assertTrue(all(d["location"] for d in conflict["definitions"]))
        area_conflict = next(d for d in result["warnings"] if d["code"] == "area_conflict")
        self.assertEqual(area_conflict["actual_area"], "Phòng khách")
        self.assertIn("Phòng ngủ", area_conflict["accepted_labels"])
        self.assertFalse(rag.resolve_entity("Đèn")["safe_for_control"])

    def test_index_error_preserves_previous_catalog_and_hash(self):
        self.write("registry.json", self.registry())
        first = rag.reindex_knowledge()
        manifest_hash = rag.index_status()["manifest"][0]["sha256"]
        self.write("registry.json", "{broken json")
        second = rag.reindex_knowledge()
        self.assertEqual(second["status"], "error")
        self.assertTrue(second["retained_previous"])
        self.assertEqual(second["indexed_fingerprint"], first["fingerprint"])
        self.assertEqual(len(rag.load_catalog()), 4)
        self.assertEqual(rag.index_status()["manifest"][0]["sha256"], manifest_hash)
        resolution = rag.resolve_entity("đèn ngủ")
        self.assertEqual(resolution["entity_id"], "light.bedroom")
        self.assertFalse(resolution["safe_for_control"])
        self.assertEqual(resolution["index_warning"]["code"], "index_error")
        self.assertTrue(all(not c["safe_for_control"] for c in resolution["candidates"]))
        hits = rag.search_knowledge("đèn ngủ")
        self.assertTrue(hits)
        self.assertTrue(all(not h["safe_for_control"] and h["index_warning"] for h in hits))

    def test_new_scan_drift_disables_control_until_reindex(self):
        self.write("registry.json", self.registry())
        rag.reindex_knowledge()
        self.assertTrue(rag.resolve_entity("đèn ngủ")["safe_for_control"])
        changed = self.registry()
        changed["entities"][0]["aliases"] = ["đèn phòng ngủ"]
        self.write("registry.json", changed)
        snapshot = rag.inspect_knowledge()
        with conn() as c:
            c.execute("CREATE TABLE knowledge_control(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            c.execute("INSERT INTO knowledge_control(key,value) VALUES('latest_scan',?)",
                      (json.dumps({"fingerprint": snapshot["fingerprint"], "created_at": snapshot["scanned_at"]}),))
        stale = rag.resolve_entity("đèn ngủ")
        self.assertEqual(stale["entity_id"], "light.bedroom")
        self.assertFalse(stale["safe_for_control"])
        self.assertEqual(stale["index_warning"]["code"], "stale_index")
        self.assertTrue(rag.index_status()["stale"])
        self.assertFalse(rag.search_knowledge("đèn ngủ")[0]["safe_for_control"])
        rag.reindex_knowledge()
        self.assertTrue(rag.resolve_entity("đèn phòng ngủ")["safe_for_control"])
        self.assertIsNone(rag.index_status()["index_warning"])

    def test_successful_index_supersedes_older_scan(self):
        self.write("registry.json", self.registry())
        old = rag.inspect_knowledge()
        with conn() as c:
            c.execute("CREATE TABLE knowledge_control(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            c.execute("INSERT INTO knowledge_control(key,value) VALUES('latest_scan',?)",
                      (json.dumps({"fingerprint": old["fingerprint"], "created_at": old["scanned_at"]}),))
        self.write("new.txt", "A new manual")
        rag.reindex_knowledge()
        self.assertTrue(rag.resolve_entity("đèn ngủ")["safe_for_control"])
        self.assertIsNone(rag.index_status()["index_warning"])

    def test_transaction_failure_does_not_replace_previous_index(self):
        self.write("old.txt", "Old retained reference")
        first = rag.reindex_knowledge()
        self.write("old.txt", "New reference")
        # A trigger models an actual mid-insertion database failure.
        with conn() as c:
            c.execute("CREATE TRIGGER reject_new BEFORE INSERT ON knowledge_records BEGIN SELECT RAISE(ABORT,'insertion failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            rag.reindex_knowledge()
        self.assertIn("Old retained", rag.search_knowledge("retained")[0]["text"])
        self.assertEqual(rag.index_status()["indexed_fingerprint"], first["fingerprint"])

    def test_new_changed_deleted_files_manifest(self):
        self.write("one.md", "A manual")
        first = rag.inspect_knowledge()
        self.assertEqual(first["fingerprint"], rag.inspect_knowledge()["fingerprint"])
        self.write("two.txt", "Second manual")
        second = rag.inspect_knowledge()
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.write("one.md", "Changed manual")
        self.assertNotEqual(second["fingerprint"], rag.inspect_knowledge()["fingerprint"])
        (self.root / "one.md").unlink()
        rag.reindex_knowledge()
        self.assertEqual([f["path"] for f in rag.index_status()["manifest"]], ["two.txt"])

    def test_bounded_file_size_and_bad_utf8(self):
        self.write("ok.txt", "ok")
        with patch.object(rag, "settings") as mocked:
            mocked.knowledge_dir = str(self.root)
            mocked.knowledge_max_file_bytes, mocked.knowledge_max_total_bytes, mocked.knowledge_max_files = 1, 100, 10
            result = rag.inspect_knowledge()
        self.assertEqual(result["files"][0]["status"], "error")
        (self.root / "bad.txt").write_bytes(b"\xff")
        result = rag.reindex_knowledge()
        self.assertEqual(result["status"], "error")

    def test_path_traversal_and_symlink_are_rejected(self):
        self.write("ok.md", "ok")
        for path in ["../outside.md", "C:/outside.md", "/outside.md", "sub\\outside.md", ".internal/file.md", "file.exe"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                rag.safe_knowledge_path(path)
        # Works without Windows symlink privileges: exercise path guard directly.
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda p: p.name == "ok.md" or original(p)):
            with self.assertRaises(ValueError):
                rag.safe_knowledge_path("ok.md", must_exist=True)
            self.assertEqual(rag.inspect_knowledge()["files"][0]["status"], "error")

    def test_safe_yaml_markdown_frontmatter_and_keyed_entities(self):
        parsed = rag.parse_knowledge_text("unsafe.yaml", "!!python/object/apply:os.system ['echo unsafe']")
        self.assertEqual(parsed["diagnostics"][0]["severity"], "error")
        parsed = rag.parse_knowledge_text("entity.md", "---\nkind: entity\nentity_id: light.desk\nname: Đèn bàn\n---\nThiết bị đọc sách")
        self.assertEqual(parsed["records"][0]["entity_id"], "light.desk")
        self.assertIn("Thiết bị đọc sách", parsed["records"][0]["text"])
        parsed = rag.parse_knowledge_text("keyed.yml", "light.desk:\n  name: Đèn bàn\n")
        self.assertEqual(parsed["records"][0]["entity_id"], "light.desk")
        self.assertTrue(rag.parse_knowledge_text("unsupported.json", '{"schema_version": 99, "entities": []}')["diagnostics"])

    def test_no_entity_resolution_from_legacy_narrative(self):
        self.write("old.md", "The desk lamp is light.desk. Turn it on when asked.")
        rag.reindex_knowledge()
        self.assertEqual(rag.resolve_entity("light.desk")["status"], "not_found")
        self.assertTrue(rag.search_knowledge('light.desk OR " *')[0]["text"])

    def test_inherited_area_and_document_aliases(self):
        self.write("bedroom.yaml", """schema_version: 1
area:
  id: bedroom
  name: Phòng ngủ
  aliases: [PN]
domain: light
aliases:
  light.desk: [đèn đọc sách]
  đèn bàn: light.desk
entities:
  - entity_id: light.desk
    name: Đèn học
""")
        self.assertEqual(rag.reindex_knowledge()["status"], "ready")
        entity = next(r for r in rag.load_catalog() if r["kind"] == "entity")
        self.assertEqual(entity["area_id"], "bedroom")
        self.assertEqual(entity["area"], "Phòng ngủ")
        self.assertEqual(set(entity["aliases"]), {"đèn đọc sách", "đèn bàn"})
        self.assertTrue(rag.resolve_entity("đèn PN")["safe_for_control"])
        self.assertEqual(rag.resolve_entity("đèn đọc sách", area="PN")["entity_id"], "light.desk")

    def test_duplicate_compatible_entity_definitions_merge_aliases(self):
        self.write("one.json", {"entities": [{"entity_id": "light.desk", "name": "Desk lamp", "aliases": ["reading lamp"]}]})
        self.write("two.json", {"entities": [{"entity_id": "light.desk", "name": "Desk lamp", "aliases": ["desk light"]}]})
        rag.reindex_knowledge()
        self.assertTrue(rag.resolve_entity("reading lamp")["safe_for_control"])

    def test_reference_entity_association_is_not_control_authority(self):
        self.write("reference.json", {"kind": "reference", "entity_id": "light.desk", "name": "Reading lamp", "text": "Read the manual"})
        rag.reindex_knowledge()
        self.assertEqual(rag.resolve_entity("Reading lamp")["status"], "not_found")
        self.assertFalse(rag.search_knowledge("Reading lamp")[0]["safe_for_control"])
        self.write("entity.json", {"entities": [{"entity_id": "light.desk", "name": "Desk lamp"}]})
        indexed = rag.reindex_knowledge()
        self.assertFalse(any(d["code"] == "entity_conflict" for d in indexed["warnings"]))
        self.assertTrue(rag.resolve_entity("Desk lamp")["safe_for_control"])

    def test_filters_and_query_punctuation(self):
        self.write("registry.json", self.registry())
        rag.reindex_knowledge()
        hits = rag.search_knowledge('"đèn" OR *', area="PN", domain="light", kind="entity")
        self.assertEqual({h["entity_id"] for h in hits}, {"light.bedroom"})
        self.assertEqual(rag.search_knowledge(""), [])
        with self.assertRaises(ValueError):
            rag.search_knowledge("đèn", kind="unsupported")

    def test_legacy_json_type_and_schema_version_remain_reference(self):
        self.write("legacy.json", {"type": "device", "schema_version": 4, "description": "Legacy manual"})
        self.assertEqual(rag.reindex_knowledge()["status"], "ready")
        self.assertEqual(rag.load_catalog()[0]["kind"], "reference")
        self.assertTrue(rag.search_knowledge("manual"))

    def test_thousand_record_retrieval_preserves_late_filtered_hits(self):
        self.write("large.json", {"entities": [{"entity_id": f"light.item_{i}", "name": f"Đèn số {i}"} for i in range(1000)],
                                  "rules": [{"id": "late", "text": "Đèn phải tắt khi đi ngủ"}]})
        rag.reindex_knowledge()
        started = perf_counter()
        exact = rag.search_knowledge("light.item_999")
        filtered = rag.search_knowledge("den", kind="rules")
        elapsed = perf_counter() - started
        self.assertEqual(exact[0]["entity_id"], "light.item_999")
        self.assertEqual(filtered[0]["kind"], "rules")
        self.assertLess(elapsed, 5.0, "1000-record lookup exceeded the generous local latency budget")

    def test_normalized_fts_absence_falls_back_without_losing_results(self):
        self.write("registry.json", self.registry())
        rag.reindex_knowledge()
        with conn() as c:
            c.execute("DROP TABLE knowledge_lookup")
        self.assertEqual(rag.search_knowledge("den ngu")[0]["entity_id"], "light.bedroom")


if __name__ == "__main__":
    unittest.main()
