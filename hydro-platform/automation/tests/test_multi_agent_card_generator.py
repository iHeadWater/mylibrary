from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.card_generators.multi_agent import MultiAgentCardGeneratorAdapter
from hydro_platform.config import (
    REQUIRED_CARD_WORKFLOW_ROLES,
    CardQualityWorkflowConfig,
    CardWorkflowRoleConfig,
)


PAGE_COUNT = 12


def evidence(page: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "page": page,
            "locator": f"第{page}页结果段",
            "evidence_text": "论文报告了可核对的事实。",
            "visual": False,
        }
    ]


def common(schema_version: int = 1) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "source_read_status": "FULL_PDF_REVIEWED",
        "source_page_count": PAGE_COUNT,
        "visual_content_status": "REVIEWED",
        "source_read_evidence": "共12页，已检查正文、末页和图表。",
    }


def fact_output(label: str) -> dict[str, Any]:
    return {
        **common(),
        "paper_type": "original-research",
        "facts": [
            {
                "fact_id": "F001",
                "category": "research_question",
                "statement": f"{label}：研究短历时降雨变化。",
                "interpretation_level": "DIRECT",
                "confidence": 0.95,
                "evidence": evidence(2),
            },
            {
                "fact_id": "F002",
                "category": "result",
                "statement": f"{label}：观测结果显示极端增强。",
                "interpretation_level": "SYNTHESIZED",
                "confidence": 0.9,
                "evidence": evidence(7),
            },
        ],
        "coverage": [
            {
                "section": "全文",
                "page_start": 1,
                "page_end": PAGE_COUNT,
                "summary": "已覆盖全文。",
            }
        ],
        "key_visuals": [
            {
                "label": "图1",
                "page": 7,
                "role": "RESULT",
                "finding": "显示主要结果。",
            }
        ],
    }


def adjudication_output() -> dict[str, Any]:
    return {
        **common(),
        "template_id": "original-research",
        "classification_confidence": 0.99,
        "classification_reason": "报告原创数据、方法与结果。",
        "verified_facts": [
            {
                "fact_id": "VF001",
                "category": "research_question",
                "statement": "研究短历时降雨变化。",
                "source_fact_ids": ["A:F001", "B:F001"],
                "resolution_basis": "AGREEMENT",
                "support_status": "SUPPORTED",
                "confidence": 0.98,
                "evidence": evidence(2),
            },
            {
                "fact_id": "VF002",
                "category": "result",
                "statement": "观测结果显示极端增强。",
                "source_fact_ids": ["A:F002", "B:F002"],
                "resolution_basis": "AGREEMENT",
                "support_status": "SUPPORTED",
                "confidence": 0.95,
                "evidence": evidence(7),
            },
        ],
        "disagreements": [],
        "coverage_gaps": [],
    }


def critical_output() -> dict[str, Any]:
    return {
        **common(),
        "analyses": [
            {
                "analysis_id": "CA001",
                "analysis_type": "external_validity",
                "statement": "结论的外推范围受研究限制。",
                "premise_fact_ids": ["VF001", "VF002"],
                "reasoning": "研究范围有限，因此不能自动推广到全部区域。",
                "scope": "论文研究区域之外",
                "severity": "MEDIUM",
                "confidence": 0.85,
                "evidence": evidence(10),
            }
        ],
        "overall_assessment": "证据支持主要结论，但存在外推边界。",
    }


def synthesis_output() -> dict[str, Any]:
    return {
        **common(schema_version=2),
        "template_id": "original-research",
        "classification_confidence": 0.99,
        "classification_reason": "事实裁决确定为原创研究。",
        "card_body_markdown": "# 原创研究证据卡：测试\n",
    }


def review_output(*, verdict: str = "PASS") -> dict[str, Any]:
    status = "SUPPORTED" if verdict == "PASS" else "UNSUPPORTED"
    return {
        **common(),
        "challenge_checks": [
            {
                "challenge_id": f"CH{index:03d}",
                "challenge_type": challenge_type,
                "target": f"卡片检查项{index}",
                "status": status,
                "severity": "HIGH",
                "reason": "已根据原文核对。",
                "evidence": evidence(7),
            }
            for index, challenge_type in enumerate(
                (
                    "factual_support",
                    "numerical_accuracy",
                    "causal_language",
                    "author_agent_boundary",
                    "visual_interpretation",
                ),
                start=1,
            )
        ],
        "coverage_checks": [
            {"area": area, "status": "COVERED", "reason": "已覆盖"}
            for area in (
                "research_question",
                "data",
                "method",
                "results",
                "visuals",
                "limitations",
                "negative_results",
            )
        ],
        "issues": [],
        "verdict": verdict,
        "verdict_reason": "通过" if verdict == "PASS" else "存在无证据结论",
    }


