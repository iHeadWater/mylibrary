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
)


def test_current_methods_are_unchanged_in_stage_one() -> None:
    """Stage 1 must not widen or narrow the accepted set."""

    assert CURRENT_METHODS == {LOCAL_PDF_PATH, CLAUDE_PDF_READ}


def test_legacy_methods_add_only_the_retired_mcp_receipt() -> None:
    assert LEGACY_METHODS == {BOUND_LOCAL_PDF_MCP, CLAUDE_PDF_READ, LOCAL_PDF_PATH}
    assert ALL_METHODS == LEGACY_METHODS


def test_markdown_prepared_is_reserved_but_not_yet_accepted() -> None:
    assert is_accepted_method(MARKDOWN_PREPARED, policy="any") is False


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
