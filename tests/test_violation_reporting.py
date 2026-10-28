"""Every gate reports the whole list, with a path per problem.

These tests pin the *reporting* contract, not the rules: a repair step can only
fix what it is told about, so "字段与制卡协议不一致" with no field name is a bug
even when the rejection itself is correct.
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from hydrolitagent.cards.application import card_draft
from hydrolitagent.cards.application.card_draft import (
    check_wire,
    collect_wire_violations,
    describe_wire_contract,
)
from hydrolitagent.cards.domain.card_output import (
    OUTPUT_SCHEMA_VERSION,
    collect_model_output_violations,
    validate_model_output_fields,
)
from hydrolitagent.cards.domain.errors import CardGenerationError
from card_fixtures import machine_fields

TEMPLATES = {"original-research": {}}
REQUIRED_FIELDS = [
    "card_body_markdown",
    "schema_version",
    "source_page_count",
    "source_read_evidence",
    "source_read_status",
    "template_id",
    "visual_content_status",
]


def _answer(**overrides):
    answer = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "source_read_status": "FULL_PDF_REVIEWED",
        "source_page_count": 3,
        "visual_content_status": "NOT_PRESENT",
        "source_read_evidence": "通读第 1-3 页，含图 1 与表 1",
        "template_id": "original-research",
        "card_body_markdown": "# 卡片\n\n正文。\n",
    }
    answer.update(overrides)
    return answer


def _schema():
    return json.loads(card_draft.SCHEMA.read_text(encoding="utf-8"))["properties"][
        "machine_fields"
    ]


# --------------------------------------------------------------------------------------
# the model answer's own fields
# --------------------------------------------------------------------------------------


def test_a_complete_answer_has_no_violations():
    assert collect_model_output_violations(_answer(), TEMPLATES) == []


def test_every_missing_field_is_named_not_just_the_first():
    violations = collect_model_output_violations({}, TEMPLATES)

    assert [violation.path for violation in violations] == REQUIRED_FIELDS
    assert {violation.code for violation in violations} == {"CARD_GENERATION_OUTPUT_INVALID"}


def test_missing_schema_version_is_reported_by_name():
    answer = _answer()
    answer.pop("schema_version")

    violations = collect_model_output_violations(answer, TEMPLATES)

    assert [violation.path for violation in violations] == ["schema_version"]
    assert violations[0].actual == "未提供"


def test_several_shape_problems_are_reported_together():
    answer = _answer(
        source_read_status="READ",
        template_id="no-such-template",
    )
    answer.pop("card_body_markdown")
    answer["schema_version"] = 1

    violations = collect_model_output_violations(answer, TEMPLATES)
    codes = [violation.code for violation in violations]

    assert len(violations) == 4  # not one round per problem
    assert "CARD_PDF_READ_UNVERIFIED" in codes
    assert "CARD_GENERATION_TEMPLATE_INVALID" in codes
    assert [v.path for v in violations].count("schema_version") == 1


def test_the_raised_error_carries_the_whole_list():
    answer = _answer(source_read_status="READ", schema_version=1)

    with pytest.raises(CardGenerationError) as caught:
        validate_model_output_fields(answer, TEMPLATES)

    assert caught.value.code == "CARD_GENERATION_OUTPUT_INVALID"
    reported = caught.value.diagnostic["violations"]
    assert [item["path"] for item in reported] == ["schema_version", "source_read_status"]
    assert reported[0]["expected"] == str(OUTPUT_SCHEMA_VERSION)
    assert reported[0]["actual"] == "数值 1"


def test_a_single_problem_keeps_its_own_wording():
    with pytest.raises(CardGenerationError) as caught:
        validate_model_output_fields(_answer(source_read_status="READ"), TEMPLATES)

    assert str(caught.value) == "模型未确认已经检查完整原始文献，拒绝写入证据卡"
    assert caught.value.code == "CARD_PDF_READ_UNVERIFIED"


# --------------------------------------------------------------------------------------
# the machine-field wire
# --------------------------------------------------------------------------------------


def test_wire_names_the_missing_key():
    fields = machine_fields()
    fields.pop("comparison_baselines")

    violations = collect_wire_violations(fields, _schema())

    assert [violation.path for violation in violations] == [
        "machine_fields.comparison_baselines"
    ]
    assert violations[0].message == "机器字段缺少该键"


def test_wire_reports_every_broken_item_with_an_index():
    fields = machine_fields()
    fields["findings"] = [deepcopy(fields["findings"][0]) for _ in range(3)]
    fields["findings"][0]["finding_id"] = None  # present but not a string
    fields["findings"][2]["source_locations"][0]["pdf_page"] = True

    paths = [violation.path for violation in collect_wire_violations(fields, _schema())]

    assert "machine_fields.findings[0].finding_id" in paths
    assert "machine_fields.findings[2].source_locations[0].pdf_page" in paths


def test_wire_names_a_key_that_belongs_somewhere_else():
    # ``finding_id`` is a real protocol key, but only inside a finding. Putting it
    # at the top level is an "extra key" and must be named as such -- without the
    # test inventing a key the schema never heard of.
    fields = machine_fields()
    fields["finding_id"] = "F001"

    violations = collect_wire_violations(fields, _schema())

    assert [violation.path for violation in violations] == ["machine_fields.finding_id"]
    assert violations[0].message == "机器字段多出协议外的键"


def test_wire_error_carries_the_full_key_contract():
    fields = machine_fields()
    fields.pop("data_and_methods")

    with pytest.raises(CardGenerationError) as caught:
        check_wire(fields, _schema())

    assert caught.value.code == "CARD_DRAFT_OUTPUT_INVALID"
    assert caught.value.diagnostic["violations"][0]["path"] == (
        "machine_fields.data_and_methods"
    )
    contract = caught.value.diagnostic["machine_fields_contract"]
    assert len(contract) == 8
    assert contract["findings"]["type"] == "array"
    assert contract["findings"]["item_type"] == "object"
    assert "finding_id" in contract["findings"]["item_keys"]
    assert "finding_id" not in contract["research_questions"]["item_keys"]
    # One level deeper: the machine-field ``source_locations`` allows only these
    # four keys, which is exactly the mistake a real run kept making.
    assert sorted(contract["findings"]["item_arrays"]["source_locations"]) == [
        "figure",
        "pdf_page",
        "section",
        "table",
    ]


def test_contract_lists_the_keys_without_needing_a_broken_answer():
    contract = describe_wire_contract(_schema())

    assert sorted(contract) == [
        "boundaries",
        "comparison_baselines",
        "data_and_methods",
        "findings",
        "missing_information",
        "research_questions",
        "schema_version",
        "study_objects_and_scales",
    ]


def test_a_valid_wire_still_passes():
    check_wire(machine_fields(), _schema())
    assert collect_wire_violations(machine_fields(), _schema()) == []
    assert collect_wire_violations(deepcopy(machine_fields()), _schema()) == []


# --------------------------------------------------------------------------------------
# what a human sees
# --------------------------------------------------------------------------------------


def test_readable_failure_lists_one_line_per_problem():
    from hydrolitagent.cards.cli import _render_human

    fields = machine_fields()
    fields.pop("boundaries")
    try:
        check_wire(fields, _schema())
    except CardGenerationError as exc:
        payload = {
            "code": exc.code,
            "message": str(exc),
            "diagnostic": exc.diagnostic,
        }

    text = _render_human(
        {
            "operation": "subject_card_draft",
            "ok": False,
            "failed_stage": "output",
            "error": payload,
        }
    )

    assert "主体卡草稿失败（output）" in text
    assert "machine_fields.boundaries" in text
    assert "机器字段缺少该键" in text