class FakeProvider:
    def __init__(self, outputs: dict[str, dict[str, Any]]):
        self.outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def preflight(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "adapter": "fake",
        }

    def smoke_test(self) -> dict[str, Any]:
        return {"schema_version": 1, "ok": True}

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        run_label = kwargs["run_label"]
        self.calls.append({"prompt": prompt, **kwargs})
        return {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "adapter": "fake",
            "cli_version": "fake-1",
            "configured_model": kwargs.get("model"),
            "configured_reasoning_effort": kwargs.get("reasoning_effort"),
            "ephemeral": True,
            "source_access": {
                "verified": True,
                "method": "bound_local_pdf_mcp",
                "server_name": "hydro_pdf_reader",
                "receipt_schema_version": 1,
                "page_count": PAGE_COUNT,
                "pages_served": PAGE_COUNT,
                "visual_pages_served": PAGE_COUNT,
            },
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": deepcopy(self.outputs[run_label]),
        }


class WorkflowFixture:
    def __init__(self, root: Path):
        self.root = root
        self.prompt_dir = root / "prompts"
        self.schema_dir = root / "schemas"
        self.prompt_dir.mkdir()
        self.schema_dir.mkdir()
        self.prompts: dict[str, Path] = {}
        self.schemas: dict[str, Path] = {}
        for name in (
            "fact_extraction",
            "fact_adjudication",
            "critical_analysis",
            "adversarial_review",
        ):
            prompt = self.prompt_dir / f"{name}.md"
            prompt.write_text(
                f'---\nprompt_version: "{name}-v1"\n---\n\n{name}\n',
                encoding="utf-8",
            )
            schema = self.schema_dir / f"{name}.json"
            schema.write_text('{"type":"object"}', encoding="utf-8")
            self.prompts[name] = prompt
            self.schemas[name] = schema
        self.synthesis_schema = self.schema_dir / "synthesis.json"
        self.synthesis_schema.write_text('{"type":"object"}', encoding="utf-8")
        self.pdf = root / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\nfixture")
        roles = {
            name: CardWorkflowRoleConfig(
                model=f"model-{name}",
                reasoning_effort="high",
                timeout_seconds=321,
            )
            for name in REQUIRED_CARD_WORKFLOW_ROLES
        }
        self.config = CardQualityWorkflowConfig(
            protocol_version="rough-card-multi-agent-v1",
            fact_extraction_prompt_file=self.prompts["fact_extraction"],
            fact_adjudication_prompt_file=self.prompts["fact_adjudication"],
            critical_analysis_prompt_file=self.prompts["critical_analysis"],
            adversarial_review_prompt_file=self.prompts["adversarial_review"],
            fact_extraction_schema_file=self.schemas["fact_extraction"],
            fact_adjudication_schema_file=self.schemas["fact_adjudication"],
            critical_analysis_schema_file=self.schemas["critical_analysis"],
            adversarial_review_schema_file=self.schemas["adversarial_review"],
            minimum_verified_facts=2,
            minimum_critical_analyses=1,
            minimum_adversarial_challenges=5,
            maximum_unresolved_high_severity=0,
            roles=roles,
        )

    def outputs(self) -> dict[str, dict[str, Any]]:
        return {
            "fact_extractor_a": fact_output("A"),
            "fact_extractor_b": fact_output("B"),
            "fact_adjudicator": adjudication_output(),
            "critical_analyst": critical_output(),
            "card_synthesizer": synthesis_output(),
            "adversarial_reviewer": review_output(),
        }

    def run(self, provider: FakeProvider, *, progress=None) -> dict[str, Any]:
        adapter = MultiAgentCardGeneratorAdapter(provider, self.config, progress=progress)
        synthesis_prompt = (
            "synthesis\n"
            '<evidence-card-template id="original-research">\n'
            "# template\n"
            "</evidence-card-template>\n"
        )
        return adapter.generate(
            synthesis_prompt,
            working_directory=self.root,
            source_pdf_path=self.pdf,
            zotero_parent_key="ABCD1234",
            output_schema_path=self.synthesis_schema,
        )


