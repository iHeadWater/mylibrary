"""The structured failure type every card step raises.

``code`` is the machine-readable reason (an error code the CLI and the tests
assert on); ``diagnostic`` carries optional context that is safe to show. It
lives in the domain because every layer above it -- orchestration, adapters and
the CLI -- raises or catches the same type.

The type is provider-free on purpose: a code such as ``CARD_PDF_READ_UNVERIFIED``
describes the reading contract, not the executor that produced the answer.
"""
from __future__ import annotations

from typing import Any


class CardGenerationError(RuntimeError):
    """A card step failed with a stable ``code`` and optional diagnostics."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        diagnostic: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic


__all__ = ["CardGenerationError"]
