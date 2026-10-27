#!/usr/bin/env python3
"""Zotero MCP Server for mylibrary — literature query service.

Exposes 12 tools over streamable HTTP on port 8002 (endpoint path ``/mcp``):
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
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from mcp.server import MCPServer
from pyzotero.zotero import Zotero

logger = logging.getLogger("zotero-mcp")

# ── Configuration (from environment) ──────────────────────────────

# <repo>/hydrolitagent/zotero/server.py -> <repo>/.  Absent in the container,
# where the Dockerfile copies only this file.
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


def _load_env_file(path: Path | None = None) -> bool:
    """Load ``<repo>/.env`` for bare-host runs, without clobbering the environment.

    Deliberately additive: under Docker the env comes from the compose file and
    must win, which is what ``load_dotenv``'s default ``override=False`` gives.
    Returns True when a file was found and loaded.
    """
    env_path = Path(path) if path is not None else _ENV_FILE
    if not env_path.exists():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:
        # The container image installs only mcp/httpx/pyzotero.
        logger.warning("[zotero-mcp] python-dotenv missing; ignoring %s", env_path)
        return False
    load_dotenv(env_path, override=False)
    return True


_load_env_file()

ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")
ZOTERO_LIBRARY_ID = os.environ.get("ZOTERO_LIBRARY_ID", "")
ZOTERO_LIBRARY_TYPE = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")


def _resolve_local_api_base() -> str:
    """Base URL of the Zotero Desktop Local API — host root, no user segment.

    ``ZOTERO_LOCAL_BASE_URL`` is the unified name shared with the other Local
    API consumers in this repo.  ``ZOTERO_LOCAL_API_URL`` is the older name and
    remains supported because container compose files already set it.

    The default is unchanged: it reaches the host from inside a container.
    """
    return os.environ.get("ZOTERO_LOCAL_BASE_URL") or os.environ.get(
        "ZOTERO_LOCAL_API_URL", "http://host.docker.internal:23119"
    )


LOCAL_API_BASE = _resolve_local_api_base()
# Every Local API route lives under /api/users/<id>.  Omitting this segment
# makes every request 404 — see _local_api_url().
LOCAL_API_USER = os.environ.get("ZOTERO_LOCAL_USER", "/api/users/0")

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


# ── Local API helpers ─────────────────────────────────────────────

LOCAL_API_TIMEOUT = 30.0
# Bookkeeping calls (attachment listing, per-candidate probes, path lookup) get
# a tighter budget: they are individually cheap, and a wedged Zotero should not
# be able to hold a metadata call open for minutes by stalling each of them.
LOCAL_API_PROBE_TIMEOUT = 10.0
PDF_CONTENT_TYPE = "application/pdf"
# Zotero item/attachment keys are 8 uppercase alphanumerics.  Allow some slack,
# but reject anything that could reshape the request path.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{1,32}\Z")
# An absolute URL inside an exception message.  httpx embeds the request URL in
# HTTPStatusError, which would carry the configured host out to the client.
_URL_IN_MESSAGE = re.compile(r"https?://\S+")
# The Local API reports no file size for either storage mode: GET
# .../items/<key>/file answers 302 with a file:// Location for stored and
# linked attachments alike.  Sizing one would mean stat-ing the user's disk —
# and hydrating Google Drive — so `size` is always reported as 0.
ATTACHMENT_SIZE_UNAVAILABLE = 0


def _local_api_url(path: str) -> str:
    """Absolute Local API URL. ``path`` is relative to the user segment.

    >>> _local_api_url("/items/ABC/fulltext")   # doctest: +SKIP
    'http://host.docker.internal:23119/api/users/0/items/ABC/fulltext'
    """
    return f"{LOCAL_API_BASE}{LOCAL_API_USER}{path}"


def _local_api_headers() -> dict[str, str]:
    """Headers every Local API request must carry.

    Zotero's local server validates the ``Host`` header as DNS-rebinding
    protection and answers ``400 Bad request`` to anything that is not the
    literal ``127.0.0.1`` or ``localhost`` — other loopback addresses included
    (measured: ``Host: 127.0.0.2:23119`` is rejected just like
    ``host.docker.internal:23119``).  The default base is ``host.docker.internal``
    because that is the only name that reaches the host from inside a container,
    and that name is exactly what Zotero refuses, so the loopback form is set
    explicitly and the port is carried over from the base.

    Rewriting the name does not change where the request lands — the connection
    still goes to ``LOCAL_API_BASE`` — only what Zotero sees as the destination.

    Returns ``{}`` when the base is already loopback, so a host-side run (and
    every test that points at ``127.0.0.1``) sends exactly what it did before.
    """
    parts = urlparse(LOCAL_API_BASE)
    if parts.hostname in ("127.0.0.1", "localhost"):
        return {}
    port = f":{parts.port}" if parts.port else ""
    return {"Host": f"127.0.0.1{port}"}


def _valid_key(key: str) -> bool:
    """Whether ``key`` is shaped like a Zotero key.

    ``item_key`` arrives from an MCP client and is interpolated into a request
    path, so it is validated at the boundary.  httpx normalises dot segments —
    ``/items/../../collections/fulltext`` collapses to
    ``/api/users/collections/fulltext`` — which is precisely why a key that
    could contain them must be rejected before it reaches a URL.

    A non-string is rejected rather than raised on, so a direct Python caller
    passing an int still gets the tool's error JSON instead of a TypeError.
    """
    return isinstance(key, str) and bool(_KEY_PATTERN.match(key))


def _key_error(tool: str, key: str, *, label: str = "item_key") -> str | None:
    """A ready-made error for a malformed key, or None when the key is fine.

    Every key-taking tool calls this before doing anything else.  Both the
    Local API tools and the pyzotero ones interpolate the key into a request
    path — pyzotero does it into an *authenticated* api.zotero.org URL — so a
    key that could reshape that path must never reach either client.
    """
    if _valid_key(key):
        return None
    return _make_error(
        tool,
        f"{label} {key!r} is not a well-formed Zotero key "
        "(expected 1-32 alphanumerics)",
    )


def _path_only(url: str) -> str:
    """Strip the host from a URL, failing closed.

    Error messages name the path but never the configured host, so an MCP
    client learns nothing about our network layout.  A URL with no path at all
    (``http://host:23119``) reduces to ``"/"`` rather than falling back to the
    whole URL — a scrubber that hands back the host when it cannot parse is
    worse than useless.
    """
    return urlparse(url).path or "/"


def _describe_exception(exc: Exception) -> str:
    """A client-facing message, with any embedded URL reduced to its path.

    Two reasons this is not just ``str(exc)``: httpx transport errors stringify
    to an empty string (so fall back to the class name), and httpx's
    HTTPStatusError carries the full request URL, which would leak the
    configured host on every non-404 failure.
    """
    text = str(exc) or type(exc).__name__
    return _URL_IN_MESSAGE.sub(lambda m: _path_only(m.group(0)), text)


def _file_url_to_path(file_url: str) -> str:
    """``file:///G:/x%20y.pdf`` -> ``G:\\x y.pdf`` (or ``/x y.pdf`` on POSIX).

    Mirrors ``hydrolitagent.literature.zotero_notebooklm._file_url_to_path``.
    Duplicated rather than imported because this module is deployed standalone
    into an image that installs only mcp/httpx/pyzotero.
    """
    parsed = urlparse(file_url)
    raw = url2pathname(unquote(parsed.path))
    if os.name == "nt" and re.match(r"^/[A-Za-z]:/", raw):
        raw = raw[1:]
    return raw


def _attachment_filename(attachment: dict, local_path: str = "") -> str:
    """Best available filename for an attachment.

    The Local API leaves ``filename`` null for linked attachments, and carries
    the name on ``path`` behind an ``attachments:`` prefix instead.
    """
    filename = attachment.get("filename")
    if filename:
        return str(filename)
    raw_path = str(attachment.get("path") or "")
    if raw_path.startswith("attachments:"):
        return raw_path.split("attachments:", 1)[1]
    if local_path:
        # Zotero runs on the host, so ``local_path`` may be a Windows path even
        # when this server runs in a Linux container. Split on both separators
        # instead of asking the local OS which one separates paths.
        return re.split(r"[\\/]", local_path.rstrip("\\/"))[-1]
    return str(attachment.get("title") or "")


async def _get_json(client, url: str, timeout: float | None = None):
    """GET a Local API URL and decode the JSON body.

    ``timeout`` overrides the client-wide budget for this one request, which
    keeps cheap bookkeeping calls from inheriting the full allowance meant for
    a large fulltext fetch.
    """
    if timeout is not None:
        response = await client.get(url, timeout=timeout)
    else:
        response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _pdf_children(client, item_key: str) -> list[dict] | None:
    """Every PDF attachment among ``item_key``'s children.

    Returns None when the lookup itself failed — so callers can tell a broken
    request apart from an item that simply has no PDF — otherwise a (possibly
    empty) list of the children's ``data`` dicts.
    """
    try:
        children = await _get_json(client, _local_api_url(f"/items/{item_key}/children"))
    except Exception:  # noqa: BLE001 - reported by the caller as "no PDF"
        return None
    if not isinstance(children, list):
        return []
    pdfs: list[dict] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        data = child.get("data", child)
        if isinstance(data, dict) and data.get("contentType") == PDF_CONTENT_TYPE:
            pdfs.append(data)
    return pdfs


async def _score_pdf_children(
    client, children: list[dict]
) -> tuple[dict, list[dict], dict | None]:
    """Probe each PDF child and return the one holding the most text.

    An item routinely carries several PDFs: the paper plus press coverage of
    it.  Measured on one entry in this library, five PDFs held 6,903 / 11,871 /
    15,286 / 61,796 / 276,543 characters — only the longest is the paper, and
    it was listed last.  Returning the first child would silently hand back a
    news article, so the longest indexed text wins and every candidate is
    reported for the caller to inspect.

    Only compares when there is something to compare: a single PDF child is
    returned unprobed, which is the common case and avoids fetching a whole
    paper just to learn it is the only candidate.  The winning probe is handed
    back so the caller need not fetch it twice.

    Returns ``(best, candidates, payload)``; ``best`` is None for empty input.
    """
    if not children:
        return None, [], None
    if len(children) == 1:
        only = children[0]
        return only, [_unprobed_candidate(only)], None

    best = children[0]  # fall back to the first PDF when none is indexed
    best_chars = -1
    best_payload: dict | None = None
    candidates: list[dict] = []
    for child in children:
        key = str(child.get("key") or "")
        payload: dict | None = None
        chars = -1
        if key:
            try:
                payload = await _get_json(
                    client,
                    _local_api_url(f"/items/{key}/fulltext"),
                    timeout=LOCAL_API_PROBE_TIMEOUT,
                )
                chars = len(str(payload.get("content") or ""))
            except Exception:  # noqa: BLE001 - try the next candidate
                payload, chars = None, -1
        candidates.append(
            {"key": key, "chars": max(chars, 0), "indexed": chars >= 0}
        )
        if chars > best_chars:
            best, best_chars, best_payload = child, chars, payload
    return best, candidates, best_payload


async def _select_pdf_attachment(
    client, item_key: str
) -> tuple[dict | None, list[dict] | None, dict | None]:
    """Resolve a parent item to its best PDF attachment.

    Returns ``(best, candidates, payload)``.  ``candidates is None`` means the
    /children listing itself failed, which the caller must report differently
    from ``[]`` — an item that genuinely has no PDF child.
    """
    children = await _pdf_children(client, item_key)
    if children is None:
        return None, None, None
    if not children:
        return None, [], None
    best, candidates, payload = await _score_pdf_children(client, children)
    return best, candidates, payload


async def _read_local_path(client, attachment_key: str) -> str:
    """Resolve an attachment to a local filesystem path, or '' if unavailable."""
    try:
        response = await client.get(
            _local_api_url(f"/items/{attachment_key}/file/view/url"),
            timeout=LOCAL_API_PROBE_TIMEOUT,
        )
        response.raise_for_status()
        body = (response.text or "").strip()
    except Exception:  # noqa: BLE001 - metadata is still useful without a path
        return ""
    return _file_url_to_path(body) if body.startswith("file://") else body


def _unprobed_candidate(attachment: dict) -> dict:
    """A candidate entry for a PDF that never had to be compared.

    ``chars`` and ``indexed`` are present as ``None`` rather than omitted, so
    every entry has the same keys and a consumer can read ``c["chars"]``
    without a KeyError.  ``None`` means "not measured", which is not the same
    as 0.
    """
    return {"key": str(attachment.get("key") or ""), "chars": None, "indexed": None}


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
    error = _key_error("zotero_get_item", item_key)
    if error:
        return error
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
    error = _key_error(
        "zotero_get_collection_items", collection_key, label="collection_key"
    )
    if error:
        return error
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
    # None and "" both mean "the whole library" here (the else-branch below),
    # so they are not keys and must not be validated as such.  Anything else --
    # including a non-string like 0 -- is a key and gets checked, rather than
    # being silently treated as "omitted" by a bare truthiness test.
    if collection_key not in (None, ""):
        error = _key_error("zotero_get_tags", collection_key, label="collection_key")
        if error:
            return error
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
    error = _key_error("zotero_get_attachments", item_key)
    if error:
        return error
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
    error = _key_error("zotero_get_annotations", item_key)
    if error:
        return error
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


async def _fetch_fulltext_payload(client, item_key: str) -> tuple[dict | None, str]:
    """Indexed fulltext for ``item_key``, resolving a parent item if needed.

    Returns ``(payload, error_message)``; exactly one is populated.
    """
    url = _local_api_url(f"/items/{item_key}/fulltext")
    response = await client.get(url)
    if response.status_code != 404:
        response.raise_for_status()
        payload = response.json()
        payload["attachmentKey"] = item_key
        payload["attachmentCandidates"] = [
            {"key": item_key, "chars": len(str(payload.get("content") or "")), "indexed": True}
        ]
        return payload, ""

    # /fulltext only answers for attachment keys — the caller may have passed
    # the parent item, so resolve it through /children and try once more.
    attachment, candidates, payload = await _select_pdf_attachment(client, item_key)
    if candidates is None:
        return None, (
            f"Could not list attachments for {item_key} "
            f"(GET "
            f"{_path_only(_local_api_url(f'/items/{item_key}/children'))} "
            f"failed; {_path_only(url)} returned 404)"
        )
    if not candidates:
        return None, (
            f"No PDF attachment to read fulltext from for {item_key} "
            f"(GET {_path_only(url)} returned 404 and listing its children "
            f"found no {PDF_CONTENT_TYPE} attachment; the key may not exist)"
        )

    attachment_key = str((attachment or {}).get("key") or "")
    if not attachment_key:
        return None, f"No usable PDF attachment for {item_key}"

    if payload is None:
        # The winning candidate was never indexed; try it once so the error
        # names the real route rather than only the parent's.
        url = _local_api_url(f"/items/{attachment_key}/fulltext")
        response = await client.get(url)
        if response.status_code == 404:
            return None, (
                f"Fulltext not indexed for any PDF attachment of {item_key}; "
                f"tried {[c['key'] for c in candidates]} "
                f"(GET {_path_only(url)} returned 404)"
            )
        response.raise_for_status()
        payload = response.json()

    payload["attachmentKey"] = attachment_key
    payload["attachmentCandidates"] = candidates
    return payload, ""


@mcp.tool()
async def zotero_get_fulltext(item_key: str) -> str:
    """Get indexed full-text content for a Zotero item via the Local API.

    Accepts either a PDF attachment key or the key of a parent item that has a
    PDF attachment — a parent key is resolved through /children, and when the
    item carries several PDFs the one with the longest indexed text wins (see
    ``_select_pdf_attachment``).  Requires Zotero Desktop running on the host
    with local API enabled.

    Returns content, indexedPages, totalPages, itemKey, the attachmentKey the
    text actually came from, and attachmentCandidates describing every PDF
    considered.
    """
    if not item_key:
        return _make_error("zotero_get_fulltext", "item_key is required")
    error = _key_error("zotero_get_fulltext", item_key)
    if error:
        return error
    try:
        async with httpx.AsyncClient(
            timeout=LOCAL_API_TIMEOUT, headers=_local_api_headers()
        ) as client:
            payload, error = await _fetch_fulltext_payload(client, item_key)
            if error or payload is None:
                return _make_error("zotero_get_fulltext", error)
            payload["itemKey"] = item_key
            payload.setdefault("attachmentKey", item_key)
            return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001 - MCP tools report, never raise
        detail = _describe_exception(e)
        logger.error("zotero_get_fulltext(%s) failed: %s", item_key, detail)
        return _make_error(
            "zotero_get_fulltext",
            f"Local API request failed: {type(e).__name__}: {detail}",
        )


async def _build_file_info(client, item_key: str) -> tuple[dict | None, str]:
    """File metadata for a PDF attachment, resolving a parent item if needed.

    ``GET .../file`` answers 302 with a ``file://`` Location — for stored and
    linked attachments alike — which httpx cannot follow, so the result is
    assembled from the item JSON plus ``/file/view/url`` instead.

    Returns ``(payload, error_message)``; exactly one is populated.
    """
    item_url = _local_api_url(f"/items/{item_key}")
    response = await client.get(item_url)
    if response.status_code == 404:
        return None, (
            f"No item or attachment found for {item_key} "
            f"(GET {_path_only(item_url)} returned 404)"
        )
    response.raise_for_status()
    body = response.json()
    data = body.get("data", body) if isinstance(body, dict) else {}

    candidates: list[dict] = []
    attachment = data if data.get("itemType") == "attachment" else None
    if attachment is None:
        # Same selection as zotero_get_fulltext, so the metadata describes the
        # same PDF whose text that tool would return.  Picking the first child
        # here would mean handing out one PDF's path and another's fulltext.
        attachment, candidates, _ = await _select_pdf_attachment(client, item_key)
        if candidates is None:
            return None, (
                f"Could not list attachments for {item_key} "
                f"(GET "
                f"{_path_only(_local_api_url(f'/items/{item_key}/children'))} "
                f"failed)"
            )
        if not candidates:
            return None, (
                f"No PDF attachment found for {item_key} "
                f"({_path_only(item_url)} is not an attachment and has no "
                f"{PDF_CONTENT_TYPE} child)"
            )

    attachment_key = str(attachment.get("key") or "")
    if not attachment_key:
        # Mirrors zotero_get_fulltext: a child with no key cannot be addressed,
        # and reporting the parent's key here would name a file that is not the
        # one being described.
        return None, (
            f"No usable PDF attachment for {item_key} "
            f"(its PDF children carry no key)"
        )
    if not candidates:
        # Handed an attachment key directly, so nothing was compared.
        candidates = [_unprobed_candidate(attachment)]
    local_path = await _read_local_path(client, attachment_key)
    return (
        {
            "contentType": attachment.get("contentType") or "",
            "linkMode": attachment.get("linkMode") or "",
            "filename": _attachment_filename(attachment, local_path),
            "path": local_path or str(attachment.get("path") or ""),
            "size": ATTACHMENT_SIZE_UNAVAILABLE,
            "itemKey": item_key,
            "attachmentKey": attachment_key,
            "attachmentCandidates": candidates,
        },
        "",
    )


# ── Tool: zotero_get_file_info (Local API) ────────────────────────


@mcp.tool()
async def zotero_get_file_info(item_key: str) -> str:
    """Get attachment file metadata for a Zotero item via the Local API.

    Accepts either a PDF attachment key or a parent item key.  A parent key
    resolves through /children using the same rule as ``zotero_get_fulltext``
    — the PDF with the longest indexed text — so both tools describe the same
    file.  Requires Zotero Desktop running on the host with local API enabled.

    Returns contentType, linkMode, filename, path, size, itemKey,
    attachmentKey and attachmentCandidates.  ``path`` is the resolved local
    file path when Zotero can provide one.  ``size`` is always 0: the Local API
    reports no file size, and sizing one would mean stat-ing the user's disk
    (and hydrating Google Drive for linked attachments).

    ``attachmentCandidates`` carries ``chars``/``indexed`` only when several
    PDFs had to be compared; a lone PDF is reported as ``{"key": ...}``.
    """
    if not item_key:
        return _make_error("zotero_get_file_info", "item_key is required")
    error = _key_error("zotero_get_file_info", item_key)
    if error:
        return error
    try:
        async with httpx.AsyncClient(
            timeout=LOCAL_API_TIMEOUT, headers=_local_api_headers()
        ) as client:
            payload, error = await _build_file_info(client, item_key)
            if error or payload is None:
                return _make_error("zotero_get_file_info", error)
            return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001 - MCP tools report, never raise
        detail = _describe_exception(e)
        logger.error("zotero_get_file_info(%s) failed: %s", item_key, detail)
        return _make_error(
            "zotero_get_file_info",
            f"Local API request failed: {type(e).__name__}: {detail}",
        )


# ── Main ──────────────────────────────────────────────────────────


async def main() -> None:
    """Run the Zotero MCP server over streamable HTTP."""
    logger.info("Starting zotero-mcp on port 8002 (streamable HTTP at /mcp)")
    await mcp.run_streamable_http_async(host="0.0.0.0", port=8002)


if __name__ == "__main__":
    asyncio.run(main())
