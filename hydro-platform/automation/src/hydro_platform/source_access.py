"""Explicit reading contracts: delivered MCP pages are not local-path model claims."""
from __future__ import annotations

from typing import Any


def source_access_acceptable(access: Any, *, expected_sha256: str | None = None,
                             expected_parent_key: str | None = None) -> bool:
    if not isinstance(access, dict):
        return False
    count = access.get("page_count")
    if type(count) is not int or count < 1:
        return False
    if access.get("method") == "bound_local_pdf_mcp":
        return (access.get("verified") is True
                and type(access.get("pages_served")) is int and access["pages_served"] == count
                and type(access.get("visual_pages_served")) is int and access["visual_pages_served"] == count)
    if access.get("method") == "claude_pdf_read":
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
    if access.get("method") != "local_pdf_path":
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
