"""Tests for zotero-mcp server.py -- FastMCP Zotero tools.

Tests for 12 MCP tools + helpers. All external calls are mocked.

Coverage:
  - _format_item helper (12 tests)
  - zotero_search (6 tests)
  - zotero_get_item (3 tests)
  - zotero_get_recent (4 tests)
  - zotero_get_collection_items (4 tests)
  - zotero_get_fulltext (4 tests)
  - zotero_get_file_info (4 tests)
  - zotero_get_collections (3 tests)  [NEW]
  - zotero_get_tags (3 tests)         [NEW]
  - zotero_search_by_tag (3 tests)    [NEW]
  - zotero_fulltext_search (3 tests)  [NEW]
  - zotero_get_attachments (3 tests)  [NEW]
  - zotero_get_annotations (4 tests)  [NEW]
  - Integration / initialization (4 tests)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# -- Stub external dependencies BEFORE importing the module under test --
# This prevents import errors when pyzotero, httpx, or mcp are not installed.

# MCPServer stub: preserve function identity through @mcp.tool() decorator
_mcp_server_module = MagicMock()
_mcp_instance = MagicMock()
_mcp_server_module.MCPServer = MagicMock(return_value=_mcp_instance)
# _mcp_instance.tool() returns a decorator that preserves the original function
_mcp_instance.tool.return_value = lambda f: f

sys.modules["mcp"] = MagicMock()
sys.modules["mcp.server"] = _mcp_server_module

# pyzotero stub
_pyzotero_module = MagicMock()
sys.modules["pyzotero"] = _pyzotero_module
sys.modules["pyzotero.zotero"] = _pyzotero_module.zotero

# httpx stub
_httpx_module = MagicMock()
sys.modules["httpx"] = _httpx_module

# -- Import the module under test --
from hydrolitagent.zotero import server  # noqa: E402


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def sample_zotero_item():
    """A realistic Zotero API item response with the data envelope."""
    return {
        "key": "ABC12345",
        "version": 1234,
        "library": {"type": "user", "id": 123456, "name": "owen"},
        "links": {
            "self": {"href": "https://api.zotero.org/users/123456/items/ABC12345"},
        },
        "meta": {
            "createdByUser": {"id": 123456, "username": "owen"},
            "lastModifiedByUser": {"id": 123456, "username": "owen"},
        },
        "data": {
            "key": "ABC12345",
            "version": 1234,
            "itemType": "journalArticle",
            "title": "Deep Learning for Hydrology: A Comprehensive Review",
            "creators": [
                {
                    "firstName": "Jane",
                    "lastName": "Smith",
                    "creatorType": "author",
                },
                {
                    "firstName": "John",
                    "lastName": "Doe",
                    "creatorType": "author",
                },
            ],
            "date": "2026-06-15",
            "DOI": "10.1234/test.2026",
            "abstractNote": (
                "A comprehensive study of deep learning applications in "
                "hydrological modeling, covering LSTM networks, transformers, "
                "and physics-informed neural networks for streamflow "
                "prediction, flood forecasting, and water quality assessment."
            ),
            "url": "https://doi.org/10.1234/test.2026",
            "publicationTitle": "Journal of Machine Learning",
            "volume": "45",
            "issue": "3",
            "pages": "100-120",
            "tags": [{"tag": "deep learning"}, {"tag": "hydrology"}],
        },
    }


@pytest.fixture
def sample_zotero_item_list(sample_zotero_item):
    """A list with one Zotero item, as returned by search/recent endpoints."""
    return [sample_zotero_item]


@pytest.fixture
def sample_zotero_item_list_empty():
    """Empty list as returned when no items match."""
    return []


@pytest.fixture
def sample_fulltext_response():
    """A realistic Zotero Local API fulltext response."""
    return {
        "content": (
            "Abstract\n\nThis paper presents a comprehensive review of deep "
            "learning applications in hydrological modeling. We examine LSTM "
            "networks, transformers, and physics-informed neural networks.\n\n"
            "Introduction\n\nHydrological modeling is critical for water resource "
            "management, flood forecasting, and climate change adaptation..."
        ),
        "indexedPages": 12,
        "totalPages": 15,
    }


@pytest.fixture
def sample_stored_attachment_item():
    """A REAL Local API payload for a *stored* attachment.

    Copied from a live Zotero Desktop :23119 response (item 2TAZ6RX4).  Note
    what is NOT here: there is no `size` field, and `path` is null while
    `filename` is set -- the mirror image of a linked attachment.
    """
    return {
        "key": "STORED001",
        "data": {
            "key": "STORED001",
            "itemType": "attachment",
            "contentType": "application/pdf",
            "linkMode": "imported_file",
            "filename": "paper.pdf",
            "title": "paper.pdf",
            "path": None,
        },
    }


@pytest.fixture
def sample_linked_attachment_item():
    """A REAL Local API payload for a `linked_file` attachment.

    Captured from a live response: `filename` is null and `path` carries the
    ``attachments:`` prefix.  No `size` field exists.
    """
    return {
        "key": "FXERFCH2",
        "data": {
            "key": "FXERFCH2",
            "itemType": "attachment",
            "contentType": "application/pdf",
            "linkMode": "linked_file",
            "filename": None,
            "title": "Lu 等 - 2024 - The AI Scientist.pdf",
            "path": "attachments:Lu 等 - 2024 - The AI Scientist.pdf",
        },
    }


@pytest.fixture
def sample_parent_item():
    """A journal article (non-attachment) that owns PDF children."""
    return {
        "key": "6HF7ADML",
        "data": {
            "key": "6HF7ADML",
            "itemType": "journalArticle",
            "title": "The AI Scientist",
        },
    }


@pytest.fixture
def sample_children_with_pdf():
    """Children listing including a non-PDF attachment ahead of the PDF."""
    return [
        {
            "key": "LINKEDURL",
            "data": {"key": "LINKEDURL", "itemType": "attachment"},
        },
        {
            "key": "FXERFCH2",
            "data": {
                "key": "FXERFCH2",
                "itemType": "attachment",
                "contentType": "application/pdf",
                "linkMode": "linked_file",
                "path": "attachments:Lu 等 - 2024 - The AI Scientist.pdf",
                "filename": None,
            },
        },
    ]


@pytest.fixture
def sample_file_view_url():
    """GET .../file/view/url returns the local path as text/plain, not JSON."""
    return (
        "file:///G:/%E6%88%91%E7%9A%84%E4%BA%91%E7%AB%AF%E7%A1%AC%E7%9B%98"
        "/Documents/Papers/Zotero_Papers/Lu%20%E7%AD%89%20-%202024%20-%20The%20AI%20Scientist.pdf"
    )


def _make_response(payload=None, *, status=200, raise_error=None, text=None, headers=None):
    """Build a stand-in for an httpx.Response.

    `status` drives the branch the code takes; `raise_error` mirrors
    ``raise_for_status()`` raising on 4xx/5xx.
    """
    response = MagicMock()
    response.status_code = status
    response.headers = headers or {}
    if payload is not None:
        response.json.return_value = payload
    if text is not None:
        response.text = text
    if raise_error is not None:
        response.raise_for_status.side_effect = raise_error
    else:
        response.raise_for_status = MagicMock()
    return response


def _make_client(responses):
    """Patch target for httpx.AsyncClient, returning `responses` in order.

    Pass a single MagicMock for "every call returns this", or a list for a
    scripted sequence.  ``client.get.call_args_list`` records the real URLs.
    """
    client = AsyncMock()
    if isinstance(responses, list):
        client.get.side_effect = responses
    else:
        client.get.return_value = responses
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    return client


def _requested_urls(client):
    """The URLs actually passed to client.get(), in order."""
    return [call[0][0] for call in client.get.call_args_list]


@pytest.fixture
def sample_no_attachment_response():
    """Response when item has no attachment."""
    return {}


@pytest.fixture
def mock_zot_client():
    """A mock pyzotero.Zotero client with common methods."""
    client = MagicMock()
    client.items = MagicMock()
    client.item = MagicMock()
    client.top = MagicMock()
    client.collection_items = MagicMock()
    client.collections = MagicMock()
    client.collection_tags = MagicMock()
    client.tags = MagicMock()
    client.children = MagicMock()
    return client


# =========================================================================
# Tests: _format_item helper
# =========================================================================


class TestFormatItem:
    """Tests for the _format_item() helper that extracts key fields."""

    def test_extracts_key_fields(self, sample_zotero_item):
        """_format_item extracts key, title, itemType, date, DOI from data."""
        result = server._format_item(sample_zotero_item)

        assert result["key"] == "ABC12345"
        assert result["title"] == "Deep Learning for Hydrology: A Comprehensive Review"
        assert result["itemType"] == "journalArticle"
        assert result["date"] == "2026-06-15"
        assert result["DOI"] == "10.1234/test.2026"

    def test_formats_creator_names(self, sample_zotero_item):
        """Creator names are formatted as 'FirstName LastName'."""
        result = server._format_item(sample_zotero_item)

        assert result["creators"] == ["Jane Smith", "John Doe"]

    def test_handles_single_creator(self):
        """Single creator works correctly."""
        item = {
            "data": {
                "key": "KEY001",
                "title": "Solo Paper",
                "itemType": "journalArticle",
                "creators": [
                    {"firstName": "Alice", "lastName": "Wang", "creatorType": "author"},
                ],
                "date": "2026-01-01",
                "DOI": "",
                "abstractNote": "",
            },
        }

        result = server._format_item(item)

        assert result["creators"] == ["Alice Wang"]

    def test_handles_institutional_author_with_name_field(self):
        """Institutional authors use the 'name' field (no firstName/lastName)."""
        item = {
            "data": {
                "key": "KEY002",
                "title": "Report",
                "itemType": "report",
                "creators": [
                    {"name": "World Health Organization", "creatorType": "author"},
                ],
                "date": "2026-01-01",
                "DOI": "",
                "abstractNote": "",
            },
        }

        result = server._format_item(item)

        assert result["creators"] == ["World Health Organization"]

    def test_handles_mixed_creators(self):
        """Mix of personal and institutional authors."""
        item = {
            "data": {
                "key": "KEY003",
                "title": "Mixed Authors",
                "itemType": "journalArticle",
                "creators": [
                    {"firstName": "Jane", "lastName": "Smith", "creatorType": "author"},
                    {"name": "NASA Climate Group", "creatorType": "author"},
                    {"firstName": "Bob", "lastName": "Lee", "creatorType": "author"},
                ],
                "date": "2026-01-01",
                "DOI": "",
                "abstractNote": "",
            },
        }

        result = server._format_item(item)

        assert result["creators"] == ["Jane Smith", "NASA Climate Group", "Bob Lee"]

    def test_includes_abstract_snippet(self, sample_zotero_item):
        """Abstract is included as abstractSnippet when present."""
        result = server._format_item(sample_zotero_item)

        assert "abstractSnippet" in result
        assert result["abstractSnippet"].startswith("A comprehensive study")

    def test_truncates_long_abstract(self):
        """Abstracts longer than 300 chars are truncated with ellipsis."""
        long_abstract = "X" * 500
        item = {
            "data": {
                "key": "KEY004",
                "title": "Long Abstract",
                "itemType": "journalArticle",
                "creators": [],
                "date": "2026-01-01",
                "DOI": "",
                "abstractNote": long_abstract,
            },
        }

        result = server._format_item(item)

        assert len(result["abstractSnippet"]) == 303  # 300 chars + "..."
        assert result["abstractSnippet"].endswith("...")

    def test_handles_missing_abstract(self):
        """abstractSnippet is omitted when abstractNote is empty."""
        item = {
            "data": {
                "key": "KEY005",
                "title": "No Abstract",
                "itemType": "journalArticle",
                "creators": [],
                "date": "2026-01-01",
                "DOI": "",
                "abstractNote": "",
            },
        }

        result = server._format_item(item)

        assert "abstractSnippet" not in result

    def test_includes_url_when_present(self, sample_zotero_item):
        """URL field is included when data has a url."""
        result = server._format_item(sample_zotero_item)

        assert "url" in result
        assert result["url"] == "https://doi.org/10.1234/test.2026"

    def test_handles_data_envelope(self, sample_zotero_item):
        """Works with items that have top-level 'data' sub-object."""
        # sample_zotero_item has the data envelope
        result = server._format_item(sample_zotero_item)

        assert result["key"] == "ABC12345"
        assert result["title"].startswith("Deep Learning")

    def test_handles_raw_data_dict(self):
        """Works with items that are the data dict directly (no envelope)."""
        raw_item = {
            "key": "DIRECT99",
            "title": "Direct Item",
            "itemType": "book",
            "creators": [
                {"firstName": "Tom", "lastName": "Jones", "creatorType": "author"},
            ],
            "date": "2026-01-01",
            "DOI": "10.9999/direct",
            "abstractNote": "Direct abstract.",
        }

        result = server._format_item(raw_item)

        assert result["key"] == "DIRECT99"
        assert result["title"] == "Direct Item"
        assert result["itemType"] == "book"
        assert result["creators"] == ["Tom Jones"]
        assert result["DOI"] == "10.9999/direct"

    def test_handles_editor_as_creator(self):
        """Editors are included as creators (not just authors)."""
        item = {
            "data": {
                "key": "KEY006",
                "title": "Edited Volume",
                "itemType": "book",
                "creators": [
                    {"firstName": "Mary", "lastName": "Chen", "creatorType": "editor"},
                    {"firstName": "David", "lastName": "Kim", "creatorType": "author"},
                ],
                "date": "2026-01-01",
                "DOI": "",
                "abstractNote": "",
            },
        }

        result = server._format_item(item)

        assert result["creators"] == ["Mary Chen", "David Kim"]


# =========================================================================
# Tests: zotero_search
# =========================================================================


class TestZoteroSearch:
    """Tests for the zotero_search tool (Web API via pyzotero)."""

    def test_search_returns_formatted_items(
        self, mock_zot_client, sample_zotero_item_list
    ):
        """Search returns formatted items with total count."""
        mock_zot_client.items.return_value = sample_zotero_item_list

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_search(query="hydrology", limit=10)
            )

        result = json.loads(result_json)
        assert result["total"] == 1
        assert result["query"] == "hydrology"
        assert len(result["items"]) == 1
        assert result["items"][0]["key"] == "ABC12345"
        assert "error" not in result

    def test_search_handles_empty_results(
        self, mock_zot_client, sample_zotero_item_list_empty
    ):
        """Search returns zero total when no items match."""
        mock_zot_client.items.return_value = sample_zotero_item_list_empty

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_search(query="nonexistent")
            )

        result = json.loads(result_json)
        assert result["total"] == 0
        assert result["items"] == []
        assert result["query"] == "nonexistent"

    def test_search_handles_api_error(self, mock_zot_client):
        """Search returns error JSON when the Zotero API fails."""
        mock_zot_client.items.side_effect = Exception("Zotero API connection error")

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_search(query="hydrology")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "context" in result
        assert "message" in result

    def test_search_respects_limit_parameter(self, mock_zot_client):
        """Search passes the limit parameter through to the API."""
        mock_zot_client.items.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            asyncio.run(server.zotero_search(query="test", limit=5))

        # Verify the API was called with the correct limit
        mock_zot_client.items.assert_called_once()
        call_kwargs = mock_zot_client.items.call_args[1]
        assert call_kwargs.get("limit") == 5

    def test_search_uses_default_limit(self, mock_zot_client):
        """Search defaults to limit=10 when not specified."""
        mock_zot_client.items.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            asyncio.run(server.zotero_search(query="test"))

        call_kwargs = mock_zot_client.items.call_args[1]
        assert call_kwargs.get("limit") == 10


# =========================================================================
# Tests: zotero_get_item
# =========================================================================


class TestZoteroGetItem:
    """Tests for the zotero_get_item tool (Web API via pyzotero)."""

    def test_get_item_returns_complete_json(
        self, mock_zot_client, sample_zotero_item
    ):
        """get_item returns the full item JSON for a valid key."""
        mock_zot_client.item.return_value = sample_zotero_item

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_item(item_key="ABC12345")
            )

        result = json.loads(result_json)
        assert result["key"] == "ABC12345"
        assert "data" in result
        assert result["data"]["title"].startswith("Deep Learning")

    def test_get_item_missing_key_raises_error(self, mock_zot_client):
        """get_item returns error when item_key is empty/missing."""
        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_item(item_key="")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "item_key" in result["message"].lower()
        # Should not have called the API
        mock_zot_client.item.assert_not_called()

    def test_get_item_not_found_handles_404(self, mock_zot_client):
        """get_item returns error JSON when item is not found (404)."""
        mock_zot_client.item.side_effect = Exception("HTTP 404: Item not found")

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_item(item_key="NONEXIST")
            )

        result = json.loads(result_json)
        assert result["error"] is True


# =========================================================================
# Tests: zotero_get_recent
# =========================================================================


class TestZoteroGetRecent:
    """Tests for the zotero_get_recent tool (Web API via pyzotero)."""

    def test_get_recent_returns_items(
        self, mock_zot_client, sample_zotero_item_list
    ):
        """get_recent returns recent items with total count."""
        mock_zot_client.top.return_value = sample_zotero_item_list

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_recent(limit=10)
            )

        result = json.loads(result_json)
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert "error" not in result

    def test_get_recent_with_since_filter(self, mock_zot_client):
        """get_recent passes the since parameter to the API."""
        mock_zot_client.top.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            asyncio.run(
                server.zotero_get_recent(limit=5, since="2026-07-01")
            )

        mock_zot_client.top.assert_called_once()
        call_kwargs = mock_zot_client.top.call_args[1]
        assert call_kwargs.get("limit") == 5
        assert call_kwargs.get("since") == "2026-07-01"

    def test_get_recent_handles_api_error(self, mock_zot_client):
        """get_recent returns error JSON when API fails."""
        mock_zot_client.top.side_effect = Exception("API unavailable")

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_recent()
            )

        result = json.loads(result_json)
        assert result["error"] is True

    def test_get_recent_uses_default_limit(self, mock_zot_client):
        """get_recent defaults to limit=10 when not specified."""
        mock_zot_client.top.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            asyncio.run(server.zotero_get_recent())

        call_kwargs = mock_zot_client.top.call_args[1]
        assert call_kwargs.get("limit") == 10


# =========================================================================
# Tests: zotero_get_collection_items
# =========================================================================


class TestZoteroGetCollectionItems:
    """Tests for the zotero_get_collection_items tool (Web API via pyzotero)."""

    def test_get_collection_items_returns_items(
        self, mock_zot_client, sample_zotero_item_list
    ):
        """get_collection_items returns items in a collection with metadata."""
        mock_zot_client.collection_items.return_value = sample_zotero_item_list

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_collection_items(collection_key="COLKEY01", limit=20)
            )

        result = json.loads(result_json)
        assert result["total"] == 1
        assert result["collectionKey"] == "COLKEY01"
        assert len(result["items"]) == 1
        assert result["items"][0]["key"] == "ABC12345"
        assert "error" not in result

    def test_get_collection_items_missing_key_raises_error(self, mock_zot_client):
        """get_collection_items returns error when collection_key is missing."""
        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_collection_items(collection_key="")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "collection_key" in result["message"].lower()
        mock_zot_client.collection_items.assert_not_called()

    def test_get_collection_items_handles_api_error(self, mock_zot_client):
        """get_collection_items returns error JSON when API fails."""
        mock_zot_client.collection_items.side_effect = Exception("Collection not found")

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_collection_items(collection_key="INVALID")
            )

        result = json.loads(result_json)
        assert result["error"] is True

    def test_get_collection_items_respects_limit(self, mock_zot_client):
        """get_collection_items passes limit to API and uses default 20."""
        mock_zot_client.collection_items.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            asyncio.run(
                server.zotero_get_collection_items(collection_key="COLKEY01")
            )

        call_kwargs = mock_zot_client.collection_items.call_args[1]
        assert call_kwargs.get("limit") == 20


# =========================================================================
# Tests: zotero_get_fulltext (Local API)
# =========================================================================


class TestZoteroGetFulltext:
    """Tests for the zotero_get_fulltext tool (Local API via httpx)."""

    def test_get_fulltext_returns_content_and_metadata(
        self, sample_fulltext_response
    ):
        """get_fulltext returns content, indexedPages, and totalPages."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_fulltext_response
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="ABC12345")
            )

        result = json.loads(result_json)
        assert result["content"] == sample_fulltext_response["content"]
        assert result["indexedPages"] == 12
        assert result["totalPages"] == 15
        assert result["itemKey"] == "ABC12345"
        assert "error" not in result

    def test_get_fulltext_missing_key_raises_error(self):
        """get_fulltext returns error when item_key is empty."""
        result_json = asyncio.run(
            server.zotero_get_fulltext(item_key="")
        )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "item_key" in result["message"].lower()

    def test_get_fulltext_handles_local_api_unreachable(self):
        """get_fulltext returns error when Local API is unreachable."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = OSError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="ABC12345")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "context" in result
        assert "message" in result

    def test_get_fulltext_handles_item_not_indexed(self):
        """An item with no PDF child is reported as such, not simply 404'd.

        The response is a MagicMock, not an AsyncMock: httpx's
        ``raise_for_status`` and ``json`` are synchronous, and mocking them as
        async silently skips the raise (which hid the 404 path from this test).
        """
        no_pdf = [{"key": "LINK", "data": {"key": "LINK", "itemType": "attachment"}}]
        mock_client = _make_client(
            [
                _make_response(status=404, raise_error=Exception("HTTP 404")),
                _make_response(no_pdf),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="NOFULLTXT")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "pdf" in result["message"].lower()

    def test_get_fulltext_distinguishes_a_failed_children_lookup(self):
        """A broken /children must not be reported as 'no PDF'."""
        mock_client = _make_client(
            _make_response(status=404, raise_error=Exception("HTTP 404"))
        )

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="NOFULLTXT")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "could not list attachments" in result["message"].lower()
        assert "/children" in result["message"]


# =========================================================================
# Tests: zotero_get_file_info (Local API)
# =========================================================================


class TestZoteroGetFileInfo:
    """Tests for the zotero_get_file_info tool (Local API via httpx)."""

    def test_get_file_info_reports_no_size_for_a_stored_attachment(
        self, sample_stored_attachment_item, sample_file_view_url
    ):
        """`size` is always 0 — the Local API exposes no file size.

        REWRITTEN TWICE, and the second rewrite is the instructive one.  The
        original fixture invented ``size: 2048000``.  The first rewrite guessed
        it came from the Content-Length of ``GET .../file`` — but measured
        against a live Zotero, that route answers **302 for stored and linked
        attachments alike**, so the Content-Length branch was dead code and its
        test mocked a 200 response that never occurs.  That is the same class of
        fiction the original bug hid behind.  Nothing is fetched for size now.
        """
        client = _make_client(
            [
                _make_response(sample_stored_attachment_item),
                _make_response(text=sample_file_view_url),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="STORED001")
            )

        result = json.loads(result_json)
        assert "error" not in result
        assert result["filename"] == "paper.pdf"
        assert result["contentType"] == "application/pdf"
        assert result["linkMode"] == "imported_file"
        assert result["size"] == 0
        assert result["itemKey"] == "STORED001"
        assert result["attachmentKey"] == "STORED001"
        # No request may be made to the /file route, which cannot serve a size.
        assert not any(
            url.endswith("/file") for url in _requested_urls(client)
        )

    def test_get_file_info_handles_linked_file(
        self, sample_linked_attachment_item, sample_file_view_url
    ):
        """A linked_file resolves its local path and reports size 0.

        REWRITTEN: the old fixture hand-wrote a Unix path.  The real response
        for a workspace PDF is a Google Drive path with a null ``filename`` and
        an ``attachments:`` prefix on ``path``.
        """
        client = _make_client(
            [
                _make_response(sample_linked_attachment_item),
                _make_response(text=sample_file_view_url),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="FXERFCH2")
            )

        result = json.loads(result_json)
        assert "error" not in result
        assert result["linkMode"] == "linked_file"
        assert "The AI Scientist.pdf" in result["path"]
        # Reading the file off Google Drive would trigger a hydration hang, so
        # linked attachments deliberately report 0 rather than stat the path.
        assert result["size"] == 0

    def test_get_file_info_handles_local_api_unreachable(self):
        """get_file_info returns error when Local API is unreachable."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = OSError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="ABC12345")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "context" in result
        assert "message" in result

    def test_get_file_info_handles_no_attachment(self):
        """get_file_info returns error when the key resolves to nothing."""
        mock_client = _make_client(
            _make_response(status=404, raise_error=Exception("HTTP 404"))
        )

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="NOATTACH1")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "NOATTACH1" in result["message"]


