"""Stage 3b: the Markdown-first pipeline is the default, ``legacy`` is rollback.

These tests only parse the environment; they never import a converter, build a
runner or call a model, so they stay fast and provider-free.
"""

from __future__ import annotations

import pytest

from hydrolitagent.cards.ai_config import describe_ai
from hydrolitagent.cards.config import (
    DEFAULT_PIPELINE_MODE,
    PIPELINE_MODES,
    ConfigError,
    resolve_pipeline_mode,
)


def test_default_pipeline_is_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARD_PIPELINE", raising=False)
    assert DEFAULT_PIPELINE_MODE == "markdown"
    assert DEFAULT_PIPELINE_MODE in PIPELINE_MODES
    assert resolve_pipeline_mode() == "markdown"


def test_empty_environment_mapping_keeps_the_default() -> None:
    assert resolve_pipeline_mode({}) == "markdown"


def test_legacy_remains_an_explicit_rollback() -> None:
    assert resolve_pipeline_mode({"CARD_PIPELINE": "legacy"}) == "legacy"


@pytest.mark.parametrize("value", ["markdown", "MARKDOWN", " Markdown ", "legacy", " Legacy "])
def test_mode_is_case_and_whitespace_insensitive(value: str) -> None:
    assert resolve_pipeline_mode({"CARD_PIPELINE": value}) == value.strip().casefold()


@pytest.mark.parametrize("value", ["pdf", "", "markdown,legacy"])
def test_unknown_mode_is_rejected(value: str) -> None:
    with pytest.raises(ConfigError, match="CARD_PIPELINE"):
        resolve_pipeline_mode({"CARD_PIPELINE": value})


def test_ai_config_reports_the_effective_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    selection = {"provider": "codex"}
    monkeypatch.delenv("CARD_PIPELINE", raising=False)
    assert describe_ai(selection)["ai"]["pipeline"] == "markdown"
    monkeypatch.setenv("CARD_PIPELINE", "legacy")
    assert describe_ai(selection)["ai"]["pipeline"] == "legacy"
    # The selection object is not mutated: ``pipeline`` is a projection.
    assert selection == {"provider": "codex"}
