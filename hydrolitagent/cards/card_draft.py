"""Single-paper draft generation (#30); transport checks are not the #31 gate."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydrolitagent._config import PathConfigError, resolve_literature_root
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.card_generation import (
    CardGenerationError, _load_template_bundle, _read_prompt,
    _validate_model_output, _validate_workflow_result, build_template_prompt,
)
from hydrolitagent.cards.card_generators import build_card_generator_adapter
from hydrolitagent.cards.config import SINGLE_AGENT_PROTOCOL_VERSION
from hydrolitagent.cards.evidence_templates import EvidenceTemplateError
from hydrolitagent.cards.source_access import source_access_acceptable

KEY = re.compile(r"[A-Z0-9]{8}")
SHA256 = re.compile(r"[a-f0-9]{64}")
SINGLE_SOURCE_TEMPLATES = frozenset({
    "original-research", "review-synthesis", "survey-monitoring-statistics",
    "engineering-report", "book-chapter", "standard-guideline-policy",
    "dataset-data-product", "software-model-code",
})
ASSETS = ASSETS_DIR
PROMPT = ASSETS / "prompts/subject-card-draft-v1.md"
SCHEMA = ASSETS / "schemas/subject-card-draft-output.schema.json"


def _fail(code: str, message: str) -> None:
    raise CardGenerationError(code, message)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _input(record: Any) -> tuple[dict, Path]:
    """Consume the READY contract of #29, without requiring its pending code."""
    if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
        or record["schema_version"] != 1 or record.get("operation") != "paper_input"
        or record.get("ok") is not True or record.get("status") != "READY"
        or type(record.get("pdf_attachment_count")) is not int
        or record["pdf_attachment_count"] != 1):
        _fail("CARD_DRAFT_INPUT_INVALID", "需要 #29 的单篇 READY 输入记录")
    library, item, pdf = (record.get(k) for k in ("library", "item", "pdf"))
    if not all(isinstance(v, dict) for v in (library, item, pdf)):
        _fail("CARD_DRAFT_INPUT_INVALID", "输入缺少文库、父条目或 PDF")
    if (library.get("type") not in {"user", "group"}
        or type(library.get("id")) is not int or library["id"] < 0
        or (library["type"] == "group" and library["id"] == 0)):
        _fail("CARD_DRAFT_INPUT_INVALID", "文库身份无效")
    parent, attachment = item.get("item_key"), pdf.get("attachment_key")
    requested = record.get("requested_item_key")
    if (not all(isinstance(k, str) and KEY.fullmatch(k) for k in (parent, attachment, requested))
        or parent == attachment or requested not in (parent, attachment) or pdf.get("parent_key") != parent
        or not isinstance(item.get("title"), str) or not item["title"].strip()
        or not isinstance(pdf.get("sha256"), str) or not SHA256.fullmatch(pdf["sha256"])
        or type(pdf.get("file_size_bytes")) is not int or pdf["file_size_bytes"] < 1
        or not isinstance(pdf.get("local_path"), str) or not pdf["local_path"].strip()):
        _fail("CARD_DRAFT_INPUT_INVALID", "论文或 PDF 身份字段无效")
    path = Path(pdf["local_path"])
    if not path.is_absolute():
        _fail("CARD_DRAFT_INPUT_INVALID", "PDF 路径必须是 #29 返回的绝对路径")
    try:
        path = path.resolve(strict=True)
        with path.open("rb") as stream:
            header = stream.read(5)
        if not path.is_file() or path.suffix.lower() != ".pdf" or header != b"%PDF-":
            _fail("CARD_DRAFT_PDF_UNREADABLE", "输入不是可读取的 PDF")
        if path.stat().st_size != pdf["file_size_bytes"] or _digest(path) != pdf["sha256"]:
            _fail("PDF_INPUT_CHANGED", "PDF 与输入记录的大小或哈希不同，请重新取得输入")
    except OSError as exc:
        raise CardGenerationError("CARD_DRAFT_PDF_UNREADABLE", "无法读取输入 PDF") from exc
    # fulltext_indexed=False is explicitly valid: the provider reads the local PDF.
    return deepcopy(record), path


