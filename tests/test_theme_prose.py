"""A theme page is read by a person: the shape of the prose is checked (#33).

Grounding already guarantees the numbers are traceable. These rules cover the
other failure mode: a page that is complete and unreadable -- workflow
vocabulary in the prose, a document that opens with revision bookkeeping, and
paragraphs cut in half by five parenthetical years.

The rejection is fed back through the same repair loop a focused reading uses,
so a bad shape costs one round, not the whole run.
"""

from __future__ import annotations

import pytest

from hydrolitagent.cards import themes as core
from hydrolitagent.cards.domain import theme_prose
from hydrolitagent.cards.theme_pool_runner import run_stage_calls

LEAD = (
    "2018 年飓风 Michael 过后，报告说 165 万人断电，模型算出 122 万。两个数差得不算离谱，"
    "但方向说明从设施坏了到人没了电中间还有好几层。这两篇文献正好在这一点上给出相反的证据，"
    "所以现在只能给出条件性结论。"
)
AUDIT = (
    "与初版相比：保留“尾部增益”这一判断，收窄了归因部分。\n\n"
    "- 原文陈述：DRUM 在 72.3% 流域优于 LSTM-p。\n"
    "- AI 推理：两篇的差异可能来自评价分层方式。\n"
    "- 不能确定：增益在超训练范围事件上是否稳定。"
)
BODY = (
    LEAD + "\n\n"
    "## 尾部增益从哪里来\n\n"
    "Ou 等（2025）报告 CRPS 改善随流量量级上升，但也承认输入降水替换后增益明显缩水，"
    "所以生成机制不是唯一来源。\n\n"
    "## 现在能下的结论\n\n"
    "可以确认尾部增益存在，不能确认它由生成机制独占。"
)


def codes(audit) -> list[str]:
    return [violation.code for violation in audit.violations]


def test_a_page_whose_entry_uses_jargon_is_rejected() -> None:
    body = "跨系统级联的归因分解是本文重点。" + BODY
    audit = theme_prose.review({"revised_markdown": body, "audit_markdown": AUDIT})

    assert "THEME_PROSE_LEAD_JARGON" in codes(audit)


def test_a_page_whose_entry_has_no_example_is_rejected() -> None:
    body = (
        "灾害与设施之间的关系值得讨论。\n\n"
        "## 分节\n\n"
        "Ou 等（2025）报告 CRPS 改善，72.3% 的流域优于对照。"
    )
    audit = theme_prose.review({"revised_markdown": body, "audit_markdown": AUDIT})

    assert "THEME_PROSE_LEAD_NO_EXAMPLE" in codes(audit)


def test_a_page_that_buries_the_entry_is_rejected() -> None:
    body = "这件事需要从很多方面说起。" * 80 + BODY
    audit = theme_prose.review({"revised_markdown": body, "audit_markdown": AUDIT})

    assert "THEME_PROSE_LEAD_TOO_LONG" in codes(audit)


def test_a_title_that_reads_like_a_paper_subtitle_is_rejected():
    output = {
        "actions": [{
            "kind": "CREATE", "theme_ids": [], "reason": "x",
            "themes": [{
                "title": "灾害下的服务中断：机制分解、空间越界与跨灾种比较",
                "candidate_markdown": "服务中断有多少越出受灾范围？这是本主题要回答的问题。",
                "paper_tasks": [],
            }],
        }],
    }
    audit = theme_prose.review_candidate(output)

    assert "THEME_TITLE_NOT_HUMAN" in codes(audit)


def test_a_candidate_that_names_a_field_instead_of_a_question_is_rejected():
    output = {
        "actions": [{
            "kind": "CREATE", "theme_ids": [], "reason": "x",
            "themes": [{
                "title": "基础设施级联风险",
                "candidate_markdown": "本主题讨论基础设施之间的相互依赖及其后果。",
                "paper_tasks": [],
            }],
        }],
    }
    audit = theme_prose.review_candidate(output)

    assert "THEME_QUESTION_MISSING" in codes(audit)


def test_a_question_shaped_candidate_passes() -> None:
    output = {
        "actions": [{
            "kind": "CREATE", "theme_ids": [], "reason": "x",
            "themes": [{
                "title": "服务中断有多少越出受灾范围",
                "candidate_markdown": "服务中断有多少越出受灾范围？现有材料给出的答案是……",
                "paper_tasks": [],
            }],
        }],
    }

    assert theme_prose.review_candidate(output).violations == ()


