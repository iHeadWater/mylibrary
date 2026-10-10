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
