"""Grounding rules: a quote proves a page only if it is really there.

These tests run on synthetic Markdown assembled in the same shape the converter
emits (page markers, canaries, prose). Every rule is exercised through the public
functions -- ``normalize_quote``, ``verify_quote`` and ``verify_reading`` -- so a
regression means the gate changed, not an internal helper.
"""

from __future__ import annotations

import pytest

from hydrolitagent.cards.domain.grounding import (
    expected_canaries,
    is_quote_too_short,
    markdown_sha256,
    normalize_quote,
    search_form,
    verify_quote,
    verify_reading,
)
from hydrolitagent.cards.domain.paper import PageAnchor
from hydrolitagent.cards.domain.reading import GroundingError, QuoteVerdict, ReadingReceipt

CANARIES = ("c-00000001", "c-00000002", "c-00000003")

PAGE_ONE = (
    "# A study of flood forecasting\n\n"
    "Abstract placeholder text for the fixture document, long enough to quote."
)
PAGE_TWO = (
    "## Results\n\n"
    "We find that the proposed model reduces peak error by 18 percent overall."
)
PAGE_THREE = (
    "## Discussion\n\n"
    "The improvement holds across all five catchments in the validation set."
)
PAGE_FOUR = (
    "## References\n\n"
    "Smith and Jones, A reference entry that is long enough to quote from."
)


def make_document(
    pages: tuple[str, ...] = (PAGE_ONE, PAGE_TWO, PAGE_THREE, PAGE_FOUR),
    *,
    roles: dict[int, str] | None = None,
) -> tuple[str, tuple[PageAnchor, ...]]:
    """Assemble ``paper.md`` with page markers and canaries, plus its anchors."""

    roles = roles or {1: "front_matter", 2: "body", 3: "body", 4: "references"}
    parts: list[str] = []
    anchors: list[PageAnchor] = []
    offset = 0
    for number, content in enumerate(pages, start=1):
        canary = CANARIES[number - 1] if number - 1 < len(CANARIES) else None
        header = f"<!-- page: {number} -->\n"
        if canary:
            header += f"<!-- reading-canary: {canary} -->\n"
        parts.append(header)
        offset += len(header)
        start = offset
        parts.append(content)
        offset += len(content)
        anchors.append(
            PageAnchor(
                page=number,
                char_start=start,
                char_end=start + len(content),
                heading=None,
                role=roles.get(number, "body"),
                canary=canary,
            )
        )
        parts.append("\n")
        offset += 1
    return "".join(parts), tuple(anchors)


def receipt(markdown: str, **overrides: object) -> dict:
    base = {
        "markdown_sha256": markdown_sha256(markdown),
        "read_mode": "file",
        "model_claimed_status": "FULL_MARKDOWN_REVIEWED",
        "model_claimed_pages": [1, 2, 3, 4],
        "canaries_seen": list(expected_canaries(markdown)),
        "self_report": "fixture",
        "source_locations": [],
    }
    base.update(overrides)
    return base


def body_locations(*pages: int) -> list[dict]:
    text = {2: PAGE_TWO, 3: PAGE_THREE, 4: PAGE_FOUR}
    return [
        {
            "anchor": f"P{page}",
            "quote": text[page].split("\n\n", 1)[1],
            "pdf_page": page,
            "section": None,
            "figure": None,
            "table": None,
        }
        for page in pages
    ]


# --------------------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------------------


def test_normalize_folds_whitespace_nfkc_and_markdown_markers() -> None:
    assert normalize_quote("  Peak   error\n was   18%  ") == "Peak error was 18%"
    assert normalize_quote("**bold** and *italic*") == "bold and italic"
    assert normalize_quote("`code` and ~~struck~~") == "code and struck"
    assert normalize_quote("［全角］ＡＢＣ") == "[全角]ABC"
    assert normalize_quote("[link text](https://example.org/x)") == "link text"
    assert normalize_quote("escaped\\_underscore") == "escapedunderscore"