# =========================================================================
# Fixtures for new tools
# =========================================================================


@pytest.fixture
def sample_collections_list():
    """A realistic Zotero collections response."""
    return [
        {
            "key": "COLA1B2C",
            "version": 42,
            "name": "Hydrology",
            "parentCollection": False,
        },
        {
            "key": "COLD3E4F",
            "version": 17,
            "name": "Deep Learning",
            "parentCollection": "COLA1B2C",
        },
    ]


@pytest.fixture
def sample_annotations():
    """Realistic Zotero PDF annotation items."""
    return [
        {
            "key": "ANN0001",
            "version": 5,
            "data": {
                "key": "ANN0001",
                "itemType": "annotation",
                "annotationType": "highlight",
                "annotationText": "LSTM outperforms traditional models",
                "annotationComment": "Key finding",
                "annotationColor": "#ffd400",
                "annotationPageLabel": "3",
                "parentItem": "ATTACH99",
            },
        },
        {
            "key": "ANN0002",
            "version": 8,
            "data": {
                "key": "ANN0002",
                "itemType": "annotation",
                "annotationType": "note",
                "annotationText": "",
                "annotationComment": "Check the cited reference for methodology details",
                "annotationColor": "#5fb236",
                "annotationPageLabel": "5",
                "parentItem": "ATTACH99",
            },
        },
    ]


