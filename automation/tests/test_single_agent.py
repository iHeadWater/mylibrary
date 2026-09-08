from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.card_generators.single_agent import SingleAgentCardGeneratorAdapter, validate_attribution
from hydro_platform.card_generation import CardGenerationError, _validate_workflow_result
from hydro_platform.config import ConfigError, SINGLE_AGENT_PROTOCOL_VERSION, load_config
from hydro_platform.evidence_packages import EvidencePackageError, load_evidence_manifest
from test_card_generation import GenerationFixture, FakeAdapter, PARENT_KEY
from test_codex_local_pdf import LocalProviderFixture
from test_config import write_config


BODY = """# 原创研究证据卡：Test paper

## 声明—原文证据对应表

| 声明ID | 本卡可核声明 | 性质 | 忠实释义 | 位置 | 限定 | 证据状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | 结果甲 | 【原文陈述】结果 | 对象甲的结果甲 | PDF 第 2 页图 1 | 仅对象甲 | 原文有据 |
| C02 | 结果乙 | 【原文转述】 | 作者引用乙研究 | PDF 第 3 页 | 未读被引论文 | 转述未独立读取 |

## AI 推理

- 【AI 推理】：由 C01 可讨论对同类对象的可能适用性，但假设过程一致；不能推出其他气候区均适用。

## 信息边界

- 【信息边界】：原文未报告其他气候区的外部验证，现有证据不能支持普适性。
"""


