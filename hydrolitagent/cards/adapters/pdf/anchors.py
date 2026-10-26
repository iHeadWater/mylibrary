"""Pure layout rules for PDF→Markdown conversion.

Nothing here imports a PDF library. The converter measures boxes and font
sizes, then hands plain numbers to these functions so ordering, page roles,
heading levels and canary placement can be tested without a PDF file.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from hydrolitagent.cards.domain.paper import PageRole

CanaryToken = str


@dataclass(frozen=True)
class Box:
    """Axis-aligned rectangle in PDF points."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2

    def contains_point(self, x: float, y: float, *, tolerance: float = 1.0) -> bool:
        return (
            self.x0 - tolerance <= x <= self.x1 + tolerance
            and self.y0 - tolerance <= y <= self.y1 + tolerance
        )

    def horizontal_overlap(self, other: "Box") -> float:
        return max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))


@dataclass(frozen=True)
class ColumnLayout:
    """Detected column structure of one page.

    ``kind`` is ``single`` or ``two``. ``gutter_x`` is the estimated boundary
    between columns. ``uncertain`` means the evidence was contradictory (for
    example text blocks straddling the gutter), so the caller should record a
    reading-order warning instead of trusting the order silently.
    """

    kind: Literal["single", "two"]
    gutter_x: float | None
    uncertain: bool


SINGLE_COLUMN = ColumnLayout(kind="single", gutter_x=None, uncertain=False)

_GUTTER_TOLERANCE = 2.0
_MIN_BLOCKS_PER_COLUMN = 2
_MIN_VERTICAL_OVERLAP = 0.30


def _vertical_overlap(left: Sequence[Box], right: Sequence[Box]) -> float:
    if not left or not right:
        return 0.0
    left_span = (min(b.y0 for b in left), max(b.y1 for b in left))
    right_span = (min(b.y0 for b in right), max(b.y1 for b in right))
    overlap = max(0.0, min(left_span[1], right_span[1]) - max(left_span[0], right_span[0]))
    smaller = min(left_span[1] - left_span[0], right_span[1] - right_span[0])
    return overlap / smaller if smaller > 0 else 0.0


def detect_columns(
    boxes: Sequence[Box],
    page_width: float,
    *,
    min_blocks_per_column: int = _MIN_BLOCKS_PER_COLUMN,
    min_overlap: float = _MIN_VERTICAL_OVERLAP,
) -> ColumnLayout:
    """Detect a two-column page from text block geometry.

    The heuristic is deliberately conservative: a page is only treated as
    two-column when both halves hold at least ``min_blocks_per_column`` blocks
    and those blocks overlap vertically. Anything that straddles the middle
    makes the result ``uncertain`` rather than silently reordering content.
    """

    usable = [b for b in boxes if b.width > 0 and b.height > 0]
    if page_width <= 0 or len(usable) < min_blocks_per_column * 2:
        return SINGLE_COLUMN

    middle = page_width / 2
    left = [b for b in usable if b.x1 <= middle - _GUTTER_TOLERANCE]
    right = [b for b in usable if b.x0 >= middle + _GUTTER_TOLERANCE]
    if len(left) < min_blocks_per_column or len(right) < min_blocks_per_column:
        return SINGLE_COLUMN
    if _vertical_overlap(left, right) < min_overlap:
        return SINGLE_COLUMN

    gutter = (max(b.x1 for b in left) + min(b.x0 for b in right)) / 2
    straddling = [
        b for b in usable
        if b.x0 < gutter - _GUTTER_TOLERANCE and b.x1 > gutter + _GUTTER_TOLERANCE
    ]
    # Wide straddling blocks are normal (titles, full-width tables). Narrow ones
    # mean the gutter estimate is wrong, so flag the order as uncertain.
    uncertain = any(b.width < page_width * 0.35 for b in straddling)
    return ColumnLayout(kind="two", gutter_x=gutter, uncertain=uncertain)


def order_boxes(boxes: Sequence[Box], layout: ColumnLayout) -> list[int]:
    """Return block indices in intended reading order.

    Single-column pages sort by ``(y, x)``. Two-column pages emit left column
    then right column, using full-width blocks (titles, wide tables, display
    equations) as band separators.

    The bands partition the page by the separators' *top* edges, so a block
    that vertically overlaps a separator is still emitted exactly once. An
    earlier version used each separator's bottom edge as the next band start
    and silently dropped any overlapping block that was not itself full width
    -- 28 formula fragments disappeared from one page of a real paper.
    """

    indices = [i for i, b in enumerate(boxes) if b.width > 0 and b.height > 0]
    if layout.kind != "two" or layout.gutter_x is None:
        return sorted(indices, key=lambda i: (round(boxes[i].y0, 2), round(boxes[i].x0, 2)))

    gutter = layout.gutter_x
    separators = sorted(
        (
            i
            for i in indices
            if boxes[i].x0 < gutter - _GUTTER_TOLERANCE
            and boxes[i].x1 > gutter + _GUTTER_TOLERANCE
        ),
        key=lambda i: (round(boxes[i].y0, 2), round(boxes[i].x0, 2)),
    )
    separator_set = set(separators)
    remaining = [i for i in indices if i not in separator_set]
    key = lambda i: (round(boxes[i].y0, 2), round(boxes[i].x0, 2))  # noqa: E731

    ordered: list[int] = []

    def emit_band(top: float, bottom: float) -> None:
        band = [i for i in remaining if top <= boxes[i].center_y < bottom]
        left = [i for i in band if boxes[i].center_x < gutter]
        right = [i for i in band if boxes[i].center_x >= gutter]
        ordered.extend(sorted(left, key=key))
        ordered.extend(sorted(right, key=key))

    cursor = float("-inf")
    for index in separators:
        boundary = boxes[index].y0
        if boundary > cursor:
            emit_band(cursor, boundary)
        ordered.append(index)
        cursor = max(cursor, boundary)
    emit_band(cursor, float("inf"))
    return ordered