def test_normalize_accepts_non_string_input_as_empty() -> None:
    assert normalize_quote(None) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "quote,too_short",
    [
        ("Abstract", True),
        ("Results", True),
        ("Peak error", True),
        ("the proposed model reduces peak error", False),
        ("提出新的预报框架", True),
        ("提出了一个新的洪水预报框架用于山区流域", False),
    ],
)
def test_quote_length_thresholds(quote: str, too_short: bool) -> None:
    assert is_quote_too_short(normalize_quote(quote)) is too_short


# --------------------------------------------------------------------------------------
# single-quote verification
# --------------------------------------------------------------------------------------


def test_quote_is_found_on_the_page_that_contains_it() -> None:
    markdown, anchors = make_document()
    verdict = verify_quote(
        "We find that the proposed model reduces peak error by 18 percent overall.",
        markdown,
        anchors,
    )
    assert verdict.ok is True
    assert verdict.reason is None
    assert verdict.page == 2


def test_quote_spanning_a_line_break_still_matches() -> None:
    markdown, anchors = make_document()
    verdict = verify_quote(
        "proposed model reduces peak error by 18 percent", markdown, anchors
    )
    assert verdict.ok is True
    assert verdict.page == 2


def test_quote_that_only_differs_in_letter_case_is_grounded() -> None:
    """A model that lifts a fragment mid-sentence capitalises its first letter."""

    markdown, anchors = make_document()
    verdict = verify_quote(
        # The page says "We find that the proposed model reduces peak error ...".
        "Reduces peak error by 18 percent overall.",
        markdown,
        anchors,
    )
    assert verdict.ok is True
    assert verdict.reason is None
    assert verdict.page == 2


def test_quote_spanning_two_consecutive_pages_is_grounded() -> None:
    """A sentence cut by a page break is still verbatim text from the paper."""

    pages = (
        "# A study of flood forecasting\n\nAbstract placeholder text long enough to quote.",
        "## Results\n\nWe find that the proposed model reduces peak error by 18 percent overall "
        "and that the gain holds across every catchment in the",
        "## Discussion\n\nvalidation set, including the four smallest basins with sparse gauges.",
    )
    markdown, anchors = make_document(
        pages, roles={1: "front_matter", 2: "body", 3: "body"}
    )
    verdict = verify_quote(
        "reduces peak error by 18 percent overall and that the gain holds "
        "across every catchment in the validation set",
        markdown,
        anchors,
    )
    assert verdict.ok is True
    assert verdict.reason is None
    # The quote occupies both pages, so either declared page is acceptable.
    assert verdict.page == 2
    assert verdict.pages == (2, 3)


def test_absent_quote_is_not_grounded() -> None:
    markdown, anchors = make_document()
    verdict = verify_quote(
        "The model was trained on 40000 synthetic hydrographs from 1990 to 2020.",
        markdown,
        anchors,
    )
    assert verdict == QuoteVerdict(False, "QUOTE_NOT_FOUND", None)


def test_heading_only_quote_is_too_weak() -> None:
    markdown, anchors = make_document()
    verdict = verify_quote("A study of flood forecasting", markdown, anchors)
    assert verdict.ok is False
    assert verdict.reason == "QUOTE_TOO_WEAK"


def test_short_quote_is_too_weak() -> None:
    markdown, anchors = make_document()
    verdict = verify_quote("Results", markdown, anchors)
    assert verdict.ok is False
    assert verdict.reason == "QUOTE_TOO_WEAK"
    assert verdict.page is None


def test_quote_inside_a_canary_comment_is_not_content() -> None:
    markdown, anchors = make_document()
    verdict = verify_quote("reading-canary: c-00000001", markdown, anchors)
    assert verdict.ok is False
    assert verdict.reason == "QUOTE_NOT_FOUND"


def test_cross_page_quote_with_a_changed_word_is_still_rejected() -> None:
    """Straddling a page break forgives layout, never a changed word."""

    pages = (
        "# A study of flood forecasting\n\nAbstract placeholder text long enough to quote.",
        "## Results\n\nWe find that the proposed model reduces peak error by 18 percent overall "
        "and that the gain holds across every catchment in the",
        "## Discussion\n\nvalidation set, including the four smallest basins with sparse gauges.",
    )
    markdown, anchors = make_document(
        pages, roles={1: "front_matter", 2: "body", 3: "body"}
    )
    verdict = verify_quote(
        # "every" became "each": the layout artefact is the same, the words are not.
        "reduces peak error by 18 percent overall and that the gain holds "
        "across each catchment in the validation set",
        markdown,
        anchors,
    )
    assert verdict.ok is False
    assert verdict.reason == "QUOTE_NOT_FOUND"


