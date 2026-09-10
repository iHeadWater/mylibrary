#!/usr/bin/env python3
"""Assemble a standalone v1.7 source or platform decision evidence card."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROFILES = {
    "original-research": ("01_original-research.md", "journal_article", ["original_research"]),
    "review-synthesis": ("02_review-synthesis.md", "journal_article", ["review_synthesis"]),
    "survey-monitoring-statistics": ("03_survey-monitoring-statistics.md", "government_report", ["descriptive_statistics", "monitoring_evidence"]),
    "engineering-report": ("04_engineering-report.md", "engineering_report", ["engineering_evidence"]),
    "book-chapter": ("05_book-chapter.md", "book_chapter", ["concept_definition", "theory_background"]),
    "standard-guideline-policy": ("06_standard-guideline-policy.md", "standard", ["normative_requirement"]),
    "dataset-data-product": ("07_dataset-data-product.md", "dataset", ["dataset_identity", "dataset_quality", "fitness_for_purpose"]),
    "software-model-code": ("08_software-model-code.md", "software_release", ["implementation_identity", "software_verification", "software_validation", "reproducibility"]),
}

MODULES = {
    "hydro-forecast-ml": "method-hydro-forecast-ml.md",
    "hydrodynamic-simulation": "method-hydrodynamic-simulation.md",
    "frequency-drought-climate": "method-frequency-drought-climate.md",
    "monitoring-quality-remote-sensing": "method-monitoring-quality-remote-sensing.md",
    "engineering-operation-safety": "method-engineering-operation-safety.md",
}

LEVEL_DEFAULTS = {
    "L0": ("ingested", "metadata", "peripheral", "currently_unusable", "not_applicable"),
    "L1": ("screened", "abstract", "peripheral", "clue_only", "transfer_check_required"),
    "L2": ("extracted", "mixed", "supporting", "partially_verified", "conditional"),
    "L3": ("extracted", "mixed", "central", "partially_verified", "conditional"),
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").strip() + "\n"


def body_without_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text.strip()
    parts = text.split("---", 2)
    return parts[2].strip() if len(parts) == 3 else text.strip()


def replace_all(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def build_source(args: argparse.Namespace) -> str:
    profile_file, default_artifact, default_roles = PROFILES[args.type]
    workflow, default_scope, relevance, readiness, applicability = LEVEL_DEFAULTS[args.level]
    roles = args.role or default_roles
    artifact = args.artifact_type or default_artifact
    research_ids = [args.research_question_id] if args.research_question_id else []
    decision_ids = [args.decision_id] if args.decision_id else []

    values = {
        "CARD_ID": args.card_id,
        "TITLE": args.title,
        "ARTIFACT_TYPE": artifact,
        "EVIDENCE_ROLES": json_list(roles),
        "WORKFLOW_STATUS": workflow,
        "COMPLETION_LEVEL": args.level,
        "SOURCE_WORK_ID": args.source_work_id or "{{SOURCE_WORK_ID}}",
        "SOURCE_MANIFESTATION_ID": args.manifestation_id or "{{SOURCE_MANIFESTATION_ID}}",
        "SOURCE_VERSION": args.source_version or "{{SOURCE_VERSION}}",
        "SOURCE_SNAPSHOT_HASH": args.source_snapshot_hash or "",
        "SOURCE_PROVENANCE": args.source_provenance,
        "ACQUIRED_VIA": args.acquired_via,
        "ACQUIRED_AT": args.acquired_at or str(date.today()),
        "VALIDITY_CHECKED_AT": args.validity_checked_at or "",
        "LANGUAGE": args.language,
        "ACCESS_LEVEL": args.access_level,
        "ZOTERO_ITEM_KEY": args.zotero_item_key or "",
        "PROJECT_IDS": json_list([args.project_id] if args.project_id else []),
        "RESEARCH_QUESTION_IDS": json_list(research_ids),
        "DECISION_IDS": json_list(decision_ids),
        "READING_SCOPE": args.reading_scope or default_scope,
        "EXTRACTION_METHOD": args.extraction_method,
        "GENERATOR_VERSION": args.generator_version,
        "CONFIDENTIALITY": args.confidentiality,
        "WATER_CONTEXT_STATUS": "partial" if args.water_context else "not_applicable",
        "METHOD_MODULES": json_list(args.module),
        "RELEVANCE": relevance,
        "VERIFICATION_READINESS": readiness,
        "APPLICABILITY": applicability,
        "RECHECK_TRIGGER": args.recheck_trigger or "",
        "CREATORS": "",
        "DATE": "",
        "VENUE": "",
        "IDENTIFIER": "",
        "SOURCE_URL": "",
    }

    chunks = [read(ROOT / "assets" / "base" / "source-frontmatter.md")]
    if args.level in {"L1", "L2", "L3"}:
        chunks.append(read(ROOT / "assets" / "base" / "level-l1.md"))
    if args.level in {"L2", "L3"}:
        profile = body_without_frontmatter(read(ROOT / "assets" / "templates" / profile_file))
        machine_additions: list[str] = []
        if args.water_context:
            machine_additions.append(read(ROOT / "assets" / "modules" / "water-context.md").strip())
        for module in args.module:
            machine_additions.append(read(ROOT / "assets" / "modules" / MODULES[module]).strip())
        l2 = read(ROOT / "assets" / "base" / "level-l2.md")
        chunks.append(
            l2.replace("{{SOURCE_TYPE_HUMAN_MODULE}}", profile)
            .replace("{{MACHINE_MODULES_CONTENT}}", "\n\n".join(machine_additions))
        )
    if args.level == "L3":
        module_note = "已启用模块：" + ("、".join(args.module) if args.module else "无；请说明为何不需要条件方法模块")
        chunks.append(read(ROOT / "assets" / "base" / "level-l3.md").replace("{{METHOD_MODULES_CONTENT}}", module_note))
    return replace_all("\n".join(chunks), values)


def build_decision(args: argparse.Namespace) -> str:
    template = read(ROOT / "assets" / "templates" / "09_platform-decision-synthesis.md")
    values = {
        "CARD_ID": args.card_id,
        "TITLE": args.title,
        "DECISION_ID": args.decision_id or "{{DECISION_ID}}",
        "RESEARCH_QUESTION_IDS": json_list([args.research_question_id] if args.research_question_id else []),
        "PROJECT_IDS": json_list([args.project_id] if args.project_id else []),
        "AS_OF_DATE": args.as_of_date or str(date.today()),
        "DECISION_OWNER": args.decision_owner or "",
    }
    return replace_all(template, values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, choices=[*PROFILES, "decision-synthesis"])
    parser.add_argument("--card-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--level", choices=list(LEVEL_DEFAULTS), default="L1")
    parser.add_argument("--artifact-type")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--module", action="append", choices=list(MODULES), default=[])
    parser.add_argument("--water-context", action="store_true")
    parser.add_argument("--source-work-id")
    parser.add_argument("--manifestation-id")
    parser.add_argument("--source-version")
    parser.add_argument("--source-snapshot-hash")
    parser.add_argument("--source-provenance", default="local_zotero")
    parser.add_argument("--acquired-via", default="zotero_local_api")
    parser.add_argument("--acquired-at")
    parser.add_argument("--validity-checked-at")
    parser.add_argument("--language", default="unknown")
    parser.add_argument("--access-level", default="internal")
    parser.add_argument("--zotero-item-key")
    parser.add_argument("--project-id")
    parser.add_argument("--research-question-id")
    parser.add_argument("--decision-id")
    parser.add_argument("--reading-scope")
    parser.add_argument("--extraction-method", choices=["human", "ai_assisted", "automated"], default="ai_assisted")
    parser.add_argument("--generator-version", default="hydrology-evidence-cards-v1.7")
    parser.add_argument("--confidentiality", default="internal")
    parser.add_argument("--recheck-trigger")
    parser.add_argument("--as-of-date")
    parser.add_argument("--decision-owner")
    args = parser.parse_args()

    text = build_decision(args) if args.type == "decision-synthesis" else build_source(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text.rstrip() + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
