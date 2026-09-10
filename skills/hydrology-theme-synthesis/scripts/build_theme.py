#!/usr/bin/env python3
"""Build a traceable established hydrology theme v1.3 draft from evidence-card files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


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
    data: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        if key.strip() and not key.startswith((" ", "\t")):
            data[key.strip()] = parse_scalar(raw)
    return data


def json_blocks(text: str, language: str) -> list[dict[str, Any]]:
    pattern = rf"(?ms)^(```|~~~){re.escape(language)}\s*\n(.*?)^\1\s*$"
    values: list[dict[str, Any]] = []
    for match in re.finditer(pattern, text):
        try:
            value = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def detect_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def detect_year(meta: dict[str, Any], text: str) -> int | None:
    for key in ("publication_year", "year"):
        value = meta.get(key)
        if isinstance(value, int) and 1000 <= value <= 3000:
            return value
        if isinstance(value, str):
            match = re.search(r"\b(19|20)\d{2}\b", value)
            if match:
                return int(match.group(0))
    match = re.search(r"(?m)^-\s*年份／发布日期：\s*(.*)$", text)
    if match:
        found = re.search(r"\b(19|20)\d{2}\b", match.group(1))
        if found:
            return int(found.group(0))
    return None


def file_record(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    text = path.read_text(encoding="utf-8-sig")
    return parse_frontmatter(text), json_blocks(text, "claim-json"), text


def replace_all(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def dump_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def discover_cards(args: argparse.Namespace) -> list[Path]:
    candidates = [Path(p) for p in args.card]
    for directory in args.cards_dir:
        candidates.extend(Path(directory).rglob("*.md"))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme-ref", required=True, help="Draft reference or human-assigned theme ID; never auto-assigned")
    parser.add_argument("--title", required=True)
    parser.add_argument("--question", default="")
    parser.add_argument("--intended-use", default="")
    parser.add_argument("--as-of-date", default=str(date.today()))
    parser.add_argument("--discovery-route", choices=("small_sample", "large_corpus", "hybrid"), default="small_sample")
    parser.add_argument("--workflow-run-ref", action="append", default=[])
    parser.add_argument("--preliminary-theme-file", action="append", required=True)
    parser.add_argument("--card", action="append", default=[])
    parser.add_argument("--cards-dir", action="append", default=[])
    parser.add_argument("--claim", action="append", default=[], help="Claim explicitly selected after scientific review")
    parser.add_argument("--include-all-verified", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    preliminary_refs: list[str] = []
    preliminary_snapshot_parts: list[str] = []
    screening_decision_refs: set[str] = set()
    for raw_path in args.preliminary_theme_file:
        preliminary_path = Path(raw_path).resolve()
        if not preliminary_path.exists():
            raise SystemExit(f"Preliminary theme not found: {preliminary_path}")
        preliminary_text = preliminary_path.read_text(encoding="utf-8-sig")
        preliminary_meta = parse_frontmatter(preliminary_text)
        preliminary_blocks = json_blocks(preliminary_text, "preliminary-theme-json")
        if preliminary_meta.get("preliminary_theme_schema") != "hydrology-preliminary-theme-v1.0" or len(preliminary_blocks) != 1:
            raise SystemExit(f"Invalid preliminary theme structure: {preliminary_path}")
        preliminary_data = preliminary_blocks[0]
        preliminary_ref = clean_text(preliminary_meta.get("preliminary_theme_ref"))
        if not preliminary_ref or preliminary_data.get("preliminary_theme_ref") != preliminary_ref:
            raise SystemExit(f"Preliminary theme ref is missing or inconsistent: {preliminary_path}")
        decision = preliminary_data.get("human_screening_decision")
        if preliminary_meta.get("allowed_use") != "screening_only":
            raise SystemExit(f"Preliminary theme allowed_use is invalid: {preliminary_path}")
        if not isinstance(decision, dict) or preliminary_meta.get("status") != "screened" or preliminary_meta.get("human_screening_status") != "completed" or decision.get("status") != "completed":
            raise SystemExit(f"Human screening is not completed: {preliminary_path}")
        if decision.get("decision") not in {"establish", "rename_then_establish", "merge"}:
            raise SystemExit(f"Preliminary theme decision does not permit establishment: {preliminary_path}")
        if args.theme_ref not in list_value(decision.get("resulting_established_theme_refs")):
            raise SystemExit(f"Human decision does not establish {args.theme_ref}: {preliminary_path}")
        for key in ("decision_ref", "rationale", "reviewer", "reviewed_at"):
            if not clean_text(decision.get(key)):
                raise SystemExit(f"Human screening {key} is missing: {preliminary_path}")
        formation = preliminary_data.get("formation_basis") if isinstance(preliminary_data.get("formation_basis"), dict) else {}
        focus = preliminary_data.get("scientific_focus_hypothesis") if isinstance(preliminary_data.get("scientific_focus_hypothesis"), dict) else {}
        boundary = preliminary_data.get("boundary_hypothesis") if isinstance(preliminary_data.get("boundary_hypothesis"), dict) else {}
        evidence = preliminary_data.get("screening_evidence") if isinstance(preliminary_data.get("screening_evidence"), dict) else {}
        if not list_value(formation.get("representative_source_refs")) or not clean_text(formation.get("machine_or_manual_grouping_basis")):
            raise SystemExit(f"Human screening lacks representative sources or grouping basis: {preliminary_path}")
        if not clean_text(focus.get("candidate_problem")) or not clean_text(focus.get("why_more_than_a_keyword_or_method_label")):
            raise SystemExit(f"Human screening lacks a defensible scientific focus: {preliminary_path}")
        if not list_value(boundary.get("tentative_inclusion")):
            raise SystemExit(f"Human screening lacks an inclusion boundary: {preliminary_path}")
        if not clean_text(evidence.get("representative_literature_summary")) or not clean_text(evidence.get("research_question_relevance")):
            raise SystemExit(f"Human screening lacks literature and relevance reasoning: {preliminary_path}")
        decision_ref = clean_text(decision.get("decision_ref"))
        preliminary_refs.append(preliminary_ref)
        screening_decision_refs.add(decision_ref)
        preliminary_snapshot_parts.append(f"{preliminary_path.as_posix()}:{hashlib.sha256(preliminary_path.read_bytes()).hexdigest()}")
    if len(screening_decision_refs) != 1:
        raise SystemExit("All preliminary themes used for one established theme must share one screening decision_ref")

    paths = discover_cards(args)
    if not paths:
        raise SystemExit("No evidence-card paths were supplied")

    selected = set(args.claim)
    sources: list[dict[str, Any]] = []
    included: list[dict[str, Any]] = []
    context_only: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen_claims: dict[str, str] = {}
    snapshot_parts: list[str] = []
    card_ids: list[str] = []
    independence_groups: set[str] = set()
    version_families: set[str] = set()

    for path in paths:
        if not path.exists():
            excluded.append({"claim_id": "", "source_card_id": "", "card_path": str(path), "reason": "card_not_found"})
            continue
        meta, claims, text = file_record(path)
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot_parts.append(f"{path.as_posix()}:{file_hash}")
        if meta.get("card_type") != "source_evidence":
            continue

        card_id = clean_text(meta.get("card_id"))
        if card_id:
            card_ids.append(card_id)
        verified_by_card = {str(x) for x in list_value(meta.get("verified_claim_ids"))}
        completion_level = meta.get("completion_level")
        source_manifestation_id = clean_text(meta.get("source_manifestation_id"))
        card_path = path.as_posix()
        claim_ids = [clean_text(c.get("claim_id")) for c in claims if clean_text(c.get("claim_id"))]
        independence_groups.update(str(x) for x in list_value(meta.get("independence_group_ids")) if str(x))
        version_families.update(str(x) for x in list_value(meta.get("version_family_ids")) if str(x))
        sources.append({
            "card_id": card_id,
            "card_path": card_path,
            "card_version": meta.get("card_version", ""),
            "file_sha256": file_hash,
            "source_work_id": meta.get("source_work_id", ""),
            "source_manifestation_id": source_manifestation_id,
            "source_version": meta.get("source_version", ""),
            "title": detect_title(text, card_id),
            "artifact_type": meta.get("artifact_type", ""),
            "evidence_roles": list_value(meta.get("evidence_roles")),
            "publication_year": detect_year(meta, text),
            "completion_level": completion_level,
            "reading_scope": meta.get("reading_scope", ""),
            "workflow_status": meta.get("workflow_status", ""),
            "independence_group_ids": list_value(meta.get("independence_group_ids")),
            "version_family_ids": list_value(meta.get("version_family_ids")),
            "claim_ids": claim_ids,
            "candidate_verified_claim_ids": [],
            "input_status": "read"
        })

        for claim in claims:
            claim_id = clean_text(claim.get("claim_id"))
            if not claim_id:
                excluded.append({"claim_id": "", "source_card_id": card_id, "card_path": card_path, "reason": "missing_claim_id"})
                continue
            duplicate_of = seen_claims.get(claim_id)
            if duplicate_of:
                excluded.append({"claim_id": claim_id, "source_card_id": card_id, "card_path": card_path, "reason": "duplicate_claim_id", "duplicate_of_path": duplicate_of})
                continue
            seen_claims[claim_id] = card_path

            verification = claim.get("verification_status")
            admissible = (
                completion_level in {"L2", "L3"}
                and verification in {"source_checked", "independently_reproduced"}
                and claim_id in verified_by_card
            )
            item = {
                "claim_id": claim_id,
                "source_card_id": card_id,
                "source_manifestation_id": source_manifestation_id,
                "card_path": card_path,
                "statement_role": claim.get("statement_role", ""),
                "inference_type": claim.get("inference_type", ""),
                "support_status": claim.get("support_status", ""),
                "statement": claim.get("statement", ""),
                "scope": claim.get("scope", {}),
                "locator": claim.get("locator", {}),
                "directly_supports": claim.get("directly_supports", ""),
                "does_not_support": claim.get("does_not_support", ""),
                "independence_group_ids": claim.get("independence_group_ids", []),
                "verification_status": verification,
            }
            if admissible:
                sources[-1]["candidate_verified_claim_ids"].append(claim_id)
                if args.include_all_verified or claim_id in selected:
                    included.append(item)
                else:
                    context_only.append({**item, "reason": "eligible_but_not_explicitly_selected"})
            else:
                reasons = []
                if completion_level not in {"L2", "L3"}:
                    reasons.append("below_L2")
                if verification not in {"source_checked", "independently_reproduced"}:
                    reasons.append("claim_not_source_checked")
                if claim_id not in verified_by_card:
                    reasons.append("absent_from_card_verified_claim_ids")
                excluded.append({**item, "reason": "+".join(reasons)})

    for missing in sorted(selected - set(seen_claims)):
        excluded.append({"claim_id": missing, "source_card_id": "", "card_path": "", "reason": "selected_claim_not_found"})

    input_hash = hashlib.sha256("\n".join(sorted(snapshot_parts)).encode("utf-8")).hexdigest()
    template = (ROOT / "assets" / "theme-template.md").read_text(encoding="utf-8-sig")
    values = {
        "THEME_REF": args.theme_ref,
        "TITLE": args.title,
        "QUESTION": args.question,
        "INTENDED_USE": args.intended_use,
        "AS_OF_DATE": args.as_of_date,
        "AS_OF_YEAR": args.as_of_date[:4],
        "DISCOVERY_ROUTE": args.discovery_route,
        "WORKFLOW_RUN_REFS": dump_compact(args.workflow_run_ref),
        "PRELIMINARY_THEME_REFS": dump_compact(preliminary_refs),
        "PRELIMINARY_THEME_SNAPSHOT_HASH": hashlib.sha256("\n".join(sorted(preliminary_snapshot_parts)).encode("utf-8")).hexdigest(),
        "HUMAN_SCREENING_DECISION_REF": next(iter(screening_decision_refs)),
        "INPUT_CARD_IDS": dump_compact(sorted(set(card_ids))),
        "INCLUDED_CLAIM_IDS": dump_compact([x["claim_id"] for x in included]),
        "CONTEXT_ONLY_CLAIM_IDS": dump_compact([x["claim_id"] for x in context_only]),
        "EXCLUDED_CLAIM_IDS": dump_compact([x["claim_id"] for x in excluded if x.get("claim_id")]),
        "INDEPENDENCE_GROUP_IDS": dump_compact(sorted(independence_groups)),
        "VERSION_FAMILY_IDS": dump_compact(sorted(version_families)),
        "SOURCE_SNAPSHOT_HASH": input_hash,
        "SOURCE_MANIFEST_ITEMS": dump(sources),
        "INCLUDED_CLAIM_ITEMS": dump(included),
        "CONTEXT_ONLY_CLAIM_ITEMS": dump(context_only),
        "EXCLUDED_CLAIM_ITEMS": dump(excluded),
    }
    output = replace_all(template, values)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output.rstrip() + "\n", encoding="utf-8")
    print(target)
    print(f"sources={len(sources)} included={len(included)} context_only={len(context_only)} excluded={len(excluded)}")
    if not included:
        print("NOTICE: no Claim included; inspect candidate_verified_claim_ids and rerun with --claim after review")


if __name__ == "__main__":
    main()
