"""Tests for ``hydrolitagent/literature/zotero_sync.py`` — Zotero linked_file sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hydrolitagent.literature.download_pdf import PdfMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pdf_meta(title="Test Title", authors=None, doi="10.1234/test.1", pages=10) -> PdfMetadata:
    """Build a minimal PdfMetadata for testing."""
    return PdfMetadata(
        title=title,
        authors=authors or ["Smith, John"],
        doi=doi,
        pages=pages,
        version="1.7",
        file_size_bytes=12345,
    )


def _make_crossref_message():
    """Return a realistic Crossref API response for a journal article."""
    return {
        "title": ["Environmental modulation of storm–flood response"],
        "author": [
            {"given": "Alice", "family": "Brown"},
            {"given": "Bob", "family": "Chen"},
        ],
        "abstract": "<p>This paper investigates environmental modulation effects.</p>",
        "published-print": {"date-parts": [[2026, 5, 15]]},
        "type": "journal-article",
        "container-title": ["Journal of Hydrology"],
        "volume": "635",
        "issue": "3",
        "page": "135902",
        "ISSN": ["0022-1694"],
        "publisher": "Elsevier",
    }


# ---------------------------------------------------------------------------
# get_gdrive_papers_path
# ---------------------------------------------------------------------------

from hydrolitagent.literature.zotero_sync import get_gdrive_papers_path  # noqa: E402


def test_get_gdrive_papers_path_returns_path(monkeypatch):
    """Returns a Path when GDRIVE_PAPERS_PATH is set."""
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", "/home/user/GDrive/papers")
    result = get_gdrive_papers_path()
    assert result == Path("/home/user/GDrive/papers")


def test_get_gdrive_papers_path_raises_when_not_set(monkeypatch):
    """Raises ValueError when GDRIVE_PAPERS_PATH is not set."""
    monkeypatch.delenv("GDRIVE_PAPERS_PATH", raising=False)
    with pytest.raises(ValueError, match="GDRIVE_PAPERS_PATH must be set"):
        get_gdrive_papers_path()


def test_get_gdrive_papers_path_raises_when_empty(monkeypatch):
    """Raises ValueError when GDRIVE_PAPERS_PATH is empty string."""
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", "")
    with pytest.raises(ValueError, match="GDRIVE_PAPERS_PATH must be set"):
        get_gdrive_papers_path()


# ---------------------------------------------------------------------------
# get_zotero_client
# ---------------------------------------------------------------------------

from hydrolitagent.literature.zotero_sync import get_zotero_client  # noqa: E402


def test_get_zotero_client_raises_when_api_key_missing(monkeypatch):
    """Raises ValueError when ZOTERO_API_KEY is missing."""
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "12345")
    with pytest.raises(ValueError, match="ZOTERO_API_KEY"):
        get_zotero_client()


def test_get_zotero_client_raises_when_library_id_missing(monkeypatch):
    """Raises ValueError when ZOTERO_LIBRARY_ID is missing."""
    monkeypatch.setenv("ZOTERO_API_KEY", "test-key")
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    with pytest.raises(ValueError, match="ZOTERO_LIBRARY_ID"):
        get_zotero_client()


def test_get_zotero_client_returns_client(monkeypatch):
    """Returns a pyzotero Zotero client when env vars are set."""
    monkeypatch.setenv("ZOTERO_API_KEY", "test-key")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "12345")
    # Isolate from other test files that patch pyzotero in the same session.
    with patch("pyzotero.zotero.Zotero") as mock_cls:
        mock_cls.return_value.library_id = "12345"
        client = get_zotero_client()
    assert client is not None
    assert client.library_id == "12345"


# ---------------------------------------------------------------------------
# _copy_to_gdrive
# ---------------------------------------------------------------------------

from hydrolitagent.literature.zotero_sync import _copy_to_gdrive  # noqa: E402


def test_copy_to_gdrive_copies_file(tmp_path):
    """Copies a PDF to the GDrive directory with the given filename."""
    # Arrange
    src = tmp_path / "source.pdf"
    src.write_bytes(b"%PDF-1.4\nfake content")
    gdrive_dir = tmp_path / "gdrive"
    gdrive_dir.mkdir()

    # Act
    result = _copy_to_gdrive(src, gdrive_dir, "j.jhydrol.2024.132471.pdf")

    # Assert
    assert result.exists()
    assert result == gdrive_dir / "j.jhydrol.2024.132471.pdf"
    assert result.read_bytes() == b"%PDF-1.4\nfake content"
    # Source is still in place (copy, not move)
    assert src.exists()


def test_copy_to_gdrive_creates_parent_dirs(tmp_path):
    """Creates parent directories if they do not exist."""
    src = tmp_path / "source.pdf"
    src.write_bytes(b"content")
    gdrive_dir = tmp_path / "gdrive" / "subdir"

    result = _copy_to_gdrive(src, gdrive_dir, "paper.pdf")
    assert result.exists()
    assert result.parent == gdrive_dir


# ---------------------------------------------------------------------------
# Metadata delegation -> paper_to_zotero.build_item (arXiv-aware)
# ---------------------------------------------------------------------------


def test_builds_arxiv_preprint_when_crossref_missing(monkeypatch):
    """arXiv DOI (Crossref 404) -> correct preprint record via build_item.

    Regression: zotero_sync used to be Crossref-only and produced a sparse
    journalArticle from PDF-embedded metadata for arXiv papers.
    """
    from hydrolitagent.zotero import paper_to_zotero as p2z

    monkeypatch.setattr(p2z, "fetch_crossref", lambda doi: None)
    monkeypatch.setattr(p2z, "fetch_published_doi_s2", lambda arxiv_id: None)
    monkeypatch.setattr(
        p2z,
        "fetch_arxiv",
        lambda arxiv_id: {
            "title": "Earth System Foundation Model (ESFM): A unified framework",
            "summary": "An abstract about earth system modelling.",
            "authors": ["Firat Ozdemir", "Yun Cheng", "Torsten Hoefler"],
            "published": "2026-04-20",
            "primary_category": "cs.LG",
            "published_doi": None,
            "journal_ref": None,
        },
    )

    item, extra = p2z.build_item("10.48550/arXiv.2605.00850", {"title": "", "author": ""})

    assert item["itemType"] == "preprint"
    assert item["date"] == "2026-04-20"
    assert item["abstractNote"] == "An abstract about earth system modelling."
    assert len(item["creators"]) == 3
    assert extra["repository"] == "arXiv"
    assert extra["archiveID"] == "arXiv:2605.00850"


def test_builds_journal_article_from_crossref(monkeypatch):
    """Journal DOI still maps to journalArticle through build_item."""
    from hydrolitagent.zotero import paper_to_zotero as p2z

    cr = _make_crossref_message()
    monkeypatch.setattr(p2z, "fetch_crossref", lambda doi: cr)

    item, extra = p2z.build_item("10.1016/j.jhydrol.2026.135902", {"title": "", "author": ""})

    assert item["itemType"] == "journalArticle"
    assert item["publicationTitle"] == "Journal of Hydrology"
    assert item["volume"] == "635"
    assert item["date"] == "2026-05-15"
    assert len(item["creators"]) == 2


# ---------------------------------------------------------------------------
# Idempotence: DOI index (server scan + local cache)
# ---------------------------------------------------------------------------

from hydrolitagent.literature.zotero_sync import (  # noqa: E402
    _load_index,
    _save_index,
    _scan_server_dois,
)


def _mock_zot_scan(items):
    """MagicMock of a Zotero client: ``top()`` returns items, scan iterates them."""
    mock_zot = MagicMock()
    mock_zot.top.return_value = items
    mock_zot.everything.side_effect = lambda it: iter(it)
    return mock_zot


def test_scan_server_dois_maps_doi_to_key():
    mock_zot = _mock_zot_scan([
        {"key": "AAAA1111", "data": {"itemType": "journalArticle", "DOI": "10.1234/test.1"}},
    ])
    assert _scan_server_dois(mock_zot) == {"10.1234/test.1": "AAAA1111"}


def test_scan_server_dois_skips_attachments():
    mock_zot = _mock_zot_scan([
        {"key": "CCCC3333", "data": {"itemType": "attachment", "DOI": "10.1234/test.1"}},
    ])
    assert _scan_server_dois(mock_zot) == {}


def test_scan_server_dois_matches_extra_doi_line():
    mock_zot = _mock_zot_scan([
        {"key": "BBBB2222", "data": {
            "itemType": "preprint",
            "DOI": "",
            "extra": "\n".join([
                "repository: arXiv",
                "archiveID: arXiv:2501.08086",
                "DOI: 10.48550/arXiv.2501.08086",
            ]),
        }},
    ])
    assert _scan_server_dois(mock_zot) == {"10.48550/arXiv.2501.08086": "BBBB2222"}


def test_index_load_save_roundtrip(tmp_path):
    _save_index(tmp_path, {"10.1234/test.1": "AAAA1111"})
    assert _load_index(tmp_path) == {"10.1234/test.1": "AAAA1111"}


def test_index_load_returns_empty_when_missing(tmp_path):
    assert _load_index(tmp_path) == {}


# ---------------------------------------------------------------------------
# _create_zotero_item
# ---------------------------------------------------------------------------

from hydrolitagent.literature.zotero_sync import _create_zotero_item  # noqa: E402


def test_create_zotero_item_creates_parent_and_attachment():
    """Creates a parent item with a linked_file attachment."""
    # Arrange
    mock_zot = MagicMock()

    def _item_template(t, *args):
        return {"itemType": t, "title": "", "creators": []}

    mock_zot.item_template.side_effect = _item_template

    # Simulate successful parent creation
    parent_key = "ABC12345"
    mock_zot.create_items.side_effect = [
        {"success": {"0": parent_key}},  # parent item
        {"success": {"0": "XYZ98765"}},  # attachment
    ]

    item_data = {
        "title": "Test Paper",
        "DOI": "10.1234/test.1",
        "itemType": "journalArticle",
        "creators": [{"creatorType": "author", "firstName": "Alice", "lastName": "Brown"}],
        "date": "2026-05-15",
    }
    extra = {"publicationTitle": "Test Journal", "volume": "10"}

    # Act
    parent, attach = _create_zotero_item(mock_zot, item_data, extra, "test.pdf")

    # Assert
    assert parent == parent_key
    assert attach == "XYZ98765"

    # Verify the attachment was created with linked_file type
    attach_call = mock_zot.item_template.call_args_list[1]
    assert attach_call[0] == ("attachment", "linked_file")

    # Verify attachment path uses attachments: scheme
    attach_item = mock_zot.create_items.call_args_list[1][0][0][0]
    assert attach_item["path"] == "attachments:test.pdf"
    assert attach_item["parentItem"] == parent_key


def test_create_zotero_item_raises_on_parent_failure():
    """Raises RuntimeError when the Zotero API rejects the parent item."""
    mock_zot = MagicMock()
    mock_zot.item_template.return_value = {"itemType": "journalArticle"}
    mock_zot.create_items.return_value = {
        "success": {},
        "failed": {"0": {"message": "Title is required"}},
    }

    with pytest.raises(RuntimeError, match="Failed to create Zotero item"):
        _create_zotero_item(mock_zot, {"itemType": "journalArticle"}, {}, "test.pdf")


def test_create_zotero_item_attachment_failure_is_not_fatal():
    """Attachment key is empty string when attachment creation fails."""
    mock_zot = MagicMock()

    def _item_template(t, *args):
        return {"itemType": t}

    mock_zot.item_template.side_effect = _item_template
    mock_zot.create_items.side_effect = [
        {"success": {"0": "ABC12345"}},  # parent OK
        {"success": {}},  # attachment failed
    ]

    parent, attach = _create_zotero_item(mock_zot, {"itemType": "journalArticle"}, {}, "test.pdf")
    assert parent == "ABC12345"
    assert attach == ""
