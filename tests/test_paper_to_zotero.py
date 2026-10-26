"""Tests for paper-to-zotero.py — focus on build_item() field routing logic."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# Stub pyzotero before loading the module under test (not installed locally)
_pyzotero_mock = MagicMock()
sys.modules["pyzotero"] = _pyzotero_mock
sys.modules["pyzotero.zotero"] = _pyzotero_mock.zotero

from hydrolitagent.zotero import paper_to_zotero


# ── Helpers ──────────────────────────────────────────────────────────


def _make_creators(*names):
    """Build creator list from "Family, Given" pairs."""
    creators = []
    for name in names:
        parts = name.split(", ", 1)
        creators.append({
            "creatorType": "author",
            "lastName": parts[0],
            "firstName": parts[1] if len(parts) > 1 else "",
        })
    return creators


# ── Tests ────────────────────────────────────────────────────────────


class TestJournalArticleRouting:
    """For journalArticle, journal metadata belongs in standard Zotero fields."""

    def test_publication_title_in_item_not_extra(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "volume": "17",
            "issue": "1",
            "page": "123-145",
            "ISSN": ["2041-1723"],
            "publisher": "Springer",
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/test", {})

        assert item["publicationTitle"] == "Nature Communications"
        assert "publicationTitle" not in extra

    def test_volume_in_item_not_extra(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "volume": "17",
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/test", {})

        assert item["volume"] == "17"
        assert "volume" not in extra

    def test_issue_in_item_not_extra(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "issue": "1",
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/test", {})

        assert item["issue"] == "1"
        assert "issue" not in extra

    def test_pages_in_item_not_extra(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "page": "123-145",
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/test", {})

        assert item["pages"] == "123-145"
        assert "pages" not in extra

    def test_issn_in_item_not_extra(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "ISSN": ["2041-1723"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/test", {})

        assert item["ISSN"] == "2041-1723"
        assert "ISSN" not in extra

    def test_publisher_in_item_not_extra(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "publisher": "Springer",
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/test", {})

        assert item["publisher"] == "Springer"
        assert "publisher" not in extra

    def test_journal_article_full_routing(self):
        """Integration check: all journal metadata lands in item, none in extra."""
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "volume": "17",
            "issue": "1",
            "page": "123-145",
            "ISSN": ["2041-1723"],
            "publisher": "Springer",
            "author": [
                {"given": "John", "family": "Doe"},
                {"given": "Jane", "family": "Smith"},
            ],
            "abstract": "An important result.",
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/test", {})

        # Standard fields
        assert item["itemType"] == "journalArticle"
        assert item["title"] == "Test Paper"
        assert item["publicationTitle"] == "Nature Communications"
        assert item["volume"] == "17"
        assert item["issue"] == "1"
        assert item["pages"] == "123-145"
        assert item["ISSN"] == "2041-1723"
        assert item["publisher"] == "Springer"
        assert item["abstractNote"] == "An important result."
        assert item["date"] == "2026-07-01"
        assert item["DOI"] == "10.1234/test"
        assert item["creators"] == _make_creators("Doe, John", "Smith, Jane")

        # None of the journal fields should be in extra
        journal_keys = {
            "publicationTitle", "volume", "issue", "pages", "ISSN", "publisher"
        }
        assert journal_keys.isdisjoint(set(extra.keys()))


class TestPreprintRouting:
    """For preprint, journal metadata stays in extra."""

    def test_preprint_keeps_metadata_in_extra(self):
        mock_cr = {
            "type": "posted-content",
            "title": ["Preprint Paper"],
            "container-title": ["arXiv preprint"],
            "volume": "1",
            "issue": "2",
            "page": "99-100",
            "ISSN": ["1234-5678"],
            "publisher": "Self-published",
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.48550/arXiv.2501.00001", {})

        assert item["itemType"] == "preprint"
        assert extra["publicationTitle"] == "arXiv preprint"
        assert extra["volume"] == "1"
        assert extra["issue"] == "2"
        assert extra["pages"] == "99-100"
        assert extra["ISSN"] == "1234-5678"
        assert extra["publisher"] == "Self-published"


class TestConferencePaperRouting:
    """For conferencePaper, proceedingsTitle and publisher go to standard fields."""

    def test_proceedings_title_in_item(self):
        mock_cr = {
            "type": "proceedings-article",
            "title": ["Conference Paper"],
            "container-title": ["Proc. of ML Conference 2026"],
            "publisher": "ACM",
            "volume": "1",
            "issue": "2",
            "page": "50-60",
            "ISBN": ["978-1-4503-9999-9"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/conf", {})

        assert item["itemType"] == "conferencePaper"
        assert item["proceedingsTitle"] == "Proc. of ML Conference 2026"
        assert item["publisher"] == "ACM"

        # Non-standard fields for conferencePaper stay in extra
        assert extra.get("volume") == "1"
        assert extra.get("issue") == "2"
        assert extra.get("pages") == "50-60"

        # ISBN from Crossref ISBN field
        assert item.get("ISBN") == "978-1-4503-9999-9"
        assert "ISBN" not in extra

    def test_conference_issn_to_item_field(self):
        """When ISBN is missing, ISSN goes to item.ISSN — NOT item.ISBN."""
        mock_cr = {
            "type": "proceedings-article",
            "title": ["Conference Paper"],
            "container-title": ["Proc. of ML Conference 2026"],
            "publisher": "ACM",
            "ISSN": ["1234-5678"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/conf-issn-only", {})

        assert item.get("ISSN") == "1234-5678"
        assert "ISBN" not in item


class TestBookSectionRouting:
    """For bookSection, bookTitle and publisher go to standard fields."""

    def test_book_title_in_item(self):
        mock_cr = {
            "type": "book-chapter",
            "title": ["Chapter One"],
            "container-title": ["Advances in Science"],
            "publisher": "Springer",
            "volume": "3",
            "issue": "1",
            "page": "10-25",
            "ISBN": ["978-3-540-99999-9"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/bookchap", {})

        assert item["itemType"] == "bookSection"
        assert item["bookTitle"] == "Advances in Science"
        assert item["publisher"] == "Springer"

        # Non-standard fields for bookSection stay in extra
        assert extra.get("volume") == "3"
        assert extra.get("issue") == "1"
        assert extra.get("pages") == "10-25"

        # ISBN from Crossref ISBN field
        assert item.get("ISBN") == "978-3-540-99999-9"
        assert "ISBN" not in extra


class TestBookRouting:
    """For book, publisher goes to standard field, ISBN from Crossref ISBN field."""

    def test_book_publisher_in_item(self):
        mock_cr = {
            "type": "book",
            "title": ["A Great Book"],
            "container-title": [],
            "publisher": "MIT Press",
            "ISBN": ["978-0-262-99999-9"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/book", {})

        assert item["itemType"] == "book"
        assert item["publisher"] == "MIT Press"
        assert item.get("ISBN") == "978-0-262-99999-9"

        # No journal metadata should leak into either item or extra
        assert "publicationTitle" not in item
        assert "publicationTitle" not in extra
        assert "volume" not in extra
        assert "issue" not in extra
        assert "pages" not in extra
        assert "ISSN" not in extra


class TestISSNEdgeCases:
    def test_issn_as_string_not_list(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature"],
            "ISSN": "0028-0836",
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/issn-string", {})

        assert item["ISSN"] == "0028-0836"

    def test_issn_empty_list(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature"],
            "ISSN": [],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/issn-empty", {})

        assert "ISSN" not in item
        assert "ISSN" not in extra


class TestCitationKeyFromStandardFields:
    """After the fix, citationKey should be built from item dict, not extra."""

    def test_citation_key_uses_publication_title_from_item(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/citekey", {})

        # citationKey should be built from item["publicationTitle"]
        assert extra.get("citationKey") == "Doe2026_NC"

    def test_citation_key_uses_proceedings_title(self):
        mock_cr = {
            "type": "proceedings-article",
            "title": ["Conference Paper"],
            "container-title": ["Proc of ML Conference"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/citekey-conf", {})

        # citationKey should be built from item["proceedingsTitle"]
        assert extra.get("citationKey") == "Doe2026_PoMC"

    def test_citation_key_uses_book_title(self):
        mock_cr = {
            "type": "book-chapter",
            "title": ["Chapter One"],
            "container-title": ["Advances in Science"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2026, 7, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1234/citekey-book", {})

        # citationKey should be built from item["bookTitle"]
        assert extra.get("citationKey") == "Doe2026_AiS"


class TestCrossrefDatePriority:
    """Crossref's ``created`` is when the *record* was deposited, not when the
    paper appeared — ranking it above ``issued`` writes the wrong year.

    Every other fixture in this file supplies ``published-print``, which wins
    first, so the ``created``/``issued`` ordering was never exercised.  These
    tests cover the fallback chain with the first pick absent.
    """

    def test_issued_wins_over_created(self):
        """The regression that motivated this: APS deposited 1914 content in 2002."""
        mock_cr = {
            "type": "journal-article",
            "title": ["On Physically Similar Systems"],
            "container-title": ["Physical Review"],
            "author": [{"given": "E.", "family": "Buckingham"}],
            "created": {"date-parts": [[2002, 7, 27]]},
            "issued": {"date-parts": [[1914, 10, 1]]},
            "deposited": {"date-parts": [[2017, 4, 6]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, extra = paper_to_zotero.build_item("10.1103/PhysRev.4.345", {})

        assert item["date"] == "1914-10-01"
        # citationKey is derived from date[:4], so it has to follow the date.
        assert extra.get("citationKey") == "Buckingham1914_PR"

    def test_published_print_still_wins_over_issued(self):
        """Print journals keep their print year — existing behaviour, unchanged."""
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Nature Communications"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2024, 3, 1]]},
            "issued": {"date-parts": [[2023, 12, 1]]},
            "published-online": {"date-parts": [[2023, 11, 1]]},
            "created": {"date-parts": [[2023, 10, 1]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, _ = paper_to_zotero.build_item("10.1234/print-wins", {})

        assert item["date"] == "2024-03-01"

    def test_published_online_wins_over_created(self):
        """Online-first records have no print date; online beats deposit."""
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Some Journal"],
            "author": [{"given": "John", "family": "Doe"}],
            "published-online": {"date-parts": [[2021, 5, 20]]},
            "created": {"date-parts": [[2023, 1, 2]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, _ = paper_to_zotero.build_item("10.1234/online-wins", {})

        assert item["date"] == "2021-05-20"

    def test_created_still_used_when_nothing_better_exists(self):
        """``created`` remains a fallback — just no longer the first choice."""
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Some Journal"],
            "author": [{"given": "John", "family": "Doe"}],
            "created": {"date-parts": [[2020, 2, 3]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, _ = paper_to_zotero.build_item("10.1234/created-only", {})

        assert item["date"] == "2020-02-03"

    def test_deposited_used_as_last_resort(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Some Journal"],
            "author": [{"given": "John", "family": "Doe"}],
            "deposited": {"date-parts": [[2019, 8, 9]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, _ = paper_to_zotero.build_item("10.1234/deposited-only", {})

        assert item["date"] == "2019-08-09"

    def test_year_only_date_parts_render_as_bare_year(self):
        """Old records often carry a year and nothing else."""
        mock_cr = {
            "type": "journal-article",
            "title": ["Test Paper"],
            "container-title": ["Some Journal"],
            "author": [{"given": "John", "family": "Doe"}],
            "issued": {"date-parts": [[1914]]},
            "created": {"date-parts": [[2002, 7, 27]]},
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, _ = paper_to_zotero.build_item("10.1234/year-only", {})

        assert item["date"] == "1914"


class TestArxivUpgrade:
    """arXiv DOI → published DOI metadata upgrade (Issue #15)."""

    # ── Shared test data ──────────────────────────────────────────

    ARXIV_DOI = "10.48550/arXiv.2304.12345"
    PUBLISHED_DOI = "10.1000/neurips2023"
    ARXIV_ID = "2304.12345"

    @staticmethod
    def _posted_content_cr():
        return {
            "type": "posted-content",
            "title": ["A Preprint Title"],
            "container-title": ["arXiv preprint"],
            "author": [{"given": "Alice", "family": "Wang"}],
            "published-print": {"date-parts": [[2023, 4, 15]]},
        }

    @staticmethod
    def _published_journal_cr():
        return {
            "type": "journal-article",
            "title": ["Published Title in Journal"],
            "container-title": ["Nature Machine Intelligence"],
            "volume": "5",
            "issue": "6",
            "page": "500-510",
            "ISSN": ["2522-5839"],
            "publisher": "Nature Publishing",
            "author": [{"given": "Alice", "family": "Wang"}],
            "abstract": "Published version abstract.",
            "published-print": {"date-parts": [[2023, 12, 1]]},
        }

    @staticmethod
    def _published_conf_cr():
        return {
            "type": "proceedings-article",
            "title": ["Published Title at Conference"],
            "container-title": ["Advances in Neural Information Processing Systems"],
            "publisher": "Curran Associates",
            "volume": "36",
            "page": "1234-1245",
            "ISBN": ["978-1-7138-7108-8"],
            "author": [{"given": "Alice", "family": "Wang"}],
            "abstract": "Conference version.",
            "published-print": {"date-parts": [[2023, 12, 10]]},
        }

    @staticmethod
    def _arxiv_data_with_published_doi():
        return {
            "title": "A Preprint Title",
            "summary": "Abstract from arXiv.",
            "authors": ["Alice Wang"],
            "published": "2023-04-15",
            "primary_category": "cs.LG",
            "published_doi": "10.1000/neurips2023",
            "journal_ref": "Nature Machine Intelligence 5, 500-510 (2023)",
        }

    @staticmethod
    def _arxiv_data_no_published_doi():
        return {
            "title": "A Preprint Title",
            "summary": "Abstract from arXiv.",
            "authors": ["Alice Wang"],
            "published": "2023-04-15",
            "primary_category": "cs.LG",
            "published_doi": None,
            "journal_ref": None,
        }

    # ── Tests ─────────────────────────────────────────────────────

    def test_arxiv_api_upgrade_to_published_journal(self):
        """arXiv <arxiv:doi> present → upgrade to published journalArticle."""
        posted = self._posted_content_cr()
        published = self._published_journal_cr()
        arxiv_data = self._arxiv_data_with_published_doi()

        def mock_crossref(doi):
            if doi == self.ARXIV_DOI:
                return posted
            if doi == self.PUBLISHED_DOI:
                return published
            return None

        with (
            patch.object(paper_to_zotero, "fetch_crossref", side_effect=mock_crossref),
            patch.object(paper_to_zotero, "fetch_arxiv", return_value=arxiv_data) as mock_arxiv,
            patch.object(paper_to_zotero, "fetch_published_doi_s2") as mock_s2,
        ):
            item, extra = paper_to_zotero.build_item(self.ARXIV_DOI, {})

        # Upgraded to published metadata
        assert item["itemType"] == "journalArticle"
        assert item["title"] == "Published Title in Journal"
        assert item["publicationTitle"] == "Nature Machine Intelligence"
        assert item["volume"] == "5"
        assert item["issue"] == "6"
        assert item["pages"] == "500-510"
        assert item["ISSN"] == "2522-5839"
        assert item["publisher"] == "Nature Publishing"
        assert item["abstractNote"] == "Published version abstract."
        assert item["date"] == "2023-12-01"

        # arXiv source preserved in extra
        assert extra["repository"] == "arXiv"
        assert extra["archiveID"] == "arXiv:2304.12345"
        assert extra["libraryCatalog"] == "arXiv.org"

        # arXiv API was called, S2 was NOT
        mock_arxiv.assert_called_once_with(self.ARXIV_ID)
        mock_s2.assert_not_called()

    def test_s2_fallback_when_arxiv_doi_missing(self):
        """arXiv <arxiv:doi> absent → S2 fallback → upgrade to conferencePaper."""
        posted = self._posted_content_cr()
        published = self._published_conf_cr()
        arxiv_data = self._arxiv_data_no_published_doi()

        def mock_crossref(doi):
            if doi == self.ARXIV_DOI:
                return posted
            if doi == self.PUBLISHED_DOI:
                return published
            return None

        with (
            patch.object(paper_to_zotero, "fetch_crossref", side_effect=mock_crossref),
            patch.object(paper_to_zotero, "fetch_arxiv", return_value=arxiv_data) as mock_arxiv,
            patch.object(
                paper_to_zotero, "fetch_published_doi_s2", return_value=self.PUBLISHED_DOI
            ) as mock_s2,
        ):
            item, extra = paper_to_zotero.build_item(self.ARXIV_DOI, {})

        # Upgraded via S2 to conference paper
        assert item["itemType"] == "conferencePaper"
        assert item["title"] == "Published Title at Conference"
        assert item["proceedingsTitle"] == "Advances in Neural Information Processing Systems"
        assert item["publisher"] == "Curran Associates"
        assert item["ISBN"] == "978-1-7138-7108-8"

        # arXiv source preserved
        assert extra["repository"] == "arXiv"
        assert extra["archiveID"] == "arXiv:2304.12345"

        # Both arXiv and S2 were called
        mock_arxiv.assert_called_once_with(self.ARXIV_ID)
        mock_s2.assert_called_once_with(self.ARXIV_ID)

    def test_stays_preprint_when_both_sources_fail(self):
        """arXiv <arxiv:doi> absent AND S2 returns None → preprint metadata."""
        posted = self._posted_content_cr()
        arxiv_data = self._arxiv_data_no_published_doi()

        def mock_crossref(doi):
            if doi == self.ARXIV_DOI:
                return posted
            return None

        with (
            patch.object(paper_to_zotero, "fetch_crossref", side_effect=mock_crossref),
            patch.object(paper_to_zotero, "fetch_arxiv", return_value=arxiv_data),
            patch.object(paper_to_zotero, "fetch_published_doi_s2", return_value=None) as mock_s2,
        ):
            item, extra = paper_to_zotero.build_item(self.ARXIV_DOI, {})

        # Falls through to preprint (posted-content not in type_map → preprint)
        assert item["itemType"] == "preprint"
        assert item["title"] == "A Preprint Title"

        # Container info goes to extra (preprint routing)
        assert extra["publicationTitle"] == "arXiv preprint"

        # arXiv source marked
        assert extra["repository"] == "arXiv"
        assert extra["archiveID"] == "arXiv:2304.12345"

        # S2 was attempted
        mock_s2.assert_called_once_with(self.ARXIV_ID)

    def test_arxiv_source_preserved_after_upgrade(self):
        """After metadata upgrade, arXiv source fields are present in extra."""
        posted = self._posted_content_cr()
        published = self._published_journal_cr()
        arxiv_data = self._arxiv_data_with_published_doi()

        def mock_crossref(doi):
            if doi == self.ARXIV_DOI:
                return posted
            if doi == self.PUBLISHED_DOI:
                return published
            return None

        with (
            patch.object(paper_to_zotero, "fetch_crossref", side_effect=mock_crossref),
            patch.object(paper_to_zotero, "fetch_arxiv", return_value=arxiv_data),
            patch.object(paper_to_zotero, "fetch_published_doi_s2"),
        ):
            item, extra = paper_to_zotero.build_item(self.ARXIV_DOI, {})

        # Source fields are present (added after upgrade)
        assert extra["repository"] == "arXiv"
        assert extra["archiveID"] == "arXiv:2304.12345"
        assert extra["libraryCatalog"] == "arXiv.org"

    def test_non_arxiv_doi_skips_upgrade_path(self):
        """Regular DOI (not arXiv) — no arXiv/S2 calls, normal routing."""
        journal_cr = self._published_journal_cr()

        with (
            patch.object(paper_to_zotero, "fetch_crossref", return_value=journal_cr) as mock_cr,
            patch.object(paper_to_zotero, "fetch_arxiv") as mock_arxiv,
            patch.object(paper_to_zotero, "fetch_published_doi_s2") as mock_s2,
        ):
            item, extra = paper_to_zotero.build_item(self.PUBLISHED_DOI, {})

        # Normal journalArticle routing
        assert item["itemType"] == "journalArticle"
        assert item["title"] == "Published Title in Journal"
        assert item["publicationTitle"] == "Nature Machine Intelligence"

        # arXiv and S2 were NEVER called
        mock_arxiv.assert_not_called()
        mock_s2.assert_not_called()

        # Crossref called exactly once with the published DOI
        mock_cr.assert_called_once_with(self.PUBLISHED_DOI)


# ── Creators (group author) + credential resolution ──────────────────


class TestCrossrefGroupAuthorFallback:
    """Crossref consortium authors carry only ``name`` — no empty given/family."""

    def test_group_author_uses_name_field(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Consortium Paper"],
            "author": [{"name": "Tabula Sapiens Consortium"}],
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, _ = paper_to_zotero.build_item("10.1234/test", {})

        assert item["creators"] == [{"creatorType": "author", "name": "Tabula Sapiens Consortium"}]

    def test_person_authors_keep_first_last(self):
        mock_cr = {
            "type": "journal-article",
            "title": ["Paper"],
            "author": [
                {"given": "Alice", "family": "Brown"},
                {"name": "Some Consortium"},
            ],
        }

        with patch.object(paper_to_zotero, "fetch_crossref", return_value=mock_cr):
            item, _ = paper_to_zotero.build_item("10.1234/test", {})

        assert item["creators"][0] == {
            "creatorType": "author", "firstName": "Alice", "lastName": "Brown",
        }
        assert item["creators"][1] == {"creatorType": "author", "name": "Some Consortium"}


class TestResolveZoteroCredentials:
    """_resolve_zotero_credentials(): TOML preferred, env fallback."""

    def test_falls_back_to_env_when_no_toml(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZOTERO_API_KEY", "env-key")
        monkeypatch.setenv("ZOTERO_LIBRARY_ID", "6789")
        monkeypatch.delenv("ZOTERO_CONFIG_PATH", raising=False)
        # Point the default config path into tmp_path where no TOML exists.
        monkeypatch.setattr(
            "os.path.expanduser", lambda p: str(tmp_path / "config.toml")
        )

        lib_id, api_key = paper_to_zotero._resolve_zotero_credentials()

        assert (lib_id, api_key) == ("6789", "env-key")

    def test_toml_takes_precedence_over_env(self, monkeypatch, tmp_path):
        cfg = tmp_path / "zot.toml"
        cfg.write_text('[zotero]\nlibrary_id = "111"\napi_key = "toml-key"\n', encoding="utf-8")
        monkeypatch.setenv("ZOTERO_CONFIG_PATH", str(cfg))
        monkeypatch.setenv("ZOTERO_API_KEY", "env-key")
        monkeypatch.setenv("ZOTERO_LIBRARY_ID", "999")

        lib_id, api_key = paper_to_zotero._resolve_zotero_credentials()

        assert (lib_id, api_key) == ("111", "toml-key")

    def test_returns_empty_when_both_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZOTERO_API_KEY", "")
        monkeypatch.setenv("ZOTERO_LIBRARY_ID", "")
        monkeypatch.delenv("ZOTERO_CONFIG_PATH", raising=False)
        monkeypatch.setattr(
            "os.path.expanduser", lambda p: str(tmp_path / "config.toml")
        )

        lib_id, api_key = paper_to_zotero._resolve_zotero_credentials()

        assert (lib_id, api_key) == ("", "")


# ── Chinese journals (CNKI DOIs absent from Crossref) ────────────────


class TestChineseJournalFallback:
    """When Crossref has no record, chndoi/publisher metadata builds the item."""

    DOI = "10.14042/j.cnki.32.1309.2026.06.001"

    def _chinese_cr(self) -> dict:
        return {
            "type": "journal-article",
            "title": ["黄河中游水沙变化归因分析"],
            "container-title": ["水科学进展"],
            "volume": "37",
            "issue": "6",
            "page": "993-1007",
            "ISSN": ["1001-6791"],
            "author": [
                {"family": "王丽川", "given": ""},
                {"family": "李四", "given": ""},
            ],
            "abstract": "目的：分析黄河中游水沙变化的驱动因素。",
            "published-print": {"date-parts": [[2026, 6, 1]]},
        }

    def test_builds_a_journal_article_from_chinese_metadata(self):
        with (
            patch.object(paper_to_zotero, "fetch_crossref", return_value=None),
            patch.object(paper_to_zotero, "fetch_chinese_crossref",
                         return_value=self._chinese_cr()) as mock_cn,
        ):
            item, extra = paper_to_zotero.build_item(self.DOI, {})

        mock_cn.assert_called_once_with(self.DOI)
        assert item["itemType"] == "journalArticle"
        assert item["title"] == "黄河中游水沙变化归因分析"
        assert item["publicationTitle"] == "水科学进展"
        assert item["volume"] == "37"
        assert item["issue"] == "6"
        assert item["pages"] == "993-1007"
        assert item["ISSN"] == "1001-6791"
        assert item["date"] == "2026-06-01"
        assert item["abstractNote"].startswith("目的")
        assert item["language"] == "zh"
        assert item["creators"] == [
            {"creatorType": "author", "firstName": "", "lastName": "王丽川"},
            {"creatorType": "author", "firstName": "", "lastName": "李四"},
        ]
        assert "publicationTitle" not in extra

    def test_source_meta_wins_and_avoids_both_fetches(self):
        """The download pipeline hands over an already-resolved record."""
        with (
            patch.object(paper_to_zotero, "fetch_crossref",
                         side_effect=AssertionError("must not be consulted")),
            patch.object(paper_to_zotero, "fetch_chinese_crossref",
                         side_effect=AssertionError("must not be consulted")),
        ):
            item, _ = paper_to_zotero.build_item(
                self.DOI, {}, source_meta=self._chinese_cr())

        assert item["publicationTitle"] == "水科学进展"
        assert item["volume"] == "37"
        assert item["pages"] == "993-1007"

    def test_arxiv_doi_skips_the_chndoi_probe(self):
        """arXiv DOIs live in DataCite; probing chndoi would only cost a hop."""
        with (
            patch.object(paper_to_zotero, "fetch_crossref", return_value=None),
            patch.object(paper_to_zotero, "fetch_arxiv", return_value=None),
            patch.object(paper_to_zotero, "fetch_published_doi_s2", return_value=None),
            patch.object(paper_to_zotero, "fetch_chinese_crossref",
                         side_effect=AssertionError("must not probe chndoi for arXiv")),
        ):
            paper_to_zotero.build_item("10.48550/arXiv.2606.06473", {"title": "T"})

    def test_crossref_still_wins_when_present(self):
        crossref_cr = {
            "type": "journal-article",
            "title": ["English Title"],
            "container-title": ["Journal"],
            "author": [{"given": "John", "family": "Doe"}],
        }

        with (
            patch.object(paper_to_zotero, "fetch_crossref", return_value=crossref_cr),
            patch.object(paper_to_zotero, "fetch_chinese_crossref",
                         side_effect=AssertionError("must not be consulted")),
        ):
            item, _ = paper_to_zotero.build_item("10.1234/test", {})

        assert item["title"] == "English Title"
