#!/usr/bin/env python3
"""Smoke-test workflow routing, admissibility, score recomputation, and provenance."""

from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_theme.py"
VALIDATE = ROOT / "scripts" / "validate_theme.py"
INIT_WORKFLOW = ROOT / "scripts" / "init_workflow_run.py"
VALIDATE_WORKFLOW = ROOT / "scripts" / "validate_workflow_run.py"
INIT_PRELIMINARY = ROOT / "scripts" / "init_preliminary_theme.py"
VALIDATE_PRELIMINARY = ROOT / "scripts" / "validate_preliminary_theme.py"

SOURCE = """---
card_schema: "evidence-card-v1.2"
card_id: "EC-TEST-001"
card_version: "1.2.0"
card_type: "source_evidence"
artifact_type: "journal_article"
workflow_status: "source_checked"
completion_level: "L2"
source_work_id: "WORK-001"
source_manifestation_id: "SRC-001"
source_version: "version-of-record"
verified_claim_ids: ["EC-TEST-001-C01"]
independence_group_ids: ["IG-001"]
version_family_ids: ["VF-001"]
reading_scope: "full_text"
---
# Test source
- 年份／发布日期：2025

~~~claim-json
{
  "claim_id": "EC-TEST-001-C01",
  "source_id": "SRC-001",
  "statement_role": "source_fact",
  "inference_type": "comparative",
  "support_status": "supported",
  "statement": "A located test statement.",
  "scope": {"object_or_denominator": "basins", "spatial": "test", "temporal": "test", "comparator": "baseline"},
  "locator": {"material": "article", "page_or_section": "Results", "table_figure_clause_or_row": "Table 1", "context": "test"},
  "directly_supports": "test comparison",
  "does_not_support": "causality",
  "independence_group_ids": ["IG-001"],
  "verification_status": "source_checked"
}
~~~
"""


