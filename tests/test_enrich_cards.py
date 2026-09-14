"""Tests for scripts/enrich_cards.py.

Analysis cards cite figures as plain text ("Fig 2b-d"), which renders as dead
text in Obsidian.  This script is a POST-PROCESSING pass -- cards are written
by sub-agents and stay untouched by it -- that adds Zotero deep links to the
card header and inlines the cited figures at the point of mention.

Two things here are easy to get wrong and are pinned down by tests:

* **Bullet vs paragraph insertion.**  Measured on the real corpus: 127 of 216
  figure-citing lines are list items.  Dropping an image block straight after
  a bullet splits the list in two; it has to be an indented continuation.
* **Lookup by item key, not slug.**  A merged card's slug does not match any
  fulltext file (the Virtual Lab card covers two items), so the slug join
  silently finds nothing.

The Zotero Local API and pymupdf are stubbed; nothing here touches the
network, a real PDF, or the developer's library.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "enrich_cards.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "enrich_cards_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


# ── Fixtures ──────────────────────────────────────────────────────────────

SLUG = "test_paper"
ITEM_KEY = "TEST0001"
ATTACH_KEY = "ATT00001"

# A card with a bullet list (where most real figure citations live) and one
# paragraph citation, so both insertion paths are exercised in one fixture.
CARD = """# Test Paper

- **作者**: Test Author
- **年份**: 2025
- **期刊**: Test Journal
- **DOI**: （无）
- **Zotero Key**: `TEST0001`

## 研究问题
Some research question (Fig 1).

## 核心方法
Method description.

## 实验设计
Experiment setup (Fig 2a).

## 关键发现
- First bullet (Fig 3).
- Second bullet, no figure.
- Third bullet repeats the same figure (Fig 3).

## 局限性
Limitations (Supp Fig 7) and a table (Table 1).

## 与领域的关系
Relevance.

## 精读理由
Why read.

## 标签
`tag1` `tag2` `谱系词`
"""

CARD_NO_FIGS = CARD.replace(" (Fig 1)", "").replace(" (Fig 2a)", "").replace(
    " (Fig 3)", ""
).replace(" (Supp Fig 7) and a table (Table 1)", "").replace("TEST0001", "TEST0002")

# Slug deliberately does NOT match the card's slug: this is the merged-card
# case, where only an item-key lookup can find the metadata.
FULLTEXT = {
    "itemKey": ITEM_KEY,
    "attachmentKey": ATTACH_KEY,
    "doi": "10.48550/arXiv.2501.00001",
    "slug": "something_else_entirely",
    "title": "Test Paper",
}


def _write_card(tmp_path: Path, text: str = CARD, slug: str = SLUG) -> Path:
    cards = tmp_path / "cards"
    cards.mkdir(parents=True, exist_ok=True)
    path = cards / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _write_fulltext(
    tmp_path: Path, payload: dict | None = None, filename: str = "whatever"
) -> Path:
    fulltext = tmp_path / "fulltext"
    fulltext.mkdir(parents=True, exist_ok=True)
    (fulltext / f"{filename}.json").write_text(
        json.dumps(payload or FULLTEXT, ensure_ascii=False), encoding="utf-8"
    )
    return fulltext


def _figures_dir(tmp_path: Path) -> Path:
    out = tmp_path / "figures"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _silent(_msg: str) -> None:
    pass


def _fake_extract(nums: list[int]):
    """Stand-in for _extract_figures: reports these figure numbers as found."""
    return {n: f"{SLUG}_fig{n:02d}.png" for n in nums}


# ── Zotero key extraction ─────────────────────────────────────────────────


def test_extract_zotero_keys_single():
    assert script._extract_zotero_keys(CARD) == [ITEM_KEY]


def test_extract_zotero_keys_merged_card_takes_first():
    """A merged card lists two keys; the first is the one to look up."""
    merged = CARD.replace(
        "- **Zotero Key**: `TEST0001`",
        "- **Zotero Key**: `AAAA1111`（预印本）/ `BBBB2222`（发表版）",
    )
    keys = script._extract_zotero_keys(merged)
    assert keys[0] == "AAAA1111"
    assert "BBBB2222" in keys


def test_extract_zotero_keys_absent():
    assert script._extract_zotero_keys("no key here") == []


# ── fulltext lookup by item key ───────────────────────────────────────────


def test_find_fulltext_by_item_key_ignores_slug(tmp_path):
    """The card's slug matches nothing; only the item key finds it."""
    fulltext = _write_fulltext(tmp_path, filename="something_else_entirely")
    found = script._find_fulltext(fulltext, ITEM_KEY)
    assert found is not None
    assert found["itemKey"] == ITEM_KEY


