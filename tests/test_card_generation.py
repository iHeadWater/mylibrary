from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hydrolitagent.cards.card_generation import (
    CardGenerationError,
    generate_evidence_card,
    generate_evidence_card_trial,
)
from hydrolitagent.cards.config import PdfGateConfig, TaskConfig, ZoteroConfig
from hydrolitagent.cards.evidence_packages import PLACEHOLDER_CARD
from hydrolitagent.cards.pdf_delivery import PdfDelivery
from hydrolitagent.cards.tasks import build_task_id

GROUP_ID = 42
PARENT_KEY = "ABCD1234"
ATTACHMENT_KEY = "WXYZ5678"
PDF_HASH = "a" * 64
SOURCE_COMMIT = "b" * 40
SOURCE_BLOB = "c" * 40
NOW = datetime(2026, 9, 7, 1, 2, 3, tzinfo=timezone.utc)

TEMPLATE = f'''---
schema_version: 1
template_id: "original-research"
template_version: "1.0.0"
template_source_commit: "{SOURCE_COMMIT}"
evidence_id: "{{{{EVIDENCE_ID}}}}"
card_state: "{{{{CARD_STATE}}}}"
title: "{{{{TITLE}}}}"
zotero_group_id: "{{{{ZOTERO_GROUP_ID}}}}"
zotero_parent_key: "{{{{ZOTERO_PARENT_KEY}}}}"
zotero_attachment_key: "{{{{ZOTERO_ATTACHMENT_KEY}}}}"
source_pdf_sha256: "{{{{PDF_SHA256}}}}"
classification_confidence: "{{{{CLASSIFICATION_CONFIDENCE}}}}"
classification_reason: "{{{{CLASSIFICATION_REASON}}}}"
reading_scope: "{{{{READING_SCOPE}}}}"
generated_at: "{{{{GENERATED_AT}}}}"
updated_at: "{{{{GENERATED_AT}}}}"
---

# 原创研究证据卡：{{{{TITLE}}}}

## 研究结论

| 结论 | 位置 |
|---|---|
| 〔待填写〕 | 〔位置〕 |
'''

VALID_BODY = """# 原创研究证据卡：Test paper

## 研究结论

| 结论 | 位置 |
|---|---|
| 原文未报告 | 当前 PDF 无法确认 |
"""

class FakeAdapter:
    def __init__(self, output: dict[str, Any] | None = None):
        self.output = output or {
            "schema_version": 2,
            "source_read_status": "FULL_PDF_REVIEWED",
            "source_page_count": 12,
            "visual_content_status": "REVIEWED",
            "source_read_evidence": "共 12 页；已检查末页及图 1、表 1。",
            "template_id": "original-research",
            "classification_confidence": 0.88,
            "classification_reason": "包含原创研究问题、方法与结果",
            "card_body_markdown": VALID_BODY,
        }
        self.calls: list[dict[str, Any]] = []

    def preflight(self) -> dict[str, Any]:
        raise AssertionError("orchestrator must call generate only")

    def smoke_test(self) -> dict[str, Any]:
        raise AssertionError("orchestrator must not run smoke test")

    def generate(
        self,
        prompt: str,
        *,
        working_directory: Path,
        source_pdf_path: Path,
        zotero_parent_key: str,
        output_schema_path: Path,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "prompt": prompt,
                "working_directory": working_directory,
                "source_pdf_path": source_pdf_path,
                "zotero_parent_key": zotero_parent_key,
                "output_schema_path": output_schema_path,
            }
        )
        workflow = {
            "status": "VALIDATED",
            "protocol_version": "rough-card-multi-agent-v1",
            "completed_role_count": 6,
            "required_roles": [
                "fact_extractor_a",
                "fact_extractor_b",
                "fact_adjudicator",
                "critical_analyst",
                "card_synthesizer",
                "adversarial_reviewer",
            ],
            "gates": {
                "isolated_required_roles": True,
                "full_pdf_access_each_role": True,
                "dual_fact_extraction": True,
                "source_grounded_adjudication": True,
                "critical_analysis_grounded": True,
                "adversarial_review_passed": True,
                "fail_closed": True,
            },
        }
        return {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "operation": "evidence_card_generation",
            "adapter": "codex_cli",
            "cli_version": "codex-cli test",
            "configured_model": "gpt-test",
            "configured_reasoning_effort": "high",
            "generation_protocol_version": "evidence-card-generation-v3",
            "source_access": {
                "verified": True,
                "method": "bound_local_pdf_mcp",
                "server_name": "hydro_pdf_reader",
                "receipt_schema_version": 1,
                "page_count": 12,
                "pages_served": 12,
                "visual_pages_served": 12,
            },
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "output": self.output,
            "workflow": workflow,
            "quality_audit": {
                "schema_version": 1,
                "quality_report": workflow,
                "roles": {},
            },
        }

