"""Offline salvage of a completed model message; never publish it as a verified card."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from hydro_platform.card_generation import (
    CardGenerationError, _load_template_bundle, _normalize_parent_key,
    _timestamp, _validate_model_output,
)
from hydro_platform.card_generators.single_agent import validate_attribution
from hydro_platform.config import AppConfig
from hydro_platform.evidence_packages import find_evidence_package, load_evidence_manifest


def export_evidence_draft(config: AppConfig, draft_path: Path) -> dict:
    """Keep the model body unchanged; check current structure without calling a model/PDF tool."""
    draft_path = draft_path.resolve()
    draft_root = (config.paths.runtime_dir / "generation-drafts").resolve()
    if draft_path.parent != draft_root or draft_path.suffix.lower() != ".json":
        raise CardGenerationError("CARD_DRAFT_PATH_INVALID", "只导出当前运行目录 generation-drafts 中的 JSON 草稿")
    try:
        raw_draft = draft_path.read_bytes()
        draft = json.loads(raw_draft.decode("utf-8"))
        if (not isinstance(draft, dict) or draft.get("schema_version") != 1
            or draft.get("status") != "UNVALIDATED_MODEL_OUTPUT"
            or draft.get("run_label") != "card_writer" or draft.get("exit_code") != 0
            or not isinstance(draft.get("parent_key"), str)
            or not isinstance(draft.get("model_message"), str)):
            raise ValueError("not a completed single-agent draft")
        output = json.loads(draft["model_message"])
    except (ValueError, UnicodeError) as exc:
        raise CardGenerationError("CARD_DRAFT_INVALID", "草稿不是完整的单 Agent 制卡 JSON 输出") from exc
    key = _normalize_parent_key(draft["parent_key"])
    package = find_evidence_package(config.paths.evidence_packs_dir, key)
    if package is None:
        raise CardGenerationError("CARD_GENERATION_PACKAGE_MISSING", "草稿对应的证据包不存在")
    manifest = load_evidence_manifest(package / "manifest.json")
    if (manifest["group_id"] != config.zotero.group_id or manifest["parent_key"] != key
        or manifest["pdf_sha256"] != draft.get("source_pdf_sha256")):
        raise CardGenerationError("EVIDENCE_INPUT_MISMATCH", "草稿与当前证据包的群组、父条目或 PDF 指纹不一致")
    catalog, templates = _load_template_bundle(
        config.paths.evidence_card_templates_dir, config.paths.evidence_card_template_catalog_file)
    validated = _validate_model_output(output, templates, title=manifest["title"], draft_path=str(draft_path))
    try:
        attribution = validate_attribution(validated["card_body_markdown"])
    except ValueError as exc:
        raise CardGenerationError("SINGLE_CARD_CONTRACT_FAILED", str(exc)) from exc

    template = templates[validated["template_id"]]
    draft_sha256 = hashlib.sha256(raw_draft).hexdigest()
    # Keep exactly the generated Markdown, not a new ROUGH/validated production front matter.
    card_content = output["card_body_markdown"]
    report = {
        "schema_version": 1, "ok": True, "operation": "evidence_draft_export",
        "action": "RECOVERED_DRAFT_EXPORTED", "status": "RECOVERED_DRAFT_PREVIEW",
        "exported_at": _timestamp(), "model_invoked": False, "production_eligible": False,
        "production_files_modified": False, "task_state_modified": False,
        "full_read_verified": False, "visual_understanding_verified": False,
        "scientific_correctness_verified": False,
        "group_id": manifest["group_id"], "parent_key": key, "evidence_id": manifest["evidence_id"],
        "source_pdf_sha256": draft["source_pdf_sha256"],
        "draft_path": str(draft_path), "draft_sha256": draft_sha256,
        "original_model": draft.get("model"), "original_reasoning_effort": draft.get("reasoning_effort"),
        "original_prompt_sha256": draft.get("prompt_sha256"),
        "template_id": validated["template_id"],
        "checked_against_template_version": template["local_version"],
        "checked_against_template_sha256": template["content_sha256"],
        "checked_against_catalog_version": catalog["catalog_version"],
        "structure_validation": validated["structure_validation"], "attribution": attribution,
        "card_sha256": hashlib.sha256(card_content.encode("utf-8")).hexdigest(),
        "note": "从已有模型输出导出原样 Markdown；只校验当前模板结构、归因格式及记录中的来源身份。"
                "原草稿未保存完整执行审计，不补造阅读回执、生成时间或原模板版本，不自动发布到正式证据包。",
    }
    parent_dir = (config.paths.card_trials_dir / "recovered" / key).resolve()
    # A misconfigured preview root must never write into the shared production packages.
    if parent_dir.is_relative_to(config.paths.evidence_packs_dir.resolve()):
        raise CardGenerationError("CARD_DRAFT_PATH_INVALID", "草稿预览目录不能位于正式证据包目录中")
    parent_dir.mkdir(parents=True, exist_ok=True)
    export_dir = parent_dir / f"{draft_sha256[:12]}-{uuid4().hex}"
    report.update(trial_path=str(export_dir), card_path=str(export_dir / "card.md"),
                  export_report_path=str(export_dir / "export.json"))
    temporary_dir = Path(tempfile.mkdtemp(prefix=".draft-export-", dir=parent_dir))
    try:
        (temporary_dir / "card.md").write_text(card_content, encoding="utf-8", newline="")
        (temporary_dir / "export.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.rename(temporary_dir, export_dir)
    except OSError as exc:
        # This directory was created by this call under the resolved preview parent.
        if temporary_dir.resolve().parent == parent_dir:
            shutil.rmtree(temporary_dir, ignore_errors=True)
        raise CardGenerationError("CARD_DRAFT_EXPORT_FAILED", "草稿 Markdown 导出失败；原草稿未修改") from exc
    return report