def test_find_fulltext_missing(tmp_path):
    fulltext = _write_fulltext(tmp_path)
    assert script._find_fulltext(fulltext, "NOPE9999") is None


# ── figure reference parsing ──────────────────────────────────────────────


def test_find_figure_refs_basic():
    assert script._find_figure_refs("Results (Fig 1) and (Fig 2).") == {1, 2}


def test_find_figure_refs_variants():
    assert script._find_figure_refs("Fig. 3, Figure 4, Fig 5a, Fig 6b–d.") == {
        3,
        4,
        5,
        6,
    }


def test_find_figure_refs_excludes_supplementary():
    assert script._find_figure_refs("Limitations (Supp Fig 7).") == set()


def test_find_figure_refs_excludes_tables():
    assert script._find_figure_refs("See Table 1 and Table 2.") == set()


def test_find_figure_refs_mixed():
    assert script._find_figure_refs("(Fig 2d, Fig 3e, Supp Fig 7)") == {2, 3}


def test_find_figure_refs_chinese():
    """Two cards cite figures as （图 N） rather than "Fig N"."""
    assert script._find_figure_refs("管理 worker 队列（图 2）。详见（图 13）。") == {2, 13}


def test_find_figure_refs_excludes_chinese_tables():
    assert script._find_figure_refs("见表 3 与表 70。") == set()


def test_find_figure_refs_excludes_fujian():
    """附图 (an appendix heading) is not a numbered figure citation."""
    assert script._find_figure_refs("## 附图\n\n图 3 已在上文给出。") == {3}
    assert script._find_figure_refs("见附图 3。") == set()


# ── link insertion ────────────────────────────────────────────────────────


def test_add_links_inserts_after_key_line(tmp_path):
    card = _write_card(tmp_path)
    assert script._add_links(card, FULLTEXT, _silent) is True

    text = card.read_text(encoding="utf-8")
    assert f"zotero://select/library/items/{ITEM_KEY}" in text
    assert f"zotero://open-pdf/library/items/{ATTACH_KEY}" in text
    assert text.index("**原文**") > text.index("Zotero Key")


def test_add_links_idempotent(tmp_path):
    card = _write_card(tmp_path)
    script._add_links(card, FULLTEXT, _silent)
    once = card.read_text(encoding="utf-8")

    assert script._add_links(card, FULLTEXT, _silent) is False
    assert card.read_text(encoding="utf-8") == once


def test_add_links_without_attachment_key_omits_pdf_link(tmp_path):
    """Items recovered from arXiv have no attachment; no empty link is written."""
    card = _write_card(tmp_path)
    payload = {"itemKey": ITEM_KEY, "attachmentKey": None, "slug": SLUG}

    assert script._add_links(card, payload, _silent) is True
    text = card.read_text(encoding="utf-8")
    assert f"zotero://select/library/items/{ITEM_KEY}" in text
    assert "zotero://open-pdf" not in text


def test_add_links_preserves_eight_sections(tmp_path):
    card = _write_card(tmp_path)
    script._add_links(card, FULLTEXT, _silent)
    assert card.read_text(encoding="utf-8").count("\n## ") == 8


# ── figure insertion: the two placement rules ─────────────────────────────