# =========================================================================
# Tests: zotero_get_collections (NEW)
# =========================================================================


class TestZoteroGetCollections:
    """Tests for the zotero_get_collections tool (Web API via pyzotero)."""

    def test_returns_collections_list(
        self, mock_zot_client, sample_collections_list
    ):
        """get_collections returns collection key, name, version."""
        mock_zot_client.collections.return_value = sample_collections_list

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_collections(limit=50)
            )

        result = json.loads(result_json)
        assert result["total"] == 2
        assert len(result["collections"]) == 2
        assert result["collections"][0]["key"] == "COLA1B2C"
        assert result["collections"][0]["name"] == "Hydrology"
        assert result["collections"][1]["parentCollection"] == "COLA1B2C"
        assert "error" not in result

    def test_handles_empty_library(self, mock_zot_client):
        """Empty library returns zero total, not an error."""
        mock_zot_client.collections.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_collections()
            )

        result = json.loads(result_json)
        assert result["total"] == 0
        assert result["collections"] == []
        assert "error" not in result

    def test_handles_api_error(self, mock_zot_client):
        """Returns error JSON when API fails."""
        mock_zot_client.collections.side_effect = Exception("API unavailable")

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_collections()
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "context" in result
        assert "message" in result


# =========================================================================
# Tests: zotero_get_tags (NEW)
# =========================================================================


