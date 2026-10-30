"""One field name, two contracts: the prompt must say which layer it means.

A card answer carries ``schema_version`` twice — once for the whole document and
once inside ``machine_fields`` — and the two numbers differ on purpose. The model
hand-copies both, so any prompt line that names the field without saying which
layer it belongs to invites the wrong number (#64). These tests pin the wording
that keeps the two apart.
"""
from __future__ import annotations

import re

import pytest

from hydrolitagent.cards.application.card_draft import PROMPT as DRAFT_PROMPT
from hydrolitagent.cards.application.card_workflow import (
    MACHINE_FIELDS_VERSION_NOTE,
    READING_PROMPT,
    _repair_prompt,
)

PROMPTS = (READING_PROMPT, DRAFT_PROMPT)
# Words that turn a bare ``schema_version`` into "this one, not the other one".
LAYER_MARKERS = ("顶层", "本块", "machine_fields")


def mentions() -> list:
    """Every prompt line that names the field, labelled with its file and number."""

    found = []
    for path in PROMPTS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "schema_version" in line:
                found.append(pytest.param(line, id=f"{path.stem}:{number}"))
    return found


@pytest.mark.parametrize("line", mentions())
def test_every_schema_version_mention_names_its_layer(line):
    for match in re.finditer("schema_version", line):
        before = line[max(0, match.start() - 24):match.start()]
        assert any(marker in before for marker in LAYER_MARKERS), (
            f"这一处没说明是哪一层的 schema_version：{line}"
        )


def test_reading_prompt_keeps_the_two_numbers_apart():
    text = READING_PROMPT.read_text(encoding="utf-8")
    assert "**顶层** `schema_version` 保持 `2`" in text
    assert "`machine_fields.schema_version`" in text
    assert "固定为 `1`" in text


def test_draft_prompt_keeps_the_two_numbers_apart():
    text = DRAFT_PROMPT.read_text(encoding="utf-8")
    assert "`machine_fields.schema_version` 固定为 `1`" in text
    assert "顶层文档契约" in text


def test_repair_prompt_explains_which_version_it_wants():
    violations = [
        {
            "code": "CARD_DRAFT_OUTPUT_INVALID",
            "path": "machine_fields.schema_version",
            "message": "机器字段取值不在协议枚举内",
            "expected": 1,
            "actual": 2,
        }
    ]
    contract = {"schema_version": {"type": "integer", "enum": [1]}}
    text = _repair_prompt("基础提示", {}, violations, contract, None)
    assert MACHINE_FIELDS_VERSION_NOTE in text
    assert "machine_fields.schema_version" in text
    assert "期望 1" in text and "实际 2" in text
