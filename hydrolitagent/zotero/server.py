#!/usr/bin/env python3
"""Zotero MCP Server for mylibrary — literature query service.

Exposes 12 tools via FastMCP SSE transport on port 8002:
  Web API (api.zotero.org via pyzotero):
    - zotero_search              -> Search library by keyword
    - zotero_fulltext_search     -> Full-text search across all fields
    - zotero_search_by_tag       -> Search items by tag(s)
    - zotero_get_item            -> Get full metadata for an item
    - zotero_get_attachments     -> Get attachment list for an item
    - zotero_get_annotations     -> Get PDF annotations for an item
    - zotero_get_recent          -> Get recently added items
    - zotero_get_collections     -> List all collections
    - zotero_get_collection_items -> Get items in a collection
    - zotero_get_tags            -> List tags (optionally by collection)
  Local API (host.docker.internal:23119 via httpx):
    - zotero_get_fulltext        -> Get indexed full-text content
    - zotero_get_file_info       -> Get attachment file metadata

Consumers connect via: http://zotero-mcp:8002/mcp
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx
from mcp.server import MCPServer
from pyzotero.zotero import Zotero

logger = logging.getLogger("zotero-mcp")

# ── Configuration (from environment) ──────────────────────────────

ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")
ZOTERO_LIBRARY_ID = os.environ.get("ZOTERO_LIBRARY_ID", "")
ZOTERO_LIBRARY_TYPE = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
LOCAL_API_BASE = os.environ.get(
    "ZOTERO_LOCAL_API_URL", "http://host.docker.internal:23119"
)

mcp = MCPServer("zotero")

# ── pyzotero client ───────────────────────────────────────────────

_zot: Zotero | None = None
if ZOTERO_API_KEY and ZOTERO_LIBRARY_ID:
    _zot = Zotero(ZOTERO_LIBRARY_ID, ZOTERO_LIBRARY_TYPE, ZOTERO_API_KEY)
else:
    logger.warning(
        "[zotero-mcp] ZOTERO_API_KEY or ZOTERO_LIBRARY_ID not set; "
        "Web API tools will be unavailable"
    )


# ── Helpers ───────────────────────────────────────────────────────


def _format_item(item: dict) -> dict:
    """Extract key fields from a Zotero item for concise, readable output.

    Handles both the list-item envelope (top-level key + data sub-object)
    and the raw data dict (from single-item endpoints that unwrap data).
    """
    data = item.get("data", item)
    creators = data.get("creators", [])
    creator_names = []
    for c in creators:
        name = " ".join(
            filter(None, [c.get("firstName", ""), c.get("lastName", "")])
        )
        if not name:
            name = c.get("name", "")
        if name:
            creator_names.append(name)

    result = {
        "key": data.get("key", item.get("key", "")),
        "title": data.get("title", ""),
        "itemType": data.get("itemType", ""),
        "creators": creator_names,
        "date": data.get("date", ""),
        "DOI": data.get("DOI", ""),
    }

    abstract = data.get("abstractNote", "")
    if abstract:
        result["abstractSnippet"] = abstract[:300] + (
            "..." if len(abstract) > 300 else ""
        )

    url = data.get("url", "")
    if url:
        result["url"] = url

    return result


def _make_error(context: str, message: str) -> str:
    """Build a JSON error response string."""
    return json.dumps(
        {"error": True, "context": context, "message": message},
        ensure_ascii=False,
    )


# ── Tool: zotero_search ──────────────────────────────────────────


@mcp.tool()
async def zotero_search(query: str, limit: int = 10) -> str:
    """Search the Zotero library by keyword.

    Returns matching items with title, creators, date, DOI, and abstract snippet.
    """
    if not _zot:
        return _make_error("zotero_search", "Web API client not initialized")
    try:
        items = await asyncio.to_thread(
            _zot.items, q=query, limit=limit
        )
        return json.dumps(
            {
                "total": len(items or []),
                "query": query,
                "items": [_format_item(i) for i in (items or [])],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error("zotero_search failed: %s", e)
        return _make_error("zotero_search", str(e))


# ── Tool: zotero_get_item ────────────────────────────────────────


@mcp.tool()
async def zotero_get_item(item_key: str) -> str:
    """Get full metadata for a specific Zotero item by its item key.

    Returns the complete item JSON with all fields.
    """
    if not item_key:
        return _make_error("zotero_get_item", "item_key is required")
    if not _zot:
        return _make_error("zotero_get_item", "Web API client not initialized")
    try:
        result = await asyncio.to_thread(_zot.item, item_key)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("zotero_get_item(%s) failed: %s", item_key, e)
        return _make_error("zotero_get_item", str(e))


# ── Tool: zotero_get_recent ───────────────────────────────────────


@mcp.tool()
async def zotero_get_recent(limit: int = 10, since: str | None = None) -> str:
    """Get recently added items, sorted by dateAdded descending."""
    if not _zot:
        return _make_error("zotero_get_recent", "Web API client not initialized")
    try:
        kwargs = {"limit": limit}
        if since:
            kwargs["since"] = since
        items = await asyncio.to_thread(_zot.top, **kwargs)
        return json.dumps(
            {
                "total": len(items or []),
                "items": [_format_item(i) for i in (items or [])],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error("zotero_get_recent failed: %s", e)
        return _make_error("zotero_get_recent", str(e))


# ── Tool: zotero_get_collection_items ─────────────────────────────


@mcp.tool()
async def zotero_get_collection_items(
    collection_key: str, limit: int = 20
) -> str:
    """Get all items in a specific Zotero collection by collection key."""
    if not collection_key:
        return _make_error(
            "zotero_get_collection_items", "collection_key is required"
        )
    if not _zot:
        return _make_error(
            "zotero_get_collection_items", "Web API client not initialized"
        )
    try:
        items = await asyncio.to_thread(
            _zot.collection_items, collection_key, limit=limit
        )
        return json.dumps(
            {
                "total": len(items or []),
                "collectionKey": collection_key,
                "items": [_format_item(i) for i in (items or [])],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(
            "zotero_get_collection_items(%s) failed: %s", collection_key, e
        )
        return _make_error("zotero_get_collection_items", str(e))


# ── Tool: zotero_get_collections ────────────────────────────────────


@mcp.tool()
async def zotero_get_collections(limit: int = 50) -> str:
    """List all collections in the Zotero library.

    Returns collection key, name, version, and parentCollection for each.
    """
    if not _zot:
        return _make_error("zotero_get_collections", "Web API client not initialized")
    try:
        collections = await asyncio.to_thread(_zot.collections, limit=limit)
        return json.dumps(
            {
                "total": len(collections or []),
                "collections": collections or [],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error("zotero_get_collections failed: %s", e)
        return _make_error("zotero_get_collections", str(e))


# ── Tool: zotero_get_tags ───────────────────────────────────────────


@mcp.tool()
async def zotero_get_tags(collection_key: str | None = None) -> str:
    """List all tags in the Zotero library, or tags for a specific collection.

    Pass collection_key to get tags scoped to one collection.
    """
    if not _zot:
        return _make_error("zotero_get_tags", "Web API client not initialized")
    try:
        if collection_key:
            tags = await asyncio.to_thread(
                _zot.collection_tags, collection_key
            )
            return json.dumps(
                {
                    "total": len(tags or []),
                    "collectionKey": collection_key,
                    "tags": tags or [],
                },
                ensure_ascii=False,
                indent=2,
            )
        else:
            tags = await asyncio.to_thread(_zot.tags)
            return json.dumps(
                {
                    "total": len(tags or []),
                    "tags": tags or [],
                },
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logger.error("zotero_get_tags failed: %s", e)
        return _make_error("zotero_get_tags", str(e))


# ── Tool: zotero_search_by_tag ──────────────────────────────────────


@mcp.tool()
async def zotero_search_by_tag(tag: str, limit: int = 20) -> str:
    """Search Zotero items by tag. Returns items matching the given tag.

    Zotero API semantics: comma-separated tags = AND, && = OR.
    """
    if not tag:
        return _make_error("zotero_search_by_tag", "tag is required")
    if not _zot:
        return _make_error("zotero_search_by_tag", "Web API client not initialized")
    try:
        items = await asyncio.to_thread(
            _zot.items, tag=tag, limit=limit
        )
        return json.dumps(
            {
                "total": len(items or []),
                "tag": tag,
                "items": [_format_item(i) for i in (items or [])],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error("zotero_search_by_tag failed: %s", e)
        return _make_error("zotero_search_by_tag", str(e))


# ── Tool: zotero_fulltext_search ───────────────────────────────────


@mcp.tool()
async def zotero_fulltext_search(query: str, limit: int = 20) -> str:
    """Search Zotero library across all fields including full-text content.

    Uses qmode=everything to search titles, creators, abstracts, and
    indexed PDF full-text content in one call.
    """
    if not query:
        return _make_error("zotero_fulltext_search", "query is required")
    if not _zot:
        return _make_error(
            "zotero_fulltext_search", "Web API client not initialized"
        )
    try:
        items = await asyncio.to_thread(
            _zot.items, q=query, qmode="everything", limit=limit
        )
        return json.dumps(
            {
                "total": len(items or []),
                "query": query,
                "items": [_format_item(i) for i in (items or [])],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error("zotero_fulltext_search failed: %s", e)
        return _make_error("zotero_fulltext_search", str(e))


# ── Tool: zotero_get_attachments ────────────────────────────────────


@mcp.tool()
async def zotero_get_attachments(item_key: str) -> str:
    """Get child items (attachments and notes) for a Zotero item.

    Returns key, title, filename, contentType, linkMode, and file size/md5
    for each attachment. Notes are included with their note text.
    """
    if not item_key:
        return _make_error("zotero_get_attachments", "item_key is required")
    if not _zot:
        return _make_error(
            "zotero_get_attachments", "Web API client not initialized"
        )
    try:
        children = await asyncio.to_thread(_zot.children, item_key)
        return json.dumps(
            {
                "total": len(children or []),
                "itemKey": item_key,
                "attachments": children or [],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error("zotero_get_attachments(%s) failed: %s", item_key, e)
        return _make_error("zotero_get_attachments", str(e))


# ── Tool: zotero_get_annotations ────────────────────────────────────


@mcp.tool()
async def zotero_get_annotations(item_key: str) -> str:
    """Get PDF annotations for a Zotero item.

    Traverses paper → attachment → annotations to find highlights and notes
    made in the Zotero PDF reader. Returns annotation type, text, color,
    page number, and comment for each annotation.
    """
    if not item_key:
        return _make_error("zotero_get_annotations", "item_key is required")
    if not _zot:
        return _make_error(
            "zotero_get_annotations", "Web API client not initialized"
        )
    try:
        # Step 1: get paper's children, find PDF attachments
        children = await asyncio.to_thread(_zot.children, item_key)
        attachment_keys = []
        for child in (children or []):
            data = child.get("data", child)
            if data.get("itemType") == "attachment":
                attachment_keys.append(data.get("key"))

        # Step 2: get annotations from each attachment
        all_annotations = []
        for att_key in attachment_keys:
            att_children = await asyncio.to_thread(_zot.children, att_key)
            for child in (att_children or []):
                data = child.get("data", child)
                if data.get("itemType") == "annotation":
                    all_annotations.append(
                        {
                            "key": data.get("key", ""),
                            "type": data.get("annotationType", ""),
                            "text": data.get("annotationText", ""),
                            "comment": data.get("annotationComment", ""),
                            "color": data.get("annotationColor", ""),
                            "page": data.get("annotationPageLabel", ""),
                        }
                    )

        return json.dumps(
            {
                "total": len(all_annotations),
                "itemKey": item_key,
                "annotations": all_annotations,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error("zotero_get_annotations(%s) failed: %s", item_key, e)
        return _make_error("zotero_get_annotations", str(e))


# ── Tool: zotero_get_fulltext (Local API) ─────────────────────────


@mcp.tool()
async def zotero_get_fulltext(item_key: str) -> str:
    """Get indexed full-text content for a Zotero item via the Local API.

    Requires Zotero Desktop running on the host with local API enabled.
    Returns content, indexedPages, and totalPages.
    """
    if not item_key:
        return _make_error("zotero_get_fulltext", "item_key is required")
    url = f"{LOCAL_API_BASE}/items/{item_key}/fulltext"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return _make_error(
                    "zotero_get_fulltext",
                    f"Fulltext not indexed for item {item_key}",
                )
            resp.raise_for_status()
            data = resp.json()
            data["itemKey"] = item_key
            return json.dumps(data, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("Local API unreachable for fulltext: %s", e)
        return _make_error(
            "zotero_get_fulltext",
            f"Local API unreachable: {e}",
        )
    except Exception as e:
        logger.error("zotero_get_fulltext(%s) failed: %s", item_key, e)
        return _make_error("zotero_get_fulltext", str(e))


# ── Tool: zotero_get_file_info (Local API) ────────────────────────


@mcp.tool()
async def zotero_get_file_info(item_key: str) -> str:
    """Get attachment file metadata for a Zotero item via the Local API.

    Requires Zotero Desktop running on the host with local API enabled.
    Returns filename, contentType, size, and optional path (for linked files).
    """
    if not item_key:
        return _make_error("zotero_get_file_info", "item_key is required")
    url = f"{LOCAL_API_BASE}/items/{item_key}/file"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return _make_error(
                    "zotero_get_file_info",
                    f"No attachment found for item {item_key}",
                )
            resp.raise_for_status()
            data = resp.json()
            data["itemKey"] = item_key
            return json.dumps(data, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("Local API unreachable for file info: %s", e)
        return _make_error(
            "zotero_get_file_info",
            f"Local API unreachable: {e}",
        )
    except Exception as e:
        logger.error("zotero_get_file_info(%s) failed: %s", item_key, e)
        return _make_error("zotero_get_file_info", str(e))


# ── Main ──────────────────────────────────────────────────────────


async def main() -> None:
    """Run the Zotero MCP server with SSE transport."""
    logger.info("Starting zotero-mcp on port 8002 (SSE transport)")
    await mcp.run_streamable_http_async(host="0.0.0.0", port=8002)


if __name__ == "__main__":
    asyncio.run(main())