def test_a_readable_page_passes() -> None:
    audit = theme_prose.review({"revised_markdown": BODY, "audit_markdown": AUDIT})
    assert codes(audit) == []


def test_workflow_vocabulary_in_the_prose_is_rejected() -> None:
    body = BODY.replace("## 现在能下的结论", "## 逐项关联 evidence_id")
    audit = theme_prose.review({"revised_markdown": body, "audit_markdown": AUDIT})

    assert "THEME_PROSE_MACHINE_TOKEN" in codes(audit)


def test_evidence_ids_in_the_prose_are_rejected() -> None:
    body = BODY.replace("Ou 等（2025）", "EV-5TVGFJZ4")
    audit = theme_prose.review({"revised_markdown": body, "audit_markdown": AUDIT})

    assert "THEME_PROSE_MACHINE_TOKEN" in codes(audit)


def test_a_fourth_level_heading_is_rejected() -> None:
    body = BODY.replace("## 现在能下的结论", "#### 现在能下的结论")
    audit = theme_prose.review({"revised_markdown": body, "audit_markdown": AUDIT})

    assert "THEME_PROSE_HEADING_DEPTH" in codes(audit)


def test_a_page_that_opens_with_bookkeeping_is_rejected() -> None:
    body = "**修订名称**：某候选（v2）。\n\n" + BODY
    audit = theme_prose.review({"revised_markdown": body, "audit_markdown": AUDIT})

    assert "THEME_PROSE_NO_SUMMARY" in codes(audit)


def test_four_parenthetical_years_in_one_paragraph_are_rejected() -> None:
    dense = (
        "## 分歧\n\n"
        "甲（2021）报告了这一点，乙（2022）报告了另一点，丙（2023）不同意，"
        "丁（2024）给出了折中的说法，因此目前没有共识。\n"
    )
    audit = theme_prose.review({"revised_markdown": LEAD + "\n\n" + dense,
                                "audit_markdown": AUDIT})

    assert "THEME_PROSE_CITATION_DENSE" in codes(audit)


def test_an_empty_audit_record_is_rejected() -> None:
    audit = theme_prose.review({"revised_markdown": BODY, "audit_markdown": "  "})

    assert "THEME_PROSE_MISSING_AUDIT" in codes(audit)


def test_a_missing_body_is_rejected() -> None:
    audit = theme_prose.review({"audit_markdown": AUDIT})

    assert "THEME_PROSE_MISSING" in codes(audit)


def test_the_page_is_asked_again_with_the_named_problem() -> None:
    """The refinement answer goes through the same repair loop as a reading."""

    prompts: list[str] = []
    answers = [
        {"revised_markdown": "**修订名称**：某候选。", "audit_markdown": AUDIT},
        {"revised_markdown": BODY, "audit_markdown": AUDIT},
    ]

    def invoke(prompt: str) -> dict:
        prompts.append(prompt)
        return {"output": answers[len(prompts) - 1]}

    payload, audit = run_stage_calls(
        stage="主题回填",
        base_prompt="## 任务\n把候选主题改写成文章。",
        invoke=invoke,
        examine=lambda item: theme_prose.review(item["output"]),
        max_repairs=2,
        subject="主题正文",
    )

    assert len(prompts) == 2
    assert "THEME_PROSE_NO_SUMMARY" in prompts[1]
    assert "上一次的主题正文被拒绝" in prompts[1]
    assert payload["output"]["revised_markdown"] == BODY
    assert audit.violations == ()


def test_an_unreadable_page_that_never_improves_stops_after_the_budget() -> None:
    bad = {"revised_markdown": "**修订名称**：某候选。", "audit_markdown": AUDIT}
    prompts: list[str] = []

    def invoke(prompt: str) -> dict:
        prompts.append(prompt)
        return {"output": bad}

    with pytest.raises(core.ThemeError) as error:
        run_stage_calls(
            stage="主题回填", base_prompt="任务", invoke=invoke,
            examine=lambda item: theme_prose.review(item["output"]),
            max_repairs=1, subject="主题正文",
        )

    assert error.value.code == "THEME_PROSE_NO_SUMMARY"
    assert len(prompts) == 2