# --------------------------------------------------------------------------------------
# Headings and page roles
# --------------------------------------------------------------------------------------

_HEADING_MAX_CHARS = 140
_BOLD_FLAG = 16
_WS = re.compile(r"[ \t ]+")

_REFERENCE_WORDS = ("references", "bibliography", "literature cited", "参考文献")
_APPENDIX_WORDS = ("appendix", "supplementary", "附录")
_ABSTRACT_WORDS = ("abstract", "摘要")
_BODY_WORDS = ("introduction", "引言", "1 introduction")


def normalize_heading(text: str) -> str:
    return _WS.sub(" ", text).strip()


# --------------------------------------------------------------------------------------
# Running headers, running footers and download stamps
# --------------------------------------------------------------------------------------

# A line is a margin candidate when its centre falls inside this fraction of the
# page height at the top or the bottom. Publisher headers live there; body text
# does not.
MARGIN_BAND = 0.08
# A text must appear in this share of the pages to count as running matter.
REPEAT_PAGE_SHARE = 0.5

_EDGE_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_DOWNLOAD_MARKERS = (
    "downloaded from",
    "onlinelibrary.wiley.com",
    "terms and conditions",
)


def normalize_margin_text(text: str) -> str:
    """Key used to compare margin lines across pages.

    Page numbers change on every page, so digit runs collapse to ``#``. That
    makes "7036" and "7037" compare equal without treating unrelated body text
    as repeated.
    """

    collapsed = _EDGE_WS.sub(" ", text).strip().casefold()
    return _DIGITS.sub("#", collapsed)


def is_margin_line(box: Box, page_height: float, *, band: float = MARGIN_BAND) -> bool:
    """True when a line starts inside the top band or ends inside the bottom one.

    Using the line edge rather than its centre matters: a 17 pt journal header
    whose baseline sits just below the 8% line still belongs to the header, and
    excluding it would leave the masthead in every page's body text.
    """

    if page_height <= 0:
        return False
    return box.y0 <= page_height * band or box.y1 >= page_height * (1 - band)


def is_download_stamp(text: str) -> bool:
    """True for publisher "Downloaded from ..." stamps and licence footers."""

    lowered = text.casefold()
    return any(marker in lowered for marker in _DOWNLOAD_MARKERS)


def repeated_margin_texts(
    page_lines: Sequence[Sequence[tuple[str, Box]]],
    page_heights: Sequence[float],
    *,
    band: float = MARGIN_BAND,
    share: float = REPEAT_PAGE_SHARE,
) -> tuple[str, ...]:
    """Normalised texts that repeat in the margins of enough pages.

    Detection is deliberately two-step: a text only becomes a candidate when it
    sits in the top/bottom band of several pages, which stops one stray body
    line from being deleted. Callers then remove every line with that text --
    including the copy on a page whose header sits slightly lower than the band,
    which is exactly the title page in real journal layouts.
    """

    if not page_lines:
        return ()
    counts: dict[str, set[int]] = {}
    for index, (lines, height) in enumerate(zip(page_lines, page_heights)):
        seen: set[str] = set()
        for text, box in lines:
            if not text.strip():
                continue
            if not is_margin_line(box, height, band=band):
                continue
            key = normalize_margin_text(text)
            if key:
                seen.add(key)
        for key in seen:
            counts.setdefault(key, set()).add(index)

    threshold = max(2, math.ceil(len(page_lines) * share))
    return tuple(sorted(key for key, pages in counts.items() if len(pages) >= threshold))


def body_font_size(spans: Iterable[tuple[str, float, bool]]) -> float:
    """Most common font size, weighted by character count.

    Using the character count instead of the span count keeps a handful of
    large section titles from defining the body size.
    """

    return dominant_size(spans, default=10.0)


def dominant_size(
    spans: Iterable[tuple[str, float, bool]], *, default: float = 0.0
) -> float:
    """Font size that carries most of the given characters.

    Journal PDFs write a run-in label (``Abstract`` in 12 pt, not bold) and the
    following paragraph as **one** line. Taking the largest span size would turn
    that whole paragraph into a section heading; weighting by characters keeps
    the line at body size, so the heading rule cannot fire on prose.
    """

    weights: dict[float, int] = {}
    for text, size, _bold in spans:
        if not text.strip() or size <= 0:
            continue
        key = round(size * 2) / 2
        weights[key] = weights.get(key, 0) + len(text.strip())
    if not weights:
        return default
    return max(sorted(weights), key=lambda value: weights[value])


