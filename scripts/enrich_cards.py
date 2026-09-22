#!/usr/bin/env python3
"""Enrich analysis cards with Zotero deep links and inline figures.

Cards are written by sub-agents as a fact layer: every claim carries a
pointer like ``（Fig 3b–e）``.  In Obsidian those pointers are dead text --
you cannot click them and you cannot see the figure.  This script is a
**post-processing pass** that fixes that without touching card generation:

* adds a ``**原文**`` line to the card header (Zotero item, and the PDF when
  the item actually has one)
* extracts the figures the card *cites* and inlines them at the point of
  first mention

Why post-processing rather than folding this into the weekly-review skill:
figure extraction is deterministic PDF work, not language work, and doing it
here means the 60 cards already on disk get enriched without re-running the
expensive per-paper sub-agents.

Three decisions worth knowing about, each of which cost a bug to learn::

    1. Look up metadata by *item key*, never by slug.
       A merged card (two Zotero items, one card) has a slug that matches no
       fulltext file at all -- the Virtual Lab card is the live example.

    2. Figures cited from a bullet go in as an *indented continuation*.
       Most figure citations sit in list items.  An unindented block after
       one splits the list in two, so bullets get four spaces of indent and
       paragraphs stay flush left.

    3. Idempotency is per figure, not per card.
       A run interrupted part-way leaves a card with some figures inlined;
       skipping the whole card would strand the rest forever.

Usage::

    uv run --with pymupdf python scripts/enrich_cards.py enrich \\
        --cards-dir    outputs/survey-ai-scientist/2026-09-10/cards \\
        --fulltext-dir outputs/survey-ai-scientist/2026-09-10/fulltext \\
        --figures-dir  outputs/survey-ai-scientist/2026-09-10/figures

``pymupdf`` is only needed for the ``figures`` half; ``links`` runs without it.

Exit codes: 0 ok, 1 bad input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests

# Zotero Desktop Local API -- same base and version header as
# scripts/fetch_collection_fulltext.py, so both agree on what "the library"
# means and neither invents its own routing.
ZOTERO_BASE_URL = "http://127.0.0.1:23119"
ZOTERO_LOCAL_USER = "/api/users/0"
ZOTERO_HEADERS = {"Zotero-API-Version": "3"}

METADATA_TIMEOUT = 30
PDF_TIMEOUT = 180

# Rendering resolution for extracted figures.  120 dpi keeps a full-width
# figure around 1000 px wide -- legible on screen without producing
# multi-megabyte PNGs for a corpus that runs to a few hundred images.
FIGURE_DPI = 120

# A caption block *begins* with this.  Anchoring at the start of the block is
# what separates a caption from a passing mention: in one measured paper
# "Figure 4" appeared on six different pages, five of them prose.
#
# Publishers separate the number from the caption text in three ways, all
# seen in this corpus: "Figure 1 | ...", "Figure 1 – ...", and "Fig. 1
# Publication ..." with nothing but a space.  Requiring a punctuation
# separator (the first draft did) silently misses the latter two, so the
# separator is optional -- and to keep prose out, a bare space must be
# followed by something a caption plausibly starts with (a capital, a digit,
# a bracket) rather than a lowercase verb like "shows".
FIGURE_CAPTION = re.compile(
    r"^\s*(?:Figure|Fig\.?)\s*(\d+)(?:\s*[.:|–—‐-]|\s+(?=[A-Z0-9(\[“\"]))"
)

# In-text citations to figure numbers, English or Chinese: the cards cite
# "Fig 2b-d" and "（图 2）" interchangeably.  The lookbehinds drop
# supplementary figures -- those live in a separate PDF we never downloaded,
# so inlining them is impossible and a broken embed would be worse than none.
# Chinese tables ("表 3") need no rule: 表 is a different character.
FIGURE_REF = re.compile(
    r"(?<!Supp )(?<!Supplementary )(?:Fig(?:ure)?\.?|(?<!附)图)\s*(\d+)",
    re.IGNORECASE,
)

_ZOTERO_KEY_LINE = re.compile(r"^\s*-\s*\*\*Zotero Key\*\*:(.*)$", re.MULTILINE)
_BACKTICKED = re.compile(r"`([A-Za-z0-9]+)`")
_ORIGINAL_LINE = "- **原文**:"

# arXiv DOIs as Zotero stores them.  The "ARXIV" part is upper-cased in some
# records and lower-cased in others, so the pattern accepts either.
_ARXIV_DOI = re.compile(r"10\.48550/[Aa][Rr][Xx][Ii][Vv]\.(\d{4}\.\d{4,5})")

# Continuation indent that keeps an embed inside its parent list item.
BULLET_INDENT = "    "

BULLET_MARKERS = ("- ", "* ", "+ ")


# ── Card header ───────────────────────────────────────────────────────────


def _extract_zotero_keys(card_text: str) -> list[str]:
    """Every Zotero key on the card's ``Zotero Key`` line, in order.

    A merged card lists two (``E86CGDYM`` preprint / ``8QGXBUJS`` published);
    the first is the one whose fulltext we already have on disk.
    """
    keys: list[str] = []
    for match in _ZOTERO_KEY_LINE.finditer(card_text):
        keys.extend(_BACKTICKED.findall(match.group(1)))
    return keys


def _add_links(card_path: Path, fulltext: dict, report) -> bool:
    """Insert the ``原文`` line after the Zotero Key line.  True if changed."""
    text = card_path.read_text(encoding="utf-8")
    if _ORIGINAL_LINE in text:
        return False

    item_key = fulltext.get("itemKey")
    if not item_key:
        return False

    parts = [f"[Zotero 条目](zotero://select/library/items/{item_key})"]
    attachment_key = fulltext.get("attachmentKey")
    if attachment_key:
        parts.append(
            f"[在 Zotero 中打开 PDF]"
            f"(zotero://open-pdf/library/items/{attachment_key})"
        )
    # Items recovered from arXiv have no attachment of their own; they get the
    # item link alone rather than a PDF link that would open nothing.
    link_line = f"{_ORIGINAL_LINE} " + " ｜ ".join(parts)

    lines = text.split("\n")
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and _ZOTERO_KEY_LINE.match(line):
            out.append(link_line)
            inserted = True
    if not inserted:
        return False

    card_path.write_text("\n".join(out), encoding="utf-8")
    return True


# ── Metadata lookup ───────────────────────────────────────────────────────


def _find_fulltext(fulltext_dir: Path, item_key: str) -> dict | None:
    """The fulltext record for this item, found by key rather than filename."""
    for path in sorted(fulltext_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("itemKey") == item_key:
            return data
    return None


# ── PDF location ──────────────────────────────────────────────────────────


def _resolve_pdf_path(attachment_key: str | None) -> str | None:
    """Ask Zotero where an attachment's file actually lives.

    Handles both storage back-ends the library mixes: linked files pointing at
    Google Drive, and attachments inside Zotero's own ``storage/`` tree.
    """
    if not attachment_key:
        return None
    url = (
        f"{ZOTERO_BASE_URL}{ZOTERO_LOCAL_USER}"
        f"/items/{attachment_key}/file/view/url"
    )
    try:
        response = requests.get(url, headers=ZOTERO_HEADERS, timeout=METADATA_TIMEOUT)
        response.raise_for_status()
        raw = response.text.strip().strip('"')
    except Exception:  # noqa: BLE001 - a missing PDF is a normal outcome
        return None

    if not raw.startswith("file://"):
        return None
    path = unquote(raw)
    for prefix in ("file:///", "file://"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
            break
    return path if Path(path).exists() else None


def _arxiv_id(doi: str) -> str | None:
    match = _ARXIV_DOI.search(doi or "")
    return match.group(1) if match else None


def _arxiv_pdf(slug: str, doi: str, cache_dir: Path) -> str | None:
    """Download the arXiv PDF, cached on disk so re-runs do not refetch."""
    arxiv_id = _arxiv_id(doi)
    if not arxiv_id:
        return None

    cached = cache_dir / f"{slug}.pdf"
    if cached.exists() and cached.stat().st_size > 0:
        return str(cached)

    cache_dir.mkdir(parents=True, exist_ok=True)
    # The bare /pdf/{id} endpoint intermittently answers with an HTML error
    # page; /pdf/{id}v1 returns the PDF reliably, with the export mirror as a
    # second try.  Checking the magic bytes catches the HTML case, which
    # otherwise fails much later as an unreadable PDF.
    for url in (
        f"https://arxiv.org/pdf/{arxiv_id}v1",
        f"https://export.arxiv.org/pdf/{arxiv_id}",
    ):
        try:
            response = requests.get(url, timeout=PDF_TIMEOUT)
        except Exception:  # noqa: BLE001 - try the next source
            continue
        if response.status_code == 200 and response.content[:4] == b"%PDF":
            cached.write_bytes(response.content)
            return str(cached)
    return None


# ── Figure extraction ─────────────────────────────────────────────────────


def _extract_figures(
    pdf_path: str, figures_dir: Path, slug: str, wanted: set[int] | None = None
) -> dict[int, str]:
    """Render figures to PNG; returns ``{number: filename}``.

    ``wanted`` limits rendering to the figures a card actually cites.  Papers
    average far more figures than any one card mentions, so rendering
    everything leaves a few hundred unreferenced PNGs on disk.


    Embedded raster images are not usable here: journal and arXiv figures are
    overwhelmingly *vector*, so ``get_images()`` returns nothing for them (one
    measured paper had 18,007 vector drawings and 6 bitmaps).  Rendering the
    clipped region works for both, at the cost of needing the region -- hence
    the caption anchor and the bounding-box union below.
    """
    try:
        import pymupdf
    except ImportError:
        print(
            "ERROR: pymupdf 未安装，无法提图。用 "
            "`uv run --with pymupdf python scripts/enrich_cards.py ...` 运行。",
            file=sys.stderr,
        )
        return {}

    try:
        document = pymupdf.open(pdf_path)
    except Exception:  # noqa: BLE001 - a corrupt download must not abort the run
        return {}

    found: dict[int, str] = {}
    try:
        for page_index in range(document.page_count):
            page = document[page_index]
            width, height = page.rect.width, page.rect.height
            for block in page.get_text("blocks"):
                caption = block[4]
                match = FIGURE_CAPTION.match(caption)
                if not match:
                    continue
                number = int(match.group(1))
                if number in found:
                    continue
                if wanted is not None and number not in wanted:
                    continue

                caption_rect = pymupdf.Rect(block[:4])
                boxes = []
                for drawing in page.get_drawings():
                    rect = drawing["rect"]
                    if rect.width < 6 or rect.height < 6:
                        continue
                    if rect.width > width * 0.97 and rect.height > height * 0.9:
                        continue  # page-wide background or rule
                    boxes.append(rect)
                for info in page.get_image_info():
                    rect = pymupdf.Rect(info["bbox"])
                    if rect.width > 20 and rect.height > 20:
                        boxes.append(rect)
                if not boxes:
                    continue

                top = max(0.0, min(box.y0 for box in boxes))
                top = min(top, caption_rect.y0)
                bottom = min(caption_rect.y1 + 4, height)
                region = pymupdf.Rect(0, top, width, bottom)
                if region.height < 60:
                    # Nothing above the caption on this page -- take the whole
                    # page rather than emit a sliver.
                    region = pymupdf.Rect(0, 0, width, bottom)

                filename = f"{slug}_fig{number:02d}.png"
                figures_dir.mkdir(parents=True, exist_ok=True)
                page.get_pixmap(dpi=FIGURE_DPI, clip=region).save(
                    str(figures_dir / filename)
                )
                found[number] = filename
    finally:
        document.close()
    return found


# ── Inline insertion ──────────────────────────────────────────────────────


def _find_figure_refs(text: str) -> set[int]:
    """Figure numbers cited in ``text``, supplementary figures excluded."""
    return {int(match.group(1)) for match in FIGURE_REF.finditer(text)}


def _insert_inline_figures(
    card_path: Path,
    fulltext: dict,
    figures_dir: Path,
    cache_dir: Path,
    report,
) -> int:
    """Inline each cited figure at its first mention.  Returns how many went in."""
    text = card_path.read_text(encoding="utf-8")
    slug = card_path.stem

    cited = _find_figure_refs(text)
    if not cited:
        return 0

    embedded = {n for n in cited if f"![[{slug}_fig{n:02d}.png]]" in text}
    needed = cited - embedded
    if not needed:
        return 0

    pdf_path = _resolve_pdf_path(fulltext.get("attachmentKey"))
    if not pdf_path:
        doi = fulltext.get("doi") or ""
        if _arxiv_id(doi):
            pdf_path = _arxiv_pdf(slug, doi, cache_dir)
    if not pdf_path:
        report(f"[skip] {slug}: 无本地 PDF 也无可用 arXiv 版本，跳过提图")
        return 0

    extracted = _extract_figures(pdf_path, figures_dir, slug, wanted=needed)
    available = {n: name for n, name in extracted.items() if n in needed}
    if not available:
        report(f"[skip] {slug}: 论文正文里没有找到卡片引用的图号 {sorted(needed)}")
        return 0

    lines = text.split("\n")
    out: list[str] = []
    inserted = 0
    # A figure cited from two bullets (or a bullet and a paragraph) must be
    # inlined once, at the first mention -- `available` alone does not shrink
    # as the loop advances, so the pass tracks what it has placed.
    placed: set[int] = set()
    for index, line in enumerate(lines):
        out.append(line)
        todo = sorted(
            n
            for n in _find_figure_refs(line)
            if n in available and n not in placed
        )
        if not todo:
            continue
        is_bullet = line.lstrip().startswith(BULLET_MARKERS)
        for number in todo:
            out.append("")
            indent = BULLET_INDENT if is_bullet else ""
            out.append(f"{indent}![[{available[number]}]]")
            placed.add(number)
            inserted += 1
        if not is_bullet:
            # Close the paragraph off, or the next one merges into the embed.
            # Skip it when the source already had a blank line there, so the
            # card does not accumulate runs of empty lines.
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if following.strip():
                out.append("")

    card_path.write_text("\n".join(out), encoding="utf-8")
    return inserted


# ── Orchestration ─────────────────────────────────────────────────────────


def enrich_cards(
    *,
    cards_dir: Path,
    fulltext_dir: Path,
    figures_dir: Path,
    do_links: bool,
    do_figures: bool,
    report,
) -> dict:
    """Enrich every card in ``cards_dir``.  Returns a run summary."""
    cache_dir = figures_dir / ".cache"
    cards = sorted(cards_dir.glob("*.md"))
    summary = {"cards": len(cards), "links": 0, "figures": 0}

    for card_path in cards:
        text = card_path.read_text(encoding="utf-8")
        keys = _extract_zotero_keys(text)
        if not keys:
            report(f"[skip] {card_path.stem}: 卡头没有 Zotero Key")
            continue

        fulltext = _find_fulltext(fulltext_dir, keys[0])
        if fulltext is None:
            report(f"[skip] {card_path.stem}: fulltext 里找不到 itemKey {keys[0]}")
            continue

        if do_links and _add_links(card_path, fulltext, report):
            summary["links"] += 1
            report(f"[link] {card_path.stem}")

        if do_figures:
            count = _insert_inline_figures(
                card_path, fulltext, figures_dir, cache_dir, report
            )
            if count:
                summary["figures"] += count
                report(f"[fig]  {card_path.stem}: {count} 张")

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich analysis cards with Zotero links and inline figures",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--cards-dir", required=True, type=Path)
        p.add_argument("--fulltext-dir", required=True, type=Path)
        p.add_argument("--quiet", action="store_true")

    links_p = sub.add_parser("links", help="Only add the 原文 link line")
    add_common(links_p)

    figures_p = sub.add_parser("figures", help="Only inline cited figures")
    add_common(figures_p)
    figures_p.add_argument("--figures-dir", required=True, type=Path)

    enrich_p = sub.add_parser("enrich", help="Both (default)")
    add_common(enrich_p)
    enrich_p.add_argument("--figures-dir", required=True, type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy codepage; card slugs and messages
    # here are not ASCII.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    args = build_parser().parse_args(argv)

    def report(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    if not args.cards_dir.is_dir():
        print(f"ERROR: --cards-dir {args.cards_dir} 不是目录", file=sys.stderr)
        return 1
    if not args.fulltext_dir.is_dir():
        print(f"ERROR: --fulltext-dir {args.fulltext_dir} 不是目录", file=sys.stderr)
        return 1

    summary = enrich_cards(
        cards_dir=args.cards_dir,
        fulltext_dir=args.fulltext_dir,
        figures_dir=getattr(args, "figures_dir", args.cards_dir.parent / "figures"),
        do_links=args.command in ("links", "enrich"),
        do_figures=args.command in ("figures", "enrich"),
        report=report,
    )

    print(
        f"处理 {summary['cards']} 张卡："
        f"加链接 {summary['links']} 张，内联图 {summary['figures']} 张"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