def _insert(card: Path, nums: list[int], figures: Path, tmp_path: Path) -> int:
    """Returns the number of figures inserted (0 == card untouched)."""
    with (
        patch.object(script, "_resolve_pdf_path", return_value="/fake.pdf"),
        patch.object(script, "_extract_figures", return_value=_fake_extract(nums)),
    ):
        return script._insert_inline_figures(
            card, FULLTEXT, figures, tmp_path / "cache", _silent
        )


def test_insert_paragraph_figure_is_flush_left(tmp_path):
    card = _write_card(tmp_path)
    assert _insert(card, [1], _figures_dir(tmp_path), tmp_path) == 1

    lines = card.read_text(encoding="utf-8").split("\n")
    idx = next(i for i, l in enumerate(lines) if "fig01" in l)
    assert lines[idx] == f"![[{SLUG}_fig01.png]]", "段落图必须顶格"
    assert lines[idx - 1] == ""
    assert lines[idx + 1] == "", "段落图后要留空行，免得和下一段粘在一起"


def test_insert_bullet_figure_is_indented_and_keeps_list_intact(tmp_path):
    """An unindented block after a bullet would split the list in two."""
    card = _write_card(tmp_path)
    assert _insert(card, [3], _figures_dir(tmp_path), tmp_path) == 1

    text = card.read_text(encoding="utf-8")
    lines = text.split("\n")
    idx = next(i for i, l in enumerate(lines) if "fig03" in l)
    assert lines[idx] == f"    ![[{SLUG}_fig03.png]]", "列表项图必须缩进 4 空格"

    # The list must survive intact.  Between the first and last bullet the
    # only legal lines are blanks, indented continuations, and other bullets
    # -- an unindented image block would show up here and split the list.
    bullets = [
        i for i, l in enumerate(lines) if l.startswith("- ") and "bullet" in l.lower()
    ]
    assert lines[bullets[0]].startswith("- First bullet")
    assert lines[bullets[-1]].startswith("- Third bullet")
    between = lines[bullets[0] + 1 : bullets[-1]]
    assert all(
        l.strip() == "" or l.startswith("    ") or l.startswith("- ") for l in between
    ), f"列表被插断：{between}"


def test_insert_only_first_mention(tmp_path):
    """Fig 3 is cited by two bullets; the image goes in once."""
    card = _write_card(tmp_path)
    _insert(card, [3], _figures_dir(tmp_path), tmp_path)
    text = card.read_text(encoding="utf-8")
    assert text.count(f"![[{SLUG}_fig03.png]]") == 1


def test_insert_idempotent(tmp_path):
    card = _write_card(tmp_path)
    figures = _figures_dir(tmp_path)
    _insert(card, [1, 2, 3], figures, tmp_path)
    once = card.read_text(encoding="utf-8")

    assert _insert(card, [1, 2, 3], figures, tmp_path) == 0
    assert card.read_text(encoding="utf-8") == once


def test_insert_completes_a_partially_inserted_card(tmp_path):
    """Per-figure idempotency: a card missing one figure must still get it.

    Whole-card skipping would leave such a card permanently incomplete.
    """
    card = _write_card(tmp_path)
    figures = _figures_dir(tmp_path)
    _insert(card, [1, 2, 3], figures, tmp_path)
    text = card.read_text(encoding="utf-8")
    # Simulate an interrupted earlier run: figure 1 never made it in.
    card.write_text(text.replace(f"\n\n![[{SLUG}_fig01.png]]", ""), encoding="utf-8")

    assert _insert(card, [1, 2, 3], figures, tmp_path) == 1
    assert f"![[{SLUG}_fig01.png]]" in card.read_text(encoding="utf-8")


def test_caption_separator_variants():
    """All three separators publishers use must be recognised.

    A first draft required [.:|], which silently dropped the en-dash and
    bare-space forms -- two cards came back with zero figures because of it.
    """
    for text, number in [
        ("Figure 1 | Performance of the method.", 1),
        ("Figure 1 – System architectures of the two frameworks.", 1),
        ("Fig. 1 Publication and projected growth trends", 1),
        ("Figure 2: Left: Evolution of the score", 2),
        ("  Figure 12\tTrends in author affiliations", 12),
    ]:
        match = script.FIGURE_CAPTION.match(text)
        assert match is not None, f"题注没识别出来：{text!r}"
        assert int(match.group(1)) == number