class MultiAgentCardGeneratorTests(unittest.TestCase):
    def test_runs_all_required_roles_and_returns_validated_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            provider = FakeProvider(fixture.outputs())

            result = fixture.run(provider)

        self.assertTrue(result["ok"])
        self.assertEqual(
            [call["run_label"] for call in provider.calls],
            list(REQUIRED_CARD_WORKFLOW_ROLES),
        )
        self.assertEqual(result["workflow"]["status"], "VALIDATED")
        self.assertTrue(result["workflow"]["gates"]["fail_closed"])
        self.assertEqual(result["quality_audit"]["quality_report"], result["workflow"])
        self.assertEqual(result["usage"]["input_tokens"], 600)

    def test_second_extractor_does_not_receive_first_extractor_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            provider = FakeProvider(fixture.outputs())

            fixture.run(provider)

        second_prompt = provider.calls[1]["prompt"]
        self.assertNotIn("A：研究短历时降雨变化", second_prompt)
        self.assertIn('"extractor": "B"', second_prompt)

    def test_internal_ids_need_not_use_zero_padded_display_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            outputs = fixture.outputs()
            outputs["fact_extractor_a"]["facts"][0]["fact_id"] = "FACT-A-1"
            outputs["fact_extractor_a"]["facts"][1]["fact_id"] = "F2"
            outputs["fact_extractor_b"]["facts"][0]["fact_id"] = "fact_b_1"
            outputs["fact_extractor_b"]["facts"][1]["fact_id"] = "fact_b_2"
            verified = outputs["fact_adjudicator"]["verified_facts"]
            verified[0]["fact_id"] = "VERIFIED-1"
            verified[0]["source_fact_ids"] = ["a: FACT-A-1", "B:fact_b_1"]
            verified[1]["fact_id"] = "VF2"
            verified[1]["source_fact_ids"] = ["A:F2", "b:fact_b_2"]
            analyses = outputs["critical_analyst"]["analyses"]
            analyses[0]["analysis_id"] = "ANALYSIS-1"
            analyses[0]["premise_fact_ids"] = [" VERIFIED-1 ", "VF2"]
            provider = FakeProvider(outputs)

            result = fixture.run(provider)

        self.assertTrue(result["ok"])
        adjudicated = result["quality_audit"]["roles"]["fact_adjudicator"]["output"]
        self.assertEqual(
            adjudicated["verified_facts"][0]["source_fact_ids"],
            ["A:FACT-A-1", "B:fact_b_1"],
        )

    def test_passes_per_role_model_reasoning_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            provider = FakeProvider(fixture.outputs())

            fixture.run(provider)

        for call in provider.calls:
            role = call["run_label"]
            self.assertEqual(call["model"], f"model-{role}")
            self.assertEqual(call["reasoning_effort"], "high")
            self.assertEqual(call["timeout_seconds"], 321)

    def test_unresolved_high_severity_disagreement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            outputs = fixture.outputs()
            outputs["fact_adjudicator"]["disagreements"] = [
                {
                    "disagreement_id": "D001",
                    "severity": "HIGH",
                    "description": "主要结论不一致",
                    "extractor_a_fact_ids": ["F002"],
                    "extractor_b_fact_ids": ["F002"],
                    "resolution_status": "UNRESOLVED",
                    "resolution": "无法裁决",
                    "evidence": evidence(7),
                }
            ]
            provider = FakeProvider(outputs)

            result = fixture.run(provider)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CARD_QUALITY_CONTRACT_FAILED")
        self.assertEqual(len(provider.calls), 3)

    def test_out_of_range_evidence_page_fails_before_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            outputs = fixture.outputs()
            outputs["fact_extractor_a"]["facts"][0]["evidence"] = evidence(99)
            provider = FakeProvider(outputs)

            result = fixture.run(provider)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CARD_QUALITY_CONTRACT_FAILED")
        self.assertEqual(len(provider.calls), 1)

    def test_adversarial_failure_never_returns_candidate_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            outputs = fixture.outputs()
            outputs["adversarial_reviewer"] = review_output(verdict="FAIL")
            provider = FakeProvider(outputs)

            result = fixture.run(provider)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CARD_QUALITY_FAILED")
        self.assertNotIn("output", result)
        self.assertEqual(len(provider.calls), 6)

    def test_preflight_rejects_missing_workflow_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkflowFixture(Path(directory))
            fixture.prompts["fact_extraction"].unlink()
            provider = FakeProvider(fixture.outputs())
            adapter = MultiAgentCardGeneratorAdapter(provider, fixture.config)

            result = adapter.preflight()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"]["code"],
            "MULTI_AGENT_WORKFLOW_CONFIG_INVALID",
        )


if __name__ == "__main__":
    unittest.main()