def _check_wire(value: Any, schema: dict, path: str = "machine_fields") -> None:
    """Only decode the fixed wire shape. Do not judge content, coverage or citations."""
    types = schema.get("type")
    if isinstance(types, list):
        if value is None and "null" in types:
            return
        types = next(t for t in types if t != "null")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) is int or (type(value) is float and math.isfinite(value)),
    }.get(types, False)
    if not valid or ("enum" in schema and value not in schema["enum"]):
        _fail("CARD_DRAFT_OUTPUT_INVALID", f"机器字段无法解析：{path}")
    if types == "object":
        properties = schema["properties"]
        if set(value) != set(properties):
            _fail("CARD_DRAFT_OUTPUT_INVALID", f"机器字段缺少或多出键：{path}")
        for key, child in properties.items():
            _check_wire(value[key], child, f"{path}.{key}")
    elif types == "array":
        for index, child in enumerate(value):
            _check_wire(child, schema["items"], f"{path}[{index}]")


def _save(root: Path, draft: dict) -> dict:
    """Write previews append-only; draft.json is the last, atomic completion marker."""
    source = draft["source"]
    library = source["library"]
    identity = f"{library['type']}-{library['id']}-{source['parent_key']}"
    directory = root / "zotero" / identity / "drafts" / draft["draft_id"]
    resolved_root, resolved_dir = root.resolve(), directory.resolve()
    if not resolved_dir.is_relative_to(resolved_root):
        _fail("CARD_DRAFT_PATH_INVALID", "草稿子目录不得通过链接逃逸出精读产物根")
    directory.mkdir(parents=True, exist_ok=False)
    card = directory / "card.md"
    # A visible status belongs to the preview, never to the model-controlled body.
    card.write_text(
        "> 待校验主体卡草稿；未通过内容门禁，不是正式发布的卡片。\n\n"
        + draft["card_body_markdown"], encoding="utf-8", newline="\n",
    )
    pending = directory / "draft.json.tmp"
    pending.write_text(json.dumps(draft, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                       encoding="utf-8", newline="\n")
    pending.replace(directory / "draft.json")
    return {"literature_root": str(resolved_root), "draft_path": str(directory / "draft.json"),
            "card_path": str(card)}


def generate_subject_card_draft(app_config, paper_input: Any, *, adapter=None, progress=None, output_root=None) -> dict:
    """Return a DRAFT_PENDING_VALIDATION or a structured failure; never retry."""
    result = {"schema_version": 1, "operation": "subject_card_draft", "ok": False,
              "status": "FAILED", "model_invoked": False,
              "content_validation_performed": False, "production_eligible": False}
    stage = "input"
    generated = None
    try:
        record, pdf_path = _input(paper_input)
        cfg = app_config.card_generator
        if cfg.workflow_mode != "single_agent" or cfg.pdf_reader.adapter != "local_path":
            _fail("CARD_DRAFT_SINGLE_AGENT_REQUIRED", "主体卡草稿只支持 single_agent + local_path")
        stage = "assets"
        root = resolve_literature_root(root=output_root)  # Same resolver and precedence as PR #27.
        base_prompt = _read_prompt(app_config.paths.evidence_card_generation_prompt_file)
        supplement = _read_prompt(PROMPT)
        catalog, all_templates = _load_template_bundle(
            app_config.paths.evidence_card_templates_dir,
            app_config.paths.evidence_card_template_catalog_file,
        )
        templates = {key: value for key, value in all_templates.items()
                     if key in SINGLE_SOURCE_TEMPLATES}
        if not templates:
            _fail("CARD_DRAFT_TEMPLATE_INVALID", "没有启用适用于单篇来源的模板")
        schema_text = SCHEMA.read_text(encoding="utf-8")
        schema = json.loads(schema_text)
        pdf = record["pdf"]
        parent = record["item"]["item_key"]
        context = {
            "library": record["library"], "item": record["item"],
            "zotero_parent_key": parent, "zotero_attachment_key": pdf["attachment_key"],
            "source_pdf_sha256": pdf["sha256"], "source_pdf_absolute_path": str(pdf_path),
            "reading_scope": "FULL_PDF", "card_state": "DRAFT_PENDING_VALIDATION",
            "enabled_template_ids": sorted(templates),
        }
        prompt = build_template_prompt(base_prompt, context, templates) + "\n" + supplement["content"]
        provider = adapter if adapter is not None else build_card_generator_adapter(cfg, progress=progress)
        stage = "generation"
        generated = provider.generate(
            prompt, working_directory=pdf_path.parent, source_pdf_path=pdf_path,
            zotero_parent_key=parent, output_schema_path=SCHEMA,
        )
        result["model_invoked"] = generated.get("model_invoked") is True
        if not generated.get("ok"):
            error = generated.get("error") or {}
            raise CardGenerationError(error.get("code", "CARD_DRAFT_GENERATION_FAILED"),
                                      error.get("message", "主体卡生成失败"),
                                      diagnostic=generated.get("diagnostic"))
        stage = "transport"
        if _digest(pdf_path) != pdf["sha256"]:
            _fail("PDF_INPUT_CHANGED", "生成期间 PDF 已改变，拒绝接受草稿")
        access = generated.get("source_access")
        if not source_access_acceptable(access, expected_sha256=pdf["sha256"],
                                        expected_parent_key=parent):
            _fail("CARD_DRAFT_SOURCE_MISMATCH", "生成记录与输入 PDF 身份不符")
        workflow, audit, _ = _validate_workflow_result(generated)
        if workflow["protocol_version"] != SINGLE_AGENT_PROTOCOL_VERSION:
            _fail("CARD_DRAFT_SINGLE_AGENT_REQUIRED", "草稿必须使用当前单 Agent 流程")
        output = _validate_model_output(generated.get("output"), templates,
                                       title=record["item"]["title"], draft_path=generated.get("draft_path"))
        if output["source_page_count"] != access["page_count"]:
            _fail("CODEX_PDF_PAGE_COUNT_MISMATCH", "模型页数与 PDF 读取记录不一致")
        fields = generated["output"].get("machine_fields")
        _check_wire(fields, schema["properties"]["machine_fields"])
        template = templates[output["template_id"]]
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        draft = {
            "schema_version": 1, "draft_id": uuid.uuid4().hex[:16],
            "status": "DRAFT_PENDING_VALIDATION", "created_at": now,
            "content_validation_performed": False, "production_eligible": False,
            "scientific_correctness_verified": False,
            "source": {"library": record["library"], "parent_key": parent,
                       "requested_item_key": record["requested_item_key"],
                       "attachment_key": pdf["attachment_key"], "pdf_sha256": pdf["sha256"],
                       "pdf_size_bytes": pdf["file_size_bytes"], "pdf_page_count": access["page_count"],
                       "item": record["item"]},
            "card_body_markdown": output["card_body_markdown"], "machine_fields": fields,
            "provenance": {
                "prompt_version": base_prompt["version"], "prompt_sha256": base_prompt["sha256"],
                "draft_prompt_version": supplement["version"], "draft_prompt_sha256": supplement["sha256"],
                "combined_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "output_schema_sha256": hashlib.sha256(schema_text.encode("utf-8")).hexdigest(),
                "template_id": output["template_id"], "template_version": template["local_version"],
                "template_sha256": template["content_sha256"], "catalog_version": catalog["catalog_version"],
                "model": generated.get("configured_model"), "reasoning_effort": generated.get("configured_reasoning_effort"),
                "generation_protocol_version": generated.get("generation_protocol_version"),
                "reading_prompt_version": generated.get("reading_prompt_version"),
                "reading_prompt_sha256": generated.get("reading_prompt_sha256"),
            },
            "reading_record": access, "process_audit": audit,
            "usage": generated.get("usage"), "warnings": generated.get("warnings", []),
        }
        stage = "save"
        saved = _save(root, draft)
        return {**result, **saved, "ok": True, "status": draft["status"],
                "draft_id": draft["draft_id"], "source": draft["source"]}
    except (CardGenerationError, EvidenceTemplateError) as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
        if getattr(exc, "diagnostic", None):
            result["error"]["diagnostic"] = exc.diagnostic
    except PathConfigError as exc:
        result["error"] = {"code": "CARD_DRAFT_PATH_INVALID", "message": str(exc)}
    except (OSError, ValueError, TypeError) as exc:
        result["error"] = {"code": "CARD_DRAFT_IO_ERROR" if isinstance(exc, OSError) else "CARD_DRAFT_INPUT_INVALID",
                           "message": f"主体卡阶段 {stage} 失败：{type(exc).__name__}"}
    if generated and generated.get("draft_path"):
        result["error"].setdefault("diagnostic", {})["unvalidated_model_output_path"] = generated["draft_path"]
    result["failed_stage"] = stage
    return result