def run(*args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([sys.executable, *args], text=True, capture_output=True)
    if ok and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    if not ok and result.returncode == 0:
        raise AssertionError("expected failure")
    return result


def replace_priority(theme: str, item: dict) -> str:
    start = theme.index("~~~literature-priority-json")
    body_start = theme.index("\n", start) + 1
    end = theme.index("\n~~~", body_start)
    block = json.loads(theme[body_start:end])
    block["items"] = [item]
    return theme[:body_start] + json.dumps(block, ensure_ascii=False, indent=2) + theme[end:]


def approve_preliminary(theme: str, established_ref: str) -> str:
    start = theme.index("~~~preliminary-theme-json")
    body_start = theme.index("\n", start) + 1
    end = theme.index("\n~~~", body_start)
    block = json.loads(theme[body_start:end])
    block["formation_basis"].update({
        "representative_source_refs": ["SRC-001"],
        "machine_or_manual_grouping_basis": "代表文献围绕同一测试问题形成可解释分组。",
    })
    block["scientific_focus_hypothesis"].update({
        "candidate_problem": "测试条件下的水文比较问题",
        "why_more_than_a_keyword_or_method_label": "它包含对象、关系和待解释条件。",
    })
    block["boundary_hypothesis"]["tentative_inclusion"] = ["测试对象及其比较结果"]
    block["screening_evidence"].update({
        "representative_literature_summary": "代表来源直接研究测试问题。",
        "research_question_relevance": "直接回答本轮结构验收问题。",
    })
    block["human_screening_decision"].update({
        "status": "completed",
        "decision_ref": "decision:test",
        "decision": "establish",
        "rationale": "人工确认该组材料围绕一个可持续研究问题。",
        "reviewer": "test-human",
        "reviewed_at": "2026-09-10",
        "resulting_established_theme_refs": [established_ref],
    })
    updated = theme[:body_start] + json.dumps(block, ensure_ascii=False, indent=2) + theme[end:]
    updated = updated.replace('human_screening_status: "not_started"', 'human_screening_status: "completed"', 1)
    return updated.replace('status: "draft"', 'status: "screened"', 1)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        workflow = work / "workflow.md"
        run(str(INIT_WORKFLOW), "--workflow-ref", "run:test", "--title", "测试工作流",
            "--question", "测试问题", "--intended-use", "结构验收",
            "--route", "large_corpus", "--output", str(workflow))
        run(str(VALIDATE_WORKFLOW), str(workflow), "--mode", "draft")
        incomplete = run(str(VALIDATE_WORKFLOW), str(workflow), "--mode", "final", ok=False)
        assert "completed human theme-screening gate" in incomplete.stdout
        broken_workflow = workflow.read_text(encoding="utf-8").replace(
            '"purpose": "allocate_full_text_review_across_established_themes_only"',
            '"purpose": "claim_credibility"',
        )
        workflow.write_text(broken_workflow, encoding="utf-8")
        result = run(str(VALIDATE_WORKFLOW), str(workflow), "--mode", "draft", ok=False)
        assert "WF06" in result.stdout

        preliminary = work / "preliminary-theme.md"
        run(str(INIT_PRELIMINARY), "--preliminary-theme-ref", "pt:test", "--title", "测试初步主题",
            "--discovery-route", "large_corpus", "--workflow-run-ref", "run:test", "--output", str(preliminary))
        run(str(VALIDATE_PRELIMINARY), str(preliminary), "--mode", "draft")
        blocked = run(str(BUILD), "--theme-ref", "et:test", "--title", "不应生成",
            "--preliminary-theme-file", str(preliminary), "--card", str(work / "missing-card.md"),
            "--output", str(work / "blocked-theme.md"), ok=False)
        assert "Human screening is not completed" in blocked.stdout + blocked.stderr
        preliminary.write_text(approve_preliminary(preliminary.read_text(encoding="utf-8"), "et:test"), encoding="utf-8")
        run(str(VALIDATE_PRELIMINARY), str(preliminary), "--mode", "final")

        source = work / "EC-TEST-001.md"
        theme = work / "theme.md"
        source.write_text(SOURCE, encoding="utf-8")
        run(str(BUILD), "--theme-ref", "et:test", "--title", "测试主题",
            "--question", "测试问题", "--intended-use", "结构验收",
            "--preliminary-theme-file", str(preliminary),
            "--card", str(source), "--claim", "EC-TEST-001-C01",
            "--output", str(theme))
        built = theme.read_text(encoding="utf-8")
        assert 'included_claim_ids: ["EC-TEST-001-C01"]' in built
        run(str(VALIDATE), str(theme), "--mode", "draft", "--index-root", str(work))

        legacy = work / "legacy-theme.md"
        legacy_text = built.replace('theme_schema: "hydrology-theme-v1.3"', 'theme_schema: "hydrology-theme-v1.1"')
        legacy_text = legacy_text.replace('theme_version: "1.3.0"', 'theme_version: "1.1.0"')
        legacy_text = "\n".join(
            line for line in legacy_text.splitlines()
            if not line.startswith((
                "discovery_route:", "workflow_run_refs:", "preliminary_theme_refs:",
                "preliminary_theme_snapshot_hash:", "human_screening_decision_ref:", "human_screening_status:", "theme_stage:",
            ))
        ) + "\n"
        legacy.write_text(legacy_text, encoding="utf-8")
        run(str(VALIDATE), str(legacy), "--mode", "draft", "--index-root", str(work))

        item = {
            "source_card_id": "EC-TEST-001",
            "source_manifestation_id": "SRC-001",
            "source_type": "journal_article",
            "publication_year": 2025,
            "eligible_claim_ids": ["EC-TEST-001-C01"],
            "scientific_roles": ["load_bearing_evidence", "current_frontier"],
            "load_bearing": True,
            "foundational_exception": {"applies": False, "reason": "", "basis_claim_ids": []},
            "journal_metric": {
                "status": "verified", "metric_name": "JIF", "metric_value": 9.0,
                "metric_year": 2025, "category": "Water Resources",
                "percentile_or_quartile": "95", "metric_resolution": "percentile",
                "source": "test authoritative record", "checked_at": "2026-09-07"
            },
            "components": {
                "evidence_quality_and_independence": 4,
                "question_directness": 4,
                "decisive_gap_closure": 4,
                "recency": 4,
                "verified_field_normalized_journal_signal": 4
            },
            "component_basis": {
                "evidence_quality_and_independence": "verified Claim",
                "question_directness": "test question",
                "decisive_gap_closure": "test decision",
                "recency": "2025 relative to 2026",
                "verified_field_normalized_journal_signal": "95th percentile"
            },
            "not_applicable_components": [], "unknown_components": [],
            "frontier_attention_score": 100, "provisional_min": 100,
            "provisional_max": 100, "ranking_completeness": "100%",
            "priority_tier": "P1", "priority_reason": "test", "next_action": "review"
        }
        theme.write_text(replace_priority(built, item), encoding="utf-8")
        run(str(VALIDATE), str(theme), "--mode", "draft", "--index-root", str(work))

        bad = theme.read_text(encoding="utf-8").replace('"category": "Water Resources"', '"category": ""')
        theme.write_text(bad, encoding="utf-8")
        result = run(str(VALIDATE), str(theme), "--mode", "draft", "--index-root", str(work), ok=False)
        assert "TG05" in result.stdout

    print("PASS: workflow, theme builder and validator invariants")


if __name__ == "__main__":
    main()