class FailingAdapter(FakeAdapter):
    def generate(
        self,
        prompt: str,
        *,
        working_directory: Path,
        source_pdf_path: Path,
        zotero_parent_key: str,
        output_schema_path: Path,
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt})
        return {
            "schema_version": 1,
            "ok": False,
            "error": {
                "code": "CODEX_RATE_LIMITED",
                "message": "Codex 模型调用受到速率限制",
            },
            "diagnostic": {
                "stage": "codex_exec",
                "exit_code": 1,
                "category": "CODEX_RATE_LIMITED",
            },
        }

class FailingAdapterWithCode(FailingAdapter):
    def __init__(self, code: str, message: str):
        super().__init__()
        self.code = code
        self.message = message

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, **kwargs})
        return {
            "schema_version": 1,
            "ok": False,
            "error": {"code": self.code, "message": self.message},
        }

class MissingSourceAccessAdapter(FakeAdapter):
    def generate(
        self,
        prompt: str,
        *,
        working_directory: Path,
        source_pdf_path: Path,
        zotero_parent_key: str,
        output_schema_path: Path,
    ) -> dict[str, Any]:
        result = super().generate(
            prompt,
            working_directory=working_directory,
            source_pdf_path=source_pdf_path,
            zotero_parent_key=zotero_parent_key,
            output_schema_path=output_schema_path,
        )
        result.pop("source_access")
        return result

