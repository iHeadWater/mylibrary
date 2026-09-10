from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.card_generation import CardGenerationError, _validate_model_output, _validate_template_structure
from hydro_platform.cli import main
from hydro_platform.draft_export import export_evidence_draft
from test_card_generation import FakeAdapter, GenerationFixture, PARENT_KEY, PDF_HASH, VALID_BODY
from test_single_agent import BODY, configure_template


class CardSavingTests(unittest.TestCase):
    def test_extra_heading_and_table_saved_without_content_check(self):
        extra = "\n### 核心图表解读\n\n| 图 | 含义 |\n| --- | --- |\n| 图 1 | 结果 |\n"
        with tempfile.TemporaryDirectory() as directory:
            f = GenerationFixture(Path(directory))
            adapter = FakeAdapter()
            adapter.output["card_body_markdown"] += extra
            result = f.generate(adapter)
            self.assertTrue(result["ok"])
            report = result["structure_validation"]
            self.assertEqual(report["status"], "NOT_CHECKED")
            self.assertFalse(report["content_validation_performed"])
            self.assertTrue((f.package / "card.md").read_text(encoding="utf-8").endswith(VALID_BODY + extra))
            audit = json.loads((f.package / "quality-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["structure_validation"], report)
            manifest = json.loads((f.package / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["generation"]["quality_audit_sha256"],
                             hashlib.sha256((f.package / "quality-audit.json").read_bytes()).hexdigest())
            self.assertEqual(len(adapter.calls), 1)

    def test_trial_records_no_content_check_without_changing_production(self):
        with tempfile.TemporaryDirectory() as directory:
            f = GenerationFixture(Path(directory))
            adapter = FakeAdapter()
            adapter.output["card_body_markdown"] += "\n### 补充说明\n具体信息。\n"
            protected = [f.package / "card.md", f.package / "manifest.json", f.task_path]
            before = [p.read_bytes() for p in protected]
            result = f.trial(adapter)
            report = result["structure_validation"]
            self.assertEqual(report["status"], "NOT_CHECKED")
            trial = json.loads((Path(result["trial_path"]) / "trial.json").read_text(encoding="utf-8"))
            audit = json.loads(Path(result["quality_audit_path"]).read_text(encoding="utf-8"))
            self.assertEqual(trial["structure_validation"], report)
            self.assertEqual(audit["structure_validation"], report)
            self.assertEqual(before, [p.read_bytes() for p in protected])

    def test_layout_variations_are_not_blockers(self):
        expected = "# 标题\n## 甲\n正文\n### 小节\n内容\n## 乙\n| a |\n| --- |\n| b |\n"
        for body in (expected.replace("### 小节", "### 自选小节"),
                     "# 自选标题\n## 乙\n内容。\n## 甲\n正文。\n",
                     "## 甲\n正文。\n## 乙\n正文表达原表格内容。\n"):
            with self.subTest(body=body):
                report = _validate_template_structure(body, expected)
                self.assertEqual(report["status"], "PASS_WITH_NOTES")
                self.assertFalse(report["scientific_correctness_verified"])

    def test_missing_major_section_is_not_a_gate_but_empty_output_keeps_draft_path(self):
        output = FakeAdapter().output
        output["card_body_markdown"] = "# 标题\n非空但缺少研究结论章节。"
        result = _validate_model_output(output, {"original-research": {"body": VALID_BODY}}, title="Test paper")
        self.assertEqual(result["structure_validation"]["status"], "NOT_CHECKED")
        with self.assertRaises(CardGenerationError) as caught:
            _validate_model_output({**output, "card_body_markdown": " "}, {"original-research": {"body": VALID_BODY}},
                                   title="Test paper", draft_path="retained.json")
        self.assertEqual(caught.exception.code, "CARD_GENERATION_OUTPUT_INVALID")
        self.assertEqual(caught.exception.diagnostic["draft_path"], "retained.json")

    def test_code_fence_heading_does_not_count_as_a_section(self):
        for fence in ("```", "~~~", "````"):
            with self.subTest(fence=fence), self.assertRaises(CardGenerationError):
                _validate_template_structure(f"{fence}markdown\n## 研究结论\n{fence}\n", VALID_BODY)

    def test_ai_heading_whitespace_variants_match_template_without_changing_body(self):
        for heading in ("## AI推理", "## AI  推理", "## AI\u3000推理", "##\tAI推理"):
            with self.subTest(heading=heading):
                body = BODY.replace("## AI 推理", heading)
                report = _validate_template_structure(body, BODY)
                self.assertEqual(report["status"], "PASS")
        with self.assertRaises(CardGenerationError):
            _validate_template_structure(BODY.replace("## AI 推理", "## AI推理之外"), BODY)

    def test_non_layout_guards_still_reject_bad_outputs(self):
        for changes in ({"card_body_markdown": ""}, {"source_read_status": "UNREADABLE"},
                        {"template_id": "unknown"}, {"visual_content_status": "UNREADABLE"}):
            with self.subTest(changes=changes), self.assertRaises(CardGenerationError):
                _validate_model_output({**FakeAdapter().output, **changes},
                                       {"original-research": {"body": VALID_BODY}}, title="Test paper")

    def test_optional_classification_metadata_and_long_text_do_not_discard_output(self):
        for confidence in (None, "high", 99, True):
            with self.subTest(confidence=confidence), tempfile.TemporaryDirectory() as directory:
                f = GenerationFixture(Path(directory))
                output = {**FakeAdapter().output, "classification_confidence": confidence,
                          "classification_reason": "", "source_read_evidence": "阅读范围说明" * 501,
                          "extra_model_note": "保留在原始输出中，不影响保存"}
                result = f.generate(FakeAdapter(output))
                self.assertTrue(result["ok"])
                self.assertIsNone(result["classification_confidence"])
                self.assertEqual(result["classification_reason"], "模型未提供分类理由")
        output = FakeAdapter().output
        output.pop("classification_confidence")
        output.pop("classification_reason")
        checked = _validate_model_output(output, {"original-research": {"body": VALID_BODY}}, title="Test paper")
        self.assertIsNone(checked["classification_confidence"])
        self.assertEqual(checked["card_body_markdown"], output["card_body_markdown"])


class DraftExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = GenerationFixture(Path(self.temp.name))
        configure_template(self.f)
        self.draft = self.f.runtime / "generation-drafts" / "saved.json"
        self.draft.parent.mkdir()
        self.body = BODY + "\n### 核心图表解读\n\n【原文陈述】图 1 对应 C01。\n"
        self.record = {"schema_version": 1, "status": "UNVALIDATED_MODEL_OUTPUT",
                       "parent_key": PARENT_KEY, "source_pdf_sha256": PDF_HASH,
                       "run_label": "card_writer", "exit_code": 0, "model": "original-model",
                       "reasoning_effort": "high", "prompt_sha256": "c" * 64,
                       "model_message": json.dumps({**FakeAdapter().output, "card_body_markdown": self.body})}
        self.write_draft()
        self.config = SimpleNamespace(zotero=self.f.zotero, paths=SimpleNamespace(
            runtime_dir=self.f.runtime, evidence_packs_dir=self.f.evidence_root,
            card_trials_dir=self.f.runtime / "custom-trials",
            evidence_card_templates_dir=self.f.templates,
            evidence_card_template_catalog_file=self.f.catalog))

    def write_draft(self):
        self.draft.write_text(json.dumps(self.record), encoding="utf-8")

    def test_export_preserves_body_original_provenance_and_all_protected_files(self):
        protected = [self.draft, self.f.pdf, self.f.task_path, self.f.package / "card.md",
                     self.f.package / "manifest.json"]
        before = [p.read_bytes() for p in protected]
        result = export_evidence_draft(self.config, self.draft)
        self.assertEqual(Path(result["card_path"]).read_bytes(), self.body.encode("utf-8"))
        self.assertEqual(result["original_model"], "original-model")
        self.assertEqual(result["original_prompt_sha256"], "c" * 64)
        self.assertNotIn("generated_at", result)
        self.assertNotIn("original_template_version", result)
        self.assertEqual(result["status"], "RECOVERED_DRAFT_PREVIEW")
        self.assertEqual(result["attribution"]["status"], "NOT_CHECKED")
        for flag in ("model_invoked", "production_eligible", "production_files_modified",
                     "task_state_modified", "full_read_verified", "scientific_correctness_verified"):
            self.assertFalse(result[flag])
        self.assertEqual(before, [p.read_bytes() for p in protected])
        self.assertTrue(Path(result["card_path"]).is_relative_to(self.config.paths.card_trials_dir))

    def test_repeat_export_creates_new_preview_and_preserves_previous_edits(self):
        result = export_evidence_draft(self.config, self.draft)
        card = Path(result["card_path"])
        card.write_text("user edited preview", encoding="utf-8")
        again = export_evidence_draft(self.config, self.draft)
        self.assertNotEqual(result["card_path"], again["card_path"])
        self.assertEqual(card.read_text(encoding="utf-8"), "user edited preview")

    def test_source_mismatch_is_rejected_before_writing(self):
        self.record["source_pdf_sha256"] = "d" * 64
        self.write_draft()
        with self.assertRaises(CardGenerationError) as caught:
            export_evidence_draft(self.config, self.draft)
        self.assertEqual(caught.exception.code, "EVIDENCE_INPUT_MISMATCH")
        self.assertFalse(self.config.paths.card_trials_dir.exists())

    def test_incomplete_or_wrong_stage_output_is_rejected(self):
        for changes in ({"exit_code": 1}, {"run_label": "fact_extractor_a"},
                        {"model_message": "incomplete JSON"}, {"parent_key": None}):
            with self.subTest(changes=changes):
                original = self.record.copy()
                self.record.update(changes)
                self.write_draft()
                with self.assertRaises(CardGenerationError):
                    export_evidence_draft(self.config, self.draft)
                self.record = original
        self.assertFalse(self.config.paths.card_trials_dir.exists())

    def test_path_boundaries(self):
        with self.assertRaises(CardGenerationError):
            export_evidence_draft(self.config, self.f.root / "outside.json")
        self.config.paths.card_trials_dir = self.f.package
        with self.assertRaises(CardGenerationError):
            export_evidence_draft(self.config, self.draft)

    def test_failed_export_does_not_change_draft_or_leave_published_preview(self):
        before = self.draft.read_bytes()
        with patch("hydro_platform.draft_export.os.rename", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(CardGenerationError) as caught:
                export_evidence_draft(self.config, self.draft)
        self.assertEqual(caught.exception.code, "CARD_DRAFT_EXPORT_FAILED")
        self.assertEqual(self.draft.read_bytes(), before)
        self.assertEqual(list(self.config.paths.card_trials_dir.rglob("card.md")), [])

    def test_cli_export_never_calls_zotero_or_model(self):
        stdout = io.StringIO()
        with patch("hydro_platform.cli.load_config", return_value=self.config), \
             patch("hydro_platform.cli.preflight", side_effect=AssertionError("no Zotero")), \
             patch("hydro_platform.cli.build_card_generator_adapter", side_effect=AssertionError("no model")), \
             redirect_stdout(stdout):
            code = main(["evidence-draft-export", "--draft", str(self.draft), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["action"], "RECOVERED_DRAFT_EXPORTED")


if __name__ == "__main__":
    unittest.main()
