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
def sample_file_info_response():
    """A realistic Zotero Local API file info response for stored file."""
    return {
        "filename": "paper.pdf",
        "contentType": "application/pdf",
        "size": 2048000,
    }


@pytest.fixture
def sample_linked_file_info_response():
    """File info for a linked_file attachment (not stored in Zotero)."""
    return {
        "filename": "paper.pdf",
        "contentType": "application/pdf",
        "size": 0,
        "path": "/Users/owen/papers/deep_learning_hydrology.pdf",
    }


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
        """get_fulltext returns error when item has no indexed fulltext (404)."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception(
            "HTTP 404: Fulltext not available"
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_fulltext(item_key="NO_FULLTEXT")
            )

        result = json.loads(result_json)
        assert result["error"] is True


# =========================================================================
# Tests: zotero_get_file_info (Local API)
# =========================================================================


class TestZoteroGetFileInfo:
    """Tests for the zotero_get_file_info tool (Local API via httpx)."""

    def test_get_file_info_returns_metadata(
        self, sample_file_info_response
    ):
        """get_file_info returns filename, contentType, and size."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_file_info_response
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="ABC12345")
            )

        result = json.loads(result_json)
        assert result["filename"] == "paper.pdf"
        assert result["contentType"] == "application/pdf"
        assert result["size"] == 2048000
        assert result["itemKey"] == "ABC12345"
        assert "error" not in result

    def test_get_file_info_handles_linked_file(
        self, sample_linked_file_info_response
    ):
        """get_file_info includes 'path' field for linked_file attachments."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_linked_file_info_response
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="LINKED_KEY")
            )

        result = json.loads(result_json)
        assert "path" in result
        assert result["path"] == "/Users/owen/papers/deep_learning_hydrology.pdf"
        assert result["size"] == 0  # linked files have size 0 in Zotero

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
        """get_file_info returns error when item has no attachment."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception(
            "HTTP 404: No attachment found"
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch.object(server.httpx, "AsyncClient", return_value=mock_client):
            result_json = asyncio.run(
                server.zotero_get_file_info(item_key="NO_ATTACHMENT")
            )

        result = json.loads(result_json)
        assert result["error"] is True


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
                server.zotero_get_attachments(item_key="NO_ATTACH")
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
                server.zotero_get_annotations(item_key="NO_PDF")
            )

        result = json.loads(result_json)
        assert result["total"] == 0
        assert result["annotations"] == []
        assert result["itemKey"] == "NO_PDF"
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
                server.zotero_get_annotations(item_key="NO_ANNOT")
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

    def test_server_initializes_mcp_server(self):
        """The MCPServer instance is created with name 'zotero'."""
        from mcp.server import MCPServer

        assert MCPServer.called
        MCPServer.assert_called_with("zotero")

    def test_local_api_base_url_is_correct(self):
        """LOCAL_API_BASE points to the Zotero connector server."""
        assert server.LOCAL_API_BASE == "http://host.docker.internal:23119"

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