class GenerationFixture:
    def __init__(self, root: Path):
        self.root = root
        self.runtime = root / ".runtime"
        self.runtime.mkdir()
        self.task_path = self.runtime / "tasks.json"
        self.lock_path = self.runtime / "worker.lock"
        self.evidence_root = root / "evidence-packs"
        self.package = self.evidence_root / f"EV-{PARENT_KEY}-test-paper"
        self.package.mkdir(parents=True)
        self.templates = root / "templates" / "evidence-cards"
        self.templates.mkdir(parents=True)
        self.prompt = root / "automation" / "prompts" / "evidence-card-generation-v3.md"
        self.prompt.parent.mkdir(parents=True)
        self.schema = root / "automation" / "schemas" / "card-generation-output.schema.json"
        self.schema.parent.mkdir(parents=True)
        self.pdf = root / "zotero" / "storage" / ATTACHMENT_KEY / "paper.pdf"
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(b"%PDF-1.7\nfixture")

        task_id = build_task_id(GROUP_ID, PARENT_KEY, ATTACHMENT_KEY, PDF_HASH)
        self.task_id = task_id
        task = {
            "record_id": f"{GROUP_ID}:{PARENT_KEY}",
            "group_id": GROUP_ID,
            "parent_key": PARENT_KEY,
            "title": "Test paper",
            "task_id": task_id,
            "input": {
                "attachment_key": ATTACHMENT_KEY,
                "pdf_sha256": PDF_HASH,
            },
            "state": "READY_FOR_EXTRACTION",
            "reason_code": "PDF_READY",
            "message": "ready",
            "attempt_count": 0,
            "lease": None,
            "created_at": "2026-09-07T01:00:00Z",
            "updated_at": "2026-09-07T01:00:00Z",
            "history": [],
        }
        self.task_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "group_id": GROUP_ID,
                    "created_at": "2026-09-07T01:00:00Z",
                    "updated_at": "2026-09-07T01:00:00Z",
                    "tasks": {PARENT_KEY: task},
                }
            ),
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "evidence_id": f"EV-{PARENT_KEY}",
            "group_id": GROUP_ID,
            "parent_key": PARENT_KEY,
            "attachment_key": ATTACHMENT_KEY,
            "pdf_sha256": PDF_HASH,
            "source_task_id": task_id,
            "title": "Test paper",
            "card_status": "PLACEHOLDER",
            "created_at": "2026-09-07T01:00:00Z",
            "updated_at": "2026-09-07T01:00:00Z",
        }
        (self.package / "manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        (self.package / "card.md").write_text(PLACEHOLDER_CARD, encoding="utf-8")

        template_path = self.templates / "01_original-research.md"
        template_path.write_text(TEMPLATE, encoding="utf-8")
        catalog = {
            "schema_version": 1,
            "catalog_version": "1.0.0",
            "source": {
                "repository": "https://example.invalid/templates",
                "commit": SOURCE_COMMIT,
                "license_status": "team-authorized",
                "authorization_basis": "fixture",
            },
            "required_template_ids": ["original-research"],
            "templates": [
                {
                    "template_id": "original-research",
                    "local_version": "1.0.0",
                    "enabled": True,
                    "file": template_path.name,
                    "source_path": "source.md",
                    "source_blob_sha": SOURCE_BLOB,
                    "content_sha256": hashlib.sha256(
                        TEMPLATE.encode("utf-8")
                    ).hexdigest(),
                }
            ],
        }
        self.catalog = self.templates / "_catalog.json"
        self.catalog.write_text(json.dumps(catalog), encoding="utf-8")
        self.prompt.write_text(
            '---\nprompt_version: "evidence-card-generation-v3"\n---\nRules\n',
            encoding="utf-8",
        )
        self.schema.write_text("{}", encoding="utf-8")

        self.zotero = ZoteroConfig(group_id=GROUP_ID)
        self.pdf_gate = PdfGateConfig(
            min_file_size_bytes=1,
            min_text_characters=1,
            hash_chunk_size_bytes=1024,
        )
        self.tasks = TaskConfig(
            lease_seconds=1800,
            lock_stale_seconds=300,
            max_history_entries=100,
        )

    def delivery(self, *_args: Any, **_kwargs: Any) -> PdfDelivery:
        return PdfDelivery(
            group_id=GROUP_ID,
            parent_key=PARENT_KEY,
            attachment_key=ATTACHMENT_KEY,
            task_id=self.task_id,
            pdf_sha256=PDF_HASH,
            pdf_path=self.pdf,
            file_size_bytes=self.pdf.stat().st_size,
            evidence_package_path=self.package,
            manifest_path=self.package / "manifest.json",
            verified_at="2026-09-07T01:02:03Z",
        )

    def generate(self, adapter: FakeAdapter) -> dict[str, Any]:
        return generate_evidence_card(
            self.zotero,
            self.pdf_gate,
            self.tasks,
            self.task_path,
            self.lock_path,
            self.evidence_root,
            self.templates,
            self.catalog,
            self.prompt,
            self.schema,
            PARENT_KEY,
            adapter,
            now=NOW,
            delivery_preparer=self.delivery,
        )

    def trial(self, adapter: FakeAdapter) -> dict[str, Any]:
        return generate_evidence_card_trial(
            self.zotero,
            self.pdf_gate,
            self.tasks,
            self.task_path,
            self.lock_path,
            self.evidence_root,
            self.runtime / "card-trials",
            self.templates,
            self.catalog,
            self.prompt,
            self.schema,
            PARENT_KEY,
            adapter,
            now=NOW,
            delivery_preparer=self.delivery,
        )

class CardGenerationTests(unittest.TestCase):
    def test_trial_on_existing_card_preserves_production_card_manifest_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            fixture.generate(FakeAdapter())
            card_before = (fixture.package / "card.md").read_bytes()
            manifest_before = (fixture.package / "manifest.json").read_bytes()
            task_before = fixture.task_path.read_bytes()

            result = fixture.trial(FakeAdapter())

            self.assertEqual(result["action"], "VALIDATED_TRIAL_SAVED")
            self.assertFalse(result["production_files_modified"])
            self.assertFalse(result["task_state_modified"])
            self.assertEqual((fixture.package / "card.md").read_bytes(), card_before)
            self.assertEqual(
                (fixture.package / "manifest.json").read_bytes(),
                manifest_before,
            )
            self.assertEqual(fixture.task_path.read_bytes(), task_before)
            trial_path = Path(result["trial_path"])
            self.assertTrue((trial_path / "card.md").is_file())
            self.assertTrue((trial_path / "quality-audit.json").is_file())
            self.assertTrue((trial_path / "trial.json").is_file())

    def test_generates_once_validates_and_marks_task_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            adapter = FakeAdapter()

            result = fixture.generate(adapter)

            self.assertEqual(result["action"], "GENERATED")
            self.assertEqual(result["task_state"], "COMPLETED")
            self.assertEqual(len(adapter.calls), 1)
            self.assertEqual(adapter.calls[0]["working_directory"], fixture.pdf.parent)
            self.assertEqual(adapter.calls[0]["source_pdf_path"], fixture.pdf)
            self.assertIn(
                json.dumps(str(fixture.pdf), ensure_ascii=False),
                adapter.calls[0]["prompt"],
            )
            self.assertIn("<evidence-card-template", adapter.calls[0]["prompt"])

            card = (fixture.package / "card.md").read_text(encoding="utf-8")
            self.assertIn('card_state: "ROUGH"', card)
            self.assertIn('template_id: "original-research"', card)
            self.assertIn("原文未报告", card)
            self.assertNotIn("{{", card)
            self.assertNotIn("〔", card)

            manifest = json.loads(
                (fixture.package / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["card_status"], "ROUGH")
            self.assertEqual(manifest["generation"]["prompt_version"], "evidence-card-generation-v3")
            self.assertEqual(manifest["generation"]["template_id"], "original-research")
            self.assertTrue(manifest["generation"]["source_access_verified"])
            self.assertEqual(manifest["generation"]["source_page_count"], 12)
            self.assertEqual(manifest["generation"]["visual_content_status"], "REVIEWED")
            self.assertEqual(manifest["generation"]["quality_status"], "VALIDATED")
            self.assertTrue((fixture.package / "quality-audit.json").is_file())
            registry = json.loads(fixture.task_path.read_text(encoding="utf-8"))
            self.assertEqual(registry["tasks"][PARENT_KEY]["state"], "COMPLETED")

    def test_existing_card_is_skipped_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            fixture.generate(FakeAdapter())
            second_adapter = FakeAdapter()

            result = fixture.generate(second_adapter)

            self.assertEqual(result["action"], "SKIPPED_EXISTING_CARD")
            self.assertFalse(result["model_invoked"])
            self.assertEqual(second_adapter.calls, [])

    def test_placeholder_words_in_body_are_not_a_saving_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            adapter = FakeAdapter(
                {
                    "schema_version": 2,
                    "source_read_status": "FULL_PDF_REVIEWED",
                    "source_page_count": 12,
                    "visual_content_status": "REVIEWED",
                    "source_read_evidence": "共 12 页；已检查图 1。",
                    "template_id": "original-research",
                    "classification_confidence": 0.5,
                    "classification_reason": "类型正确",
                    "card_body_markdown": VALID_BODY.replace(
                        "原文未报告",
                        "〔待填写〕",
                    ),
                }
            )

            result = fixture.generate(adapter)
            self.assertEqual(result["structure_validation"]["status"], "NOT_CHECKED")
            self.assertTrue((fixture.package / "card.md").read_text(encoding="utf-8").endswith(adapter.output["card_body_markdown"]))
            self.assertTrue((fixture.package / "quality-audit.json").exists())
            manifest = json.loads(
                (fixture.package / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["card_status"], "ROUGH")
            registry = json.loads(fixture.task_path.read_text(encoding="utf-8"))
            self.assertEqual(registry["tasks"][PARENT_KEY]["state"], "COMPLETED")

    def test_model_failure_keeps_placeholder_and_records_retry_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))

            with self.assertRaises(CardGenerationError) as caught:
                fixture.generate(FailingAdapter())

            self.assertEqual(caught.exception.code, "CODEX_RATE_LIMITED")
            self.assertEqual(
                caught.exception.diagnostic,
                {
                    "stage": "codex_exec",
                    "exit_code": 1,
                    "category": "CODEX_RATE_LIMITED",
                },
            )
            self.assertEqual(
                (fixture.package / "card.md").read_text(encoding="utf-8"),
                PLACEHOLDER_CARD,
            )
            registry = json.loads(fixture.task_path.read_text(encoding="utf-8"))
            task = registry["tasks"][PARENT_KEY]
            self.assertEqual(task["state"], "RETRY_PENDING")
            self.assertEqual(task["reason_code"], "CODEX_RATE_LIMITED")

    def test_quality_failure_keeps_placeholder_and_stops_automatic_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))

            with self.assertRaises(CardGenerationError) as caught:
                fixture.generate(
                    FailingAdapterWithCode(
                        "CARD_QUALITY_FAILED",
                        "对抗复核未通过",
                    )
                )

            self.assertEqual(caught.exception.code, "CARD_QUALITY_FAILED")
            self.assertEqual(
                (fixture.package / "card.md").read_text(encoding="utf-8"),
                PLACEHOLDER_CARD,
            )
            registry = json.loads(fixture.task_path.read_text(encoding="utf-8"))
            task = registry["tasks"][PARENT_KEY]
            self.assertEqual(task["state"], "QUALITY_FAILED")
            self.assertEqual(task["reason_code"], "CARD_QUALITY_FAILED")

    def test_missing_source_access_evidence_keeps_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))

            with self.assertRaises(CardGenerationError) as caught:
                fixture.generate(MissingSourceAccessAdapter())

            self.assertEqual(caught.exception.code, "CODEX_PDF_NOT_ACCESSED")
            self.assertEqual(
                (fixture.package / "card.md").read_text(encoding="utf-8"),
                PLACEHOLDER_CARD,
            )

    def test_unverified_visual_reading_keeps_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            adapter = FakeAdapter(
                {
                    "schema_version": 2,
                    "source_read_status": "FULL_PDF_REVIEWED",
                    "source_page_count": 12,
                    "visual_content_status": "UNREADABLE",
                    "source_read_evidence": "共 12 页，但图表无法读取。",
                    "template_id": "original-research",
                    "classification_confidence": 0.8,
                    "classification_reason": "原创研究",
                    "card_body_markdown": VALID_BODY,
                }
            )

            with self.assertRaises(CardGenerationError) as caught:
                fixture.generate(adapter)

            self.assertEqual(caught.exception.code, "CODEX_PDF_VISUALS_UNVERIFIED")
            self.assertEqual(
                (fixture.package / "card.md").read_text(encoding="utf-8"),
                PLACEHOLDER_CARD,
            )

    def test_illegal_template_id_is_not_replaced_with_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            adapter = FakeAdapter(
                {
                    "schema_version": 2,
                    "source_read_status": "FULL_PDF_REVIEWED",
                    "source_page_count": 12,
                    "visual_content_status": "REVIEWED",
                    "source_read_evidence": "共 12 页；已检查图 1。",
                    "template_id": "unknown-template",
                    "classification_confidence": 0.2,
                    "classification_reason": "无法判断",
                    "card_body_markdown": VALID_BODY,
                }
            )

            with self.assertRaises(CardGenerationError) as caught:
                fixture.generate(adapter)

            self.assertEqual(caught.exception.code, "CARD_GENERATION_TEMPLATE_INVALID")
            self.assertEqual(
                (fixture.package / "card.md").read_text(encoding="utf-8"),
                PLACEHOLDER_CARD,
            )

    def test_missing_template_section_does_not_block_saving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            adapter = FakeAdapter(
                {
                    "schema_version": 2,
                    "source_read_status": "FULL_PDF_REVIEWED",
                    "source_page_count": 12,
                    "visual_content_status": "REVIEWED",
                    "source_read_evidence": "共 12 页；已检查图 1。",
                    "template_id": "original-research",
                    "classification_confidence": 0.8,
                    "classification_reason": "原创研究",
                    "card_body_markdown": "# 原创研究证据卡：Test paper\n",
                }
            )

            result = fixture.generate(adapter)
            self.assertEqual(result["structure_validation"]["status"], "NOT_CHECKED")
            self.assertTrue((fixture.package / "card.md").read_text(encoding="utf-8").endswith(adapter.output["card_body_markdown"]))

    def test_body_wording_is_not_scanned_or_endorsed_by_saving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            output = dict(FakeAdapter().output)
            output["card_body_markdown"] = (
                VALID_BODY + "\n- 本人复查：已完成全文复查\n"
            )

            result = fixture.generate(FakeAdapter(output))
            self.assertFalse(result["structure_validation"]["scientific_correctness_verified"])
            self.assertTrue((fixture.package / "card.md").read_text(encoding="utf-8").endswith(output["card_body_markdown"]))

    def test_manifest_replace_failure_rolls_card_back_to_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = GenerationFixture(Path(directory))
            real_replace = os.replace
            failed = False

            def replace_with_manifest_failure(source: Any, destination: Any) -> None:
                nonlocal failed
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    not failed
                    and destination_path == fixture.package / "manifest.json"
                    and source_path.name.startswith(".manifest.json.")
                ):
                    failed = True
                    raise OSError("simulated manifest replace failure")
                real_replace(source, destination)

            with patch(
                "hydrolitagent.cards.card_generation.os.replace",
                side_effect=replace_with_manifest_failure,
            ):
                with self.assertRaises(CardGenerationError) as caught:
                    fixture.generate(FakeAdapter())

            self.assertEqual(caught.exception.code, "EVIDENCE_PACKAGE_WRITE_FAILED")
            self.assertEqual(
                (fixture.package / "card.md").read_text(encoding="utf-8"),
                PLACEHOLDER_CARD,
            )
            self.assertFalse((fixture.package / "quality-audit.json").exists())
            manifest = json.loads(
                (fixture.package / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["card_status"], "PLACEHOLDER")

if __name__ == "__main__":
    unittest.main()
