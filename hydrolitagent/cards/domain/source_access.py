"""Reading contracts shared by every runner.

The method strings are part of the on-disk contract (drafts, manifests, theme
records), so they live here instead of being repeated as literals across the
validation, workflow and adapter layers.

Stage 1 of the decoupling migration keeps the accepted set identical to the
previous behaviour; ``MARKDOWN_PREPARED`` is reserved for the Markdown-first
pipeline and is not accepted yet.
"""
from __future__ import annotations

from typing import Any

BOUND_LOCAL_PDF_MCP = "bound_local_pdf_mcp"
CLAUDE_PDF_READ = "claude_pdf_read"
LOCAL_PDF_PATH = "local_pdf_path"
MARKDOWN_PREPARED = "markdown_prepared"

# Methods that may appear in newly generated artifacts.
CURRENT_METHODS = frozenset({LOCAL_PDF_PATH, CLAUDE_PDF_READ})
# Methods that historical artifacts may carry; still readable, never written.
LEGACY_METHODS = frozenset({BOUND_LOCAL_PDF_MCP, CLAUDE_PDF_READ, LOCAL_PDF_PATH})
ALL_METHODS = CURRENT_METHODS | LEGACY_METHODS


def is_accepted_method(method: Any, *, policy: str = "current") -> bool:
    """Return whether ``method`` is acceptable under ``policy``.

    ``policy`` is one of ``current`` (new artifacts), ``historical`` (legacy
    artifacts) or ``any``.
    """
    if not isinstance(method, str):
        return False
    if policy == "current":
        return method in CURRENT_METHODS
    if policy == "historical":
        return method in LEGACY_METHODS
    if policy == "any":
        return method in ALL_METHODS
    raise ValueError(f"unknown source access policy: {policy}")


def source_access_acceptable(access: Any, *, expected_sha256: str | None = None,
                             expected_parent_key: str | None = None) -> bool:
    """Validate the reading receipt attached to a generated card."""
    if not isinstance(access, dict):
        return False
    count = access.get("page_count")
    if type(count) is not int or count < 1:
        return False
    if access.get("method") == BOUND_LOCAL_PDF_MCP:
        return (access.get("verified") is True
                and type(access.get("pages_served")) is int and access["pages_served"] == count
                and type(access.get("visual_pages_served")) is int and access["visual_pages_served"] == count)
    if access.get("method") == CLAUDE_PDF_READ:
        digest = access.get("source_sha256")
        pages = access.get("pages_requested_successfully")
        return (isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
                and isinstance(access.get("parent_key"), str) and bool(access["parent_key"])
                and (expected_sha256 is None or digest == expected_sha256)
                and (expected_parent_key is None or access["parent_key"] == expected_parent_key)
                and isinstance(pages, list) and all(type(p) is int for p in pages) and pages == list(range(1, count + 1))
                and all(access.get(k) is True for k in ("source_identity_verified", "source_unchanged",
                    "model_reading_report_accepted", "model_claim_full_text", "model_claim_visuals", "read_only_tools"))
                and all(access.get(k) is False for k in ("verified", "full_read_verified", "visual_understanding_verified")))
    if access.get("method") != LOCAL_PDF_PATH:
        return False
    digest = access.get("source_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
        or not isinstance(access.get("parent_key"), str) or not access["parent_key"]):
        return False
    if expected_sha256 is not None and digest != expected_sha256:
        return False
    if expected_parent_key is not None and access["parent_key"] != expected_parent_key:
        return False
    return (
        access.get("verified") is False
        and access.get("full_read_verified") is False
        and access.get("visual_understanding_verified") is False
        and access.get("source_identity_verified") is True
        and access.get("source_unchanged") is True
        and access.get("sandbox_preflight_passed") is True
        and access.get("model_reading_report_accepted") is True
        and access.get("model_claim_full_text") is True
        and access.get("model_claim_visuals") is True
        and type(access.get("command_event_count")) is int and access["command_event_count"] > 0
        and access.get("pages_served") is None and access.get("visual_pages_served") is None
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