class TestZoteroGetTags:
    """Tests for the zotero_get_tags tool (Web API via pyzotero)."""

    def test_returns_all_tags(self, mock_zot_client):
        """get_tags returns a list of tag strings."""
        mock_zot_client.tags.return_value = ["deep learning", "hydrology", "LSTM"]

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_tags()
            )

        result = json.loads(result_json)
        assert result["total"] == 3
        assert result["tags"] == ["deep learning", "hydrology", "LSTM"]
        assert "error" not in result

    def test_returns_tags_for_collection(self, mock_zot_client):
        """get_tags filters by collection_key when provided."""
        mock_zot_client.collection_tags.return_value = ["hydrology"]

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_tags(collection_key="COLA1B2C")
            )

        result = json.loads(result_json)
        assert result["total"] == 1
        assert result["tags"] == ["hydrology"]
        assert result["collectionKey"] == "COLA1B2C"
        mock_zot_client.collection_tags.assert_called_once_with("COLA1B2C")
        # tags() should NOT be called when collection_key is provided
        mock_zot_client.tags.assert_not_called()

    def test_handles_api_error(self, mock_zot_client):
        """Returns error JSON when API fails."""
        mock_zot_client.tags.side_effect = Exception("API unavailable")

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_tags()
            )

        result = json.loads(result_json)
        assert result["error"] is True


# =========================================================================
# Tests: zotero_search_by_tag (NEW)
# =========================================================================


class TestZoteroSearchByTag:
    """Tests for the zotero_search_by_tag tool (Web API via pyzotero)."""

    def test_returns_items_with_tag(
        self, mock_zot_client, sample_zotero_item_list
    ):
        """search_by_tag returns formatted items matching a tag."""
        mock_zot_client.items.return_value = sample_zotero_item_list

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_search_by_tag(tag="hydrology", limit=20)
            )

        result = json.loads(result_json)
        assert result["total"] == 1
        assert result["tag"] == "hydrology"
        assert len(result["items"]) == 1
        assert result["items"][0]["key"] == "ABC12345"
        assert "error" not in result

    def test_missing_tag_returns_error(self, mock_zot_client):
        """search_by_tag returns error when tag is empty."""
        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_search_by_tag(tag="")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "tag" in result["message"].lower()
        mock_zot_client.items.assert_not_called()

    def test_passes_tag_to_api(self, mock_zot_client):
        """search_by_tag passes the tag parameter to items()."""
        mock_zot_client.items.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            asyncio.run(server.zotero_search_by_tag(tag="hydrology"))

        call_kwargs = mock_zot_client.items.call_args[1]
        assert call_kwargs.get("tag") == "hydrology"
        assert call_kwargs.get("limit") == 20


# =========================================================================
# Tests: zotero_fulltext_search (NEW)
# =========================================================================


class TestZoteroFulltextSearch:
    """Tests for the zotero_fulltext_search tool (Web API via pyzotero)."""

    def test_returns_items_with_fulltext_match(
        self, mock_zot_client, sample_zotero_item_list
    ):
        """fulltext_search returns items matching across all fields."""
        mock_zot_client.items.return_value = sample_zotero_item_list

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_fulltext_search(query="streamflow prediction", limit=20)
            )

        result = json.loads(result_json)
        assert result["total"] == 1
        assert result["query"] == "streamflow prediction"
        assert len(result["items"]) == 1
        assert "error" not in result

    def test_passes_qmode_everything_to_api(self, mock_zot_client):
        """fulltext_search uses qmode='everything' for full-text search."""
        mock_zot_client.items.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            asyncio.run(server.zotero_fulltext_search(query="neural network"))

        call_kwargs = mock_zot_client.items.call_args[1]
        assert call_kwargs.get("q") == "neural network"
        assert call_kwargs.get("qmode") == "everything"

    def test_missing_query_returns_error(self, mock_zot_client):
        """fulltext_search returns error when query is empty."""
        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_fulltext_search(query="")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "query" in result["message"].lower()
        mock_zot_client.items.assert_not_called()


# =========================================================================
# Tests: zotero_get_attachments (NEW)
# =========================================================================


class TestZoteroGetAttachments:
    """Tests for the zotero_get_attachments tool (Web API via pyzotero)."""

    def test_returns_attachments_list(self, mock_zot_client):
        """get_attachments returns child items of type attachment."""
        attachments = [
            {
                "key": "ATTACH99",
                "version": 12,
                "data": {
                    "key": "ATTACH99",
                    "itemType": "attachment",
                    "title": "paper.pdf",
                    "filename": "paper.pdf",
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                    "md5": "abc123",
                    "size": 2048000,
                },
            },
            {
                "key": "NOTE01",
                "version": 3,
                "data": {
                    "key": "NOTE01",
                    "itemType": "note",
                    "note": "Important paper",
                },
            },
        ]
        mock_zot_client.children.return_value = attachments

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_attachments(item_key="ABC12345")
            )

        result = json.loads(result_json)
        # Should include both attachment and note children
        assert result["total"] == 2
        assert len(result["attachments"]) == 2
        assert result["itemKey"] == "ABC12345"
        assert "error" not in result

    def test_missing_key_returns_error(self, mock_zot_client):
        """get_attachments returns error when item_key is empty."""
        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_attachments(item_key="")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "item_key" in result["message"].lower()
        mock_zot_client.children.assert_not_called()

    def test_handles_item_with_no_attachments(self, mock_zot_client):
        """Item with no children returns empty list."""
        mock_zot_client.children.return_value = []

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_attachments(item_key="NOATTACH1")
            )

        result = json.loads(result_json)
        assert result["total"] == 0
        assert result["attachments"] == []
        assert "error" not in result


