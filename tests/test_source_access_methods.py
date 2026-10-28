"""Unit tests for the reading-method policy in ``domain.source_access``.

The method strings are persisted in drafts, manifests and theme records. The
policy decides which of them may appear in *newly generated* artifacts versus
which one are only readable for historical ones.
"""

from __future__ import annotations

import pytest

from hydrolitagent.cards.domain.source_access import (
    ALL_METHODS,
    BOUND_LOCAL_PDF_MCP,
    CLAUDE_PDF_READ,
    CURRENT_METHODS,
    LEGACY_METHODS,
    LOCAL_PDF_PATH,
    MARKDOWN_PREPARED,
    is_accepted_method,
    source_access_acceptable,
)


def test_current_methods_gain_only_the_markdown_pipeline() -> None:
    """Stage 3a adds the Markdown receipt next to the two legacy methods."""

    assert CURRENT_METHODS == {LOCAL_PDF_PATH, CLAUDE_PDF_READ, MARKDOWN_PREPARED}


def test_legacy_methods_stay_read_only_history() -> None:
    assert LEGACY_METHODS == {BOUND_LOCAL_PDF_MCP, CLAUDE_PDF_READ, LOCAL_PDF_PATH}
    assert ALL_METHODS == CURRENT_METHODS | LEGACY_METHODS
    assert ALL_METHODS == {BOUND_LOCAL_PDF_MCP, CLAUDE_PDF_READ, LOCAL_PDF_PATH, MARKDOWN_PREPARED}


def test_markdown_prepared_is_writable_but_never_historical() -> None:
    assert is_accepted_method(MARKDOWN_PREPARED, policy="current") is True
    assert is_accepted_method(MARKDOWN_PREPARED, policy="any") is True
    # It is a new on-disk method, so no historical artifact can carry it.
    assert is_accepted_method(MARKDOWN_PREPARED, policy="historical") is False


@pytest.mark.parametrize("method", [LOCAL_PDF_PATH, CLAUDE_PDF_READ])
def test_current_policy_accepts_current_methods(method: str) -> None:
    assert is_accepted_method(method, policy="current") is True
    assert is_accepted_method(method, policy="any") is True


def test_current_policy_rejects_retired_method() -> None:
    assert is_accepted_method(BOUND_LOCAL_PDF_MCP, policy="current") is False
    assert is_accepted_method(BOUND_LOCAL_PDF_MCP, policy="historical") is True
    assert is_accepted_method(BOUND_LOCAL_PDF_MCP, policy="any") is True


@pytest.mark.parametrize("value", [None, 1, "", "unknown_method", {"method": LOCAL_PDF_PATH}])
def test_non_string_and_unknown_values_are_rejected(value: object) -> None:
    assert is_accepted_method(value, policy="any") is False


def test_unknown_policy_raises() -> None:
    with pytest.raises(ValueError):
        is_accepted_method(LOCAL_PDF_PATH, policy="future")


# --------------------------------------------------------------------------------------
# The Markdown receipt is stricter than the legacy ones on purpose: it must bind
# both digests, the converter identity and the program-computed reading verdict.
# --------------------------------------------------------------------------------------

PDF_SHA = "a" * 64
MARKDOWN_SHA = "b" * 64


def _markdown_access(**overrides: object) -> dict:
    access = {
        "method": MARKDOWN_PREPARED,
        "source_pdf_sha256": PDF_SHA,
        "markdown_sha256": MARKDOWN_SHA,
        "parent_key": "ABCD1234",
        "page_count": 3,
        "converter_id": "pymupdf",
        "converter_version": "1.24.0",
        "reading": {
            "verified": True,
            "canaries_ok": True,
            "scientific_correctness_verified": False,
        },
    }
    access.update(overrides)
    return access


def _mutate(dotted: str, value: object) -> dict:
    access = _markdown_access()
    target = access
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    return access


def test_markdown_access_is_accepted_when_every_field_matches() -> None:
    assert source_access_acceptable(
        _markdown_access(), expected_sha256=PDF_SHA, expected_parent_key="ABCD1234"
    ) is True


@pytest.mark.parametrize(
    "dotted,value",
    [
        ("markdown_sha256", "not-a-digest"),
        ("markdown_sha256", None),
        ("source_pdf_sha256", "B" * 64),
        ("parent_key", ""),
        ("converter_id", ""),
        ("converter_version", ""),
        ("reading", None),
        ("reading.verified", False),
        ("reading.canaries_ok", False),
        ("reading.scientific_correctness_verified", True),
    ],
)
def test_markdown_access_rejects_a_broken_receipt(dotted: str, value: object) -> None:
    assert source_access_acceptable(_mutate(dotted, value)) is False


@pytest.mark.parametrize(
    "expected_sha256,expected_parent_key",
    [(MARKDOWN_SHA, None), (None, "OTHERKEY"), (PDF_SHA, "OTHERKEY")],
)
def test_markdown_access_rejects_a_different_source(
    expected_sha256: str | None, expected_parent_key: str | None
) -> None:
    assert source_access_acceptable(
        _markdown_access(),
        expected_sha256=expected_sha256,
        expected_parent_key=expected_parent_key,
    ) is False


def test_markdown_access_still_requires_a_positive_page_count() -> None:
    assert source_access_acceptable(_mutate("page_count", 0)) is False
    assert source_access_acceptable(_mutate("page_count", None)) is False
