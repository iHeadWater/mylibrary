"""A short focused reading is asked again, not turned into a dead end (#33).

The repair round is the difference between "this 56-page paper ended the run"
and "the model was told which 21 pages it skipped". These tests pin both halves
of that promise: the threshold never moves, and only the pages that are really
missing are asked for.

Everything runs on synthetic Markdown; no model, no PDF, no network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydrolitagent.cards import themes as core
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards.config.models import ConfigError
from hydrolitagent.cards.domain.grounding import (
    audit_reading_output,
    expected_canaries,
    markdown_sha256,
)
from hydrolitagent.cards.domain.paper import PageAnchor
from hydrolitagent.cards.domain.reading_repair import (
    FIXABLE_READING_CODES,
    MAX_REPAIR_ROUNDS,
    RepairRequest,
    repair_prompt,
    repair_request,
    retry_prompt,
)
from hydrolitagent.cards.domain.violations import Violation
from hydrolitagent.cards.theme_pool_runner import run_stage_calls
from test_config import write_config

CANARIES = ("c-00000001", "c-00000002", "c-00000003")


def _paragraphs(tag: str, count: int = 6) -> list[str]:
    return [
        f"Paragraph {index} of the {tag} section states that compound flood depth "
        f"rises with the joint probability of surge and rainfall ({tag}-{index})."
        for index in range(count)
    ]


PAGES = (
    "\n\n".join(_paragraphs("introduction")),
    "\n\n".join(_paragraphs("methods")),
    "\n\n".join(_paragraphs("results")),
)
QUOTES = tuple(page.split("\n\n")[0] for page in PAGES)


def document() -> tuple[str, tuple[PageAnchor, ...]]:
    """Three body pages, each with enough prose to count towards coverage."""

    parts: list[str] = []
    anchors: list[PageAnchor] = []
    offset = 0
    for number, content in enumerate(PAGES, start=1):
        canary = CANARIES[number - 1]
        header = f"<!-- page: {number} -->\n<!-- reading-canary: {canary} -->\n"
        parts.append(header)
        offset += len(header)
        start = offset
        parts.append(content)
        offset += len(content)
        anchors.append(
            PageAnchor(
                page=number,
                char_start=start,
                char_end=start + len(content),
                heading=None,
                role="body",
                canary=canary,
            )
        )
        parts.append("\n")
        offset += 1
    return "".join(parts), tuple(anchors)


def answer(markdown: str, pages: tuple[int, ...]) -> dict:
    """One reading answer in the wire shape the schema defines."""

    return {
        "reading_receipt": {
            "markdown_sha256": markdown_sha256(markdown),
            "read_mode": "file",
            "model_claimed_status": "FULL_MARKDOWN_REVIEWED",
            "model_claimed_pages": [1, 2, 3],
            "canaries_seen": list(expected_canaries(markdown)),
            "self_report": "fixture",
        },
        "source_locations": [
            {
                "anchor": f"P{page}",
                "quote": QUOTES[page - 1],
                "pdf_page": page,
                "section": None,
                "figure": None,
                "table": None,
            }
            for page in pages
        ],
    }


def audit(markdown: str, anchors, output: dict):
    return audit_reading_output(output, markdown, anchors)


# --------------------------------------------------------------------------------------
# what counts as repairable
# --------------------------------------------------------------------------------------


def test_a_reading_that_covered_one_page_of_three_asks_for_the_other_two() -> None:
    markdown, anchors = document()
    result = audit(markdown, anchors, answer(markdown, (1,)))

    assert result.reading is not None and not result.reading.verified
    request = repair_request(result)
    assert request is not None
    assert request.violations == ()
    assert request.missing_pages == (2, 3)


def test_a_verified_reading_has_nothing_left_to_ask() -> None:
    markdown, anchors = document()
    result = audit(markdown, anchors, answer(markdown, (1, 2, 3)))

    assert result.reading is not None and result.reading.verified
    assert repair_request(result) is None


def test_a_violation_the_model_cannot_fix_is_not_asked_again() -> None:
    markdown, anchors = document()
    good = answer(markdown, (1, 2, 3))
    broken = {**good, "reading_receipt": {**good["reading_receipt"], "markdown_sha256": "0" * 64}}
    result = audit(markdown, anchors, broken)

    assert [item.code for item in result.violations] == ["MARKDOWN_SHA_MISMATCH"]
    assert "MARKDOWN_SHA_MISMATCH" not in FIXABLE_READING_CODES
    assert repair_request(result) is None


def test_an_invented_identifier_is_repairable_but_a_changed_input_is_not() -> None:
    fixable = SimpleNamespace(
        violations=(Violation("CARD_SENTENCE_ID_UNKNOWN", "source_locations[0]", "编号不存在"),),
        reading=None,
        coverage=None,
    )
    assert repair_request(fixable) is not None

    unfixable = SimpleNamespace(
        violations=(Violation("MARKDOWN_SHA_MISMATCH", "reading_receipt", "摘要不符"),),
        reading=None,
        coverage=None,
    )
    assert repair_request(unfixable) is None


# --------------------------------------------------------------------------------------
# the prompt a repair round sends
# --------------------------------------------------------------------------------------


def test_repair_prompt_states_the_gap_and_that_the_bar_does_not_move() -> None:
    markdown, anchors = document()
    result = audit(markdown, anchors, answer(markdown, (1,)))
    request = repair_request(result)
    assert request is not None

    prompt = repair_prompt(
        "## 任务\n按问题精读整篇论文。",
        answer(markdown, (1,)),
        request,
        round_number=1,
        max_rounds=3,
    )

    assert "第 1/3 次修正" in prompt
    assert "尚未覆盖的页面" in prompt
    assert "2, 3" in prompt
    assert "已覆盖 1 页，需要 3 页" in prompt
    assert "不会因为这次修正而降低" in prompt
    # The previous answer travels with the question, so the model edits rather
    # than starts over.
    assert "P1" in prompt


def test_repair_prompt_lists_violations_with_what_to_change() -> None:
    request = RepairRequest(
        violations=(
            {"code": "QUOTE_NOT_FOUND", "path": "source_locations[0]", "message": "引文不在原文"},
        ),
    )
    prompt = repair_prompt("任务", {"source_locations": []}, request,
                           round_number=2, max_rounds=3)

    assert "[QUOTE_NOT_FOUND] source_locations[0]" in prompt
    assert "修复要点" in prompt
    assert "第 2/3 次修正" in prompt


def test_retry_prompt_says_the_task_did_not_change() -> None:
    prompt = retry_prompt("任务", "RUNNER_OUTPUT_INVALID", "输出被截断")

    assert "RUNNER_OUTPUT_INVALID" in prompt
    assert "不是新任务" in prompt


# --------------------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------------------


def _stage(markdown, anchors, answers, *, max_repairs):
    prompts: list[str] = []

    def invoke(prompt: str) -> dict:
        prompts.append(prompt)
        item = answers[len(prompts) - 1]
        if isinstance(item, Exception):
            raise item
        return {"output": item}

    payload, result = run_stage_calls(
        stage="定向精读",
        base_prompt="## 任务\n按问题精读整篇论文。",
        invoke=invoke,
        examine=lambda item: audit(markdown, anchors, item["output"]),
        max_repairs=max_repairs,
    )
    return payload, result, prompts


def test_a_short_reading_is_sent_back_and_then_accepted() -> None:
    markdown, anchors = document()
    payload, result, prompts = _stage(
        markdown, anchors, [answer(markdown, (1,)), answer(markdown, (1, 2, 3))],
        max_repairs=2,
    )

    assert len(prompts) == 2
    assert "尚未覆盖的页面" in prompts[1]
    assert result.reading is not None and result.reading.verified
    assert payload["output"]["source_locations"]


def test_a_reading_that_never_covers_the_paper_stops_after_the_budget() -> None:
    markdown, anchors = document()
    short = answer(markdown, (1,))
    prompts: list[str] = []

    def invoke(prompt: str) -> dict:
        prompts.append(prompt)
        return {"output": short}

    with pytest.raises(core.ThemeError) as error:
        run_stage_calls(
            stage="定向精读", base_prompt="任务", invoke=invoke,
            examine=lambda item: audit(markdown, anchors, item["output"]),
            max_repairs=2,
        )

    assert error.value.code == "THEME_READING_NOT_VERIFIED"
    assert error.value.details["coverage"]["missing_pages"] == [2, 3]
    # One first answer plus exactly the two repair rounds it was allowed.
    assert len(prompts) == 3


def test_zero_repairs_means_one_attempt() -> None:
    markdown, anchors = document()
    short = answer(markdown, (1,))
    with pytest.raises(core.ThemeError):
        _stage(markdown, anchors, [short, short], max_repairs=0)


def test_a_call_that_answered_nothing_is_retried_without_spending_a_repair() -> None:
    markdown, anchors = document()
    payload, result, prompts = _stage(
        markdown, anchors,
        [core.ThemeError("RUNNER_OUTPUT_INVALID", "输出被截断"), answer(markdown, (1, 2, 3))],
        max_repairs=0,   # no repair budget at all: the retry still happens
    )

    assert len(prompts) == 2
    assert "RUNNER_OUTPUT_INVALID" in prompts[1]
    assert result.reading is not None and result.reading.verified


def test_a_transport_failure_is_not_retried_forever() -> None:
    markdown, anchors = document()
    failure = core.ThemeError("RUNNER_OUTPUT_INVALID", "输出被截断")
    with pytest.raises(core.ThemeError) as error:
        _stage(markdown, anchors, [failure, failure, failure, failure], max_repairs=0)

    assert error.value.code == "RUNNER_OUTPUT_INVALID"


def test_an_unfixable_answer_is_reported_on_the_first_call() -> None:
    markdown, anchors = document()
    good = answer(markdown, (1, 2, 3))
    broken = {**good, "reading_receipt": {**good["reading_receipt"], "markdown_sha256": "0" * 64}}
    prompts: list[str] = []

    def invoke(prompt: str) -> dict:
        prompts.append(prompt)
        return {"output": broken}

    with pytest.raises(core.ThemeError) as error:
        run_stage_calls(
            stage="定向精读", base_prompt="任务", invoke=invoke,
            examine=lambda item: audit(markdown, anchors, item["output"]),
            max_repairs=3,
        )

    assert error.value.code == "MARKDOWN_SHA_MISMATCH"
    assert len(prompts) == 1


def test_a_synthesis_stage_only_retries_it_never_repairs() -> None:
    prompts: list[str] = []

    def invoke(prompt: str) -> dict:
        prompts.append(prompt)
        return {"output": {"any": "answer"}}

    payload, result = run_stage_calls(
        stage="主题回填", base_prompt="任务", invoke=invoke, examine=None, max_repairs=3,
    )

    assert payload["output"] == {"any": "answer"}
    assert result is None
    assert len(prompts) == 1


# --------------------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 1, MAX_REPAIR_ROUNDS])
def test_max_repairs_accepts_the_documented_range(tmp_path: Path, value: int) -> None:
    path = write_config(tmp_path, overrides={"theme_pipeline": {"enabled": True, "max_repairs": value}})
    assert load_config(path).theme_pipeline.max_repairs == value


@pytest.mark.parametrize("value", [-1, MAX_REPAIR_ROUNDS + 1, 2.5, "3"])
def test_max_repairs_rejects_anything_else(tmp_path: Path, value) -> None:
    path = write_config(tmp_path, overrides={"theme_pipeline": {"enabled": True, "max_repairs": value}})
    with pytest.raises(ConfigError):
        load_config(path)


def test_max_repairs_defaults_to_three_rounds(tmp_path: Path) -> None:
    path = write_config(tmp_path, overrides={"theme_pipeline": {"enabled": True}})
    assert load_config(path).theme_pipeline.max_repairs == 3
