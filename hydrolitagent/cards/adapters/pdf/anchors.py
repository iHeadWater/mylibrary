"""Pure layout rules for PDF→Markdown conversion.

Nothing here imports a PDF library. The converter measures boxes and font
sizes, then hands plain numbers to these functions so ordering, page roles,
heading levels and canary placement can be tested without a PDF file.
"""
from __future__ import annotations

import hashlib
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
    then right column, using full-width blocks as band separators so titles and
    wide tables stay between the columns they belong to.
    """

    indices = [i for i, b in enumerate(boxes) if b.width > 0 and b.height > 0]
    if layout.kind != "two" or layout.gutter_x is None:
        return sorted(indices, key=lambda i: (round(boxes[i].y0, 2), round(boxes[i].x0, 2)))

    gutter = layout.gutter_x
    full_width = [
        i for i in indices
        if boxes[i].x0 < gutter - _GUTTER_TOLERANCE
        and boxes[i].x1 > gutter + _GUTTER_TOLERANCE
    ]
    band_edges = sorted(((boxes[i].y0, boxes[i].y1, i) for i in full_width))

    ordered: list[int] = []

    def emit_columns(top: float, bottom: float) -> None:
        left = [i for i in indices if i not in full_width and top <= boxes[i].center_y < bottom
                and boxes[i].center_x < gutter]
        right = [i for i in indices if i not in full_width and top <= boxes[i].center_y < bottom
                 and boxes[i].center_x >= gutter]
        key = lambda i: (round(boxes[i].y0, 2), round(boxes[i].x0, 2))  # noqa: E731
        ordered.extend(sorted(left, key=key))
        ordered.extend(sorted(right, key=key))

    cursor = float("-inf")
    for top, bottom, index in band_edges:
        emit_columns(cursor, top)
        ordered.append(index)
        cursor = bottom
    emit_columns(cursor, float("inf"))
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


def body_font_size(spans: Iterable[tuple[str, float, bool]]) -> float:
    """Most common font size, weighted by character count.

    Using the character count instead of the span count keeps a handful of
    large section titles from defining the body size.
    """

    weights: dict[float, int] = {}
    for text, size, _bold in spans:
        if not text.strip() or size <= 0:
            continue
        key = round(size * 2) / 2
        weights[key] = weights.get(key, 0) + len(text.strip())
    if not weights:
        return 10.0
    return max(sorted(weights), key=lambda size: weights[size])


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
    "MIN_READABLE_CHARACTERS",
    "SINGLE_COLUMN",
    "assign_page_roles",
    "body_font_size",
    "canary_assignment",
    "canary_marker",
    "canary_token",
    "detect_columns",
    "heading_level",
    "is_readable_page",
    "normalize_heading",
    "order_boxes",
    "page_marker",
    "readable_characters",
    "text_coverage",
]