def test_caption_rejects_prose_mention():
    """A sentence that merely names a figure is not a caption."""
    assert script.FIGURE_CAPTION.match("Figure 4 shows that the model is") is None
    assert script.FIGURE_CAPTION.match("Fig. 3 compares the two runs") is None


def test_insert_asks_only_for_the_figures_it_needs(tmp_path):
    """Rendering every captioned figure would leave hundreds of orphan PNGs.

    Papers average far more figures than a given card cites -- the first
    backfill wrote 420 files for 165 citations.
    """
    card = _write_card(tmp_path)
    with (
        patch.object(script, "_resolve_pdf_path", return_value="/fake.pdf"),
        patch.object(
            script, "_extract_figures", return_value=_fake_extract([1, 2, 3])
        ) as extractor,
    ):
        script._insert_inline_figures(
            card, FULLTEXT, _figures_dir(tmp_path), tmp_path / "cache", _silent
        )

    assert extractor.call_args.kwargs.get("wanted") == {1, 2, 3}


def test_insert_skips_supplementary_and_table_refs(tmp_path):
    card = _write_card(tmp_path)
    _insert(card, [1, 2, 3, 7], _figures_dir(tmp_path), tmp_path)

    text = card.read_text(encoding="utf-8")
    assert "_fig07" not in text, "Supp Fig 不该插图"


def test_insert_does_nothing_when_no_figures_extracted(tmp_path):
    card = _write_card(tmp_path)
    before = card.read_text(encoding="utf-8")

    assert _insert(card, [], _figures_dir(tmp_path), tmp_path) == 0
    assert card.read_text(encoding="utf-8") == before


def test_insert_does_nothing_when_pdf_unresolvable(tmp_path):
    card = _write_card(tmp_path)
    before = card.read_text(encoding="utf-8")

    with patch.object(script, "_resolve_pdf_path", return_value=None), patch.object(
        script, "_arxiv_pdf", return_value=None
    ):
        assert (
            script._insert_inline_figures(
                card, FULLTEXT, _figures_dir(tmp_path), tmp_path / "cache", _silent
            )
            == 0
        )
    assert card.read_text(encoding="utf-8") == before


def test_insert_falls_back_to_arxiv_when_local_pdf_missing(tmp_path):
    """12 papers have no local PDF; their arXiv id is in the doi field."""
    card = _write_card(tmp_path)
    fetched = tmp_path / "cache" / "from_arxiv.pdf"
    fetched.parent.mkdir(parents=True, exist_ok=True)
    fetched.write_bytes(b"%PDF-1.7 fake")

    with (
        patch.object(script, "_resolve_pdf_path", return_value=None),
        patch.object(script, "_arxiv_pdf", return_value=str(fetched)) as arxiv,
        patch.object(script, "_extract_figures", return_value=_fake_extract([1])),
    ):
        changed = script._insert_inline_figures(
            card, FULLTEXT, _figures_dir(tmp_path), tmp_path / "cache", _silent
        )

    assert changed == 1
    arxiv.assert_called_once()
    assert f"![[{SLUG}_fig01.png]]" in card.read_text(encoding="utf-8")


def test_insert_no_arxiv_fallback_without_arxiv_doi(tmp_path):
    """A non-arXiv item with no local PDF must not trigger a download."""
    card = _write_card(tmp_path)
    payload = dict(FULLTEXT, doi="10.1038/s41586-023-06792-0")

    with (
        patch.object(script, "_resolve_pdf_path", return_value=None),
        patch.object(script, "_arxiv_pdf") as arxiv,
    ):
        script._insert_inline_figures(
            card, payload, _figures_dir(tmp_path), tmp_path / "cache", _silent
        )
    arxiv.assert_not_called()


