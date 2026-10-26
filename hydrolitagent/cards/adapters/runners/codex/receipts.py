"""Interpretation of the (legacy) bound-PDF MCP access receipt.

Stage 3 removes the MCP reading path. Until then the receipt decoder stays
byte-compatible with its previous behaviour so old failure records remain
readable; it is kept separate from event decoding because it is about source
provenance, not transport.
"""
from __future__ import annotations

from typing import Any

from hydrolitagent.cards.adapters.runners.diagnostics import (
    event_diagnostic_parts,
    sanitize_diagnostic_text,
)
from hydrolitagent.cards.domain.source_access import BOUND_LOCAL_PDF_MCP


def _pdf_access_diagnostic(
    events: list[dict[str, Any]],
    *,
    server_name: str,
    output: Any,
) -> dict[str, Any]:
    mcp_events: list[dict[str, str]] = []
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            continue
        observed_server = item.get("server") or item.get("server_name")
        if isinstance(observed_server, str) and observed_server != server_name:
            continue
        observed: dict[str, str] = {}
        if isinstance(observed_server, str):
            observed["server"] = observed_server
        observed_tool = item.get("tool") or item.get("tool_name") or item.get("name")
        if isinstance(observed_tool, str):
            observed["tool"] = observed_tool
        observed_status = item.get("status")
        if isinstance(observed_status, str):
            observed["status"] = observed_status
        error_parts = event_diagnostic_parts(item.get("error"), key="error")
        if error_parts:
            observed["error_summary"] = sanitize_diagnostic_text(
                " | ".join(error_parts)
            )
        event_type = event.get("type")
        if isinstance(event_type, str):
            observed["event"] = event_type
        mcp_events.append(observed)

    model_claim: dict[str, Any] = {}
    if isinstance(output, dict):
        for field in (
            "source_read_status",
            "source_page_count",
            "visual_content_status",
        ):
            value = output.get(field)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                model_claim[field] = value
    return {
        "stage": "pdf_access_verification",
        "mcp_event_count": len(mcp_events),
        "mcp_events": mcp_events[:20],
        "model_claim": model_claim,
    }


def _source_pdf_access_from_receipt(
    receipt: Any,
    *,
    expected_sha256: str,
    server_name: str,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        return (
            None,
            "CODEX_PDF_NOT_ACCESSED",
            "Codex 已完成调用，但专用 PDF 读取器没有留下有效回执",
        )
    if receipt.get("source_sha256") != expected_sha256:
        return (
            None,
            "CODEX_PDF_BINDING_MISMATCH",
            "PDF 读取回执与本次任务绑定的文件指纹不一致",
        )
    if receipt.get("inspected") is not True:
        return (
            None,
            "CODEX_PDF_NOT_ACCESSED",
            "Codex 没有通过专用 PDF 读取器检查本次原始 PDF",
        )
    page_count = receipt.get("page_count")
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count < 1
    ):
        return (
            None,
            "CODEX_PDF_RECEIPT_INVALID",
            "专用 PDF 读取器没有返回有效页数",
        )
    raw_pages = receipt.get("pages")
    if not isinstance(raw_pages, dict):
        raw_pages = {}
    served_pages: set[int] = set()
    visual_pages: set[int] = set()
    for raw_page, details in raw_pages.items():
        try:
            page = int(raw_page)
        except (TypeError, ValueError):
            continue
        if not 1 <= page <= page_count or not isinstance(details, dict):
            continue
        served_pages.add(page)
        if details.get("image_delivered") is True:
            visual_pages.add(page)
    expected_pages = set(range(1, page_count + 1))
    if served_pages != expected_pages:
        return (
            None,
            "CODEX_PDF_NOT_FULLY_ACCESSED",
            f"Codex 只读取了原始 PDF 的 {len(served_pages)}/{page_count} 页",
        )
    if visual_pages != expected_pages:
        return (
            None,
            "CODEX_PDF_VISUALS_NOT_ACCESSED",
            f"Codex 只取得了原始 PDF 的 {len(visual_pages)}/{page_count} 个页面图像",
        )
    return (
        {
            "verified": True,
            "method": BOUND_LOCAL_PDF_MCP,
            "server_name": server_name,
            "receipt_schema_version": 1,
            "page_count": page_count,
            "pages_served": len(served_pages),
            "visual_pages_served": len(visual_pages),
        },
        None,
        None,
    )


__all__ = ["_pdf_access_diagnostic", "_source_pdf_access_from_receipt"]