def heading_level(
    text: str,
    size: float,
    bold: bool,
    body_size: float,
) -> int | None:
    """Return a Markdown heading level (1–3) or ``None`` for body text."""

    stripped = normalize_heading(text)
    if not stripped or len(stripped) > _HEADING_MAX_CHARS:
        return None
    if stripped.endswith(".") and not bold:
        return None
    if size >= body_size + 5:
        return 1
    if size >= body_size + 2:
        return 2
    if size >= body_size + 0.5 and bold:
        return 3
    if bold and size >= body_size - 0.5 and len(stripped) <= 80:
        return 3
    return None


def _matches(words: Sequence[str], heading: str) -> bool:
    lowered = heading.casefold()
    return any(word in lowered for word in words)


def assign_page_roles(
    page_headings: Sequence[Sequence[str]],
) -> tuple[tuple[PageRole, ...], tuple[str | None, ...]]:
    """Classify pages and pick their most prominent heading.

    Returns one role and one heading (``None`` when the page has none) per
    page. A page turns into ``references``/``appendix`` from the heading where
    that section starts and keeps that role until the next section.
    """

    roles: list[PageRole] = []
    primary: list[str | None] = []
    in_references = False
    in_appendix = False
    body_started = False

    for index, headings in enumerate(page_headings):
        normalized = [normalize_heading(h) for h in headings if normalize_heading(h)]
        for heading in normalized:
            if _matches(_REFERENCE_WORDS, heading):
                in_references = True
            if _matches(_APPENDIX_WORDS, heading):
                in_appendix = True
            if _matches(_BODY_WORDS, heading):
                body_started = True

        if in_references:
            role: PageRole = "references"
        elif in_appendix:
            role = "appendix"
        elif not body_started and (index == 0 or any(_matches(_ABSTRACT_WORDS, h) for h in normalized)):
            role = "front_matter"
        else:
            role = "body"
        roles.append(role)
        primary.append(normalized[0] if normalized else None)

    return tuple(roles), tuple(primary)


# --------------------------------------------------------------------------------------
# Coverage and canaries
# --------------------------------------------------------------------------------------

MIN_READABLE_CHARACTERS = 40


def readable_characters(text: str) -> int:
    return sum(1 for character in text if not character.isspace())


def is_readable_page(text: str, *, minimum: int = MIN_READABLE_CHARACTERS) -> bool:
    return readable_characters(text) >= minimum


def text_coverage(page_texts: Sequence[str], *, minimum: int = MIN_READABLE_CHARACTERS) -> float:
    """Fraction of pages that hold a usable amount of text."""

    if not page_texts:
        return 0.0
    readable = sum(1 for text in page_texts if is_readable_page(text, minimum=minimum))
    return readable / len(page_texts)


def canary_token(pdf_sha256: str, index: int) -> str:
    """Deterministic integrity marker for one canary slot."""

    digest = hashlib.sha256(f"{pdf_sha256}:{index}".encode("utf-8")).hexdigest()
    return f"c-{digest[:8]}"


def canary_assignment(
    page_count: int, pdf_sha256: str, *, count: int = 3
) -> dict[int, tuple[CanaryToken, ...]]:
    """Map 0-based page index to the canary tokens written inside that page.

    Slots are spaced evenly across the document (0%, 50%, 100% by default).
    On a one-page document all slots land on that page, which still yields the
    requested number of distinct markers.
    """

    if page_count <= 0 or count <= 0:
        return {}
    tokens = tuple(canary_token(pdf_sha256, index) for index in range(count))
    if count == 1:
        positions = (0,)
    else:
        positions = tuple(
            min(page_count - 1, int(index / (count - 1) * page_count))
            for index in range(count)
        )
    assigned: dict[int, list[CanaryToken]] = {}
    for page_index, token in zip(positions, tokens):
        assigned.setdefault(page_index, []).append(token)
    return {page: tuple(values) for page, values in assigned.items()}


def canary_marker(token: CanaryToken) -> str:
    return f"<!-- reading-canary: {token} -->"


def page_marker(page: int) -> str:
    return f"<!-- page: {page} -->"


__all__ = [
    "Box",
    "CanaryToken",
    "ColumnLayout",
    "MARGIN_BAND",
    "MIN_READABLE_CHARACTERS",
    "REPEAT_PAGE_SHARE",
    "SINGLE_COLUMN",
    "assign_page_roles",
    "body_font_size",
    "canary_assignment",
    "canary_marker",
    "canary_token",
    "detect_columns",
    "dominant_size",
    "heading_level",
    "is_download_stamp",
    "is_margin_line",
    "is_readable_page",
    "normalize_heading",
    "normalize_margin_text",
    "order_boxes",
    "page_marker",
    "readable_characters",
    "repeated_margin_texts",
    "text_coverage",
]