# ── end to end ────────────────────────────────────────────────────────────


def test_enrich_adds_links_and_figures_and_keeps_eight_sections(tmp_path):
    _write_card(tmp_path)
    fulltext = _write_fulltext(tmp_path)
    figures = _figures_dir(tmp_path)

    with (
        patch.object(script, "_resolve_pdf_path", return_value="/fake.pdf"),
        patch.object(script, "_extract_figures", return_value=_fake_extract([1, 2, 3])),
    ):
        summary = script.enrich_cards(
            cards_dir=tmp_path / "cards",
            fulltext_dir=fulltext,
            figures_dir=figures,
            do_links=True,
            do_figures=True,
            report=_silent,
        )

    text = (tmp_path / "cards" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert "**原文**" in text
    assert f"![[{SLUG}_fig01.png]]" in text
    assert text.count("\n## ") == 8
    assert summary["cards"] == 1
    assert summary["figures"] == 3


def test_enrich_is_idempotent_end_to_end(tmp_path):
    _write_card(tmp_path)
    fulltext = _write_fulltext(tmp_path)
    figures = _figures_dir(tmp_path)
    kwargs = dict(
        cards_dir=tmp_path / "cards",
        fulltext_dir=fulltext,
        figures_dir=figures,
        do_links=True,
        do_figures=True,
        report=_silent,
    )

    with (
        patch.object(script, "_resolve_pdf_path", return_value="/fake.pdf"),
        patch.object(script, "_extract_figures", return_value=_fake_extract([1, 2, 3])),
    ):
        script.enrich_cards(**kwargs)
        once = (tmp_path / "cards" / f"{SLUG}.md").read_text(encoding="utf-8")
        script.enrich_cards(**kwargs)

    assert (tmp_path / "cards" / f"{SLUG}.md").read_text(encoding="utf-8") == once


def test_enrich_links_only(tmp_path):
    _write_card(tmp_path)
    fulltext = _write_fulltext(tmp_path)

    script.enrich_cards(
        cards_dir=tmp_path / "cards",
        fulltext_dir=fulltext,
        figures_dir=_figures_dir(tmp_path),
        do_links=True,
        do_figures=False,
        report=_silent,
    )

    text = (tmp_path / "cards" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert "**原文**" in text
    assert "![[test_paper_fig" not in text


def test_enrich_leaves_a_no_figure_card_otherwise_intact(tmp_path):
    card = _write_card(tmp_path, CARD_NO_FIGS, slug="plain_paper")
    fulltext = _write_fulltext(
        tmp_path,
        {"itemKey": "TEST0002", "attachmentKey": "ATT00002", "slug": "plain_paper"},
        filename="plain_paper",
    )

    with (
        patch.object(script, "_resolve_pdf_path", return_value="/fake.pdf"),
        patch.object(script, "_extract_figures", return_value={5: "x.png"}),
    ):
        script.enrich_cards(
            cards_dir=tmp_path / "cards",
            fulltext_dir=fulltext,
            figures_dir=_figures_dir(tmp_path),
            do_links=True,
            do_figures=True,
            report=_silent,
        )

    text = card.read_text(encoding="utf-8")
    assert "**原文**" in text  # links are always added
    assert "![[plain_paper_fig" not in text  # but no figures were cited


def test_enrich_survives_a_card_without_a_zotero_key(tmp_path):
    """A malformed card must not abort the whole run."""
    cards = tmp_path / "cards"
    cards.mkdir(parents=True)
    (cards / "broken.md").write_text("# Broken\n\nno key here\n", encoding="utf-8")
    _write_card(tmp_path)

    summary = script.enrich_cards(
        cards_dir=cards,
        fulltext_dir=_write_fulltext(tmp_path),
        figures_dir=_figures_dir(tmp_path),
        do_links=True,
        do_figures=False,
        report=_silent,
    )

    assert summary["cards"] == 2
    assert summary["links"] == 1  # only the well-formed card
