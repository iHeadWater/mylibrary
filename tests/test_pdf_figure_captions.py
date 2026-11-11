"""Regression tests for figure capture: caption labels and tile merging.

Both rules come from real papers that the earlier converter got wrong. Nature,
Communications and Elsevier print captions as ``Fig. 1 | Title`` or as
``Fig. 1 Title`` with no separator at all, so a separator-only pattern found no
caption on those PDFs and every image fell through to the appendix. A
two-column layout, in turn, delivers one figure as several embedded images (or
vector fragments); the caption label is the only evidence that they belong
together, so tiles sharing a label are unioned into a single crop.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

from hydrolitagent.cards.adapters.pdf.anchors import Box
from hydrolitagent.cards.adapters.pdf.captions import caption_label
from hydrolitagent.cards.adapters.pdf.figures import (
    FigurePlacement,
    merge_caption_duplicates,
)
from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.ports.paper import ConversionOptions, ConversionRequest

PAGE_WIDTH = 595
PAGE_HEIGHT = 842

BODY = (
    "The flood chain was tracked from rainfall through runoff to inundation. "
    "Each link is measured at the same gauging station and reported in the same units. "
)


# --------------------------------------------------------------------------------------
# Caption labels
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fig. 1 | Wadi Derna flood extent for the two events.", ("figure", 1, "Figure 1")),
        ("Figure 3. Disruptions to the transport network.", ("figure", 3, "Figure 3")),
        ("Fig. 1 Pipeline for hazard-chain identification.", ("figure", 1, "Figure 1")),
        ("FIG. 2: Observed hydrograph at the outlet.", ("figure", 2, "Figure 2")),
        ("Fig. 4 — Model structure and forcing.", ("figure", 4, "Figure 4")),
        ("Fig 12 灾害链传递路径示意图", ("figure", 12, "Figure 12")),
        ("Table 2 | Reported losses by district.", ("table", 2, "Table 2")),
        ("Table 1 Population and exposure by settlement.", ("table", 1, "Table 1")),
        ("Figure 5", ("figure", 5, "Figure 5")),
    ],
)
def test_caption_label_accepts_the_shapes_printers_use(
    text: str, expected: tuple[str, int, str]
) -> None:
    assert caption_label(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Figure 5 shows population-averaged exposure in the delta.",
        "Figure 1a compares the two runs.",
        "Fig. 2 and Fig. 3 report the same pattern.",
        "As shown in Figure 2, the peak arrives late.",
        "Figure",
        "Figures 2-4 summarise the events.",
    ],
)
def test_caption_label_rejects_body_prose(text: str) -> None:
    assert caption_label(text) is None


# --------------------------------------------------------------------------------------
# Tile merging
# --------------------------------------------------------------------------------------


def test_merge_caption_duplicates_unions_tiles_of_one_figure() -> None:
    placements = (
        FigurePlacement(
            page=5, ordinal=1, box=Box(x0=50, y0=100, x1=200, y1=300), caption="Fig. 1 | Left"
        ),
        FigurePlacement(
            page=5, ordinal=2, box=Box(x0=210, y0=100, x1=360, y1=300), caption="Fig. 1 | Left"
        ),
        FigurePlacement(
            page=5, ordinal=3, box=Box(x0=50, y0=320, x1=360, y1=520), caption="Fig. 2. Second"
        ),
        FigurePlacement(page=5, ordinal=4, box=Box(x0=50, y0=600, x1=120, y1=660), caption=None),
    )

    merged = merge_caption_duplicates(placements)

    assert [placement.ordinal for placement in merged] == [1, 2, 3]
    assert merged[0].box == Box(x0=50, y0=100, x1=360, y1=300)
    assert merged[0].caption and merged[0].caption.startswith("Fig. 1")
    assert merged[0].figure_id == "page-005-fig-1"
    assert merged[1].box == Box(x0=50, y0=320, x1=360, y1=520)
    assert merged[2].caption is None


def test_merge_caption_duplicates_never_crosses_pages() -> None:
    placements = (
        FigurePlacement(page=2, ordinal=1, box=Box(x0=50, y0=100, x1=200, y1=300), caption="Fig. 1 | A"),
        FigurePlacement(page=3, ordinal=1, box=Box(x0=50, y0=100, x1=200, y1=300), caption="Fig. 1 | B"),
    )

    merged = merge_caption_duplicates(placements)

    assert len(merged) == 2
    assert [placement.page for placement in merged] == [2, 3]


# --------------------------------------------------------------------------------------
# End-to-end through the converter
# --------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _convert(pdf_path: Path, output_dir: Path):
    request = ConversionRequest(
        pdf_path=pdf_path,
        pdf_sha256=_sha256(pdf_path),
        size_bytes=pdf_path.stat().st_size,
        output_dir=output_dir,
        options=ConversionOptions(),
    )
    return PymupdfConverter().convert(request)


def _image(page: pymupdf.Page, rect: pymupdf.Rect, colour: tuple[int, int, int]) -> None:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), 0)
    pixmap.set_rect(pixmap.irect, colour)
    page.insert_image(rect, pixmap=pixmap)


def _split_figure_pdf(tmp_path: Path) -> Path:
    """One figure, delivered as two tiles, plus a fragment with no caption."""

    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 80), "Flood Chain Response", fontsize=16)
    page.insert_textbox(pymupdf.Rect(72, 95, 523, 340), BODY * 3, fontsize=10)

    _image(page, pymupdf.Rect(72, 360, 252, 480), (30, 120, 200))
    _image(page, pymupdf.Rect(262, 360, 442, 480), (200, 120, 30))
    page.insert_text(
        (72, 500),
        "Fig. 1 | Observed hydrograph and its components across the events.",
        fontsize=9,
    )
    page.insert_textbox(pymupdf.Rect(72, 515, 523, 660), BODY * 2, fontsize=10)

    # A 60 pt fragment far below the caption: no label, too small to be a figure.
    _image(page, pymupdf.Rect(72, 700, 132, 760), (120, 120, 120))

    path = tmp_path / "split-figure.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_tiles_sharing_a_caption_become_one_figure(tmp_path: Path) -> None:
    pdf = _split_figure_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    assert len(prepared.figures) == 1
    figure = prepared.figures[0]
    assert figure.page == 1
    assert figure.figure_id == "page-001-fig-1"
    assert figure.caption and figure.caption.startswith("Fig. 1")
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert markdown.count("](figures/") == 1
