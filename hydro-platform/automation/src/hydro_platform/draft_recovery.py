"""Publish completed format-blocked drafts without another model call or invented receipts."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from hydro_platform.card_generation import CardGenerationError, _timestamp, _write_generated_package
from hydro_platform.draft_export import inspect_evidence_draft
from hydro_platform.evidence_packages import find_evidence_package, load_evidence_manifest
from hydro_platform.publication import identity, text_hash, validate_saved_package
from hydro_platform.tasks import RuntimeLock, complete_task_from_package, load_task_registry


RECOVERABLE_FORMAT_REASONS = {"SINGLE_CARD_CONTRACT_FAILED", "CARD_GENERATION_STRUCTURE_INVALID",
                             "CARD_GENERATION_PLACEHOLDER_REMAINED", "CARD_GENERATION_FALSE_HUMAN_REVIEW",
                             "CARD_GENERATION_CLASSIFICATION_INVALID"}
RECOVERY_PROTOCOL = "rough-card-draft-recovery-v1"


def recover_failed_draft(config, task, *, now=None):
    """Only format failures: no reading failures, active tasks, or already-written cards."""
    if (task.get("state") not in {"QUALITY_FAILED", "RETRY_PENDING"}
        or task.get("reason_code") not in RECOVERABLE_FORMAT_REASONS):
        return None
    key = task["parent_key"]
    package = find_evidence_package(config.paths.evidence_packs_dir, key)
    if package is None:
        return None
    manifest = load_evidence_manifest(package / "manifest.json")
    if manifest["card_status"] != "PLACEHOLDER":
        return None
    # Never fall back to an older draft after the newest matching attempt fails validation.
    candidates = []
    root = (config.paths.runtime_dir / "generation-drafts").resolve()
    for path in root.glob("*.json"):
        if path.resolve().parent != root:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError):
            continue
        if (isinstance(record, dict) and record.get("parent_key") == key
            and record.get("source_pdf_sha256") == manifest["pdf_sha256"]
            and record.get("run_label") == "card_writer"):
            candidates.append(path)
    if not candidates:
        return None
    path = max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name))
    checked = inspect_evidence_draft(config, path)
    draft, output = checked["draft"], checked["output"]
    if not isinstance(draft.get("prompt_sha256"), str) or len(draft["prompt_sha256"]) != 64:
        raise CardGenerationError("CARD_DRAFT_INVALID", "草稿缺少原始提示词指纹")
    at = _timestamp(now)
    template, catalog = checked["template"], checked["catalog"]
    # This is a formal storage decision, not an upgrade of the historical reading evidence.
    provenance = {
        "protocol_version": RECOVERY_PROTOCOL, "status": "DRAFT_RECOVERED",
        "recovered_at": at, "model_invoked_during_recovery": False,
        "original_generation_time": None, "original_template_version": None,
        "original_model": draft.get("model"), "original_reasoning_effort": draft.get("reasoning_effort"),
        "original_prompt_sha256": draft["prompt_sha256"],
        "draft_sha256": hashlib.sha256(checked["raw_draft"]).hexdigest(),
        "source_record_identity_matched": True,
        "full_read_verified": False, "visual_understanding_verified": False,
        "scientific_correctness_verified": False,
        "content_validation_performed": False,
        "checked_against_template_id": output["template_id"],
        "checked_against_template_version": template["local_version"],
        "checked_against_template_sha256": template["content_sha256"],
        "checked_against_catalog_version": catalog["catalog_version"],
        "source_read_status_reported_by_model": output["source_read_status"],
        "source_page_count_reported_by_model": output["source_page_count"],
        "visual_content_status_reported_by_model": output["visual_content_status"],
        "source_read_evidence_reported_by_model": output["source_read_evidence"],
        "note": "从历史拦截的已完成草稿正式恢复，正文保持不变；只核对来源、模板索引、非空输出、重复与安全写入，不检查正文格式或内容质量。"
                "旧执行回执、原模板版本及原生成时间未在草稿中完整留存；不补造、不宣称独立阅读或科学正确性验证。",
    }
    audit = {"schema_version": 1, "source_pdf_sha256": manifest["pdf_sha256"],
             "quality_report": provenance, "structure_validation": checked["validated"]["structure_validation"],
             "attribution": checked["attribution"], "original_model_output": output,
             "preserved_provider_reading_record": draft.get("provider_reading_record")}
    audit_text = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    front = {"schema_version": 1, "card_state": "ROUGH", "evidence_id": manifest["evidence_id"],
             "title": manifest["title"], "zotero_group_id": manifest["group_id"],
             "zotero_parent_key": key, "zotero_attachment_key": manifest["attachment_key"],
             "source_pdf_sha256": manifest["pdf_sha256"], "recovered_at": at,
             "generation_provenance": "DRAFT_RECOVERED", "independent_reading_verified": False,
             "checked_against_template_id": output["template_id"],
             "checked_against_template_version": template["local_version"]}
    card = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()) + "\n---\n\n" + output["card_body_markdown"]
    final_manifest = deepcopy(manifest)
    final_manifest.update(card_status="ROUGH", updated_at=at, generation={
        "workflow_protocol_version": RECOVERY_PROTOCOL, "quality_status": "DRAFT_RECOVERED",
        "recovered_at": at, "card_sha256": text_hash(card), "quality_audit_file": "quality-audit.json",
        "quality_audit_sha256": text_hash(audit_text), "recovery": provenance})
    # Check the latest task again; no new model claim or attempt counter increment.
    with RuntimeLock(config.paths.lock_file, stale_seconds=config.tasks.lock_stale_seconds):
        current = load_task_registry(config.paths.tasks_file, config.zotero.group_id)["tasks"].get(key)
        if (not current or any(current.get(k) != task.get(k) for k in
            ("state", "reason_code", "task_id", "input", "updated_at"))
            or manifest["source_task_id"] != current["task_id"]
            or manifest["group_id"] != config.zotero.group_id
            or manifest["attachment_key"] != current["input"]["attachment_key"]
            or manifest["pdf_sha256"] != current["input"]["pdf_sha256"]
            or identity(manifest) != identity(checked["manifest"])):
            raise CardGenerationError("EVIDENCE_INPUT_MISMATCH", "恢复前任务或来源已变化，保留原文件")
        validate_saved_package(package)
    _write_generated_package({"package_path": package, "manifest": manifest}, card, audit_text,
                             final_manifest, config.tasks, config.paths.lock_file,
                             recovery_task_check=(config.paths.tasks_file, task))
    complete_task_from_package(config.zotero.group_id, key, final_manifest, config.tasks,
                               config.paths.tasks_file, config.paths.lock_file, now=now)
    return {"action": "DRAFT_RECOVERED", "model_invoked": False, "card_path": str(package / "card.md"),
            "manifest_path": str(package / "manifest.json"), "draft_path": str(path),
            "quality_status": "DRAFT_RECOVERED", "full_read_verified": False,
            "scientific_correctness_verified": False}
