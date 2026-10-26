"""Pure figure-selection helpers.

The converter measures image boxes and text boxes; this module decides which
images are worth extracting, where their captions are and how they are named.
No PDF library and no file I/O lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .anchors import Box

# A 50×50 pt image is the practical floor for a figure; smaller images are
# usually bullets, rules or publisher logos.
MIN_IMAGE_EDGE = 40.0
MIN_IMAGE_AREA = 2500.0
CAPTION_MAX_GAP = 90.0
CAPTION_MIN_HORIZONTAL_OVERLAP = 8.0
_CAPTION_PREFIXES = ("fig.", "fig ", "figure", "图")


@dataclass(frozen=True)
class CaptionBlock:
    box: Box
    text: str


@dataclass(frozen=True)
class FigurePlacement:
    page: int
    ordinal: int
    box: Box
    caption: str | None

    @property
    def figure_id(self) -> str:
        return figure_id(self.page, self.ordinal)

    @property
    def filename(self) -> str:
        return f"{self.figure_id}.png"

    def box_tuple(self) -> tuple[float, float, float, float]:
        return (self.box.x0, self.box.y0, self.box.x1, self.box.y1)


def figure_id(page: int, ordinal: int) -> str:
    """Stable identifier: page number (1-based) plus figure ordinal on the page."""

    return f"page-{page:03d}-fig-{ordinal}"


def figure_filename(page: int, ordinal: int) -> str:
    return f"{figure_id(page, ordinal)}.png"


def is_significant_image(
    box: Box,
    *,
    min_edge: float = MIN_IMAGE_EDGE,
    min_area: float = MIN_IMAGE_AREA,
) -> bool:
    return box.width >= min_edge and box.height >= min_edge and box.area >= min_area


def _is_caption_text(text: str) -> bool:
    stripped = text.strip().casefold()
    return any(stripped.startswith(prefix) for prefix in _CAPTION_PREFIXES)


def find_caption(
    image: Box,
    blocks: Sequence[CaptionBlock],
    *,
    max_gap: float = CAPTION_MAX_GAP,
) -> str | None:
    """Pick the closest caption-like text block directly below ``image``.

    A caption must be below the image, share horizontal space with it and start
    with a figure label. The nearest such block wins; plain body text below an
    image is not mistaken for a caption.
    """

    best: tuple[float, str] | None = None
    for block in blocks:
        gap = block.box.y0 - image.y1
        if gap < -2.0 or gap > max_gap:
            continue
        if image.horizontal_overlap(block.box) < CAPTION_MIN_HORIZONTAL_OVERLAP:
            continue
        if not _is_caption_text(block.text):
            continue
        if best is None or gap < best[0]:
            best = (gap, block.text.strip())
    return best[1] if best else None


def select_figures(
    page: int,
    images: Sequence[Box],
    text_blocks: Sequence[CaptionBlock],
    *,
    min_edge: float = MIN_IMAGE_EDGE,
    min_area: float = MIN_IMAGE_AREA,
) -> tuple[FigurePlacement, ...]:
    """Filter and order the images of one page deterministically."""

    usable = [box for box in images if is_significant_image(box, min_edge=min_edge, min_area=min_area)]
    usable.sort(key=lambda box: (round(box.y0, 2), round(box.x0, 2), round(box.area, 2)))
    placements = [
        FigurePlacement(
            page=page,
            ordinal=ordinal,
            box=box,
            caption=find_caption(box, text_blocks),
        )
        for ordinal, box in enumerate(usable, start=1)
    ]
    return tuple(placements)


__all__ = [
    "CAPTION_MAX_GAP",
    "CaptionBlock",
    "FigurePlacement",
    "MIN_IMAGE_AREA",
    "MIN_IMAGE_EDGE",
    "figure_filename",
    "figure_id",
    "find_caption",
    "is_significant_image",
    "select_figures",
]