def test_quote_split_by_a_midpage_heading_is_an_anchor_mismatch() -> None:
    """The text exists, but no page (or page pair) holds it contiguously.

    Reporting ``QUOTE_NOT_FOUND`` here would accuse the model of fabricating a
    sentence that is in fact in the paper.
    """

    pages = (
        "# A study of flood forecasting\n\nAbstract placeholder text long enough to quote.",
        "## Results\n\nWe find that the proposed model reduces peak error by 18 percent "
        "overall.\n\n## Discussion\n\nThe improvement holds across all five catchments "
        "in the validation set.",
        "## References\n\nSmith and Jones, A reference entry that is long enough to quote.",
    )
    markdown, anchors = make_document(
        pages, roles={1: "front_matter", 2: "body", 3: "references"}
    )
    verdict = verify_quote(
        "reduces peak error by 18 percent overall. The improvement holds across "
        "all five catchments",
        markdown,
        anchors,
    )
    assert verdict.ok is False
    assert verdict.reason == "ANCHOR_MISMATCH"


def test_text_between_page_ranges_is_an_anchor_mismatch() -> None:
    # A quote that exists in the file but in no anchor range means the anchor map
    # is wrong; that is an anchor failure, not a fabricated quote.
    content = f"{PAGE_TWO}\n\ntrailing note outside the page range"
    header = "<!-- page: 2 -->\n<!-- reading-canary: c-00000002 -->\n"
    markdown = header + content
    anchors = (
        PageAnchor(
            page=2,
            char_start=len(header),
            char_end=len(header) + len(PAGE_TWO),
            heading=None,
            role="body",
            canary="c-00000002",
        ),
    )
    verdict = verify_quote("trailing note outside the page range", markdown, anchors)
    assert verdict.ok is False
    assert verdict.reason == "ANCHOR_MISMATCH"
    assert verdict.page is None


# --------------------------------------------------------------------------------------
# whole-receipt verification
# --------------------------------------------------------------------------------------


def _verified(markdown: str, anchors, **overrides: object):
    locations = overrides.pop("source_locations", body_locations(2, 3, 4))
    return verify_reading(
        receipt(markdown, source_locations=locations, **overrides), markdown, anchors
    )


def test_full_body_coverage_is_verified() -> None:
    markdown, anchors = make_document()
    reading = _verified(markdown, anchors)
    assert reading.status == "VERIFIED"
    assert reading.verified is True
    assert reading.full_read_verified is True
    assert reading.scientific_correctness_verified is False
    assert reading.canaries_ok is True
    assert reading.verified_pages == (2, 3, 4)
    assert reading.quote_coverage == 1.0


def test_partial_coverage_is_downgraded_but_still_reported() -> None:
    markdown, anchors = make_document()
    reading = _verified(markdown, anchors, source_locations=body_locations(2))
    assert reading.status == "PARTIAL"
    assert reading.verified is False
    # Two of the four fixture pages are body pages; one is covered.
    assert reading.quote_coverage == pytest.approx(0.5)
    # A partial reading can never be promoted to a production-eligible card.
    assert reading.as_dict()["scientific_correctness_verified"] is False


def test_markdown_digest_must_be_echoed() -> None:
    markdown, anchors = make_document()
    with pytest.raises(GroundingError) as raised:
        _verified(markdown, anchors, markdown_sha256="0" * 64)
    assert raised.value.code == "MARKDOWN_SHA_MISMATCH"


def test_missing_digest_is_a_mismatch_not_a_crash() -> None:
    markdown, anchors = make_document()
    with pytest.raises(GroundingError) as raised:
        _verified(markdown, anchors, markdown_sha256=None)
    assert raised.value.code == "MARKDOWN_SHA_MISMATCH"