# =========================================================================
# Tests: zotero_get_annotations (NEW)
# =========================================================================


class TestZoteroGetAnnotations:
    """Tests for the zotero_get_annotations tool (Web API, two-step)."""

    def test_returns_annotations_from_pdf_attachment(
        self, mock_zot_client, sample_annotations
    ):
        """get_annotations traverses paper→attachment→annotations."""
        # Step 1: paper has a PDF attachment child
        paper_children = [
            {
                "key": "ATTACH99",
                "version": 12,
                "data": {
                    "key": "ATTACH99",
                    "itemType": "attachment",
                    "title": "paper.pdf",
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                },
            },
            {
                "key": "NOTE01",
                "version": 3,
                "data": {
                    "key": "NOTE01",
                    "itemType": "note",
                    "note": "Important paper",
                },
            },
        ]
        # Step 2: the attachment has annotation children
        attachment_children = sample_annotations

        # First children() call returns paper's direct children
        # Second call returns the attachment's children
        mock_zot_client.children.side_effect = [
            paper_children,
            attachment_children,
        ]

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_annotations(item_key="ABC12345")
            )

        result = json.loads(result_json)
        assert result["total"] == 2
        assert result["itemKey"] == "ABC12345"
        assert len(result["annotations"]) == 2
        assert result["annotations"][0]["key"] == "ANN0001"
        assert result["annotations"][0]["type"] == "highlight"
        assert result["annotations"][0]["text"] == "LSTM outperforms traditional models"
        assert result["annotations"][0]["color"] == "#ffd400"
        assert result["annotations"][0]["page"] == "3"
        assert result["annotations"][1]["type"] == "note"
        assert result["annotations"][1]["comment"] == (
            "Check the cited reference for methodology details"
        )
        assert "error" not in result

    def test_missing_key_returns_error(self, mock_zot_client):
        """get_annotations returns error when item_key is empty."""
        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_annotations(item_key="")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "item_key" in result["message"].lower()
        mock_zot_client.children.assert_not_called()

    def test_handles_item_with_no_attachment(self, mock_zot_client):
        """Paper with no attachment children returns empty annotations."""
        # Paper has children but no attachment type
        mock_zot_client.children.return_value = [
            {
                "key": "NOTE01",
                "version": 3,
                "data": {
                    "key": "NOTE01",
                    "itemType": "note",
                    "note": "Important paper",
                },
            },
        ]

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_annotations(item_key="NOPDF0001")
            )

        result = json.loads(result_json)
        assert result["total"] == 0
        assert result["annotations"] == []
        assert result["itemKey"] == "NOPDF0001"
        assert "error" not in result

    def test_handles_attachment_with_no_annotations(self, mock_zot_client):
        """PDF attachment exists but has no annotation children."""
        paper_children = [
            {
                "key": "ATTACH99",
                "version": 12,
                "data": {
                    "key": "ATTACH99",
                    "itemType": "attachment",
                    "title": "paper.pdf",
                    "contentType": "application/pdf",
                },
            },
        ]

        mock_zot_client.children.side_effect = [
            paper_children,
            [],  # attachment has no annotations
        ]

        with patch.object(server, "_zot", mock_zot_client):
            result_json = asyncio.run(
                server.zotero_get_annotations(item_key="NOANNOT1")
            )

        result = json.loads(result_json)
        assert result["total"] == 0
        assert result["annotations"] == []
        assert "error" not in result


# =========================================================================
# Tests: Integration / Initialization
# =========================================================================


