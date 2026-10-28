"""Shared on-disk fixtures for the subject-card tests.

The legacy evidence-package generator and its provider adapters are gone, so
these helpers build the same artifacts directly: one completed rough evidence
package (the theme pool still reads those), one placeholder package (PDF
delivery) and one historical ``schema_version: 1`` draft (the read-only
validator still has to read drafts written before the Markdown pipeline).

Nothing here calls a model. A fixture that produced a card through a live
executor would make the test itself the thing under test.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter

from hydrolitagent.cards import card_validation as gate
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.application.card_draft import SINGLE_SOURCE_TEMPLATES
from hydrolitagent.cards.application.prompts import (
    build_template_prompt,
    load_template_bundle,
    read_prompt,
)
from hydrolitagent.cards.config import PdfGateConfig, TaskConfig, ZoteroConfig
from hydrolitagent.cards.evidence_packages import PLACEHOLDER_CARD
from hydrolitagent.cards.pdf_delivery import PdfDelivery
from hydrolitagent.cards.publication import text_hash
from hydrolitagent.cards.tasks import build_task_id

GROUP_ID = 42
PARENT_KEY = "ABCD1234"
ATTACHMENT_KEY = "WXYZ5678"
PDF_HASH = "a" * 64
SOURCE_COMMIT = "b" * 40
SOURCE_BLOB = "c" * 40
PAGE_COUNT = 12
GENERATED_AT = "2026-09-07T01:02:03Z"

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

AUDIT = json.dumps(
    {"schema_version": 1, "quality_report": {"status": "VALIDATED"}},
    ensure_ascii=False,
    indent=2,
    sort_keys=True,
) + "\n"


def write_pdf(path: Path, pages: int = PAGE_COUNT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=300, height=300)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def paper_input_record(
    pdf: Path,
    *,
    library: dict[str, Any] | None = None,
    item_key: str = PARENT_KEY,
    title: str = "Fixed test paper",
    requested_item_key: str = "ATTACH01",
) -> dict[str, Any]:
    """One READY ``paper_input`` record pointing at a real local PDF."""

    pdf = Path(pdf)
    return {
        "schema_version": 1,
        "ok": True,
        "operation": "paper_input",
        "status": "READY",
        "reason_code": "PDF_READY",
        "library": library or {"type": "user", "id": 0},
        "requested_item_key": requested_item_key,
        "item": {"item_key": item_key, "title": title},
        "pdf_attachment_count": 1,
        "pdf": {
            "attachment_key": "ATTACH01",
            "parent_key": item_key,
            "file_size_bytes": pdf.stat().st_size,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "local_path": str(pdf.resolve()),
            "fulltext_indexed": False,
        },
    }


def machine_fields() -> dict[str, Any]:
    """A minimal, shape-valid ``machine_fields`` block."""

    statement = {
        "statement": "Synthetic fixture result; not a scientific claim.",
        "statement_role": "original_statement",
        "information_status": "reported",
        "source_locations": [
            {"pdf_page": 2, "section": "Results", "figure": None, "table": None}
        ],
    }
    fields: dict[str, Any] = {"schema_version": 1}
    for key in gate.FIELDS:
        fields[key] = [deepcopy(statement)]
    fields["findings"][0]["finding_id"] = "F001"
    return fields


def v1_draft(
    record: dict[str, Any],
    *,
    assets: "gate.ValidationAssets | None" = None,
    body: str = "# Fixed paper\n\nF001: fixture result.\n",
    fields: dict[str, Any] | None = None,
    draft_id: str = "a" * 16,
) -> dict[str, Any]:
    """The ``schema_version: 1`` envelope the removed provider path saved."""

    assets = assets or gate.ValidationAssets.from_root()
    catalog, all_templates = load_template_bundle(assets.templates_dir, assets.catalog_file)
    templates = {k: v for k, v in all_templates.items() if k in SINGLE_SOURCE_TEMPLATES}
    template = templates["original-research"]
    base = read_prompt(assets.generation_prompt)
    supplement = read_prompt(assets.draft_prompt)
    reading = read_prompt(assets.reading_prompt)
    pdf = record["pdf"]
    parent = record["item"]["item_key"]
    context = {
        "library": record["library"],
        "item": record["item"],
        "zotero_parent_key": parent,
        "zotero_attachment_key": pdf["attachment_key"],
        "source_pdf_sha256": pdf["sha256"],
        "source_pdf_absolute_path": gate._source_path(pdf["local_path"]),
        "reading_scope": "FULL_PDF",
        "card_state": "DRAFT_PENDING_VALIDATION",
        "enabled_template_ids": sorted(templates),
    }
    prompt = build_template_prompt(base, context, templates) + "\n" + supplement["content"]
    return {
        "schema_version": 1,
        "draft_id": draft_id,
        "status": "DRAFT_PENDING_VALIDATION",
        "created_at": GENERATED_AT,
        "content_validation_performed": False,
        "production_eligible": False,
        "scientific_correctness_verified": False,
        "source": {
            "library": deepcopy(record["library"]),
            "parent_key": parent,
            "requested_item_key": record["requested_item_key"],
            "attachment_key": pdf["attachment_key"],
            "pdf_sha256": pdf["sha256"],
            "pdf_size_bytes": pdf["file_size_bytes"],
            "pdf_page_count": PAGE_COUNT,
            "item": deepcopy(record["item"]),
        },
        "card_body_markdown": body,
        "machine_fields": fields if fields is not None else machine_fields(),
        "provenance": {
            "prompt_version": base["version"],
            "prompt_sha256": base["sha256"],
            "draft_prompt_version": supplement["version"],
            "draft_prompt_sha256": supplement["sha256"],
            "reading_prompt_version": reading["version"],
            "reading_prompt_sha256": reading["sha256"],
            "output_schema_sha256": hashlib.sha256(
                assets.output_schema.read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest(),
            "combined_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "catalog_version": catalog["catalog_version"],
            "template_id": "original-research",
            "template_version": template["local_version"],
            "template_sha256": template["content_sha256"],
            "generation_protocol_version": "codex-local-pdf-v1",
        },
        "reading_record": {
            "method": "local_pdf_path",
            "source_sha256": pdf["sha256"],
            "parent_key": parent,
            "page_count": PAGE_COUNT,
            "source_identity_verified": True,
            "source_unchanged": True,
            "model_reading_report_accepted": True,
            "model_claim_full_text": True,
            "model_claim_visuals": True,
            "verified": False,
            "full_read_verified": False,
            "visual_understanding_verified": False,
        },
        "process_audit": {"schema_version": 1, "status": "PROCESS_VALIDATED"},
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "warnings": [],
    }


class GenerationFixture:
    """Runtime layout, task registry, template catalog and one evidence package."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.runtime = self.root / ".runtime"
        self.runtime.mkdir()
        self.task_path = self.runtime / "tasks.json"
        self.lock_path = self.runtime / "worker.lock"
        self.evidence_root = self.root / "evidence-packs"
        self.package = self.evidence_root / f"EV-{PARENT_KEY}-test-paper"
        self.package.mkdir(parents=True)
        self.templates = self.root / "templates" / "evidence-cards"
        self.templates.mkdir(parents=True)
        self.prompt = self.root / "automation" / "prompts" / "evidence-card-generation-v3.md"
        self.prompt.parent.mkdir(parents=True)
        self.schema = self.root / "automation" / "schemas" / "card-generation-output.schema.json"
        self.schema.parent.mkdir(parents=True)
        self.pdf = self.root / "zotero" / "storage" / ATTACHMENT_KEY / "paper.pdf"
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(b"%PDF-1.7\nfixture")

        self.task_id = build_task_id(GROUP_ID, PARENT_KEY, ATTACHMENT_KEY, PDF_HASH)
        task = {
            "record_id": f"{GROUP_ID}:{PARENT_KEY}",
            "group_id": GROUP_ID,
            "parent_key": PARENT_KEY,
            "title": "Test paper",
            "task_id": self.task_id,
            "input": {"attachment_key": ATTACHMENT_KEY, "pdf_sha256": PDF_HASH},
            "state": "READY_FOR_EXTRACTION",
            "reason_code": "PDF_READY",
            "message": "ready",
            "attempt_count": 0,
            "lease": None,
            "created_at": "2026-09-07T01:00:00Z",
            "updated_at": "2026-09-07T01:00:00Z",
            "history": [],
        }
        self.task = task
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
        (self.package / "manifest.json").write_text(
            json.dumps(self.placeholder_manifest()), encoding="utf-8"
        )
        (self.package / "card.md").write_text(PLACEHOLDER_CARD, encoding="utf-8")

        template_path = self.templates / "01_original-research.md"
        template_path.write_text(TEMPLATE, encoding="utf-8")
        self.catalog = self.templates / "_catalog.json"
        self.catalog.write_text(
            json.dumps(
                {
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
            ),
            encoding="utf-8",
        )
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

    def placeholder_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "evidence_id": f"EV-{PARENT_KEY}",
            "group_id": GROUP_ID,
            "parent_key": PARENT_KEY,
            "attachment_key": ATTACHMENT_KEY,
            "pdf_sha256": PDF_HASH,
            "source_task_id": self.task_id,
            "title": "Test paper",
            "card_status": "PLACEHOLDER",
            "created_at": "2026-09-07T01:00:00Z",
            "updated_at": "2026-09-07T01:00:00Z",
        }

    def completed_manifest(self) -> dict[str, Any]:
        return {
            **self.placeholder_manifest(),
            "card_status": "ROUGH",
            "updated_at": GENERATED_AT,
            "generation": {
                "generator_adapter": "in_session",
                "generator_protocol_version": "evidence-card-generation-v3",
                "cli_version": "fixture",
                "model": "fixture-model",
                "reasoning_effort": "none",
                "prompt_version": "evidence-card-generation-v3",
                "prompt_sha256": hashlib.sha256(
                    self.prompt.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                "output_schema_version": 2,
                "output_schema_sha256": hashlib.sha256(
                    self.schema.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                "template_catalog_version": "1.0.0",
                "template_id": "original-research",
                "template_version": "1.0.0",
                "template_source_commit": SOURCE_COMMIT,
                "template_content_sha256": hashlib.sha256(
                    TEMPLATE.encode("utf-8")
                ).hexdigest(),
                "classification_confidence": 0.88,
                "classification_reason": "包含原创研究问题、方法与结果",
                "reading_scope": "FULL_PDF",
                "source_access_verified": True,
                "source_access_method": "bound_local_pdf_mcp",
                "source_access_server": "hydro_pdf_reader",
                "source_access_receipt_schema_version": 1,
                "source_pages_served": PAGE_COUNT,
                "source_visual_pages_served": PAGE_COUNT,
                "source_read_status": "FULL_PDF_REVIEWED",
                "source_page_count": PAGE_COUNT,
                "visual_content_status": "REVIEWED",
                "source_read_evidence": "共 12 页；已检查末页及图 1、表 1。",
                "generated_at": GENERATED_AT,
                "card_sha256": text_hash(VALID_BODY),
                "quality_status": "VALIDATED",
                "workflow_protocol_version": "rough-card-multi-agent-v1",
                "workflow_role_count": 6,
                "quality_audit_file": "quality-audit.json",
                "quality_audit_sha256": text_hash(AUDIT),
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }

    def complete(self) -> dict[str, Any]:
        """Write the completed rough package the legacy generator used to save."""

        manifest = self.completed_manifest()
        (self.package / "card.md").write_text(VALID_BODY, encoding="utf-8")
        (self.package / "quality-audit.json").write_text(AUDIT, encoding="utf-8")
        (self.package / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return manifest

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
            verified_at=GENERATED_AT,
        )


@pytest.fixture
def legacy_draft_case(tmp_path):
    """A historical v1 draft on disk plus the READY input record it came from."""

    from dataclasses import replace

    from hydrolitagent.cards.config import load_config
    from test_config import write_config

    pdf = write_pdf(tmp_path / "paper.pdf")
    app = load_config(write_config(tmp_path / "app", {"zotero": {"group_id": None}}))
    app = replace(
        app,
        paths=replace(
            app.paths,
            evidence_card_templates_dir=ASSETS_DIR / "templates/evidence-cards",
            evidence_card_template_catalog_file=ASSETS_DIR / "templates/evidence-cards/_catalog.json",
            evidence_card_generation_prompt_file=ASSETS_DIR / "prompts/evidence-card-generation-v8.md",
        ),
    )
    record = paper_input_record(pdf)
    draft = v1_draft(record)
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    path = draft_dir / "draft.json"
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    input_path = tmp_path / "paper-input.json"
    input_path.write_text(json.dumps(record), encoding="utf-8")
    return app, draft, record, path, input_path
