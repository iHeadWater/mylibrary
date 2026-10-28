"""Pure figure-selection helpers.

The converter measures image boxes and text boxes; this module decides which
images are worth extracting, where their captions are and how they are named.
No PDF library and no file I/O lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .anchors import Box
from .captions import caption_label

# A 50×50 pt image is the practical floor for a figure; smaller images are
# usually bullets, rules or publisher logos.
MIN_IMAGE_EDGE = 40.0
MIN_IMAGE_AREA = 2500.0
CAPTION_MAX_GAP = 90.0
CAPTION_MIN_HORIZONTAL_OVERLAP = 8.0

# Vector figures are line drawings. The drawing cluster above a caption is
# grown upward while the vertical gap stays below this many points.
VECTOR_MAX_GAP = 32.0
MIN_VECTOR_WIDTH = 80.0
MIN_VECTOR_HEIGHT = 50.0
# A whitespace band below this height is too thin to hold a readable figure,
# above the upper bound it is a layout gap rather than a figure.
WHITESPACE_MIN_HEIGHT = 45.0
WHITESPACE_MAX_HEIGHT = 460.0
# Full-width hairlines are page decoration (section rules, table frames), not
# figure content.
DECORATION_WIDTH_SHARE = 0.75
DECORATION_MAX_HEIGHT = 3.0
COVERAGE_DEDUPE = 0.5


@dataclass(frozen=True)
class VectorFigure:
    """A figure rendered from vector drawings instead of an embedded image."""

    box: Box
    caption: str
    label: str


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
    info = caption_label(text)
    return info is not None and info[0] == "figure"


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


def _overlap_area(left: Box, right: Box) -> float:
    width = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    height = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    return width * height


def _covered(region: Box, boxes: Sequence[Box]) -> bool:
    """True when another asset already covers most of ``region``."""

    if region.area <= 0:
        return True
    for box in boxes:
        overlap = _overlap_area(region, box)
        if overlap <= 0:
            continue
        if overlap / min(region.area, box.area) >= COVERAGE_DEDUPE:
            return True
    return False


def _is_decoration(box: Box, page_width: float) -> bool:
    if box.width <= 2 or box.height <= 2:
        return True
    return box.width >= page_width * DECORATION_WIDTH_SHARE and box.height <= DECORATION_MAX_HEIGHT


def _barrier(caption: Box, text_blocks: Sequence[CaptionBlock]) -> float:
    """Bottom edge of the nearest text above the caption in the same column."""

    limit = 0.0
    for block in text_blocks:
        if block.box.y1 > caption.y0 - 1:
            continue
        if caption.horizontal_overlap(block.box) < CAPTION_MIN_HORIZONTAL_OVERLAP:
            continue
        limit = max(limit, block.box.y1)
    return limit


def vector_figure_region(
    caption: CaptionBlock,
    drawings: Sequence[Box],
    text_blocks: Sequence[CaptionBlock],
    page_width: float,
    page_height: float,
) -> Box | None:
    """Region occupied by the vector drawing above ``caption``.

    Drawings are grown upward from the caption while they stay close together
    and below the nearest body text. If no usable drawing cluster exists, the
    whitespace band between that text and the caption is used instead -- many
    figures mix a vector plot with an embedded image or leave wide margins.
    """

    caption_box = caption.box
    barrier = _barrier(caption_box, text_blocks)
    nearby = [
        box
        for box in drawings
        if not _is_decoration(box, page_width)
        and box.y1 <= caption_box.y0 - 1
        and box.x1 > caption_box.x0 - 30
        and box.x0 < caption_box.x1 + 30
    ]
    nearby.sort(key=lambda box: (box.y1, box.x0), reverse=True)

    region: Box | None = None
    if nearby:
        top = nearby[0].y0
        bottom = nearby[0].y1
        left = nearby[0].x0
        right = nearby[0].x1
        for box in nearby[1:]:
            if top - box.y1 > VECTOR_MAX_GAP:
                break
            if box.y0 < barrier - 2:
                break
            top = min(top, box.y0)
            left = min(left, box.x0)
            right = max(right, box.x1)
        candidate = Box(
            x0=max(0.0, left - 2),
            y0=max(0.0, min(top, caption_box.y0) - 4),
            x1=min(page_width, right + 2),
            y1=min(caption_box.y0 - 2, bottom + 6),
        )
        if candidate.width >= MIN_VECTOR_WIDTH and candidate.height >= MIN_VECTOR_HEIGHT:
            region = candidate

    if region is None:
        top = max(barrier + 4, 0.0)
        bottom = caption_box.y0 - 4
        if WHITESPACE_MIN_HEIGHT <= bottom - top <= WHITESPACE_MAX_HEIGHT:
            width_box = Box(
                x0=max(0.0, caption_box.x0 - 5),
                y0=top,
                x1=min(page_width, caption_box.x1 + 30),
                y1=bottom,
            )
            if width_box.width >= MIN_VECTOR_WIDTH:
                region = width_box

    if region is None:
        return None
    if region.y0 >= page_height or region.y1 <= 0:
        return None
    return region


def select_vector_figures(
    page: int,
    captions: Sequence[CaptionBlock],
    drawings: Sequence[Box],
    text_blocks: Sequence[CaptionBlock],
    page_width: float,
    page_height: float,
    *,
    raster_boxes: Sequence[Box] = (),
) -> tuple[VectorFigure, ...]:
    """Caption-anchored vector figures, deduplicated against raster images."""

    selected: list[VectorFigure] = []
    claimed: list[Box] = list(raster_boxes)
    for caption in captions:
        info = caption_label(caption.text)
        if info is None or info[0] != "figure":
            continue
        region = vector_figure_region(
            caption, drawings, text_blocks, page_width, page_height
        )
        if region is None:
            continue
        if _covered(region, claimed):
            continue
        claimed.append(region)
        selected.append(
            VectorFigure(box=region, caption=caption.text.strip(), label=info[2])
        )
    selected.sort(key=lambda figure: (round(figure.box.y0, 2), round(figure.box.x0, 2)))
    return tuple(selected)


__all__ = [
    "CAPTION_MAX_GAP",
    "CaptionBlock",
    "FigurePlacement",
    "MIN_IMAGE_AREA",
    "MIN_IMAGE_EDGE",
    "MIN_VECTOR_HEIGHT",
    "MIN_VECTOR_WIDTH",
    "VECTOR_MAX_GAP",
    "VectorFigure",
    "figure_filename",
    "figure_id",
    "find_caption",
    "is_significant_image",
    "select_figures",
    "select_vector_figures",
    "vector_figure_region",
]
