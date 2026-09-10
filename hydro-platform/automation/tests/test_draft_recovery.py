from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.card_generation import CardGenerationError
from hydro_platform.config import load_config
from hydro_platform.draft_recovery import recover_failed_draft
from hydro_platform.evidence_packages import EvidencePackageError, load_evidence_manifest
from hydro_platform.pipeline import run_once
from hydro_platform.publication import publication_path, recover_publication, validate_saved_package
from hydro_platform.tasks import RuntimeLock, load_task_registry, save_task_registry
from test_card_generation import FakeAdapter, GenerationFixture, NOW, PARENT_KEY, PDF_HASH
from test_config import write_config
from test_single_agent import BODY, configure_template


class DraftRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.f = GenerationFixture(root)
        configure_template(self.f)
        config = load_config(write_config(root))
        self.config = replace(config, card_generator=replace(config.card_generator, workflow_mode="single_agent", multi_agent_workflow=None))
        registry = load_task_registry(self.f.task_path, self.f.zotero.group_id)
        registry["tasks"][PARENT_KEY].update(state="QUALITY_FAILED", reason_code="SINGLE_CARD_CONTRACT_FAILED", attempt_count=1)
        save_task_registry(self.f.task_path, registry)
        self.task = deepcopy(registry["tasks"][PARENT_KEY])
        self.body = BODY.replace("【原文陈述】结果", "【原文陈述·方法】")
        self.record = {"schema_version": 1, "status": "UNVALIDATED_MODEL_OUTPUT", "parent_key": PARENT_KEY,
                       "source_pdf_sha256": PDF_HASH, "run_label": "card_writer", "exit_code": 0,
                       "model": "original-model", "reasoning_effort": "high", "prompt_sha256": "b" * 64,
                       "model_message": json.dumps({**FakeAdapter().output, "card_body_markdown": self.body})}
        self.draft = self.f.runtime / "generation-drafts" / "saved.json"
        self.draft.parent.mkdir()
        self.write_draft()

    def write_draft(self):
        self.draft.write_text(json.dumps(self.record), encoding="utf-8")

    def recover(self):
        return recover_failed_draft(self.config, self.task, now=NOW)

    def test_recovery_saves_formally_without_model_or_changing_body_and_provenance(self):
        original = self.draft.read_bytes()
        result = self.recover()
        self.assertFalse(result["model_invoked"])
        card = Path(result["card_path"]).read_text(encoding="utf-8")
        self.assertTrue(card.endswith(self.body))
        manifest = validate_saved_package(self.f.package)
        self.assertEqual(manifest["card_status"], "ROUGH")
        provenance = manifest["generation"]["recovery"]
        self.assertEqual(provenance["original_model"], "original-model")
        self.assertIsNone(provenance["original_template_version"])
        self.assertIsNone(provenance["original_generation_time"])
        self.assertFalse(provenance["full_read_verified"])
        self.assertFalse(provenance["scientific_correctness_verified"])
        task = load_task_registry(self.f.task_path, self.f.zotero.group_id)["tasks"][PARENT_KEY]
        self.assertEqual(task["state"], "COMPLETED")
        self.assertEqual(task["attempt_count"], 1)
        self.assertEqual(original, self.draft.read_bytes())
        protected = [self.f.package / "card.md", self.f.package / "manifest.json", self.f.task_path]
        before = [p.read_bytes() for p in protected]
        self.assertIsNone(self.recover())
        self.assertEqual(before, [p.read_bytes() for p in protected])

    def test_run_once_recovers_failure_without_generator_preflight(self):
        with patch("hydro_platform.pipeline.preflight", return_value={"ok": True}), \
             patch("hydro_platform.pipeline.sync_tasks", return_value={"tasks": [self.task]}), \
             patch("hydro_platform.pipeline.build_card_generator_adapter", side_effect=AssertionError("no model")):
            result = run_once(self.config, now=NOW)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["counts"]["recovered"], 1)
        self.assertEqual(result["generation_attempt_count"], 0)
        self.assertEqual(result["items"][0]["recovery"]["quality_status"], "DRAFT_RECOVERED")
        self.assertTrue(Path(result["items"][0]["card_path"]).exists())

    def test_compact_ai_marker_draft_is_recovered_without_rewriting_or_model(self):
        body = self.body.replace("【AI 推理】", "【AI推理】")
        self.record["model_message"] = json.dumps({**FakeAdapter().output, "card_body_markdown": body})
        self.write_draft()
        original = self.draft.read_bytes()
        result = self.recover()
        self.assertFalse(result["model_invoked"])
        self.assertTrue(Path(result["card_path"]).read_text(encoding="utf-8").endswith(body))
        self.assertEqual(self.draft.read_bytes(), original)

    def test_reading_failures_active_tasks_and_no_draft_do_not_recover(self):
        for changes in ({"reason_code": "PDF_DIRECT_READING_INCOMPLETE"}, {"state": "PROCESSING"},
                        {"state": "READY_FOR_EXTRACTION"}):
            with self.subTest(changes=changes):
                self.assertIsNone(recover_failed_draft(self.config, {**self.task, **changes}))
        self.draft.unlink()
        self.assertIsNone(self.recover())

    def test_recovery_does_not_recheck_template_text_or_claim_references(self):
        body = self.body.replace("## AI 推理", "## 别的内容").replace("【原文陈述·方法】", "【AI 推理】") + "\n引用 C99\n"
        self.record["model_message"] = json.dumps({**FakeAdapter().output, "card_body_markdown": body})
        self.write_draft()
        with patch("hydro_platform.card_generators.single_agent.validate_attribution", side_effect=AssertionError("must not inspect body")), \
             patch("hydro_platform.card_generation._validate_template_structure", side_effect=AssertionError("must not inspect layout")):
            result = self.recover()
        self.assertFalse(result["model_invoked"])
        self.assertTrue(Path(result["card_path"]).read_text(encoding="utf-8").endswith(body))

    def test_newest_incomplete_draft_does_not_fall_back_to_an_older_output(self):
        newer = self.draft.with_name("newer.json")
        newer.write_text(json.dumps({**self.record, "exit_code": 1}), encoding="utf-8")
        stamp = self.draft.stat().st_mtime + 10
        os.utime(newer, (stamp, stamp))
        with self.assertRaises(CardGenerationError):
            self.recover()
        self.assertIsNone(validate_saved_package(self.f.package))

    def test_source_mismatch_and_human_edits_are_not_overwritten(self):
        self.record["source_pdf_sha256"] = "d" * 64
        self.write_draft()
        self.assertIsNone(self.recover())
        self.record["source_pdf_sha256"] = PDF_HASH
        self.write_draft()
        (self.f.package / "card.md").write_text("user edit", encoding="utf-8")
        with self.assertRaises(EvidencePackageError):
            self.recover()
        self.assertEqual((self.f.package / "card.md").read_text(encoding="utf-8"), "user edit")

    def test_changed_task_is_rejected_at_final_write(self):
        from hydro_platform.draft_recovery import _write_generated_package
        def race(*args, **kwargs):
            registry = load_task_registry(self.f.task_path, self.f.zotero.group_id)
            registry["tasks"][PARENT_KEY]["state"] = "PROCESSING"
            save_task_registry(self.f.task_path, registry)
            return _write_generated_package(*args, **kwargs)
        with patch("hydro_platform.draft_recovery._write_generated_package", side_effect=race):
            with self.assertRaises(CardGenerationError):
                self.recover()
        self.assertIsNone(validate_saved_package(self.f.package))

    def test_interrupted_recovery_uses_pending_publication_not_another_model(self):
        original = load_evidence_manifest(self.f.package / "manifest.json")
        real_replace = os.replace
        def crash(source, destination):
            if Path(destination) == self.f.package / "manifest.json":
                raise KeyboardInterrupt()
            return real_replace(source, destination)
        with patch("hydro_platform.card_generation.os.replace", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.recover()
        self.assertTrue(publication_path(self.f.lock_path, original).exists())
        with RuntimeLock(self.f.lock_path, stale_seconds=300):
            self.assertTrue(recover_publication(self.f.package, self.f.lock_path, original))
        self.assertEqual(validate_saved_package(self.f.package)["generation"]["quality_status"], "DRAFT_RECOVERED")

    def test_recovery_manifest_cannot_claim_full_validation_or_fabricate_old_metadata(self):
        self.recover()
        path = self.f.package / "manifest.json"
        manifest = load_evidence_manifest(path)
        for changes in ({"full_read_verified": True}, {"original_generation_time": "now"},
                        {"original_template_version": "1.0.0"}, {"source_record_identity_matched": False},
                        {"source_page_count_reported_by_model": True}, {"draft_sha256": "bad"}):
            with self.subTest(changes=changes):
                modified = deepcopy(manifest)
                modified["generation"]["recovery"].update(changes)
                path.write_text(json.dumps(modified), encoding="utf-8")
                with self.assertRaises(EvidencePackageError):
                    load_evidence_manifest(path)


if __name__ == "__main__":
    unittest.main()
