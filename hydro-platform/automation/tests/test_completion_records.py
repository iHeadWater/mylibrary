"""Completion is saved content + provenance, never merely a directory or task flag."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydrolitagent.cards.card_generation import CardGenerationError
from hydrolitagent.cards.evidence_packages import EvidencePackageError, PLACEHOLDER_CARD
from hydrolitagent.cards.publication import text_hash, validate_saved_package
from test_card_generation import FakeAdapter, GenerationFixture, PARENT_KEY


class CompletionRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = GenerationFixture(Path(self.temp.name))

    def manifest(self):
        return json.loads((self.f.package / "manifest.json").read_text(encoding="utf-8"))

    def save_manifest(self, manifest):
        (self.f.package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def assert_not_completed_or_overwritten(self, code):
        before = {p.name: p.read_bytes() for p in self.f.package.iterdir() if p.is_file()}
        tasks = self.f.task_path.read_bytes()
        adapter = FakeAdapter()
        with self.assertRaises(CardGenerationError) as caught:
            self.f.generate(adapter)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(adapter.calls, [])
        self.assertEqual(self.f.task_path.read_bytes(), tasks)
        self.assertEqual({p.name: p.read_bytes() for p in self.f.package.iterdir() if p.is_file()}, before)

    def test_placeholder_is_not_complete_and_can_be_generated(self):
        self.assertIsNone(validate_saved_package(self.f.package))
        adapter = FakeAdapter()
        self.assertEqual(self.f.generate(adapter)["action"], "GENERATED")
        self.assertEqual(len(adapter.calls), 1)
        self.assertIsNotNone(validate_saved_package(self.f.package))

    def test_directory_without_card_or_manifest_is_not_complete(self):
        (self.f.package / "card.md").unlink()
        (self.f.package / "manifest.json").unlink()
        self.assert_not_completed_or_overwritten("EVIDENCE_PACKAGE_INCOMPLETE")

    def test_arbitrary_text_without_generation_record_is_not_existing_card(self):
        for text in ("", " \n", "A manually edited draft, without a completion record"):
            with self.subTest(text=text):
                (self.f.package / "card.md").write_text(text, encoding="utf-8")
                self.assert_not_completed_or_overwritten("EVIDENCE_PACKAGE_INCONSISTENT")

    def test_complete_task_flag_with_placeholder_is_not_trusted(self):
        registry = json.loads(self.f.task_path.read_text(encoding="utf-8"))
        registry["tasks"][PARENT_KEY]["state"] = "COMPLETED"
        self.f.task_path.write_text(json.dumps(registry), encoding="utf-8")
        self.assert_not_completed_or_overwritten("EVIDENCE_PACKAGE_INCONSISTENT")

    def test_missing_completion_record_is_not_trusted(self):
        self.f.generate(FakeAdapter())
        manifest = self.manifest()
        manifest.pop("generation")
        self.save_manifest(manifest)
        self.assert_not_completed_or_overwritten("EVIDENCE_MANIFEST_INVALID")

    def test_matching_hash_cannot_make_blank_or_placeholder_complete(self):
        self.f.generate(FakeAdapter())
        for text in ("", " \n\t", PLACEHOLDER_CARD, PLACEHOLDER_CARD + "\n"):
            with self.subTest(text=text):
                (self.f.package / "card.md").write_text(text, encoding="utf-8")
                manifest = self.manifest()
                manifest["generation"]["card_sha256"] = text_hash(text)
                self.save_manifest(manifest)
                with self.assertRaises(EvidencePackageError) as caught:
                    validate_saved_package(self.f.package)
                self.assertEqual(caught.exception.code, "EVIDENCE_CARD_EMPTY_OR_PLACEHOLDER")
                self.assert_not_completed_or_overwritten("EVIDENCE_CARD_EMPTY_OR_PLACEHOLDER")

    def test_changed_hash_is_not_skipped_as_completed(self):
        self.f.generate(FakeAdapter())
        (self.f.package / "card.md").write_text("user changes", encoding="utf-8")
        self.assert_not_completed_or_overwritten("EVIDENCE_CARD_CHANGED")

    def test_missing_audit_is_not_complete(self):
        self.f.generate(FakeAdapter())
        (self.f.package / "quality-audit.json").unlink()
        self.assert_not_completed_or_overwritten("EVIDENCE_CARD_INVALID")

    def test_valid_free_form_card_and_records_are_skipped_without_new_model_call(self):
        self.f.generate(FakeAdapter())
        # No new heading/table/wording constraints: keep free-form content acceptable.
        text = "自由格式研究笔记。无需特定标题、表格或归因标签。"
        (self.f.package / "card.md").write_text(text, encoding="utf-8")
        manifest = self.manifest()
        manifest["generation"]["card_sha256"] = text_hash(text)
        self.save_manifest(manifest)
        adapter = FakeAdapter()
        self.assertEqual(self.f.generate(adapter)["action"], "SKIPPED_EXISTING_CARD")
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