class TestWebApiUnavailable:
    """Tests for graceful degradation when _zot is None (no API key)."""

    def test_search_returns_error_when_no_zot_client(self):
        """zotero_search returns error when pyzotero client is not initialized."""
        with patch.object(server, "_zot", None):
            result_json = asyncio.run(
                server.zotero_search(query="test")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert result["context"] == "zotero_search"
        assert "not initialized" in result["message"].lower()

    def test_get_item_returns_error_when_no_zot_client(self):
        """zotero_get_item returns error when pyzotero client is not initialized."""
        with patch.object(server, "_zot", None):
            result_json = asyncio.run(
                server.zotero_get_item(item_key="ABC12345")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert result["context"] == "zotero_get_item"
        assert "not initialized" in result["message"].lower()

    def test_get_recent_returns_error_when_no_zot_client(self):
        """zotero_get_recent returns error when pyzotero client is not initialized."""
        with patch.object(server, "_zot", None):
            result_json = asyncio.run(
                server.zotero_get_recent(limit=10)
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert result["context"] == "zotero_get_recent"
        assert "not initialized" in result["message"].lower()


class TestServerInitialization:
    """Tests for server module-level initialization."""

    def test_exposes_twelve_zotero_tools(self):
        """The server registers exactly 12 zotero_* tools.

        Asserted as a contract on the module rather than on the stubbed
        constructor: this file's ``sys.modules`` stubs only take effect if it
        wins the import race against other test modules, so asserting
        "MCPServer was called" made the result depend on collection order.
        """
        tool_names = sorted(n for n in dir(server) if n.startswith("zotero_"))
        assert tool_names == [
            "zotero_fulltext_search",
            "zotero_get_annotations",
            "zotero_get_attachments",
            "zotero_get_collection_items",
            "zotero_get_collections",
            "zotero_get_file_info",
            "zotero_get_fulltext",
            "zotero_get_item",
            "zotero_get_recent",
            "zotero_get_tags",
            "zotero_search",
            "zotero_search_by_tag",
        ]

    def test_local_api_base_url_is_correct(self, monkeypatch):
        """The resolver's default targets the host from inside a container."""
        monkeypatch.delenv("ZOTERO_LOCAL_BASE_URL", raising=False)
        monkeypatch.delenv("ZOTERO_LOCAL_API_URL", raising=False)

        assert (
            server._resolve_local_api_base() == "http://host.docker.internal:23119"
        )

    def test_env_vars_have_sensible_defaults(self, monkeypatch):
        """Module-level config defaults are set correctly."""
        # Reload the module with controlled env
        import importlib

        with monkeypatch.context() as m:
            m.delenv("ZOTERO_API_KEY", raising=False)
            m.delenv("ZOTERO_LIBRARY_ID", raising=False)
            m.delenv("ZOTERO_LIBRARY_TYPE", raising=False)

            # The server was already imported; just verify the constants exist
            assert hasattr(server, "ZOTERO_API_KEY")
            assert hasattr(server, "ZOTERO_LIBRARY_ID")
            assert hasattr(server, "ZOTERO_LIBRARY_TYPE")
            assert server.ZOTERO_LIBRARY_TYPE in ("user", "group")

    def test_web_api_client_initialized_when_env_vars_present(self):
        """pyzotero.Zotero is called when ZOTERO_API_KEY and ZOTERO_LIBRARY_ID are set."""
        from pyzotero.zotero import Zotero

        # Since our stubbed env has no env vars, _zot may be None
        # But the Zotero constructor pattern is imported and available
        assert hasattr(server, "_zot")


# =========================================================================
# Tests: Local API URL construction (regression -- the /api/users/0 segment)
# =========================================================================


class TestLocalApiUrlConstruction:
    """The Local API lives under /api/users/0; omitting it 404s every call.

    These assert on the *request URL* rather than the response, because the
    pre-existing tests only ever mocked responses -- which is structurally why
    a wrong URL could never fail them.
    """

    def test_fulltext_url_includes_local_api_user_segment(
        self, sample_fulltext_response
    ):
        client = _make_client(_make_response(sample_fulltext_response))

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            asyncio.run(server.zotero_get_fulltext(item_key="FXERFCH2"))

        url = _requested_urls(client)[0]
        assert "/api/users/0/items/FXERFCH2/fulltext" in url, (
            f"Local API fulltext needs the /api/users/0 segment, got: {url}"
        )

    def test_file_info_url_includes_local_api_user_segment(
        self, sample_linked_attachment_item, sample_file_view_url
    ):
        client = _make_client(
            [
                _make_response(sample_linked_attachment_item),
                _make_response(text=sample_file_view_url),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            asyncio.run(server.zotero_get_file_info(item_key="FXERFCH2"))

        for url in _requested_urls(client):
            assert "/api/users/0/items/" in url, (
                f"every Local API call needs the /api/users/0 segment, got: {url}"
            )

    def test_fulltext_404_error_reports_requested_path(self):
        """A 404 must not be reported as 'not indexed' without the path.

        The original message ("Fulltext not indexed for item X") described a
        business outcome for what was actually a misconfigured URL, which is
        why this went unnoticed.
        """
        client = _make_client(
            _make_response(status=404, raise_error=Exception("HTTP 404"))
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="NOFULLTXT")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "/api/users/0/items/NOFULLTXT/fulltext" in result["message"]

    def test_transport_error_message_does_not_leak_the_host(self):
        """httpx embeds the full request URL in its exception messages.

        The 404 path builds its message with ``_path_only`` and was already
        covered; this exercises the ``raise_for_status`` path, whose message
        carries the configured host verbatim.
        """
        leaky = Exception(
            "Server error '500 Internal Server Error' for url "
            "'http://host.docker.internal:23119/api/users/0/items/ABCX0001/fulltext'"
        )
        client = _make_client(_make_response(status=500, raise_error=leaky))

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="ABCX0001")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "host.docker.internal" not in result["message"]
        assert "/api/users/0/items/ABCX0001/fulltext" in result["message"]


# =========================================================================
# Tests: item_key validation at the boundary
# =========================================================================


class TestItemKeyValidation:
    """`item_key` arrives from an MCP client and lands in a request path.
    Dot segments survive httpx's normalisation, so it is validated up front."""

    @pytest.mark.parametrize(
        "bad_key",
        [
            "../../collections",
            "ABC/../..",
            "ABC?q=1",
            "ABC#frag",
            "x" * 33,
            "ABC 123",
        ],
    )
    def test_rejects_a_key_that_could_reshape_the_request(self, bad_key):
        result = json.loads(
            asyncio.run(server.zotero_get_fulltext(item_key=bad_key))
        )

        assert result["error"] is True
        assert "well-formed" in result["message"]

    def test_rejects_a_malformed_key_for_file_info_too(self):
        result = json.loads(
            asyncio.run(server.zotero_get_file_info(item_key="../items"))
        )

        assert result["error"] is True
        assert "well-formed" in result["message"]

    def test_accepts_a_real_zotero_key(self):
        assert server._valid_key("6HF7ADML") is True
        assert server._valid_key("FXERFCH2") is True
        assert server._valid_key("") is False

    def test_a_non_string_key_is_rejected_not_raised_on(self):
        """A direct caller passing a non-string must get an error, not a
        TypeError out of a tool that promises to report rather than raise."""
        assert server._valid_key(123) is False
        assert server._valid_key(None) is False

        mock_zot = MagicMock()
        with patch.object(server, "_zot", mock_zot):
            result = json.loads(asyncio.run(server.zotero_get_item(item_key=123)))

        # Assert the *guard's* message, not merely "some error": a downstream
        # API failure would also set error=True and say nothing about the key.
        assert result["error"] is True
        assert "well-formed" in result["message"]
        assert mock_zot.mock_calls == []

    def test_tags_with_a_non_string_key_is_rejected_by_the_guard(self):
        """A falsy non-key such as 0 must not be read as "collection omitted"."""
        mock_zot = MagicMock()
        # Give the library-wide branch something serialisable, so reverting the
        # guard fails on the assertion rather than on a MagicMock not being
        # JSON-serialisable (which would obscure what broke).
        mock_zot.tags.return_value = []

        with patch.object(server, "_zot", mock_zot):
            result = json.loads(
                asyncio.run(server.zotero_get_tags(collection_key=0))
            )

        assert result["error"] is True
        assert "well-formed" in result["message"]
        assert mock_zot.mock_calls == []


# =========================================================================
# Tests: the 5 Web API tools that take a key validate it too
# =========================================================================


class TestWebApiKeyValidation:
    """These tools pass the client-supplied key straight to pyzotero, which
    interpolates it into an *authenticated* api.zotero.org path
    (``items/{key.upper()}``).  A key such as ``../../collections`` survives
    httpx's dot-segment normalisation and reaches a different endpoint on the
    user's own library, so it is rejected before pyzotero sees it."""

    MALFORMED = "../../collections"

    @pytest.mark.parametrize(
        "tool_name, kwargs",
        [
            ("zotero_get_item", {"item_key": "../../collections"}),
            ("zotero_get_attachments", {"item_key": "../../collections"}),
            ("zotero_get_annotations", {"item_key": "../../collections"}),
            ("zotero_get_collection_items", {"collection_key": "../../collections"}),
            ("zotero_get_tags", {"collection_key": "../../collections"}),
        ],
    )
    def test_rejects_a_malformed_key_before_calling_pyzotero(self, tool_name, kwargs):
        mock_zot = MagicMock()

        with patch.object(server, "_zot", mock_zot):
            result = json.loads(asyncio.run(getattr(server, tool_name)(**kwargs)))

        assert result["error"] is True
        assert "well-formed" in result["message"]
        # Nothing may reach the authenticated API.
        assert mock_zot.mock_calls == []

    def test_a_well_formed_key_still_reaches_pyzotero(self, sample_zotero_item):
        mock_zot = MagicMock()
        mock_zot.item.return_value = sample_zotero_item

        with patch.object(server, "_zot", mock_zot):
            result = json.loads(
                asyncio.run(server.zotero_get_item(item_key="ABC12345"))
            )

        assert "error" not in result
        mock_zot.item.assert_called_once_with("ABC12345")

    def test_tags_without_a_collection_key_is_still_allowed(self):
        """collection_key is optional; the guard must not reject None."""
        mock_zot = MagicMock()
        mock_zot.tags.return_value = []

        with patch.object(server, "_zot", mock_zot):
            result = json.loads(asyncio.run(server.zotero_get_tags()))

        assert "error" not in result
        assert mock_zot.collection_tags.call_count == 0
        # The library-wide listing must actually have been asked for.
        mock_zot.tags.assert_called_once()

    def test_tags_with_an_empty_collection_key_means_the_whole_library(self):
        """An empty string has always meant "no collection" here.

        The pre-existing branch is `if collection_key:` (truthy), so "" falls
        through to the library-wide listing.  Guarding on `is not None` would
        reject it as a malformed key and turn a working call into an error —
        a behaviour regression even though it fails closed.
        """
        mock_zot = MagicMock()
        mock_zot.tags.return_value = []

        with patch.object(server, "_zot", mock_zot):
            result = json.loads(asyncio.run(server.zotero_get_tags(collection_key="")))

        assert "error" not in result
        assert mock_zot.collection_tags.call_count == 0
        mock_zot.tags.assert_called_once()

    def test_key_error_helper_returns_none_for_a_good_key(self):
        assert server._key_error("zotero_get_item", "ABC12345") is None

    def test_key_error_helper_labels_the_parameter(self):
        message = json.loads(
            server._key_error("zotero_get_tags", "../x", label="collection_key")
        )["message"]

        assert "collection_key" in message


# =========================================================================
# Tests: resolving an item key to its PDF attachment (regression)
# =========================================================================


class TestFulltextAttachmentResolution:
    """`/fulltext` only answers for an *attachment* key; an item key must be
    resolved through /children rather than surfaced as a bare 404."""

    def test_attachment_key_costs_a_single_request(self, sample_fulltext_response):
        client = _make_client(_make_response(sample_fulltext_response))

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="FXERFCH2")
            )

        result = json.loads(result_json)
        assert "error" not in result
        assert len(_requested_urls(client)) == 1

    def test_item_key_is_resolved_to_pdf_attachment(
        self, sample_fulltext_response, sample_children_with_pdf
    ):
        client = _make_client(
            [
                _make_response(status=404, raise_error=Exception("HTTP 404")),
                _make_response(sample_children_with_pdf),
                _make_response(sample_fulltext_response),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="6HF7ADML")
            )

        result = json.loads(result_json)
        assert "error" not in result
        assert result["attachmentKey"] == "FXERFCH2"
        assert result["content"] == sample_fulltext_response["content"]

        urls = _requested_urls(client)
        assert urls[0].endswith("/items/6HF7ADML/fulltext")
        assert urls[1].endswith("/items/6HF7ADML/children")
        assert urls[2].endswith("/items/FXERFCH2/fulltext")

    def test_a_lone_pdf_child_costs_no_extra_probe(
        self, sample_fulltext_response, sample_children_with_pdf
    ):
        """With one candidate there is nothing to compare, so it is used as-is.

        Probing it would mean reading a whole paper just to learn it is the
        only one — and a single PDF is the common case for a normal item.
        """
        client = _make_client(
            [
                _make_response(status=404, raise_error=Exception("HTTP 404")),
                _make_response(sample_children_with_pdf),
                _make_response(sample_fulltext_response),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="PARENT01")
            )

        result = json.loads(result_json)
        assert "error" not in result
        # Same keys as a probed candidate, with None meaning "not measured".
        assert result["attachmentCandidates"] == [
            {"key": "FXERFCH2", "chars": None, "indexed": None}
        ]
        # 404 -> /children -> the single fulltext fetch.  No selection probe.
        assert len(_requested_urls(client)) == 3

    def test_error_when_item_has_no_pdf_child(self):
        no_pdf = [
            {"key": "LINK", "data": {"key": "LINK", "itemType": "attachment"}},
        ]
        client = _make_client(
            [
                _make_response(status=404, raise_error=Exception("HTTP 404")),
                _make_response(no_pdf),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="HASNOPDF1")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "pdf" in result["message"].lower()

    def test_longest_pdf_wins_when_an_item_has_several(self):
        """A parent item may carry the paper plus press coverage of it.

        Measured live on item 6HF7ADML: five PDF children holding 6,903 /
        11,871 / 15,286 / 61,796 / 276,543 characters, where only the longest
        is the paper -- and it was listed LAST.  Taking the first child hands
        back a news article while looking perfectly successful.
        """
        short, long = "SHORT0001", "LONG00002"
        children = [
            {
                "key": short,
                "data": {
                    "key": short,
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                },
            },
            {
                "key": long,
                "data": {
                    "key": long,
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                },
            },
        ]
        short_payload = {"content": "x" * 6903, "indexedPages": 1, "totalPages": 1}
        long_payload = {"content": "y" * 276543, "indexedPages": 186, "totalPages": 186}

        client = _make_client(
            [
                _make_response(status=404, raise_error=Exception("HTTP 404")),
                _make_response(children),
                _make_response(short_payload),
                _make_response(long_payload),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="6HF7ADML")
            )

        result = json.loads(result_json)
        assert "error" not in result
        assert result["attachmentKey"] == long
        assert result["content"] == long_payload["content"]
        # Every candidate is reported, so a wrong pick is visible.
        assert result["attachmentCandidates"] == [
            {"key": short, "chars": 6903, "indexed": True},
            {"key": long, "chars": 276543, "indexed": True},
        ]

    def test_unindexed_candidates_still_report_the_attempt(self):
        """When no child is indexed the error names every key that was tried."""
        children = [
            {
                "key": "NOPE0001",
                "data": {
                    "key": "NOPE0001",
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                },
            },
            {
                "key": "NOPE0002",
                "data": {
                    "key": "NOPE0002",
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                },
            },
        ]
        not_indexed = _make_response(
            status=404, raise_error=Exception("HTTP 404")
        )
        client = _make_client(
            [
                not_indexed,  # /items/PARENT/fulltext
                _make_response(children),  # /children
                not_indexed,  # probe NOPE0001
                not_indexed,  # probe NOPE0002
                not_indexed,  # retry the fallback pick
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="PARENT01")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "NOPE0001" in result["message"]
        assert "NOPE0002" in result["message"]


# =========================================================================
# Tests: file_info against the real endpoint contract
# =========================================================================


class TestFileInfoRealContract:
    """`GET .../file` is a 302 to a ``file://`` URL that httpx cannot follow, so
    file_info must build its answer from the item JSON plus /file/view/url."""

    def test_parent_item_key_resolves_to_attachment(
        self, sample_parent_item, sample_children_with_pdf, sample_file_view_url
    ):
        client = _make_client(
            [
                _make_response(sample_parent_item),
                _make_response(sample_children_with_pdf),
                _make_response(text=sample_file_view_url),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="6HF7ADML")
            )

        result = json.loads(result_json)
        assert "error" not in result
        assert result["itemKey"] == "6HF7ADML"
        assert result["attachmentKey"] == "FXERFCH2"
        assert result["contentType"] == "application/pdf"
        assert result["linkMode"] == "linked_file"
        # A lone PDF needs no comparison, so no fulltext is fetched here.
        assert result["attachmentCandidates"] == [
            {"key": "FXERFCH2", "chars": None, "indexed": None}
        ]
        assert len(_requested_urls(client)) == 3
        # /children is listed exactly once, not once per resolution step
        assert sum(
            url.endswith("/children") for url in _requested_urls(client)
        ) == 1

    def test_filename_derived_from_attachments_path_prefix(
        self, sample_linked_attachment_item, sample_file_view_url
    ):
        """`filename` is null on linked attachments; strip the ``attachments:``
        prefix from `path` instead."""
        client = _make_client(
            [
                _make_response(sample_linked_attachment_item),
                _make_response(text=sample_file_view_url),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="FXERFCH2")
            )

        result = json.loads(result_json)
        assert result["filename"] == "Lu 等 - 2024 - The AI Scientist.pdf"
        assert not result["filename"].startswith("attachments:")

    def test_keyless_pdf_child_is_refused_not_mislabelled(self):
        """A child with no key must not be reported under the parent's key.

        zotero_get_fulltext already errors here; file_info used to fall back to
        the parent item key, naming a file that is not the one described.
        """
        children = [
            {"data": {"itemType": "attachment", "contentType": "application/pdf"}}
        ]
        client = _make_client(
            [
                _make_response(
                    {
                        "key": "PARENT01",
                        "data": {"key": "PARENT01", "itemType": "journalArticle"},
                    }
                ),
                _make_response(children),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="PARENT01")
            )

        result = json.loads(result_json)
        assert result["error"] is True
        assert "no key" in result["message"]

    def test_file_view_url_failure_still_returns_metadata(
        self, sample_linked_attachment_item
    ):
        """A view/url hiccup must degrade, not lose the whole answer."""
        client = _make_client(
            [
                _make_response(sample_linked_attachment_item),
                _make_response(status=500, raise_error=Exception("HTTP 500")),
            ]
        )

        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="FXERFCH2")
            )

        result = json.loads(result_json)
        assert "error" not in result
        assert result["contentType"] == "application/pdf"
        # falls back to the raw Zotero path field
        assert "The AI Scientist.pdf" in result["path"]


# =========================================================================
# Tests: .env loading must never clobber container-provided env vars
# =========================================================================


class TestEnvFileLoading:
    """The server runs in a container where env comes from the host.  Loading
    .env must therefore be additive only."""

    def test_env_file_fills_missing_vars(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("HYDROLITAGENT_TEST_FILL=from-file\n", encoding="utf-8")
        monkeypatch.delenv("HYDROLITAGENT_TEST_FILL", raising=False)

        assert server._load_env_file(env_file) is True
        assert os.environ["HYDROLITAGENT_TEST_FILL"] == "from-file"

    def test_env_file_does_not_override_existing_vars(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("HYDROLITAGENT_TEST_KEEP=from-file\n", encoding="utf-8")
        monkeypatch.setenv("HYDROLITAGENT_TEST_KEEP", "from-container")

        assert server._load_env_file(env_file) is True
        assert os.environ["HYDROLITAGENT_TEST_KEEP"] == "from-container"

    def test_missing_dotenv_package_is_a_noop(self, tmp_path, monkeypatch):
        """The container image has no python-dotenv; loading must not explode."""
        env_file = tmp_path / ".env"
        env_file.write_text("HYDROLITAGENT_TEST_X=1\n", encoding="utf-8")
        # A None entry in sys.modules makes `from dotenv import ...` raise ImportError.
        monkeypatch.setitem(sys.modules, "dotenv", None)

        assert server._load_env_file(env_file) is False


# =========================================================================
# Tests: Local API best-effort helpers
# =========================================================================


class TestAttachmentHelpers:
    """These degrade rather than raise -- the tools are diagnostic surfaces,
    so a missing size or path must not lose the rest of the answer."""

    def test_filename_prefers_the_explicit_field(self):
        attachment = {"filename": "a.pdf", "path": "attachments:b.pdf"}

        assert server._attachment_filename(attachment) == "a.pdf"

    def test_filename_strips_the_attachments_prefix(self):
        attachment = {"filename": None, "path": "attachments:Lu 等 - 2024.pdf"}

        assert server._attachment_filename(attachment) == "Lu 等 - 2024.pdf"

    def test_filename_falls_back_to_local_path(self):
        attachment = {"filename": None}

        assert (
            server._attachment_filename(attachment, r"G:\papers\deep learning.pdf")
            == "deep learning.pdf"
        )

    def test_filename_falls_back_to_title(self):
        assert server._attachment_filename({"title": "paper.pdf"}) == "paper.pdf"

    def test_file_url_to_path_decodes_gdrive_urls(self):
        path = server._file_url_to_path(
            "file:///G:/%E6%88%91%E7%9A%84%E4%BA%91%E7%AB%AF%E7%A1%AC%E7%9B%98"
            "/Documents/Papers/x.pdf"
        )

        assert path.endswith("x.pdf")
        assert "我的云端硬盘" in path
        assert not path.startswith("/G:")

    def test_pdf_children_returns_none_when_the_lookup_fails(self):
        """A failed /children is distinguishable from an item with no PDF."""
        client = _make_client(
            _make_response(status=500, raise_error=Exception("HTTP 500"))
        )

        assert asyncio.run(server._pdf_children(client, "K")) is None

    def test_pdf_children_ignores_a_non_list_payload(self):
        client = _make_client(_make_response({"unexpected": "dict"}))

        assert asyncio.run(server._pdf_children(client, "K")) == []

    def test_pdf_children_skips_non_dict_and_non_pdf_entries(self):
        client = _make_client(
            _make_response(
                [
                    "junk",
                    {"data": {"itemType": "attachment"}},
                    {"data": {"contentType": "application/pdf", "key": "P1"}},
                ]
            )
        )

        assert asyncio.run(server._pdf_children(client, "K")) == [
            {"contentType": "application/pdf", "key": "P1"}
        ]

    def test_select_pdf_attachment_falls_back_to_the_first_when_none_indexed(self):
        children = [
            {"key": "A1", "data": {"key": "A1", "contentType": "application/pdf"}},
            {"key": "B2", "data": {"key": "B2", "contentType": "application/pdf"}},
        ]
        client = _make_client(
            [
                _make_response(children),
                _make_response(status=404, raise_error=Exception("HTTP 404")),
                _make_response(status=404, raise_error=Exception("HTTP 404")),
            ]
        )

        best, candidates, payload = asyncio.run(
            server._select_pdf_attachment(client, "PARENT01")
        )

        assert best["key"] == "A1"
        assert payload is None
        assert candidates == [
            {"key": "A1", "chars": 0, "indexed": False},
            {"key": "B2", "chars": 0, "indexed": False},
        ]

    def test_describe_exception_survives_an_empty_message(self):
        """httpx transport errors stringify to ''; that must not blank the report."""

        class Silent(Exception):
            def __str__(self) -> str:
                return ""

        assert server._describe_exception(Silent()) == "Silent"

    def test_describe_exception_reduces_urls_to_their_path(self):
        """No message may carry the configured host out to the client."""

        class Leaky(Exception):
            def __str__(self) -> str:
                return (
                    "Server error '500' for url "
                    "'http://host.docker.internal:23119/api/users/0/items/X/fulltext'"
                )

        described = server._describe_exception(Leaky())

        assert "host.docker.internal" not in described
        assert "/api/users/0/items/X/fulltext" in described

    def test_path_only_strips_the_host(self):
        assert (
            server._path_only("http://h:23119/api/users/0/items/X/fulltext")
            == "/api/users/0/items/X/fulltext"
        )

    def test_path_only_fails_closed_on_a_bare_host_url(self):
        """A URL with no path must not fall back to the whole URL.

        `urlparse("http://host:23119").path` is empty, so an `or url` fallback
        hands the host straight back — the exact opposite of this function's
        purpose.
        """
        assert server._path_only("http://host.docker.internal:23119") == "/"

    def test_describe_exception_scrubs_a_bare_host_url(self):
        leaked = server._describe_exception(
            Exception("failed to connect to http://host.docker.internal:23119")
        )

        assert "host.docker.internal" not in leaked

    def test_valid_key_rejects_a_trailing_newline(self):
        """`$` matches before a final newline; `\\Z` does not."""
        assert server._valid_key("6HF7ADML\n") is False

    def test_pdf_children_ignores_a_string_data_field(self):
        client = _make_client(
            _make_response([{"key": "X", "data": "junk-string"}])
        )

        assert asyncio.run(server._pdf_children(client, "K")) == []

    def test_score_pdf_children_handles_empty_input(self):
        best, candidates, payload = asyncio.run(
            server._score_pdf_children(None, [])
        )

        assert (best, candidates, payload) == (None, [], None)


# =========================================================================
# Tests: Local API base URL env var aliasing (container compatibility)
# =========================================================================


class TestLocalApiEnvAliasing:
    """`ZOTERO_LOCAL_BASE_URL` is the unified name; `ZOTERO_LOCAL_API_URL` must
    keep working because container compose files already set it."""

    def test_unified_name_wins(self, monkeypatch):
        monkeypatch.setenv("ZOTERO_LOCAL_BASE_URL", "http://from-base:23119")
        monkeypatch.setenv("ZOTERO_LOCAL_API_URL", "http://from-legacy:23119")
        assert server._resolve_local_api_base() == "http://from-base:23119"

    def test_legacy_name_still_honored(self, monkeypatch):
        monkeypatch.delenv("ZOTERO_LOCAL_BASE_URL", raising=False)
        monkeypatch.setenv("ZOTERO_LOCAL_API_URL", "http://from-legacy:23119")
        assert server._resolve_local_api_base() == "http://from-legacy:23119"


# =========================================================================
# Tests: Local API Host header (container -> host reachability)
# =========================================================================


class TestLocalApiHostHeader:
    """The Local API client must present a loopback ``Host``.

    Zotero's local server validates ``Host`` as DNS-rebinding protection and
    answers ``400 Bad request`` to anything that is not the literal
    ``127.0.0.1``/``localhost``.  Measured against Zotero 9.0.6: not even other
    loopback addresses are accepted -- ``Host: 127.0.0.2:23119`` is rejected
    exactly like ``host.docker.internal:23119``.

    The default base is ``host.docker.internal``: the only name that reaches the
    host from inside a container, and precisely what Zotero refuses.  The
    loopback form is therefore set explicitly and the port carried over from the
    base -- the connection still lands on ``LOCAL_API_BASE``, only what Zotero
    reads as the destination changes.

    Every test in this file otherwise runs on a bare host where the base is
    already loopback, which is why the container-only breakage was invisible.
    """

    def test_container_default_is_rewritten_to_loopback(self, monkeypatch):
        monkeypatch.setattr(
            server, "LOCAL_API_BASE", "http://host.docker.internal:23119"
        )
        assert server._local_api_headers() == {"Host": "127.0.0.1:23119"}

    def test_port_follows_the_base(self, monkeypatch):
        """A non-default port must be carried over, not assumed."""
        monkeypatch.setattr(server, "LOCAL_API_BASE", "http://zotero.internal:9999")
        assert server._local_api_headers() == {"Host": "127.0.0.1:9999"}

    @pytest.mark.parametrize(
        "base", ["http://127.0.0.1:23119", "http://localhost:23119"]
    )
    def test_loopback_base_is_already_correct(self, monkeypatch, base):
        """Host-side runs keep sending exactly what they sent before."""
        monkeypatch.setattr(server, "LOCAL_API_BASE", base)
        assert server._local_api_headers() == {}

    @pytest.mark.parametrize(
        "call",
        [
            lambda: server.zotero_get_fulltext(item_key="ABC12345"),
            lambda: server.zotero_get_file_info(item_key="ABC12345"),
        ],
        ids=["get_fulltext", "get_file_info"],
    )
    def test_both_local_tools_build_their_client_with_it(self, monkeypatch, call):
        """A helper nothing calls is not a fix -- pin the call sites."""
        monkeypatch.setattr(
            server, "LOCAL_API_BASE", "http://host.docker.internal:23119"
        )
        seen = {}

        def fake_client(*args, **kwargs):
            seen.update(kwargs)
            mock_client = AsyncMock()
            mock_client.get.return_value = _make_response({"content": "x"})
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            return mock_client

        with patch.object(server.httpx, "AsyncClient", fake_client):
            asyncio.run(call())

        assert seen.get("headers") == {"Host": "127.0.0.1:23119"}
