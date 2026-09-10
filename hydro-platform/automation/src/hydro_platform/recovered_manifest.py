"""Validation for honest legacy-draft provenance, separate from a normal execution audit."""
import re


def recovered_generation_valid(generation):
    if not isinstance(generation, dict) or set(generation) != {
        "workflow_protocol_version", "quality_status", "recovered_at", "card_sha256",
        "quality_audit_file", "quality_audit_sha256", "recovery"}:
        return False
    recovery = generation.get("recovery")
    if not isinstance(recovery, dict):
        return False
    if (generation.get("workflow_protocol_version") != "rough-card-draft-recovery-v1"
        or generation.get("quality_status") != "DRAFT_RECOVERED"
        or generation.get("quality_audit_file") != "quality-audit.json"
        or recovery.get("protocol_version") != generation["workflow_protocol_version"]
        or recovery.get("status") != generation["quality_status"]
        or recovery.get("recovered_at") != generation["recovered_at"]
        or recovery.get("source_record_identity_matched") is not True):
        return False
    for field in ("model_invoked_during_recovery", "full_read_verified", "visual_understanding_verified", "scientific_correctness_verified"):
        if recovery.get(field) is not False:
            return False
    for field in ("original_generation_time", "original_template_version"):
        if field not in recovery or recovery[field] is not None:
            return False
    for record, fields in ((generation, ("card_sha256", "quality_audit_sha256")),
                           (recovery, ("original_prompt_sha256", "draft_sha256", "checked_against_template_sha256"))):
        if any(not isinstance(record.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", record[k]) for k in fields):
            return False
    for field in ("recovered_at", "checked_against_template_id", "checked_against_template_version",
                  "checked_against_catalog_version", "source_read_evidence_reported_by_model", "note"):
        if not isinstance(recovery.get(field), str) or not recovery[field].strip():
            return False
    pages = recovery.get("source_page_count_reported_by_model")
    return (type(pages) is int and pages > 0
            and recovery.get("source_read_status_reported_by_model") == "FULL_PDF_REVIEWED"
            and recovery.get("visual_content_status_reported_by_model") in {"REVIEWED", "NOT_PRESENT"})
