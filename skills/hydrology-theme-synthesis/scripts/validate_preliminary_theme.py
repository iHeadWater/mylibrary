#!/usr/bin/env python3
"""Validate a screening-only preliminary hydrology theme and its human decision gate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "hydrology-preliminary-theme-v1.0"
ROUTES = {"small_sample", "large_corpus", "hybrid"}
STATUSES = {"draft", "ready_for_human_screening", "screened", "superseded", "archived"}
HUMAN_STATUSES = {"not_started", "in_review", "completed"}
DECISIONS = {
    "establish", "rename_then_establish", "merge", "split_and_rescreen",
    "watch", "supplement_before_decision", "reject",
}


def scalar(raw: str) -> Any:
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return raw.strip().strip("\"'")


def frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    result: dict[str, Any] = {}
    for line in parts[1].splitlines() if len(parts) == 3 else []:
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            result[key.strip()] = scalar(value)
    return result


def block(text: str) -> dict[str, Any]:
    match = re.search(r"(?ms)^~~~preliminary-theme-json\s*\n(.*?)^~~~\s*$", text)
    if not match:
        raise ValueError("PT00 requires one preliminary-theme-json block")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("PT00 preliminary-theme-json must contain one object")
    return value


def blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, str) and "{{" in value)


def validate(meta: dict[str, Any], data: dict[str, Any], final: bool) -> list[str]:
    errors: list[str] = []
    required = (
        "preliminary_theme_schema", "preliminary_theme_ref", "title", "discovery_route",
        "workflow_run_refs", "status", "allowed_use", "as_of_date", "generated_by",
        "generator_version", "human_screening_status",
    )
    for key in required:
        if key not in meta:
            errors.append(f"PT00 missing frontmatter field: {key}")
    if meta.get("preliminary_theme_schema") != SCHEMA:
        errors.append(f"PT00 preliminary_theme_schema must be {SCHEMA}")
    if meta.get("discovery_route") not in ROUTES:
        errors.append("PT01 invalid discovery_route")
    if meta.get("status") not in STATUSES:
        errors.append("PT01 invalid status")
    if meta.get("allowed_use") != "screening_only":
        errors.append("PT01 preliminary theme allowed_use must be screening_only")
    if data.get("preliminary_theme_ref") != meta.get("preliminary_theme_ref"):
        errors.append("PT00 preliminary theme ref differs between frontmatter and block")

    decision = data.get("human_screening_decision") if isinstance(data.get("human_screening_decision"), dict) else {}
    formation = data.get("formation_basis") if isinstance(data.get("formation_basis"), dict) else {}
    focus = data.get("scientific_focus_hypothesis") if isinstance(data.get("scientific_focus_hypothesis"), dict) else {}
    boundary = data.get("boundary_hypothesis") if isinstance(data.get("boundary_hypothesis"), dict) else {}
    evidence = data.get("screening_evidence") if isinstance(data.get("screening_evidence"), dict) else {}
    status = decision.get("status")
    if status not in HUMAN_STATUSES or status != meta.get("human_screening_status"):
        errors.append("PT02 human screening status is invalid or inconsistent")
    if status == "completed" or final:
        if not formation.get("representative_source_refs") or blank(formation.get("machine_or_manual_grouping_basis")):
            errors.append("PT02 completed screening requires representative sources and grouping basis")
        for key in ("candidate_problem", "why_more_than_a_keyword_or_method_label"):
            if blank(focus.get(key)):
                errors.append(f"PT02 completed screening requires scientific_focus_hypothesis.{key}")
        if not boundary.get("tentative_inclusion"):
            errors.append("PT02 completed screening requires at least one tentative inclusion boundary")
        for key in ("representative_literature_summary", "research_question_relevance"):
            if blank(evidence.get(key)):
                errors.append(f"PT02 completed screening requires screening_evidence.{key}")
        if decision.get("decision") not in DECISIONS:
            errors.append("PT02 completed screening requires an allowed decision")
        for key in ("decision_ref", "rationale", "reviewer", "reviewed_at"):
            if blank(decision.get(key)):
                errors.append(f"PT02 completed screening requires {key}")
        if decision.get("decision") in {"establish", "rename_then_establish", "merge"} and not decision.get("resulting_established_theme_refs"):
            errors.append("PT03 establishment decision requires resulting_established_theme_refs")
        if decision.get("decision") == "split_and_rescreen" and not decision.get("split_into_preliminary_theme_refs"):
            errors.append("PT03 split decision requires split_into_preliminary_theme_refs")
    if final and status != "completed":
        errors.append("PT02 final preliminary theme requires completed human screening")
    if final and meta.get("status") != "screened":
        errors.append("PT02 final preliminary theme status must be screened")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preliminary_theme")
    parser.add_argument("--mode", choices=("draft", "final"), default="draft")
    args = parser.parse_args()
    path = Path(args.preliminary_theme)
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = block(text)
        parse_error = None
    except (ValueError, json.JSONDecodeError) as exc:
        data = {}
        parse_error = str(exc)
    errors = validate(frontmatter(text), data, args.mode == "final")
    if parse_error:
        errors.insert(0, parse_error)
    for item in errors:
        print(f"ERROR: {item}")
    if errors:
        raise SystemExit(1)
    print("PASS: PT00-PT03 preliminary-theme structure passed; scientific meaning still requires human review")


if __name__ == "__main__":
    main()
