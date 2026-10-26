"""Compatibility shim: the reading contract now lives in ``domain.source_access``.

Kept so existing imports in tests and callers keep working during the
decoupling migration. It will be removed once the migration completes.
"""
from __future__ import annotations

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

__all__ = [
    "ALL_METHODS",
    "BOUND_LOCAL_PDF_MCP",
    "CLAUDE_PDF_READ",
    "CURRENT_METHODS",
    "LEGACY_METHODS",
    "LOCAL_PDF_PATH",
    "MARKDOWN_PREPARED",
    "is_accepted_method",
    "source_access_acceptable",
]
