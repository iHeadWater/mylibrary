"""Sentence identifiers: the model picks a sentence, the program owns the text.

These tests cover the mechanism the whole card gate now rests on (#65): the
numbering of prose and table rows, the expansion back into quotes, and the
per-page inventory that stops a model from inventing an identifier.
"""

from __future__ import annotations

from hydrolitagent.cards.domain.sentence_index import (
    annotate,
    expand,
    identifiers_of,
    inventory,
    strip_ids,
)

PAGE_ONE = (
    "<!-- page: 1 -->\n"
    "# A study of flood forecasting\n"
    "\n"
    "Urban flooding damages roads and buildings in most Chinese cities today.\n"
    "Short sentences are dropped.\n"
    "\n"
    "![figure](figures/fig1.png)\n"
    "Figure 1. A map of the study area.\n"
)

PAGE_TWO = (
    "<!-- page: 2 -->\n"
    "## Results\n"
    "\n"
    "| Catchment | Peak error | Period |\n"
    "|---|---|---|\n"
    "| A | 18 percent | 2019 to 2021 |\n"
    "\n"
    "The proposed model reduced peak error by eighteen percent across catchments.\n"
)

PAGE_THREE = "<!-- page: 3 -->\n\n![only a figure](figures/fig2.png)\n"

PAGE_FOUR = (
    "<!-- page: 4 -->\n"
    "# References\n"
    "\n"
    "Smith and Jones (2020). A reference entry long enough to be numbered.\n"
)

MARKDOWN = PAGE_ONE + PAGE_TWO + PAGE_THREE + PAGE_FOUR


def test_prose_and_table_rows_get_ids_and_the_text_survives() -> None:
    annotated, index = annotate(MARKDOWN)

    assert index["P1-S001"]["page"] == 1
    assert index["P1-S001"]["kind"] == "prose"
    assert "Urban flooding damages roads" in index["P1-S001"]["text"]
    # A table row is cited as a row, not as a sentence.
    assert index["P2-T001"]["kind"] == "table"
    assert "18 percent" in index["P2-T001"]["text"]
    assert "⟨P1-S001⟩" in annotated
    # The words are the paper's own: annotation inserts a marker, nothing else.
    assert strip_ids(annotated).replace("\n", "") != ""
    assert "Urban flooding damages roads and buildings" in strip_ids(annotated)


def test_headings_captions_images_and_references_are_not_numbered() -> None:
    _, index = annotate(MARKDOWN)

    texts = " ".join(meta["text"] for meta in index.values())
    assert "A study of flood forecasting" not in texts
    assert "A map of the study area" not in texts
    assert "Smith and Jones" not in texts
    assert all(meta["page"] != 4 for meta in index.values())


def test_a_page_with_no_prose_yields_no_ids() -> None:
    _, index = annotate(MARKDOWN)
    assert all(meta["page"] != 3 for meta in index.values())


def test_expand_fills_the_quote_and_the_page() -> None:
    _, index = annotate(MARKDOWN)

    expanded, problems = expand(
        [{"sentence_ids": ["P1-S001"], "section": None, "figure": None, "table": None}],
        index,
    )

    assert problems == []
    assert expanded[0]["pdf_page"] == 1
    assert expanded[0]["anchor"] == "P1"
    assert "Urban flooding damages roads" in expanded[0]["quote"]
    # The identifier is an address, not part of the evidence.
    assert "sentence_ids" not in expanded[0]
    assert "⟨" not in expanded[0]["quote"]


def test_an_unknown_identifier_is_reported_never_guessed() -> None:
    _, index = annotate(MARKDOWN)

    expanded, problems = expand(
        [{"sentence_ids": ["P3-S001"], "section": None, "figure": None, "table": None}],
        index,
    )

    assert expanded == []
    assert problems[0]["code"] == "CARD_SENTENCE_ID_UNKNOWN"
    assert problems[0]["actual"] == "P3-S001"


def test_identifiers_from_two_pages_are_refused() -> None:
    _, index = annotate(MARKDOWN)

    expanded, problems = expand(
        [{"sentence_ids": ["P1-S001", "P2-S001"], "section": None, "figure": None, "table": None}],
        index,
    )

    assert expanded == []
    assert problems[0]["code"] == "CARD_SENTENCE_IDS_CROSS_PAGE"


def test_a_location_without_ids_is_left_alone() -> None:
    _, index = annotate(MARKDOWN)
    location = {"quote": "text from an older answer", "pdf_page": 2}

    expanded, problems = expand([location], index)

    assert problems == []
    assert expanded == [location]


def test_identifiers_of_reads_only_strings() -> None:
    assert identifiers_of({"sentence_ids": ["P1-S001", 3]}) == ["P1-S001"]
    assert identifiers_of({"quote": "no ids"}) == []


def test_inventory_lists_real_ranges_and_flags_empty_pages() -> None:
    _, index = annotate(MARKDOWN)

    text = inventory(index, 4)

    assert "第 1 页：P1-S001（共 1 句）" in text
    # A page can carry both prose and table rows; both ranges are named.
    assert "第 2 页：P2-S001（共 1 句）；P2-T001（共 1 行表格）" in text
    assert "第 3 页：没有可引用的句子" in text
    assert "第 4 页：没有可引用的句子" in text


def test_inventory_describes_table_only_pages_as_rows() -> None:
    markdown = (
        "<!-- page: 1 -->\n"
        "| A | 18 percent | 2019 |\n"
        "| B | 22 percent | 2020 |\n"
    )
    _, index = annotate(markdown)

    text = inventory(index, 1)

    assert "P1-T001–P1-T002（共 2 行表格）" in text