def test_every_canary_must_be_echoed() -> None:
    markdown, anchors = make_document()
    with pytest.raises(GroundingError) as raised:
        _verified(markdown, anchors, canaries_seen=[CANARIES[0], CANARIES[1]])
    assert raised.value.code == "INCOMPLETE_MARKDOWN_READ"
    assert raised.value.detail["missing_canaries"] == [CANARIES[2]]


def test_document_without_canaries_cannot_be_verified() -> None:
    markdown = "<!-- page: 1 -->\n" + PAGE_TWO
    anchors = (
        PageAnchor(
            page=1,
            char_start=len("<!-- page: 1 -->\n"),
            char_end=len(markdown),
            heading=None,
            role="body",
            canary=None,
        ),
    )
    with pytest.raises(GroundingError) as raised:
        verify_reading(receipt(markdown), markdown, anchors)
    assert raised.value.code == "INCOMPLETE_MARKDOWN_READ"


def test_missing_receipt_is_rejected() -> None:
    markdown, anchors = make_document()
    with pytest.raises(GroundingError) as raised:
        verify_reading(None, markdown, anchors)
    assert raised.value.code == "INCOMPLETE_MARKDOWN_READ"


def test_no_locations_is_a_grounding_failure() -> None:
    markdown, anchors = make_document()
    with pytest.raises(GroundingError) as raised:
        _verified(markdown, anchors, source_locations=[])
    assert raised.value.code == "QUOTE_NOT_FOUND"


def test_fabricated_quote_is_rejected_with_its_index() -> None:
    markdown, anchors = make_document()
    locations = body_locations(3, 4)
    locations.append(
        {
            "anchor": "P2",
            "quote": "Peak error fell by 92 percent under every tested scenario.",
            "pdf_page": 2,
            "section": None,
            "figure": None,
            "table": None,
        }
    )
    with pytest.raises(GroundingError) as raised:
        _verified(markdown, anchors, source_locations=locations)
    assert raised.value.code == "QUOTE_NOT_FOUND"
    assert raised.value.detail["location_index"] == 2


def test_wrong_page_claim_is_excluded_and_recorded() -> None:
    """A real quote on the wrong page is not usable evidence for that page.

    It is dropped from coverage and listed as a conflict, so one bad page label
    cannot silently pass; the rest of the reading is still judged on its merits.
    """

    markdown, anchors = make_document()
    locations = body_locations(3, 4)
    locations.append(
        {
            "anchor": "P1",
            "quote": PAGE_TWO.split("\n\n", 1)[1],
            "pdf_page": 1,
            "section": None,
            "figure": None,
            "table": None,
        }
    )
    reading = _verified(markdown, anchors, source_locations=locations)
    assert reading.verified_pages == (3, 4)
    assert reading.verified_quotes == 2
    assert len(reading.anchor_conflicts) == 1
    conflict = reading.anchor_conflicts[0]
    assert (conflict.location_index, conflict.declared_page, conflict.found_page) == (2, 1, 2)
    assert reading.as_dict()["anchor_conflicts"] == [
        {"location_index": 2, "declared_page": 1, "found_page": 2}
    ]
    # Only page 3 of the two body pages is covered, so coverage stays honest.
    assert reading.quote_coverage == pytest.approx(0.5)
    assert reading.status == "PARTIAL"


def test_a_sentence_repeated_on_two_pages_satisfies_either_page() -> None:
    repeated = (
        "Sediment transport in the upper catchment is dominated by episodic "
        "mass wasting events in the wet season."
    )
    pages = (
        "# Title\n\n" + repeated,
        "## Methods\n\n" + repeated,
        "## Results\n\n" + PAGE_THREE.split("\n\n", 1)[1],
    )
    markdown, anchors = make_document(pages, roles={1: "front_matter", 2: "body", 3: "body"})
    location = {
        "anchor": "P1",
        "quote": repeated,
        "pdf_page": 1,
        "section": None,
        "figure": None,
        "table": None,
    }
    reading = verify_reading(
        receipt(markdown, source_locations=[location, {
            "anchor": "P3",
            "quote": PAGE_THREE.split("\n\n", 1)[1],
            "pdf_page": 3,
            "section": None,
            "figure": None,
            "table": None,
        }]),
        markdown,
        anchors,
        min_coverage=0.5,
    )
    assert reading.anchor_conflicts == ()
    assert reading.verified_pages == (1, 3)


