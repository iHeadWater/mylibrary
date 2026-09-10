#!/usr/bin/env python3
"""Validate a hydrology literature-to-theme workflow run ledger."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMAS = {"hydrology-literature-to-theme-v1.0", "hydrology-literature-to-theme-v1.1"}
ROUTES = {"small_sample", "large_corpus", "hybrid"}
STATUSES = {"draft", "running", "human_review", "mentor_review", "complete", "blocked"}
FEEDBACK_TYPES = {"source_recheck", "corpus_supplement", "discovery_model_correction"}
THEME_PURPOSE_V1 = "allocate_full_text_review_across_candidate_themes_only"
DOCUMENT_PURPOSE_V1 = "rank_documents_within_a_candidate_theme_for_full_text_review_only"
THEME_PURPOSE_V11 = "allocate_full_text_review_across_established_themes_only"
DOCUMENT_PURPOSE_V11 = "rank_documents_within_an_established_theme_for_full_text_review_only"
SCREENING_DECISIONS = {
    "establish", "rename_then_establish", "merge", "split_and_rescreen",
    "watch", "supplement_before_decision", "reject",
}


def parse_scalar(raw: str) -> Any:
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return raw.strip().strip("\"'")


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    result: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = parse_scalar(value)
    return result


def workflow_block(text: str) -> dict[str, Any]:
    match = re.search(r"(?ms)^~~~workflow-run-json\s*\n(.*?)^~~~\s*$", text)
    if not match:
        raise ValueError("WF00 expected exactly one workflow-run-json block")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("WF00 workflow-run-json must contain one object")
    return value


def blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, str) and "{{" in value)


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def require(errors: list[str], obj: dict[str, Any], keys: tuple[str, ...], prefix: str) -> None:
    for key in keys:
        if key not in obj:
            errors.append(f"{prefix} missing {key}")


def validate(meta: dict[str, Any], run: dict[str, Any], final: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    require(errors, meta, (
        "workflow_schema", "workflow_ref", "workflow_version", "title", "route", "status",
        "as_of_date", "generated_by", "generator_version", "human_review_status",
        "mentor_decision_status",
    ), "WF00 frontmatter")
    schema = meta.get("workflow_schema")
    if schema not in SCHEMAS:
        errors.append(f"WF00 workflow_schema must be one of {sorted(SCHEMAS)}")
    route = str(meta.get("route") or "")
    if route not in ROUTES:
        errors.append("WF01 route must be small_sample, large_corpus or hybrid")
    if meta.get("status") not in STATUSES:
        errors.append("WF00 invalid workflow status")

    task = run.get("research_task") if isinstance(run.get("research_task"), dict) else {}
    selection = run.get("route_selection") if isinstance(run.get("route_selection"), dict) else {}
    preliminary_key = "preliminary_theme_review" if schema == "hydrology-literature-to-theme-v1.1" else "candidate_direction_review"
    preliminary = run.get(preliminary_key) if isinstance(run.get(preliminary_key), dict) else {}
    screening = run.get("theme_screening_gate") if isinstance(run.get("theme_screening_gate"), dict) else {}
    theme_priority = run.get("theme_level_priority") if isinstance(run.get("theme_level_priority"), dict) else {}
    document_priority = run.get("document_level_priority") if isinstance(run.get("document_level_priority"), dict) else {}
    admission = run.get("claim_admission") if isinstance(run.get("claim_admission"), dict) else {}
    recalculation = run.get("recalculation") if isinstance(run.get("recalculation"), dict) else {}
    decision = run.get("human_and_mentor_decision") if isinstance(run.get("human_and_mentor_decision"), dict) else {}

    for key in (
        "research_task", "route_selection", preliminary_key, "theme_level_priority",
        "document_level_priority", "full_text_queue", "evidence_card_handoff", "claim_admission",
        "feedback_loops", "recalculation", "human_and_mentor_decision", "limitations", "audit_log",
    ):
        if key not in run:
            errors.append(f"WF00 workflow-run-json missing {key}")
    if schema == "hydrology-literature-to-theme-v1.1":
        for key in ("theme_screening_gate", "established_themes"):
            if key not in run:
                errors.append(f"WF00 v1.1 workflow-run-json missing {key}")

    if blank(task.get("question")):
        errors.append("WF02 research question is required")
    if not isinstance(task.get("boundary_frozen"), bool):
        errors.append("WF02 boundary_frozen must be boolean")
    if selection.get("route") != route:
        errors.append("WF01 route differs between frontmatter and workflow block")
    if final and blank(selection.get("rationale")):
        errors.append("WF01 final run requires route rationale")

    small = selection.get("small_sample") if isinstance(selection.get("small_sample"), dict) else {}
    large = selection.get("large_corpus") if isinstance(selection.get("large_corpus"), dict) else {}
    if route in {"small_sample", "hybrid"}:
        if final and blank(small.get("zotero_collection_or_list")):
            errors.append("WF03 small-sample final run requires Zotero collection or list")
        if small.get("topic_growth_status") not in {
            "not_applicable_unless_adequate_time_slices", "not_applicable", "unknown", "measured"
        }:
            errors.append("WF03 invalid small-sample topic_growth_status")
    if route in {"large_corpus", "hybrid"}:
        for key in ("corpus_snapshot_ref", "retrieval_log_ref"):
            if final and blank(large.get(key)):
                errors.append(f"WF04 large-corpus final run requires {key}")
        topic_model = large.get("topic_model") if isinstance(large.get("topic_model"), dict) else {}
        trend = large.get("topic_trend") if isinstance(large.get("topic_trend"), dict) else {}
        if topic_model.get("method") not in {"DTM", "LDA", "BERTopic", "other", "not_run"}:
            errors.append("WF04 unsupported topic model method label")
        if trend.get("popularity_definition") != "annual_relative_topic_share_sums_to_one":
            errors.append("WF05 topic trend must use documented annual relative topic share")
        if trend.get("slope_estimator") != "Theil-Sen" or trend.get("significance_test") != "Mann-Kendall":
            errors.append("WF05 topic trend must record Theil-Sen and Mann-Kendall")
        if final and trend.get("status") == "completed":
            for key in ("raw_counts_reported", "annual_denominator_reported", "multiple_testing_recorded"):
                if trend.get(key) is not True:
                    errors.append(f"WF05 completed topic trend requires {key}=true")

    expected_theme_purpose = THEME_PURPOSE_V11 if schema == "hydrology-literature-to-theme-v1.1" else THEME_PURPOSE_V1
    expected_document_purpose = DOCUMENT_PURPOSE_V11 if schema == "hydrology-literature-to-theme-v1.1" else DOCUMENT_PURPOSE_V1
    if theme_priority.get("purpose") != expected_theme_purpose:
        errors.append("WF06 theme priority has the wrong analysis unit or purpose")
    if document_priority.get("purpose") != expected_document_purpose:
        errors.append("WF06 document priority has the wrong analysis unit or purpose")
    if theme_priority.get("composite_weight_status") not in {"not_frozen", "pilot_registered", "mentor_frozen"}:
        errors.append("WF06 invalid theme composite weight status")
    if document_priority.get("composite_weight_status") not in {"not_frozen", "pilot_registered", "mentor_frozen"}:
        errors.append("WF06 invalid document composite weight status")

    for item in list_value(theme_priority.get("items")):
        if not isinstance(item, dict):
            errors.append("WF06 theme priority item must be an object")
            continue
        if item.get("paper_id") or item.get("source_card_id"):
            errors.append("WF06 topic growth cannot be assigned directly to a paper in theme priority")
        if schema == "hydrology-literature-to-theme-v1.1" and blank(item.get("established_theme_ref")):
            errors.append("WF06 v1.1 theme priority item requires established_theme_ref")
        trend = item.get("topic_growth_trend")
        if trend not in (None, "unknown", "not_applicable") and not isinstance(trend, dict):
            errors.append("WF05 topic_growth_trend must be an object, unknown or not_applicable")

    for item in list_value(document_priority.get("items")):
        if not isinstance(item, dict):
            errors.append("WF06 document priority item must be an object")
            continue
        theme_ref_key = "established_theme_ref" if schema == "hydrology-literature-to-theme-v1.1" else "candidate_direction_ref"
        if blank(item.get(theme_ref_key)) or blank(item.get("source_ref")):
            errors.append(f"WF06 document priority item requires {theme_ref_key} and source_ref")
        if "topic_growth_score" in item:
            errors.append("WF06 document priority must not copy a topic-growth score onto a paper")
        for signal_name in ("citation_signal", "journal_signal"):
            signal = item.get(signal_name)
            if signal is None:
                continue
            if not isinstance(signal, dict) or signal.get("status") not in {"verified", "unknown", "not_applicable"}:
                errors.append(f"WF06 {signal_name} requires verified, unknown or not_applicable status")
                continue
            if signal.get("status") == "verified":
                required = ("metric_year", "category", "normalized_value_or_band", "source", "checked_at")
                for key in required:
                    if blank(signal.get(key)):
                        errors.append(f"WF06 verified {signal_name} missing {key}")

    if not isinstance(preliminary.get("human_boundary_reviewed"), bool):
        errors.append("WF07 human_boundary_reviewed must be boolean")
    if schema == "hydrology-literature-to-theme-v1.1":
        if preliminary.get("status") not in {"not_started", "generated", "human_review", "completed", "blocked"}:
            errors.append("WF07 invalid preliminary-theme review status")
        if screening.get("status") not in {"not_started", "in_review", "completed", "blocked"}:
            errors.append("WF07 invalid theme-screening gate status")
        if not isinstance(screening.get("all_preliminary_themes_decided"), bool):
            errors.append("WF07 all_preliminary_themes_decided must be boolean")
        decision_refs: set[str] = set()
        decided_preliminary_refs: set[str] = set()
        decision_links = list_value(screening.get("decision_links"))
        for item in decision_links:
            if not isinstance(item, dict):
                errors.append("WF07 screening decision link must be an object")
                continue
            linked_preliminary_refs = {str(x) for x in list_value(item.get("preliminary_theme_refs")) if str(x)}
            linked_source_files = {str(x) for x in list_value(item.get("source_file_refs")) if str(x)}
            if blank(item.get("decision_ref")) or not linked_preliminary_refs or not linked_source_files:
                errors.append("WF07 screening decision link requires decision_ref, preliminary_theme_refs and source_file_refs")
            else:
                decision_refs.add(str(item.get("decision_ref")))
                decided_preliminary_refs.update(linked_preliminary_refs)
            if item.get("decision") not in SCREENING_DECISIONS:
                errors.append("WF07 screening decision is not allowed")
            if item.get("decision") in {"establish", "rename_then_establish", "merge"} and not list_value(item.get("resulting_established_theme_refs")):
                errors.append("WF07 establishment decision requires resulting_established_theme_refs")
            if item.get("decision") == "split_and_rescreen" and not list_value(item.get("split_into_preliminary_theme_refs")):
                errors.append("WF07 split decision requires split_into_preliminary_theme_refs")
        if len(decision_refs) != len(decision_links):
            errors.append("WF07 screening decision_ref values must be unique and nonblank")
        preliminary_refs = {str(x) for x in list_value(preliminary.get("preliminary_theme_refs")) if str(x)}
        if screening.get("all_preliminary_themes_decided") is True and not preliminary_refs.issubset(decided_preliminary_refs):
            errors.append("WF07 all_preliminary_themes_decided=true but some preliminary themes lack decisions")
        established_refs: set[str] = set()
        for item in list_value(run.get("established_themes")):
            if not isinstance(item, dict):
                errors.append("WF07 established theme must be an object")
                continue
            ref = str(item.get("established_theme_ref") or "")
            if not ref:
                errors.append("WF07 established theme requires established_theme_ref")
            established_refs.add(ref)
            for key in ("screening_decision_ref", "theme_file_ref"):
                if blank(item.get(key)):
                    errors.append(f"WF07 established theme missing {key}")
            if item.get("screening_decision_ref") not in decision_refs:
                errors.append("WF07 established theme must point to a recorded screening decision")
            if not list_value(item.get("source_preliminary_theme_refs")):
                errors.append("WF07 established theme requires source_preliminary_theme_refs")
        if len(established_refs) != len(list_value(run.get("established_themes"))):
            errors.append("WF07 established_theme_ref values must be unique and nonblank")
    for feedback in list_value(run.get("feedback_loops")):
        if not isinstance(feedback, dict):
            errors.append("WF08 feedback entry must be an object")
            continue
        feedback_type = feedback.get("feedback_type")
        if feedback_type not in FEEDBACK_TYPES:
            errors.append("WF08 invalid feedback_type")
            continue
        for key in ("triggering_judgment", "decisive_gap", "expected_change", "stop_condition", "status"):
            if blank(feedback.get(key)):
                errors.append(f"WF08 {feedback_type} missing {key}")
        if feedback_type == "source_recheck":
            if blank(feedback.get("source_card_id")) or not list_value(feedback.get("affected_claim_ids")):
                errors.append("WF08 source_recheck requires source_card_id and affected_claim_ids")
        elif feedback_type == "corpus_supplement" and blank(feedback.get("retrieval_or_scope_ref")):
            errors.append("WF08 corpus_supplement requires retrieval_or_scope_ref")
        elif feedback_type == "discovery_model_correction":
            if blank(feedback.get("affected_stage")) or blank(feedback.get("configuration_ref")) or blank(feedback.get("validation_sample_ref")):
                errors.append("WF08 discovery_model_correction requires affected_stage, configuration_ref and validation_sample_ref")

    if recalculation.get("required") is True and not list_value(recalculation.get("affected_stages")):
        errors.append("WF09 recalculation requires affected_stages")
    if decision.get("human_review_status") != meta.get("human_review_status"):
        errors.append("WF10 human review status differs between frontmatter and workflow block")
    if decision.get("mentor_decision_status") != meta.get("mentor_decision_status"):
        errors.append("WF10 mentor decision status differs between frontmatter and workflow block")
    if final:
        if task.get("boundary_frozen") is not True:
            errors.append("WF02 final run requires frozen research boundary")
        if preliminary.get("human_boundary_reviewed") is not True:
            errors.append("WF07 final run requires human preliminary-theme boundary review")
        if schema == "hydrology-literature-to-theme-v1.1":
            if screening.get("status") != "completed" or screening.get("all_preliminary_themes_decided") is not True:
                errors.append("WF07 final v1.1 run requires a completed human theme-screening gate")
        if meta.get("human_review_status") != "completed":
            errors.append("WF10 final run requires completed human review")
        if meta.get("mentor_decision_status") != "confirmed":
            errors.append("WF10 final run requires confirmed mentor decision")
    else:
        if not task.get("boundary_frozen"):
            warnings.append("WF02 research boundary is not yet frozen")
        if not preliminary.get("human_boundary_reviewed"):
            warnings.append("WF07 preliminary-theme boundary has not completed human review")
        if schema == "hydrology-literature-to-theme-v1.1" and screening.get("status") != "completed":
            warnings.append("WF07 preliminary themes have not completed the human screening gate")

    # Prevent discovery signals from masquerading as evidence admission.
    for claim_id in list_value(admission.get("included_claim_ids")):
        if not isinstance(claim_id, str) or not claim_id.strip():
            errors.append("WF11 included_claim_ids must contain non-empty Claim IDs")

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_run")
    parser.add_argument("--mode", choices=("draft", "final"), default="draft")
    args = parser.parse_args()

    path = Path(args.workflow_run)
    text = path.read_text(encoding="utf-8-sig")
    meta = parse_frontmatter(text)
    try:
        run = workflow_block(text)
        block_error = None
    except (ValueError, json.JSONDecodeError) as exc:
        run = {}
        block_error = str(exc)
    errors, warnings = validate(meta, run, args.mode == "final")
    if block_error:
        errors.insert(0, block_error)

    print(f"workflow_run: {path}")
    print(f"ref: {meta.get('workflow_ref')}")
    print(f"route: {meta.get('route')}")
    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}")
    if errors:
        raise SystemExit(1)
    print("PASS: WF00-WF11 workflow structure, two-theme gate and boundary checks completed; scientific validity still requires source and human review")


if __name__ == "__main__":
    main()
