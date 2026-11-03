"""The reading layer turns machine evidence ids into something a reader can follow.

The theme body is the model's text stored verbatim; the prompt asked it to
"逐项关联 evidence_id", so a real candidate says ``依据 EV-9FKZ6X3B 与
EV-DW4KFPP8``. The reading layer is the only place that can rewrite it without
touching a hashed artifact, so these tests pin the two rules it must not get
wrong: link a source once, and never merge two papers that share an author and a
year.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydrolitagent.cards.application.reading_citations import (
    EvidenceLabel,
    humanize_evidence,
    labels_for_theme,
    short_title,
)
from hydrolitagent.cards.application.reading_layer import (
    _authors_of,
    _theme_readings_text,
    _Theme,
)


def _label(key: str, authors: str | None, year: int | None, title: str | None,
           card: Path | None = None, doi: str | None = None,
           ambiguous: bool = False) -> EvidenceLabel:
    return EvidenceLabel(key=key, authors=authors, year=year, title=title,
                          doi=doi, card=card, ambiguous=ambiguous)


@pytest.fixture()
def tree(tmp_path: Path):
    """A product root whose cards/ and reading/themes/ are siblings."""

    root = tmp_path / "outputs"
    page_dir = root / "reading" / "themes"

    def card(key: str) -> Path:
        path = root / "cards" / key / "card.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# card\n", encoding="utf-8")
        return path

    return page_dir, card


def test_first_mention_is_linked_and_later_ones_shrink(tree) -> None:
    page_dir, card = tree
    labels = {"AAAA1111": _label(
        "AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method", card=card("AAAA1111"))}

    body = "先看 EV-AAAA1111，再看 EV-AAAA1111 的结论。"
    new, order = humanize_evidence(body, labels, page_dir)

    assert order == ["AAAA1111"]
    assert new == (
        "先看[Bartlett 等（2016）《Beyond the SCS-CN method》](<../../cards/AAAA1111/card.md>)，"
        "再看Bartlett 等（2016）的结论。"
    )
    # The id survives only inside the link target, never as prose.
    assert "EV-AAAA1111" not in new.replace("cards/AAAA1111", "")


def test_a_trailing_year_is_absorbed_not_duplicated(tree) -> None:
    """Real shape: ``依据 EV-EXF9I3Z4（2015）修订`` must not become 2015 twice."""

    page_dir, card = tree
    labels = {"AAAA1111": _label(
        "AAAA1111", "Bartlett 等", 2015, "Stochastic rainfall-runoff model",
        card=card("AAAA1111"))}

    new, _ = humanize_evidence("依据 EV-AAAA1111（2015）修订", labels, page_dir)

    assert new == (
        "依据[Bartlett 等（2015）《Stochastic rainfall-runoff model》]"
        "(<../../cards/AAAA1111/card.md>)修订"
    )
    assert new.count("2015") == 1


def test_a_later_mention_also_absorbs_its_year(tree) -> None:
    """The first mention may be an id without a year; the bullet repeats one."""

    page_dir, card = tree
    labels = {"AAAA1111": _label(
        "AAAA1111", "Bartlett 等", 2015, "Stochastic rainfall-runoff model",
        card=card("AAAA1111"))}

    new, _ = humanize_evidence("依据 EV-AAAA1111。\n- **EV-AAAA1111（2015）——方法母体。**",
                               labels, page_dir)

    assert "（2015）（2015）" not in new
    assert new.endswith("**Bartlett 等（2015）——方法母体。**")


def test_two_papers_with_the_same_author_and_year_are_never_merged(tree) -> None:
    page_dir, card = tree
    labels = {
        "AAAA1111": _label("AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method",
                           card=card("AAAA1111"), ambiguous=True),
        "BBBB2222": _label("BBBB2222", "Bartlett 等", 2016,
                           "Framework for event-based semidistributed modeling",
                           card=card("BBBB2222"), ambiguous=True),
    }

    new, order = humanize_evidence(
        "依据 EV-AAAA1111 与 EV-BBBB2222 修订；再提 EV-AAAA1111。", labels, page_dir)

    assert order == ["AAAA1111", "BBBB2222"]
    assert "《Beyond the SCS-CN method》](<../../cards/AAAA1111/card.md>)" in new
    assert "《Framework for event-based semidistributed…》](<../../cards/BBBB2222/card.md>)" in new
    # Later mention keeps the title: "Bartlett 等（2016）" alone names both papers.
    assert "再提Bartlett 等（2016）《Beyond the SCS-CN method》。" in new


def test_a_bare_ambiguous_label_is_left_alone(tree) -> None:
    """Negative control: without a title there is no way to know which 2016 it is."""

    page_dir, card = tree
    labels = {
        "AAAA1111": _label("AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method",
                           card=card("AAAA1111"), ambiguous=True),
        "BBBB2222": _label("BBBB2222", "Bartlett 等", 2016,
                           "Framework for event-based semidistributed modeling",
                           card=card("BBBB2222"), ambiguous=True),
    }

    body = "参见 Bartlett 等（2016）的分析。"
    new, order = humanize_evidence(body, labels, page_dir)

    assert new == body
    assert order == []


def test_a_title_qualified_label_is_linkable(tree) -> None:
    page_dir, card = tree
    labels = {
        "AAAA1111": _label("AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method",
                           card=card("AAAA1111"), ambiguous=True),
        "BBBB2222": _label("BBBB2222", "Bartlett 等", 2016,
                           "Framework for event-based semidistributed modeling",
                           card=card("BBBB2222"), ambiguous=True),
    }

    new, order = humanize_evidence(
        "参见 Bartlett 等（2016）《Framework for event-based semidistributed modeling》的分析。",
        labels, page_dir)

    assert order == ["BBBB2222"]
    assert new.startswith("参见[Bartlett 等（2016）《Framework for event-based semidistributed…》]")


def test_code_and_maths_are_literal(tree) -> None:
    page_dir, card = tree
    labels = {"AAAA1111": _label("AAAA1111", "Bartlett 等", 2016, "Title", card=card("AAAA1111"))}

    body = "正文 EV-AAAA1111。\n```\nEV-AAAA1111\n```\n`EV-AAAA1111` 与 $EV-AAAA1111$ 保持原样。"
    new, _ = humanize_evidence(body, labels, page_dir)

    assert "```\nEV-AAAA1111\n```" in new
    assert "`EV-AAAA1111`" in new
    assert "$EV-AAAA1111$" in new


def test_an_id_without_a_card_is_left_as_written(tree) -> None:
    page_dir, _ = tree
    labels = {"AAAA1111": _label("AAAA1111", "Bartlett 等", 2016, "Title", card=None)}

    new, order = humanize_evidence("依据 EV-AAAA1111 修订", labels, page_dir)

    assert new == "依据 EV-AAAA1111 修订"
    assert order == []


def test_ambiguity_is_decided_inside_one_theme(tree) -> None:
    """Two Bartlett 2016 papers elsewhere in the library must not rename this one."""

    page_dir, card = tree
    labels = {
        "AAAA1111": _label("AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method",
                           card=card("AAAA1111")),
        "BBBB2222": _label("BBBB2222", "Bartlett 等", 2016, "Other paper",
                           card=card("BBBB2222")),
    }
    theme = _Theme(
        theme_id="TH-1", title="t", status="ACTIVE",
        directory=page_dir, source_file=page_dir / "x.md",
        readings=({"source": {"evidence_id": "EV-AAAA1111", "parent_key": "AAAA1111"}},),
    )

    themed = labels_for_theme(labels, theme.readings)

    assert themed["AAAA1111"].ambiguous is False
    assert themed["BBBB2222"].ambiguous is False
    # Labels for the whole library stay available, but ambiguity is scoped to
    # what this theme actually cites.
    assert set(themed) == {"AAAA1111", "BBBB2222"}


def test_a_bare_mention_never_links_to_the_wrong_library_duplicate(tree) -> None:
    """A paper outside the theme sharing an author-year must not steal the link.

    Its label is not "ambiguous" for this theme (only AAAA is cited), but a bare
    mention is still unattributable, so the rewrite leaves it alone.
    """

    page_dir, card = tree
    labels = {
        "AAAA1111": _label("AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method",
                           card=card("AAAA1111")),
        "BBBB2222": _label("BBBB2222", "Bartlett 等", 2016, "Other paper",
                           card=card("BBBB2222")),
    }
    theme = _Theme(
        theme_id="TH-1", title="t", status="ACTIVE",
        directory=page_dir, source_file=page_dir / "x.md",
        readings=({"source": {"evidence_id": "EV-AAAA1111", "parent_key": "AAAA1111"}},),
    )
    themed = labels_for_theme(labels, theme.readings)

    body = "参见 Bartlett 等（2016）的分析。"
    assert humanize_evidence(body, themed, page_dir) == (body, [])

    new, order = humanize_evidence(
        "参见 Bartlett 等（2016）《Beyond the SCS-CN method》的分析。", themed, page_dir)
    assert order == ["AAAA1111"]
    assert "cards/AAAA1111/card.md" in new


def test_authors_drop_the_bidi_isolates_zotero_adds() -> None:
    """``creatorSummary`` wraps names in U+2068/U+2069; they render as stray boxes."""

    assert _authors_of({"creators": "⁨Eddin⁩和⁨Gall⁩"}) == "Eddin和Gall"
    assert _authors_of({"creators": ["⁨A 等⁩", "B"]}) == "A 等；B"
    assert _authors_of({"creators": []}) is None
    assert _authors_of({"creators": "⁨⁩"}) is None


def test_short_title_splits_at_the_colon_and_truncates() -> None:
    assert short_title("Beyond the SCS-CN method: A theoretical framework") == "Beyond the SCS-CN method"
    assert short_title("   ") == ""
    long = short_title("A very long title that keeps going past the limit of a reader's patience")
    assert long.endswith("…")
    assert len(long) <= 49


def test_display_math_and_fences_are_literal(tree) -> None:
    """A reference inside maths/code is not prose and must not be rewritten."""

    page_dir, card = tree
    labels = {"AAAA1111": _label(
        "AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method", card=card("AAAA1111"))}

    body = "\n".join([
        "$$",
        "EV-AAAA1111",
        "$$",
        "~~~",
        "EV-AAAA1111",
        "~~~",
        "``EV-AAAA1111``",
        "正文 EV-AAAA1111。",
    ])
    new, order = humanize_evidence(body, labels, page_dir)

    assert "$$\nEV-AAAA1111\n$$" in new
    assert "~~~\nEV-AAAA1111\n~~~" in new
    assert "``EV-AAAA1111``" in new
    assert "正文[Bartlett 等（2016）《Beyond the SCS-CN method》]" in new
    assert order == ["AAAA1111"]


def test_an_existing_link_is_left_alone_and_the_rewrite_is_idempotent(tree) -> None:
    """A finished link already points at a paper; nesting one inside it breaks
    both, and re-running the rewrite must be a no-op."""

    page_dir, card = tree
    labels = {"AAAA1111": _label(
        "AAAA1111", "Bartlett 等", 2016, "Beyond the SCS-CN method", card=card("AAAA1111"))}

    body = "见 [EV-AAAA1111 粗卡](<../../cards/AAAA1111/card.md>) 与 https://x.org/EV-AAAA1111。"
    new, order = humanize_evidence(body, labels, page_dir)

    assert new == body
    assert order == []
    assert humanize_evidence(new, labels, page_dir)[0] == new


def test_bibliography_follows_the_prose_and_puts_unmentioned_sources_last(tmp_path) -> None:
    """R3: first-mentioned first, never-mentioned last, DOI and links present."""

    root = tmp_path / "outputs"
    page_dir = root / "reading" / "themes"
    page_dir.mkdir(parents=True)
    cards: dict[str, Path] = {}
    labels: dict[str, EvidenceLabel] = {}
    for key, authors, title in (
        ("AAAA1111", "A 等", "论文 A"),
        ("BBBB2222", "B 等", "论文 B"),
        ("CCCC3333", "C 等", "论文 C"),
    ):
        card = root / "cards" / key / "card.md"
        card.parent.mkdir(parents=True)
        card.write_text("# card\n", encoding="utf-8")
        cards[key] = card
        labels[key] = _label(key, authors, 2020, title, card=card, doi=f"10.1/{key}")
    theme = _Theme(
        theme_id="TH-1", title="t", status="ACTIVE",
        directory=page_dir, source_file=page_dir / "x.md",
        readings=(
            {"source": {"evidence_id": "EV-BBBB2222", "parent_key": "BBBB2222"}},
            {"source": {"evidence_id": "EV-AAAA1111", "parent_key": "AAAA1111"}},
            {"source": {"evidence_id": "EV-CCCC3333", "parent_key": "CCCC3333"}},
            # A malformed ref must not become a "- None" bullet.
            {"source": {}},
        ),
    )

    text = _theme_readings_text(theme, root, cards, page_dir, labels, ["AAAA1111"])

    assert text.index("论文 A") < text.index("论文 B") < text.index("论文 C")
    assert "doi:10.1/AAAA1111" in text
    assert "证据卡" in text
    assert "None" not in text