def configure_template(f):
    path = f.templates / "01_original-research.md"
    front = path.read_text(encoding="utf-8").split("---", 2)[:2]
    content = "---" + front[1] + "---\n\n" + BODY.replace("Test paper", "{{TITLE}}")
    path.write_text(content, encoding="utf-8")
    catalog = json.loads(f.catalog.read_text(encoding="utf-8"))
    catalog["templates"][0]["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    f.catalog.write_text(json.dumps(catalog), encoding="utf-8")


class SingleAgentTests(unittest.TestCase):
    def test_one_call_persists_truthful_formal_card_and_skips_existing(self):
        digest = hashlib.sha256(b"%PDF-1.7\nfixture").hexdigest()
        with tempfile.TemporaryDirectory() as directory, patch("test_card_generation.PDF_HASH", digest):
            root = Path(directory)
            f = GenerationFixture(root)
            configure_template(f)
            provider = LocalProviderFixture(root / "provider")
            provider.outputs = [{**FakeAdapter().output, "card_body_markdown": BODY}]
            events = []
            adapter = SingleAgentCardGeneratorAdapter(provider.adapter, progress=events.append)
            result = f.generate(adapter)
            self.assertTrue(result["ok"], result)
            self.assertEqual(len(provider.calls), 1)
            manifest_path = f.package / "manifest.json"
            manifest = load_evidence_manifest(manifest_path)
            self.assertEqual(manifest["generation"]["workflow_role_count"], 1)
            self.assertEqual(manifest["generation"]["quality_status"], "STRUCTURE_VALIDATED")
            self.assertFalse(manifest["generation"]["source_access_verified"])
            audit = json.loads((f.package / "quality-audit.json").read_text(encoding="utf-8"))
            self.assertFalse(audit["quality_report"]["gates"]["independent_review"])
            self.assertEqual(list(audit["roles"]), ["card_writer"])
            self.assertEqual([e["total"] for e in events if e["event"] == "role_started"], [1])
            self.assertEqual(f.generate(adapter)["action"], "SKIPPED_EXISTING_CARD")
            self.assertEqual(len(provider.calls), 1)
            for change in ({"workflow_role_count": 6}, {"quality_status": "VALIDATED"},
                           {"source_access_verified": True}, {"workflow_role_count": True}):
                corrupted = deepcopy(manifest)
                corrupted["generation"].update(change)
                manifest_path.write_text(json.dumps(corrupted), encoding="utf-8")
                with self.assertRaises(EvidencePackageError):
                    load_evidence_manifest(manifest_path)

    def test_single_trial_preserves_old_formal_card_and_task(self):
        digest = hashlib.sha256(b"%PDF-1.7\nfixture").hexdigest()
        with tempfile.TemporaryDirectory() as directory, patch("test_card_generation.PDF_HASH", digest):
            root = Path(directory)
            f = GenerationFixture(root)
            f.generate(FakeAdapter())  # historical six-role artifact stays intact
            configure_template(f)
            provider = LocalProviderFixture(root / "provider")
            provider.outputs = [{**FakeAdapter().output, "card_body_markdown": BODY}]
            protected = [f.pdf, f.package / "card.md", f.package / "manifest.json", f.task_path]
            before = [p.read_bytes() for p in protected]
            result = f.trial(SingleAgentCardGeneratorAdapter(provider.adapter))
            self.assertEqual(result["action"], "VALIDATED_TRIAL_SAVED")
            self.assertEqual(result["quality_status"], "STRUCTURE_VALIDATED")
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(before, [p.read_bytes() for p in protected])
            self.assertTrue((Path(result["trial_path"]) / "card.md").exists())

    def test_attribution_contract_rejects_mixing_handoff_and_dangling_ids(self):
        self.assertEqual(validate_attribution(BODY)["claim_count"], 2)
        self.assertEqual(validate_attribution(BODY + "\n本卡不需要人工核验。\n")["claim_count"], 2)
        self.assertEqual(validate_attribution(BODY + "\n【原文陈述】作者的方法需要人工核验样本。\n")["claim_count"], 2)
        for body in (BODY.replace("【原文陈述】结果", "已证实"),
                     BODY.replace("C02 |", "C01 |"),
                     BODY + "\n依据 C99\n",
                     BODY.replace("【AI 推理】", "结论"),
                     BODY.replace("【信息边界】", "备注"),
                     BODY + "\n需要人工进一步核验\n",
                     BODY + "\n请导师复核\n",
                     BODY + "\n- 本人复查：已完成\n"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate_attribution(body)
        self.assertEqual(validate_attribution(BODY.replace("结果甲 | 【原文", "结果甲含 \\| 符号 | 【原文"))["claim_count"], 2)

    def test_bad_attribution_keeps_draft_and_no_formal_write(self):
        digest = hashlib.sha256(b"%PDF-1.7\nfixture").hexdigest()
        with tempfile.TemporaryDirectory() as directory, patch("test_card_generation.PDF_HASH", digest):
            root = Path(directory)
            f = GenerationFixture(root)
            configure_template(f)
            provider = LocalProviderFixture(root / "provider")
            provider.outputs = [{**FakeAdapter().output, "card_body_markdown": BODY + "\n请导师复核\n"}]
            before = (f.package / "card.md").read_bytes()
            with self.assertRaises(CardGenerationError) as caught:
                f.generate(SingleAgentCardGeneratorAdapter(provider.adapter))
            self.assertEqual(caught.exception.code, "SINGLE_CARD_CONTRACT_FAILED")
            self.assertTrue(Path(caught.exception.diagnostic["draft_path"]).exists())
            self.assertEqual((f.package / "card.md").read_bytes(), before)
            self.assertEqual(json.loads(f.task_path.read_text(encoding="utf-8"))["tasks"][PARENT_KEY]["state"], "QUALITY_FAILED")
            self.assertEqual(len(provider.calls), 1)

    def test_independent_review_claim_or_malformed_audit_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = LocalProviderFixture(Path(directory))
            provider.outputs = [{**FakeAdapter().output, "card_body_markdown": BODY}]
            result = SingleAgentCardGeneratorAdapter(provider.adapter).generate("prompt",
                working_directory=provider.pdf.parent, source_pdf_path=provider.pdf,
                zotero_parent_key=PARENT_KEY, output_schema_path=provider.schema)
            _validate_workflow_result(result)
            for mutation in ("independent", "roles", "output"):
                bad = deepcopy(result)
                if mutation == "independent":
                    bad["workflow"]["gates"]["independent_review"] = True
                elif mutation == "roles":
                    bad["quality_audit"]["roles"] = []
                else:
                    bad["output"]["card_body_markdown"] += "changed"
                with self.assertRaises(CardGenerationError):
                    _validate_workflow_result(bad)

    def test_cleanup_failure_does_not_erase_output_or_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = LocalProviderFixture(Path(directory))
            with patch("hydro_platform.card_generators.codex_local_pdf.shutil.rmtree",
                       side_effect=PermissionError(13, "denied")):
                result = provider.run()
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["warnings"][0]["code"], "SCRATCH_CLEANUP_FAILED")
            draft = json.loads(Path(result["draft_path"]).read_text(encoding="utf-8"))
            self.assertEqual(draft["status"], "UNVALIDATED_MODEL_OUTPUT")
            self.assertEqual(json.loads(draft["model_message"]), result["output"])
            self.assertEqual(len(provider.calls), 1)
            self.assertTrue(provider.workspaces[0].exists())

    def test_cleanup_failure_does_not_mask_original_process_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = LocalProviderFixture(Path(directory))
            provider.runner.side_effect = PermissionError(13, "secret path must not be logged")
            with patch("hydro_platform.card_generators.codex_local_pdf.shutil.rmtree",
                       side_effect=PermissionError(13, "cleanup denied")):
                result = provider.run()
            self.assertFalse(result["ok"])
            self.assertEqual(result["diagnostic"]["stage"], "model_process")
            self.assertEqual(result["diagnostic"]["exception_type"], "PermissionError")
            self.assertEqual(result["diagnostic"]["errno"], 13)
            self.assertNotIn("secret path", json.dumps(result))
            self.assertEqual(result["warnings"][0]["code"], "SCRATCH_CLEANUP_FAILED")

    def test_single_config_has_no_six_role_assets_and_rejects_ambiguous_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            data = json.loads(config.read_text())
            data["card_generator"].update(workflow_mode="single_agent")
            data["card_generator"]["pdf_reader"]["adapter"] = "local_path"
            with self.subTest(mode="ambiguous"):
                config.write_text(json.dumps(data))
                with self.assertRaises(ConfigError):
                    load_config(config)
            del data["card_generator"]["multi_agent_workflow"]
            config.write_text(json.dumps(data))
            self.assertIsNone(load_config(config).card_generator.multi_agent_workflow)
            data["card_generator"]["workflow_mode"] = "unknown"
            config.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                load_config(config)

    def test_all_eight_adapted_templates_have_attribution_and_no_human_review_fields(self):
        root = Path(__file__).resolve().parents[2] / "templates" / "evidence-cards"
        templates = list(root.glob("0*.md"))
        self.assertEqual(len(templates), 8)
        for path in templates:
            body = path.read_text(encoding="utf-8")
            self.assertIn('template_version: "1.1.0"', body)
            self.assertIn("## AI 推理", body)
            self.assertIn("## 信息边界", body)
            self.assertNotIn("- 本人", body)
            self.assertNotIn("- 独立检查", body)
            self.assertNotIn("原文短摘录", body)


if __name__ == "__main__":
    unittest.main()