def test_hyphenated_line_break_still_matches_the_full_word() -> None:
    """Real journals break ``Typically`` as ``Typ-`` / ``ically``."""

    pages = (
        "# Title\n\n" + PAGE_TWO,
        "## Methods\n\nTyp- ically, VIC and PDM both assume a Pareto distribution "
        "for the PDF, which we describe below in detail.",
        "## Results\n\n" + PAGE_THREE.split("\n\n", 1)[1],
    )
    markdown, anchors = make_document(pages, roles={1: "front_matter", 2: "body", 3: "body"})
    assert search_form("Typ- ically") == "Typically"
    verdict = verify_quote(
        "Typically, VIC and PDM both assume a Pareto distribution for the PDF",
        markdown,
        anchors,
    )
    assert verdict.ok is True
    assert verdict.page == 2


def test_hyphen_tolerance_does_not_forgive_other_differences() -> None:
    markdown, anchors = make_document()
    verdict = verify_quote(
        "We find that the proposed model reduces total peak error by 18 percent",
        markdown,
        anchors,
    )
    assert verdict.ok is False
    assert verdict.reason == "QUOTE_NOT_FOUND"


@pytest.mark.parametrize(
    "quote",
    [
        # "hence" dropped from the source sentence.
        "We find that the proposed model reduces peak error by 18 percent.",
        # A word inserted: "peak" became "the peak".
        "We find that the proposed model reduces the peak error by 18 percent overall.",
        # The number changed: 18 percent became 80 percent.
        "We find that the proposed model reduces peak error by 80 percent overall.",
    ],
)
def test_case_folding_does_not_forgive_word_changes(quote: str) -> None:
    """Case is ignored; a changed word, number or a gap is still a paraphrase."""

    markdown, anchors = make_document()
    verdict = verify_quote(quote, markdown, anchors)
    assert verdict.ok is False
    assert verdict.reason == "QUOTE_NOT_FOUND"


def test_anchor_label_alone_is_enough_to_declare_a_page() -> None:
    markdown, anchors = make_document()
    location = {
        "anchor": "P3",
        "quote": PAGE_THREE.split("\n\n", 1)[1],
        "pdf_page": None,
        "section": None,
        "figure": None,
        "table": None,
    }
    # The anchor label alone declares page 3, and the quote is on page 3, so
    # there is no conflict; only the coverage of the other body page is missing.
    reading = _verified(markdown, anchors, source_locations=[location])
    assert reading.verified_pages == (3,)
    assert reading.status == "PARTIAL"


def test_receipt_object_and_mapping_are_equivalent() -> None:
    markdown, anchors = make_document()
    raw = receipt(markdown, source_locations=body_locations(2, 3, 4))
    assert verify_reading(ReadingReceipt.from_mapping(raw), markdown, anchors) == verify_reading(
        raw, markdown, anchors
    )


def test_output_blocks_are_joined_into_one_receipt() -> None:
    markdown, _ = make_document()
    output = {
        "reading_receipt": receipt(markdown),
        "source_locations": body_locations(2),
    }
    parsed = ReadingReceipt.from_output(output)
    assert parsed is not None
    assert parsed.markdown_sha256 == markdown_sha256(markdown)
    assert [location.pdf_page for location in parsed.source_locations] == [2]


def test_output_without_a_receipt_is_unusable() -> None:
    assert ReadingReceipt.from_output({}) is None
    assert ReadingReceipt.from_output(None) is None


def test_min_coverage_is_configurable() -> None:
    markdown, anchors = make_document()
    reading = verify_reading(
        receipt(markdown, source_locations=body_locations(2)),
        markdown,
        anchors,
        min_coverage=0.3,
    )
    assert reading.status == "VERIFIED"


def test_invalid_min_coverage_is_a_programming_error() -> None:
    markdown, anchors = make_document()
    with pytest.raises(ValueError):
        verify_reading(receipt(markdown), markdown, anchors, min_coverage=1.5)
