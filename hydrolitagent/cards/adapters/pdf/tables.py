"""Borderless table recovery from text-block alignment.

Many journal PDFs draw tables without rules, so ``page.find_tables()`` (which
looks for line segments) returns nothing. This module rebuilds a table grid
from text geometry alone:

1. lines that start at ``Table N.`` are captions;
2. lines below a caption are grouped into rows by vertical proximity;
3. a row cell is a span group separated from its neighbour by a wide gap;
4. columns are the recurring x-positions across rows; cells too far from any
   recurring column are dropped (they belong to the neighbouring text column);
5. only a table with stable columns and readable text becomes Markdown. Anything
   formula-heavy or unstable is reported as ``markdown=None`` so the converter
   renders the region as an image instead of printing a garbled grid.

Nothing here imports a PDF library or writes files -- the converter measures and
renders, this module decides.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from .anchors import Box
from .captions import caption_label

# A cell gap must be clearly wider than a word space (~0.3 em).
CELL_GAP_MIN = 6.0
CELL_GAP_SIZE_FACTOR = 0.9
# Rows are lines whose vertical centres fall inside this tolerance.
ROW_TOLERANCE_MIN = 2.5
ROW_TOLERANCE_MAX = 6.0
ROW_TOLERANCE_FACTOR = 0.5
# Consecutive rows further apart than this many line heights end the table.
ROW_GAP_FACTOR = 2.4
# Column clustering.
ANCHOR_MERGE = 25.0
ANCHOR_ASSIGN = 90.0
ANCHOR_STABLE = 45.0
ANCHOR_SUPPORT_SHARE = 0.4
MAX_COLUMNS = 8
# Share of cells allowed to contain mathematical glyphs before the table is
# considered too formula-heavy for a text grid.
MAX_MATHY_SHARE = 0.25
MAX_SCAN_DEPTH = 400.0
MAX_ROWS = 60

_WHITESPACE = re.compile(r"\s+")
_CELL_PIPE = re.compile(r"\|")
_MATHY = set("ðÞ∫∑√≈≤≥±×÷")
_MATHY.update(chr(code) for code in range(0x02, 0x08))


@dataclass(frozen=True)
class Cell:
    text: str
    box: Box


@dataclass(frozen=True)
class TableLine:
    """One text line, already split into cells by the converter."""

    text: str
    box: Box
    cells: tuple[Cell, ...] = ()
    size: float = 9.0


@dataclass(frozen=True)
class TableRow:
    cells: tuple[Cell, ...]

    @property
    def y0(self) -> float:
        return min((cell.box.y0 for cell in self.cells), default=0.0)

    @property
    def y1(self) -> float:
        return max((cell.box.y1 for cell in self.cells), default=0.0)

    @property
    def x0(self) -> float:
        return min((cell.box.x0 for cell in self.cells), default=0.0)

    @property
    def x1(self) -> float:
        return max((cell.box.x1 for cell in self.cells), default=0.0)


@dataclass(frozen=True)
class TextTable:
    """A caption-anchored table region.

    ``markdown`` is ``None`` when the layout was not trustworthy enough to
    serialise as a grid; the converter then renders :attr:`box` as an image.
    """

    label: str
    caption: str
    box: Box
    rows: tuple[TableRow, ...]
    markdown: str | None

    @property
    def rendered_as_image(self) -> bool:
        return self.markdown is None


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return _CELL_PIPE.sub(r"\|", text)


def markdown_table(rows: Sequence[Sequence[Any]]) -> str | None:
    """Render table cells as a Markdown table.

    Fully empty columns and rows are dropped, which keeps the extra empty
    columns that layout-based extraction sometimes inserts from polluting the
    output. The first non-empty row becomes the header.
    """

    cleaned = [[clean_cell(cell) for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return None
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    keep = [index for index in range(width) if any(row[index] for row in cleaned)]
    if not keep:
        return None
    cleaned = [[row[index] for index in keep] for row in cleaned]

    header, body = cleaned[0], cleaned[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def split_cells(
    fragments: Sequence[tuple[str, Box, float]],
) -> tuple[Cell, ...]:
    """Join span fragments into cells, splitting at wide horizontal gaps."""

    cells: list[Cell] = []
    parts: list[str] = []
    current: Box | None = None
    previous_x1: float | None = None
    previous_size = 0.0

    def flush() -> None:
        nonlocal parts, current
        text = _WHITESPACE.sub(" ", " ".join(parts)).strip()
        if text and current is not None:
            cells.append(Cell(text=text, box=current))
        parts = []
        current = None

    for text, box, size in fragments:
        if not text.strip():
            continue
        threshold = max(CELL_GAP_MIN, CELL_GAP_SIZE_FACTOR * (size or previous_size))
        if previous_x1 is not None and box.x0 - previous_x1 > threshold:
            flush()
        parts.append(text)
        if current is None:
            current = box
        else:
            current = Box(
                x0=min(current.x0, box.x0),
                y0=min(current.y0, box.y0),
                x1=max(current.x1, box.x1),
                y1=max(current.y1, box.y1),
            )
        previous_x1 = box.x1
        previous_size = size or previous_size
    flush()
    return tuple(cells)


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 8.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def build_rows(lines: Sequence[TableLine]) -> tuple[TableRow, ...]:
    """Group lines into rows by vertical centre proximity."""

    if not lines:
        return ()
    tolerance = min(
        ROW_TOLERANCE_MAX,
        max(ROW_TOLERANCE_MIN, _median([line.box.height for line in lines]) * ROW_TOLERANCE_FACTOR),
    )
    ordered = sorted(lines, key=lambda line: (line.box.center_y, line.box.x0))
    rows: list[TableRow] = []
    bucket: list[Cell] = []
    anchor = ordered[0].box.center_y
    count = 0

    def flush() -> None:
        nonlocal bucket, count
        if bucket:
            rows.append(TableRow(cells=tuple(sorted(bucket, key=lambda cell: (cell.box.x0, cell.box.y0)))))
        bucket = []
        count = 0

    for line in ordered:
        center = line.box.center_y
        if count and abs(center - anchor) > tolerance:
            flush()
        if not count:
            anchor = center
        bucket.extend(line.cells)
        count += 1
        anchor = (anchor * (count - 1) + center) / count
    flush()
    return tuple(rows)


def _anchor_clusters(
    rows: Sequence[TableRow],
    *,
    merge: float = ANCHOR_MERGE,
    support_share: float = ANCHOR_SUPPORT_SHARE,
) -> tuple[float, ...]:
    multi = [row for row in rows if len(row.cells) >= 2]
    if not multi:
        return ()
    points = sorted(cell.box.x0 for row in multi for cell in row.cells)
    clusters: list[list[float]] = []
    for point in points:
        if clusters and point - clusters[-1][-1] <= merge:
            clusters[-1].append(point)
        else:
            clusters.append([point])

    threshold = max(2, int(len(multi) * support_share + 0.999))
    anchors: list[float] = []
    for cluster in clusters:
        if len(cluster) >= threshold:
            anchors.append(_median(cluster))
    return tuple(anchors)


def _nearest(anchors: Sequence[float], x: float) -> tuple[int, float] | None:
    if not anchors:
        return None
    best_index, best_distance = 0, abs(x - anchors[0])
    for index, anchor in enumerate(anchors[1:], start=1):
        distance = abs(x - anchor)
        if distance < best_distance:
            best_index, best_distance = index, distance
    return best_index, best_distance


def _assign_row(row: TableRow, anchors: Sequence[float]) -> dict[int, list[Cell]]:
    assigned: dict[int, list[Cell]] = {}
    for cell in row.cells:
        match = _nearest(anchors, cell.box.x0)
        if match is None:
            continue
        index, distance = match
        if distance > ANCHOR_ASSIGN:
            continue
        assigned.setdefault(index, []).append(cell)
    return assigned


def _is_mathy(cell: Cell) -> bool:
    return any(character in _MATHY for character in cell.text)


def _confident(
    rows: Sequence[TableRow],
    anchors: Sequence[float],
) -> bool:
    if not 2 <= len(anchors) <= MAX_COLUMNS:
        return False
    if len(rows) < 3:
        return False
    assigned_rows = [row for row in rows if len(_assign_row(row, anchors)) >= 2]
    if len(assigned_rows) < 3:
        return False
    cells = [cell for row in assigned_rows for cell in row.cells]
    if not cells:
        return False
    mathy = sum(1 for cell in cells if _is_mathy(cell))
    if mathy / len(cells) > MAX_MATHY_SHARE:
        return False
    # Cells that no recurring column explains mean the grid is a fiction: the
    # row is a formula or wrapped prose rather than table columns.
    unassigned = 0
    for row in assigned_rows:
        assigned = _assign_row(row, anchors)
        explained = sum(len(items) for items in assigned.values())
        unassigned += len(row.cells) - explained
    if unassigned / len(cells) > MAX_MATHY_SHARE:
        return False
    stable = 0
    for index, anchor in enumerate(anchors):
        near = [
            cell
            for row in assigned_rows
            for cell in _assign_row(row, anchors).get(index, ())
            if abs(cell.box.x0 - anchor) <= ANCHOR_STABLE
        ]
        if len(near) >= max(2, len(assigned_rows) // 2):
            stable += 1
    if stable < len(anchors):
        return False
    # A table whose first row is a caption-like sentence is usually prose that
    # happens to start with a grid-shaped line.
    first = _assign_row(rows[0], anchors)
    if not first:
        return False
    return True


def _grid(
    rows: Sequence[TableRow], anchors: Sequence[float]
) -> list[list[str]]:
    grid: list[list[str]] = []
    for row in rows:
        assigned = _assign_row(row, anchors)
        values = [
            _WHITESPACE.sub(
                " ",
                " ".join(cell.text for cell in assigned.get(index, ())),
            ).strip()
            for index in range(len(anchors))
        ]
        if any(values):
            grid.append(values)
    return grid


def detect_text_table(
    caption: TableLine,
    lines: Sequence[TableLine],
    *,
    gutter: float | None = None,
) -> TextTable | None:
    """Recover a borderless table that starts at ``caption``.

    ``gutter`` is the detected column boundary. A caption that sits entirely in
    one column must not pick up lines from the other column; a full-width
    caption ignores the gutter.

    Returns ``None`` when no table body follows the caption at all. When the
    body exists but cannot be trusted as a grid, the result carries
    ``markdown=None`` so the caller renders an image instead of dropping the
    table silently.
    """

    label_info = caption_label(caption.text)
    if label_info is None or label_info[0] != "table":
        return None
    _kind, _number, label = label_info

    single_column = gutter is not None and (
        caption.box.x1 <= gutter or caption.box.x0 >= gutter
    )

    def in_column(line: TableLine) -> bool:
        if not single_column or gutter is None:
            return True
        if caption.box.x1 <= gutter:
            return line.box.x0 < gutter
        return line.box.x0 >= gutter

    below = sorted(
        (
            line
            for line in lines
            if line is not caption
            and line.box.y0 >= caption.box.y1 - 1
            and in_column(line)
        ),
        key=lambda line: (line.box.center_y, line.box.x0),
    )
    body: list[TableLine] = []
    previous_bottom = caption.box.y1
    tolerance = max(ROW_TOLERANCE_MIN, _median([line.box.height for line in below]) * ROW_GAP_FACTOR)
    for line in below:
        if line.box.y0 - previous_bottom > tolerance:
            break
        if line.box.y0 - caption.box.y0 > MAX_SCAN_DEPTH:
            break
        if caption_label(line.text) is not None:
            break
        body.append(line)
        previous_bottom = max(previous_bottom, line.box.y1)
        if len(body) >= MAX_ROWS:
            break

    rows = build_rows(body)
    if not rows:
        return None

    # Walk the rows in order, growing the table extent as it goes. Rows that
    # live entirely outside the extent belong to the neighbouring text column
    # and are skipped; a row inside the extent with only one cell is the start
    # of the footnote block and ends the table.
    trimmed: list[TableRow] = []
    extent_x0 = caption.box.x0
    extent_x1 = caption.box.x1
    leading_skips = 0
    for row in rows:
        if single_column:
            inside = [
                cell
                for cell in row.cells
                if extent_x0 - 40 <= cell.box.x0 <= extent_x1 + 40
            ]
        else:
            inside = list(row.cells)
        if len(inside) < 2:
            if not inside and trimmed:
                continue
            if trimmed:
                break
            leading_skips += 1
            if leading_skips > 2:
                break
            continue
        row = TableRow(cells=tuple(inside))
        trimmed.append(row)
        extent_x0 = min(extent_x0, row.x0)
        extent_x1 = max(extent_x1, row.x1)

    anchors = _anchor_clusters(trimmed)
    # Drop trailing rows whose cells fall outside every recurring column.
    while trimmed and len(_assign_row(trimmed[-1], anchors)) < 2:
        trimmed.pop()
    # Drop leading single-cell rows (multi-line captions).
    skipped = 0
    while trimmed and len(_assign_row(trimmed[0], anchors)) < 2 and skipped < 2:
        trimmed.pop(0)
        skipped += 1
    if not trimmed:
        return None

    anchors = _anchor_clusters(trimmed)
    box = _region_box(caption.box, trimmed) if trimmed else caption.box
    if _confident(trimmed, anchors):
        grid = _grid(trimmed, anchors)
        markdown = markdown_table(grid) if len(grid) >= 2 else None
        if markdown:
            return TextTable(
                label=label,
                caption=caption.text,
                box=box,
                rows=tuple(trimmed),
                markdown=markdown,
            )
    return TextTable(
        label=label,
        caption=caption.text,
        box=box,
        rows=tuple(trimmed),
        markdown=None,
    )


def _region_box(caption: Box, rows: Sequence[TableRow]) -> Box:
    x0 = min([caption.x0] + [row.x0 for row in rows])
    y0 = caption.y0
    x1 = max([caption.x1] + [row.x1 for row in rows])
    y1 = max([caption.y1] + [row.y1 for row in rows])
    return Box(x0=x0, y0=y0, x1=x1, y1=y1)


def find_captions(lines: Sequence[TableLine]) -> tuple[TableLine, ...]:
    """Table captions in reading order (top-to-bottom, left-to-right)."""

    captions = []
    for line in lines:
        info = caption_label(line.text)
        if info is not None and info[0] == "table":
            captions.append(line)
    captions.sort(key=lambda line: (round(line.box.y0, 2), line.box.x0))
    return tuple(captions)


__all__ = [
    "ANCHOR_ASSIGN",
    "Cell",
    "MAX_COLUMNS",
    "MAX_MATHY_SHARE",
    "TableLine",
    "TableRow",
    "TextTable",
    "build_rows",
    "clean_cell",
    "detect_text_table",
    "find_captions",
    "markdown_table",
    "split_cells",
]
