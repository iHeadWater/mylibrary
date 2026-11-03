"""Prompt/schema contract for the theme discovery templates.

DeepSeek accepts ``response_format`` but does not enforce the JSON schema, so
the prompt text is the only place the model learns the field names. On
2026-11-02 ``pool-discovery.md`` described the four operations without ever
naming the ``kind`` field; the model wrote ``operation`` instead, the run was
rejected with ``THEME_ROUTE_INVALID``, and because a failed answer is cached per
input hash the retry reproduced the identical failure.

These tests pin the field names into the prompt, so a template edit cannot
silently drop one again. They deliberately do not check the model's output —
that is the validator's job.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

THEMES_DIR = Path(__file__).resolve().parents[1] / "hydrolitagent/cards/assets/templates/themes"

PAIRS = [
    pytest.param("pool-discovery.md", "pool-discovery.schema.json", id="pool-discovery"),
    pytest.param("discovery.md", "discovery.schema.json", id="discovery"),
]


def required_names(node: object) -> set[str]:
    """Every property name listed in a ``required`` array, at any depth."""

    names: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            names.update(name for name in value.get("required") or [] if isinstance(name, str))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return names


def missing_names(prompt: str, schema: object) -> set[str]:
    """Required field names the prompt never mentions as a word."""

    return {
        name
        for name in required_names(schema)
        if not re.search(rf"\b{re.escape(name)}\b", prompt)
    }


@pytest.mark.parametrize("prompt_name,schema_name", PAIRS)
def test_prompt_names_every_required_schema_field(prompt_name: str, schema_name: str) -> None:
    prompt = (THEMES_DIR / prompt_name).read_text(encoding="utf-8")
    schema = json.loads((THEMES_DIR / schema_name).read_text(encoding="utf-8"))

    assert required_names(schema), f"{schema_name} declares no required fields"
    assert missing_names(prompt, schema) == set()


def test_focused_reading_forbids_caption_quotes() -> None:
    """Table/figure captions are not prose; quoting them fails QUOTE_TOO_WEAK.

    Pages that hold only an ``Extended Data Table`` heading must not be given
    a quote at all. ``v2`` said "不要选标题" but the model treated a table
    caption as body text and blocked the whole run twice.
    """

    prompt = (THEMES_DIR / "focused-reading-markdown.md").read_text(encoding="utf-8")

    for word in ("表题", "图题", "表头", "Extended Data Table"):
        assert word in prompt
    assert "仅含图表" in prompt and "不要提供引文" in prompt
    # Two-column PDFs interleave the columns line by line; a reflowed quote is
    # not verbatim and is rejected as ANCHOR_MISMATCH/QUOTE_NOT_FOUND.
    assert "连续出现" in prompt and "另一栏" in prompt


def test_check_reports_fields_a_prompt_drops() -> None:
    """Negative control: the guard must fail on the pre-fix prompt shape."""

    schema = json.loads((THEMES_DIR / "pool-discovery.schema.json").read_text(encoding="utf-8"))
    stripped = "CREATE：新的研究问题；UPDATE：补充已有候选。"

    missing = missing_names(stripped, schema)

    assert {"kind", "theme_ids", "reason", "themes", "problem_clusters_markdown"} <= missing
