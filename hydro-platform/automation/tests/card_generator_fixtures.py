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
