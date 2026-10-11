#!/usr/bin/env python3
"""Validate hydrology theme v1.1-v1.3 structure, provenance, screening gate, and deep narrative."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

META_REQUIRED = [
    "theme_schema", "theme_ref", "theme_version", "title", "lifecycle_state",
    "workflow_status", "as_of_date", "intended_use", "input_card_ids",
    "included_claim_ids", "context_only_claim_ids", "excluded_claim_ids",
    "independence_group_ids", "version_family_ids", "source_snapshot_hash",
    "generated_by", "generator_version", "human_review_status", "human_reviewer",
    "mentor_decision_status", "lifecycle_proposal_status",
    "lifecycle_effect_status", "load_bearing_conflict",
    "unresolved_conflict_ids", "last_evidence_refresh", "next_review_trigger",
    "narrative_depth", "narrative_status", "minimum_visible_scientific_chars",
]
BLOCKS = [
    "theme-scope-json", "source-manifest-json", "theme-synthesis-json",
    "literature-priority-json", "evidence-feedback-json",
    "writing-readiness-json", "theme-review-json",
]
LIFECYCLE = {"candidate_dossier", "established_developing", "observation", "active", "contested", "dormant", "archived"}
WORKFLOW = {"draft", "machine_synthesized", "human_reviewed", "mentor_confirmed", "superseded", "archived"}
KNOWLEDGE = {"supported", "provisionally_supported", "contested", "context_dependent", "insufficient", "unknown"}
PROFILE_LEVELS = {"high", "medium", "low", "unknown"}
PROFILE_DIMS = ["directness", "internal_validity", "independence", "precision", "applicability", "reproducibility"]
ACTIONS = {
    "targeted_recheck", "correct_locator", "split_claim", "merge_duplicate",
    "add_boundary", "add_relation", "add_independence_group", "update_version",
    "downgrade_verification", "request_level_upgrade",
}
FEEDBACK_STATUS = {"proposed", "source_checked", "applied", "rejected", "blocked"}
FEEDBACK_TYPES = {"source_recheck", "corpus_supplement", "discovery_model_correction"}
DISCOVERY_ROUTES = {"small_sample", "large_corpus", "hybrid"}
WEIGHTS = {
    "evidence_quality_and_independence": 25,
    "question_directness": 20,
    "decisive_gap_closure": 15,
    "recency": 25,
    "verified_field_normalized_journal_signal": 15,
}
NARRATIVE_START = "<!-- SCIENTIFIC_NARRATIVE_START -->"
NARRATIVE_END = "<!-- SCIENTIFIC_NARRATIVE_END -->"
NARRATIVE_STATUS = {"in_progress", "ready_for_handoff", "blocked_source_limit"}


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip("\"'")


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    result: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        if key.strip() and not key.startswith((" ", "\t")):
            result[key.strip()] = parse_scalar(raw)
    return result


def json_blocks(text: str, language: str) -> tuple[list[dict[str, Any]], list[str]]:
    pattern = rf"(?ms)^(```|~~~){re.escape(language)}\s*\n(.*?)^\1\s*$"
    values: list[dict[str, Any]] = []
    errors: list[str] = []
    for idx, match in enumerate(re.finditer(pattern, text), 1):
        try:
            value = json.loads(match.group(2))
            if isinstance(value, dict):
                values.append(value)
            else:
                errors.append(f"TG00 {language} block {idx} must contain one object")
        except json.JSONDecodeError as exc:
            errors.append(f"TG00 invalid {language} block {idx}: {exc.msg} line {exc.lineno}")
    return values, errors


def blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, str) and "{{" in value)


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def narrative_region(text: str) -> tuple[str, list[str]]:
    errors: list[str] = []
    if text.count(NARRATIVE_START) != 1 or text.count(NARRATIVE_END) != 1:
        return "", ["TG11 theme requires exactly one scientific narrative marker pair"]
    start = text.index(NARRATIVE_START) + len(NARRATIVE_START)
    end = text.index(NARRATIVE_END)
    if end <= start:
        errors.append("TG11 scientific narrative markers are reversed or empty")
        return "", errors
    return text[start:end], errors


def strip_markdown_for_count(region: str) -> tuple[str, list[str], list[str]]:
    text = re.sub(r"(?is)<details\b.*?</details>", "", region)
    text = re.sub(r"(?ms)^(```|~~~).*?^\1\s*$", "", text)
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    clean_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.match(r"^#{1,6}\s", line) or line.startswith("|"):
            clean_lines.append("")
            continue
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^(?:[-*+] |\d+[.)]\s+)", "", line)
        line = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", line)
        line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"[`*_~]", "", line)
        clean_lines.append(line)
    joined = "\n".join(clean_lines)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", joined) if p.strip()]
    sentences = [s.strip() for s in re.split(r"[。！？!?]+", " ".join(paragraphs)) if s.strip()]
    return "\n\n".join(paragraphs), paragraphs, sentences


def normalize_prose(value: str) -> str:
    value = re.sub(r"EC-\d{8}-\d{3}(?:-C\d+)?", "EC", value, flags=re.I)
    value = re.sub(r"\d+(?:\.\d+)?", "N", value)
    value = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    return value.lower()


def narrative_checks(text: str, meta: dict[str, Any]) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    region, marker_errors = narrative_region(text)
    errors.extend(marker_errors)
    if marker_errors:
        return errors, warnings, 0
    clean, paragraphs, sentences = strip_markdown_for_count(region)
    char_count = len(re.sub(r"\s+", "", clean))
    status = meta.get("narrative_status")
    if meta.get("narrative_depth") != "deep":
        errors.append("TG11 narrative_depth must be deep")
    if status not in NARRATIVE_STATUS:
        errors.append("TG11 invalid narrative_status")
    try:
        minimum = int(meta.get("minimum_visible_scientific_chars"))
    except (TypeError, ValueError):
        minimum = 0
        errors.append("TG11 minimum_visible_scientific_chars must be numeric")
    if minimum < 10000:
        errors.append("TG11 deep theme minimum must be at least 10000 visible scientific characters")

    headings = re.findall(r"(?m)^###\s+.+$", region)
    source_ids = set(re.findall(r"EC-\d{8}-\d{3}", region))
    long_paragraphs = [p for p in paragraphs if len(re.sub(r"\s+", "", p)) >= 120]
    cited_long = [p for p in long_paragraphs if re.search(r"EC-\d{8}-\d{3}", p)]

    if status == "ready_for_handoff":
        if char_count < minimum:
            errors.append(f"TG11 visible scientific narrative is {char_count} chars; requires {minimum}")
        if len(headings) < 8:
            errors.append("TG11 ready deep narrative requires at least eight substantive subsections")
        expected_sources = min(5, len(list_value(meta.get("input_card_ids"))))
        if len(source_ids) < expected_sources:
            errors.append(f"TG12 narrative cites only {len(source_ids)} distinct evidence cards; requires {expected_sources}")
        if len(long_paragraphs) < 20:
            errors.append("TG11 ready deep narrative requires at least twenty substantive prose paragraphs")
        elif len(cited_long) / len(long_paragraphs) < 0.6:
            errors.append("TG12 fewer than 60% of substantive paragraphs carry evidence-card provenance")
    else:
        warnings.append(f"TG11 narrative is {status}; visible scientific chars={char_count}")

    seen_paragraphs: dict[str, int] = {}
    for idx, paragraph in enumerate(long_paragraphs, 1):
        token = normalize_prose(paragraph)
        if len(token) < 80:
            continue
        if token in seen_paragraphs:
            errors.append(f"TG13 repeated substantive paragraph {seen_paragraphs[token]} and {idx}")
        else:
            seen_paragraphs[token] = idx
    seen_sentences: set[str] = set()
    for sentence in sentences:
        token = normalize_prose(sentence)
        if len(token) < 80:
            continue
        if token in seen_sentences:
            errors.append("TG13 repeated long sentence in scientific narrative")
            break
        seen_sentences.add(token)
    return errors, warnings, char_count


def get_blocks(text: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    found: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for language in BLOCKS:
        values, block_errors = json_blocks(text, language)
        errors.extend(block_errors)
        if len(values) != 1:
            errors.append(f"TG00 expected exactly one {language} block")
        elif values:
            found[language] = values[0]
    return found, errors


def collect_claim_index(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    claims: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in root.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        meta = parse_frontmatter(text)
        if meta.get("card_type") != "source_evidence":
            continue
        blocks, block_errors = json_blocks(text, "claim-json")
        errors.extend(f"{path}: {item}" for item in block_errors)
        verified_ids = {str(x) for x in list_value(meta.get("verified_claim_ids"))}
        for claim in blocks:
            cid = str(claim.get("claim_id") or "")
            if not cid:
                continue
            if cid in claims:
                errors.append(f"TG04 duplicate Claim ID {cid}: {claims[cid]['path']} and {path}")
                continue
            claims[cid] = {
                "path": str(path),
                "completion_level": meta.get("completion_level"),
                "workflow_status": meta.get("workflow_status"),
                "verification_status": claim.get("verification_status"),
                "verified_in_card": cid in verified_ids,
                "source_manifestation_id": meta.get("source_manifestation_id"),
            }
    return claims, errors


def expected_recency(year: int, as_of_year: int) -> float:
    age = max(0, as_of_year - year)
    if age <= 2:
        return 4
    if age <= 5:
        return 3
    if age <= 10:
        return 2
    if age <= 20:
        return 1
    return 0


def expected_venue(metric: dict[str, Any]) -> float | None:
    token = str(metric.get("percentile_or_quartile") or "").strip().upper()
    resolution = str(metric.get("metric_resolution") or "").strip()
    if resolution == "quartile_only" or token in {"Q1", "Q2", "Q3", "Q4"}:
        return {"Q1": 3.5, "Q2": 2.5, "Q3": 1.5, "Q4": 0.5}.get(token)
    try:
        percentile = float(token.rstrip("%"))
    except (TypeError, ValueError):
        return None
    if percentile >= 90:
        return 4
    if percentile >= 75:
        return 3
    if percentile >= 50:
        return 2
    if percentile >= 25:
        return 1
    return 0


def score_bounds(components: dict[str, Any], na: set[str], unknown: set[str]) -> tuple[float, float, float]:
    applicable = {key: weight for key, weight in WEIGHTS.items() if key not in na}
    denominator = sum(applicable.values())
    if not denominator:
        return 0.0, 100.0, 0.0
    known_weight = sum(weight for key, weight in applicable.items() if key not in unknown and isinstance(components.get(key), (int, float)))
    known_points = sum(weight * float(components[key]) / 4 for key, weight in applicable.items() if key not in unknown and isinstance(components.get(key), (int, float)))
    unknown_weight = sum(weight for key, weight in applicable.items() if key in unknown or components.get(key) is None)
    return (
        100 * known_points / denominator,
        100 * (known_points + unknown_weight) / denominator,
        100 * known_weight / denominator,
    )


def validate(meta: dict[str, Any], blocks: dict[str, dict[str, Any]], final: bool, known: dict[str, dict[str, Any]] | None, text: str) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []

    for key in META_REQUIRED:
        if key not in meta:
            errors.append(f"TG00 missing frontmatter field: {key}")
    schema = meta.get("theme_schema")
    if schema not in {"hydrology-theme-v1.1", "hydrology-theme-v1.2", "hydrology-theme-v1.3"}:
        errors.append("TG00 theme_schema must be hydrology-theme-v1.1, hydrology-theme-v1.2 or hydrology-theme-v1.3")
    if schema in {"hydrology-theme-v1.2", "hydrology-theme-v1.3"}:
        for key in ("discovery_route", "workflow_run_refs", "candidate_direction_refs"):
            if schema == "hydrology-theme-v1.3" and key == "candidate_direction_refs":
                continue
            if key not in meta:
                errors.append(f"TG00 {schema} theme missing frontmatter field: {key}")
        if meta.get("discovery_route") not in DISCOVERY_ROUTES:
            errors.append(f"TG00 {schema} theme requires small_sample, large_corpus or hybrid discovery_route")
        if final and not list_value(meta.get("workflow_run_refs")):
            errors.append(f"TG00 {schema} final theme requires a workflow_run_ref")
    if schema == "hydrology-theme-v1.3":
        for key in ("theme_stage", "preliminary_theme_refs", "preliminary_theme_snapshot_hash", "human_screening_decision_ref", "human_screening_status"):
            if key not in meta:
                errors.append(f"TG00 v1.3 established theme missing frontmatter field: {key}")
        if meta.get("theme_stage") != "established":
            errors.append("TG00 v1.3 theme_stage must be established")
        if not list_value(meta.get("preliminary_theme_refs")):
            errors.append("TG00 v1.3 established theme requires preliminary_theme_refs")
        if blank(meta.get("preliminary_theme_snapshot_hash")):
            errors.append("TG00 v1.3 established theme requires a preliminary_theme_snapshot_hash")
        if blank(meta.get("human_screening_decision_ref")) or meta.get("human_screening_status") != "approved":
            errors.append("TG00 v1.3 established theme requires an approved human screening decision")
    if meta.get("lifecycle_state") not in LIFECYCLE:
        errors.append("TG09 invalid lifecycle_state")
    if meta.get("workflow_status") not in WORKFLOW:
        errors.append("TG09 invalid workflow_status")

    scope = blocks.get("theme-scope-json", {})
    manifest = blocks.get("source-manifest-json", {})
    synthesis = blocks.get("theme-synthesis-json", {})
    priority = blocks.get("literature-priority-json", {})
    feedback = blocks.get("evidence-feedback-json", {})
    writing = blocks.get("writing-readiness-json", {})
    review = blocks.get("theme-review-json", {})

    required_scope = [
        "theme_ref", "one_sentence_argument", "core_question",
        "literature_basis_claim_ids", "direction_basis", "use_basis",
        "existing_theme_comparison", "not_a_filter_dimension_because",
        "included_scope", "excluded_scope", "target_water_context",
        "active_questions", "split_merge_assessment", "continuing_use",
        "next_update_trigger",
    ]
    for key in required_scope:
        if key not in scope:
            errors.append(f"TG02 theme-scope-json missing {key}")
    if scope.get("theme_ref") != meta.get("theme_ref"):
        errors.append("TG02 theme_ref differs between frontmatter and scope")

    manifest_included = [str(x.get("claim_id")) for x in list_value(manifest.get("included_claims")) if isinstance(x, dict) and x.get("claim_id")]
    manifest_context = [str(x.get("claim_id")) for x in list_value(manifest.get("context_only_claims")) if isinstance(x, dict) and x.get("claim_id")]
    manifest_excluded = [str(x.get("claim_id")) for x in list_value(manifest.get("excluded_claims")) if isinstance(x, dict) and x.get("claim_id")]
    meta_included = [str(x) for x in list_value(meta.get("included_claim_ids"))]
    meta_context = [str(x) for x in list_value(meta.get("context_only_claim_ids"))]
    meta_excluded = [str(x) for x in list_value(meta.get("excluded_claim_ids"))]
    if meta_included != manifest_included:
        errors.append("TG01 included Claim IDs differ between frontmatter and source manifest")
    if meta_context != manifest_context:
        errors.append("TG01 context-only Claim IDs differ between frontmatter and source manifest")
    if meta_excluded != manifest_excluded:
        errors.append("TG01 excluded Claim IDs differ between frontmatter and source manifest")
    if (set(meta_included) & set(meta_context)) or (set(meta_included) & set(meta_excluded)):
        errors.append("TG01 a Claim cannot be both included and context-only/excluded")
    for item in list_value(manifest.get("excluded_claims")):
        if isinstance(item, dict) and blank(item.get("reason")):
            errors.append("TG01 every excluded Claim requires a reason")

    if known is not None:
        for cid in meta_included:
            item = known.get(cid)
            if not item:
                errors.append(f"TG01 included Claim does not exist in index: {cid}")
                continue
            if item["completion_level"] not in {"L2", "L3"}:
                errors.append(f"TG01 included Claim below L2: {cid}")
            if item["verification_status"] not in {"source_checked", "independently_reproduced"} or not item["verified_in_card"]:
                errors.append(f"TG01 included Claim is not source checked and card-verified: {cid}")

    frames = {str(x.get("frame_id")) for x in list_value(synthesis.get("comparison_frames")) if isinstance(x, dict) and x.get("frame_id")}
    statements = list_value(synthesis.get("statements"))
    statement_ids: set[str] = set()
    for item in statements:
        if not isinstance(item, dict):
            errors.append("TG03 every synthesis statement must be an object")
            continue
        sid = str(item.get("synthesis_id") or "")
        if not sid:
            errors.append("TG03 synthesis statement missing synthesis_id")
        elif sid in statement_ids:
            errors.append(f"TG03 duplicate synthesis_id: {sid}")
        statement_ids.add(sid)
        if item.get("knowledge_state") not in KNOWLEDGE:
            errors.append(f"TG03 {sid} invalid knowledge_state")
        cited: list[str] = []
        for key in ("supporting_claim_ids", "limiting_claim_ids", "opposing_claim_ids"):
            cited.extend(str(x) for x in list_value(item.get(key)))
        if any(cid not in meta_included for cid in cited):
            errors.append(f"TG03 {sid} cites a non-included Claim as evidence")
        if item.get("knowledge_state") == "contested" and not list_value(item.get("opposing_claim_ids")):
            errors.append(f"TG03 {sid} contested requires opposing_claim_ids")
        frame_id = str(item.get("comparison_frame_id") or "")
        if frame_id and frame_id not in frames:
            errors.append(f"TG03 {sid} references an unknown comparison frame")
        profile = item.get("evidence_profile")
        if not isinstance(profile, dict):
            errors.append(f"TG03 {sid} missing evidence_profile")
        else:
            for dim in PROFILE_DIMS:
                value = profile.get(dim)
                if not isinstance(value, dict) or value.get("level") not in PROFILE_LEVELS or not isinstance(value.get("basis_claim_ids"), list):
                    errors.append(f"TG03 {sid} evidence_profile.{dim} requires level and basis_claim_ids")
                elif any(str(cid) not in meta_included for cid in value.get("basis_claim_ids", [])):
                    errors.append(f"TG03 {sid} evidence_profile.{dim} cites a non-included Claim")
        if final:
            for key in ("statement", "wording_strength", "strongest_permitted_conclusion", "does_not_support", "change_trigger"):
                if blank(item.get(key)):
                    errors.append(f"TG03 {sid} final statement has blank {key}")
            if not cited:
                errors.append(f"TG03 {sid} final statement has no evidence Claim")

    for conflict in list_value(synthesis.get("true_conflicts")):
        if not isinstance(conflict, dict):
            errors.append("TG03 true_conflicts entries must be objects")
            continue
        if not conflict.get("comparison_frame_id") or conflict.get("comparison_frame_id") not in frames:
            errors.append("TG03 true conflict requires a valid comparison_frame_id")
        if not conflict.get("context_alignment_checked"):
            errors.append("TG03 true conflict requires context_alignment_checked=true")
        if len(list_value(conflict.get("claim_ids"))) < 2:
            errors.append("TG03 true conflict requires at least two Claim IDs")

    if priority.get("score_purpose") != "frontier_reading_and_recheck_priority_only":
        errors.append("TG05 priority score must be limited to frontier reading and recheck")
    if priority.get("weights") != WEIGHTS:
        errors.append("TG06 priority weights must remain E25/D20/G15/R25/V15")
    try:
        as_of_year = int(priority.get("as_of_year"))
    except (TypeError, ValueError):
        as_of_year = 0
        errors.append("TG06 literature priority requires numeric as_of_year")

    for item in list_value(priority.get("items")):
        if not isinstance(item, dict):
            errors.append("TG06 priority item must be an object")
            continue
        source_id = str(item.get("source_card_id") or "<unknown>")
        if not list_value(item.get("scientific_roles")):
            errors.append(f"TG05 {source_id} requires scientific_roles independent of score")
        components = item.get("components") if isinstance(item.get("components"), dict) else {}
        na = {str(x) for x in list_value(item.get("not_applicable_components"))}
        unknown = {str(x) for x in list_value(item.get("unknown_components"))}
        if any(key not in WEIGHTS for key in na | unknown):
            errors.append(f"TG06 {source_id} has unknown component names")
        if na & unknown:
            errors.append(f"TG06 {source_id} component cannot be both unknown and not_applicable")
        for key in WEIGHTS:
            value = components.get(key)
            if key in na or key in unknown:
                if value is not None:
                    errors.append(f"TG06 {source_id} {key} must be null when unknown/not_applicable")
            elif not isinstance(value, (int, float)) or not 0 <= float(value) <= 4:
                errors.append(f"TG06 {source_id} {key} must be 0-4 or explicitly unknown/not_applicable")

        pub_year = item.get("publication_year")
        recency = components.get("recency")
        if isinstance(pub_year, int) and as_of_year and "recency" not in na | unknown and isinstance(recency, (int, float)):
            if not math.isclose(float(recency), expected_recency(pub_year, as_of_year)):
                errors.append(f"TG06 {source_id} recency score does not match publication year")

        metric = item.get("journal_metric") if isinstance(item.get("journal_metric"), dict) else {}
        metric_status = metric.get("status")
        venue_key = "verified_field_normalized_journal_signal"
        if metric_status not in {"verified", "unknown", "not_applicable"}:
            errors.append(f"TG05 {source_id} invalid journal_metric.status")
        if metric_status == "not_applicable" and venue_key not in na:
            errors.append(f"TG05 {source_id} non-applicable journal metric must be not_applicable")
        if metric_status == "unknown" and venue_key not in unknown:
            errors.append(f"TG05 {source_id} unknown journal metric must be unknown")
        if metric_status == "verified":
            for key in ("metric_name", "metric_year", "category", "percentile_or_quartile", "metric_resolution", "source", "checked_at"):
                if blank(metric.get(key)):
                    errors.append(f"TG05 {source_id} verified journal metric missing {key}")
            expected = expected_venue(metric)
            venue_value = components.get(venue_key)
            if expected is None:
                errors.append(f"TG05 {source_id} raw JIF without percentile/quartile cannot be scored")
            elif not isinstance(venue_value, (int, float)) or not math.isclose(float(venue_value), expected):
                errors.append(f"TG06 {source_id} venue score does not match percentile/quartile")

        minimum, maximum, completeness = score_bounds(components, na, unknown)
        if unknown:
            if item.get("frontier_attention_score") is not None:
                errors.append(f"TG06 {source_id} unknown components require null exact score")
            for field, expected in (("provisional_min", minimum), ("provisional_max", maximum)):
                value = item.get(field)
                if not isinstance(value, (int, float)) or not math.isclose(float(value), expected, abs_tol=0.11):
                    errors.append(f"TG06 {source_id} {field} does not match recomputed range")
        else:
            value = item.get("frontier_attention_score")
            if not isinstance(value, (int, float)) or not math.isclose(float(value), minimum, abs_tol=0.11):
                errors.append(f"TG06 {source_id} frontier_attention_score does not match recomputation")
        declared = item.get("ranking_completeness")
        try:
            declared_value = float(str(declared).rstrip("%"))
            if not math.isclose(declared_value, completeness, abs_tol=0.11):
                errors.append(f"TG06 {source_id} ranking_completeness does not match known-weight coverage")
        except (TypeError, ValueError):
            errors.append(f"TG06 {source_id} ranking_completeness must be numeric or percentage")

    for req in list_value(feedback.get("requests")):
        if not isinstance(req, dict):
            errors.append("TG07 feedback request must be an object")
            continue
        rid = str(req.get("request_id") or "<unknown>")
        feedback_type = req.get("feedback_type") or "source_recheck"
        if feedback_type not in FEEDBACK_TYPES:
            errors.append(f"TG07 {rid} uses an unsupported feedback type")
            continue
        if req.get("status") not in FEEDBACK_STATUS:
            errors.append(f"TG07 {rid} invalid status")
        gates = req.get("three_gate_check")
        if not isinstance(gates, dict) or set(gates) != {"decision_exists", "gap_is_locatable", "new_material_may_change_judgment"}:
            errors.append(f"TG07 {rid} requires exact three-gate check")
        if req.get("status") in {"source_checked", "applied"} and (not isinstance(gates, dict) or not all(gates.values())):
            errors.append(f"TG07 {rid} cannot advance without all three gates")
        if feedback_type == "source_recheck":
            if req.get("allowed_action") not in ACTIONS or req.get("problem_type") not in ACTIONS:
                errors.append(f"TG07 {rid} uses an unsupported source-recheck action")
            if not req.get("source_card_id") or not req.get("source_card_path") or not list_value(req.get("affected_claim_ids")):
                errors.append(f"TG07 {rid} source_recheck must point to original card and Claim IDs")
        elif feedback_type == "corpus_supplement":
            if blank(req.get("retrieval_or_scope_ref")):
                errors.append(f"TG07 {rid} corpus_supplement requires retrieval_or_scope_ref")
        elif feedback_type == "discovery_model_correction":
            for key in ("affected_stage", "configuration_ref", "validation_sample_ref"):
                if blank(req.get(key)):
                    errors.append(f"TG07 {rid} discovery_model_correction missing {key}")
        if req.get("status") == "applied":
            if feedback_type == "source_recheck":
                for key in ("source_check_result", "card_revision_before", "card_revision_after", "evidence_card_validation", "theme_recalculation"):
                    if blank(req.get(key)):
                        errors.append(f"TG08 {rid} applied source feedback missing {key}")
                if not list_value(req.get("changed_claim_ids")):
                    errors.append(f"TG08 {rid} applied source feedback requires changed_claim_ids")
            else:
                for key in ("application_result", "theme_recalculation"):
                    if blank(req.get(key)):
                        errors.append(f"TG08 {rid} applied {feedback_type} missing {key}")
        if final:
            for key in ("problem", "theme_consequence", "pre_check_judgment", "decisive_gap", "expected_theme_change", "stop_condition"):
                if blank(req.get(key)):
                    errors.append(f"TG07 {rid} final feedback has blank {key}")

    for signal in list_value(writing.get("opportunity_signals")):
        if not isinstance(signal, dict):
            errors.append("TG10 opportunity signal must be an object")
            continue
        if signal.get("status") != "signal_only":
            errors.append("TG10 opportunity must remain signal_only in this skill")
        basis = [str(x) for x in list_value(signal.get("basis_synthesis_ids"))]
        if any(x not in statement_ids for x in basis):
            errors.append("TG10 opportunity cites an unknown synthesis_id")
        if final and (blank(signal.get("missing_novelty_search")) or blank(signal.get("next_verification")) or blank(signal.get("stop_condition"))):
            errors.append("TG10 opportunity requires novelty gap, next verification and stop condition")

    human = review.get("human_source_review") if isinstance(review.get("human_source_review"), dict) else {}
    mentor = review.get("mentor_decision") if isinstance(review.get("mentor_decision"), dict) else {}
    lifecycle = review.get("lifecycle") if isinstance(review.get("lifecycle"), dict) else {}
    if human.get("status") != meta.get("human_review_status"):
        errors.append("TG09 human review status differs between frontmatter and review block")
    if mentor.get("status") != meta.get("mentor_decision_status"):
        errors.append("TG09 mentor status differs between frontmatter and review block")
    if lifecycle.get("proposal_status") != meta.get("lifecycle_proposal_status") or lifecycle.get("effect_status") != meta.get("lifecycle_effect_status"):
        errors.append("TG09 lifecycle status differs between frontmatter and review block")
    if meta.get("lifecycle_state") in {"observation", "active", "contested", "dormant", "archived"}:
        if meta.get("mentor_decision_status") != "confirmed" or meta.get("lifecycle_effect_status") != "applied":
            errors.append("TG09 formal lifecycle state requires mentor confirmation and applied event")
    if meta.get("lifecycle_state") == "active" and (meta.get("load_bearing_conflict") is True or list_value(meta.get("unresolved_conflict_ids"))):
        errors.append("TG09 unresolved load-bearing conflict blocks active state")
    if writing.get("overall_readiness") == "ready" and meta.get("human_review_status") != "completed":
        errors.append("TG10 writing readiness cannot be ready before human source review")

    if final:
        for key in ("theme_ref", "title", "as_of_date", "intended_use", "source_snapshot_hash", "last_evidence_refresh", "next_review_trigger"):
            if blank(meta.get(key)):
                errors.append(f"TG00 final theme has blank {key}")
        for key in ("one_sentence_argument", "core_question", "direction_basis", "use_basis", "not_a_filter_dimension_because", "next_update_trigger"):
            if blank(scope.get(key)):
                errors.append(f"TG02 final theme scope has blank {key}")
        if not meta_included:
            errors.append("TG01 final theme requires an included source-checked Claim")
        if not statements:
            errors.append("TG03 final theme requires a synthesis statement")
        if meta.get("human_review_status") != "completed" or blank(meta.get("human_reviewer")):
            errors.append("TG09 final handoff requires completed human source review")
    else:
        if meta.get("human_review_status") != "completed":
            warnings.append("TG09 draft has not completed human source review")
        if not meta_included:
            warnings.append("TG01 draft has no included Claim; select admissible Claims before synthesis")

    narrative_errors, narrative_warnings, narrative_chars = narrative_checks(text, meta)
    errors.extend(narrative_errors)
    warnings.extend(narrative_warnings)
    if final and meta.get("narrative_status") != "ready_for_handoff":
        errors.append("TG11 final theme requires narrative_status ready_for_handoff")

    return errors, warnings, narrative_chars


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme")
    parser.add_argument("--mode", choices=["draft", "final"], default="draft")
    parser.add_argument("--index-root")
    args = parser.parse_args()

    path = Path(args.theme)
    text = path.read_text(encoding="utf-8-sig")
    meta = parse_frontmatter(text)
    blocks, block_errors = get_blocks(text)
    known = None
    index_errors: list[str] = []
    if args.index_root:
        known, index_errors = collect_claim_index(Path(args.index_root))
    errors, warnings, narrative_chars = validate(meta, blocks, args.mode == "final", known, text)
    errors = block_errors + index_errors + errors

    print(f"theme: {path}")
    print(f"ref: {meta.get('theme_ref')}")
    print(f"state: {meta.get('lifecycle_state')}")
    print(f"visible_scientific_chars: {narrative_chars}")
    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}")
    if errors:
        raise SystemExit(1)
    print("PASS: TG01-TG13 structural, provenance, and visible-depth checks completed; scientific validity still requires source and expert review")


if __name__ == "__main__":
    main()
