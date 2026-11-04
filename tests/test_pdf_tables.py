"""Borderless table recovery from synthetic geometry (no PDF involved).

``detect_text_table`` used to look only below a caption. CVPR-style layouts put
the caption under the grid, so those tables were flattened into one run-on line
of numbers. These tests pin both directions, the regression for captions above,
and the region box the converter uses to suppress the body-line duplicate.
"""

from __future__ import annotations

from hydrolitagent.cards.adapters.pdf.anchors import Box
from hydrolitagent.cards.adapters.pdf.tables import (
    Cell,
    TableLine,
    _region_box,
    build_rows,
    detect_text_table,
)

COLUMNS = (72.0, 200.0, 330.0, 440.0)
CELL_WIDTH = 60.0
ROW_HEIGHT = 10.0
ROW_STEP = 20.0


def _table_row(values: tuple[str, ...], top: float) -> TableLine:
    cells = tuple(
        Cell(
            text=value,
            box=Box(x0=x, y0=top, x1=x + CELL_WIDTH, y1=top + ROW_HEIGHT),
        )
        for x, value in zip(COLUMNS, values)
    )
    return TableLine(
        text=" ".join(values),
        box=Box(
            x0=min(cell.box.x0 for cell in cells),
            y0=top,
            x1=max(cell.box.x1 for cell in cells),
            y1=top + ROW_HEIGHT,
        ),
        cells=cells,
    )


def _caption(top: float) -> TableLine:
    return TableLine(
        text="Table 1. Ablation of the encoder.",
        box=Box(x0=72.0, y0=top, x1=330.0, y1=top + ROW_HEIGHT),
    )


TABLE_VALUES = (
    ("Model", "mAP", "R@1", "R@5"),
    ("+ Maps", "62.4", "92.9", "50.7"),
    ("+ Encode Maps", "56.8", "92.3", "49.0"),
    ("+ Contrastive Loss", "56.8", "92.3", "49.0"),
)


def _grid(top: float) -> list[TableLine]:
    return [
        _table_row(values, top + index * ROW_STEP)
        for index, values in enumerate(TABLE_VALUES)
    ]


def test_caption_below_the_grid_is_recovered() -> None:
    rows = _grid(100.0)
    caption = _caption(180.0)

    table = detect_text_table(caption, [*rows, caption])

    assert table is not None
    assert table.markdown is not None
    assert "| Model | mAP | R@1 | R@5 |" in table.markdown
    assert "| + Maps | 62.4 | 92.9 | 50.7 |" in table.markdown
    # Reading order: the header stays first even though it was collected last.
    assert table.markdown.splitlines()[0] == "| Model | mAP | R@1 | R@5 |"


def test_caption_above_the_grid_is_unchanged() -> None:
    caption = _caption(80.0)
    rows = _grid(100.0)

    table = detect_text_table(caption, [caption, *rows])

    assert table is not None
    assert table.markdown is not None
    assert "| Model | mAP | R@1 | R@5 |" in table.markdown
    assert "| + Contrastive Loss | 56.8 | 92.3 | 49.0 |" in table.markdown


def test_prose_on_both_sides_is_not_mistaken_for_a_table() -> None:
    # Two cells per line at positions that no recurring column explains: this is
    # prose with wide spaces, not a grid.
    def prose(top: float, xs: tuple[float, float]) -> TableLine:
        cells = tuple(
            Cell(
                text="word",
                box=Box(x0=x, y0=top, x1=x + 40.0, y1=top + ROW_HEIGHT),
            )
            for x in xs
        )
        return TableLine(
            text="word word",
            box=Box(x0=min(xs), y0=top, x1=max(xs) + 40.0, y1=top + ROW_HEIGHT),
            cells=cells,
        )

    caption = _caption(100.0)
    lines = [
        prose(40.0, (72.0, 300.0)),
        prose(60.0, (200.0, 480.0)),
        caption,
        prose(120.0, (90.0, 380.0)),
        prose(140.0, (120.0, 420.0)),
        prose(160.0, (170.0, 500.0)),
    ]

    table = detect_text_table(caption, lines)

    assert table is None or table.markdown is None


def test_region_box_covers_the_rows_above_a_below_caption() -> None:
    rows = _grid(100.0)
    caption = _caption(180.0)

    table = detect_text_table(caption, [*rows, caption])

    assert table is not None
    # The converter suppresses body lines by point-in-box; a box pinned to the
    # caption would emit the grid a second time as body text.
    assert table.box.y0 <= min(row.box.y0 for row in rows)
    assert table.box.y0 <= 100.0
    assert table.box.y1 >= caption.box.y1


def test_region_box_direct_call_uses_the_topmost_row() -> None:
    rows = _grid(100.0)

    box = _region_box(_caption(180.0).box, build_rows(rows))

    assert box.y0 == 100.0
    assert box.y1 == 190.0


WIDE_COLUMNS = (72.0, 150.0, 230.0, 310.0, 390.0, 470.0, 550.0)
WIDE_CELL_WIDTH = 40.0


def _wide_row_lines(values: tuple[str, ...], top: float) -> list[TableLine]:
    """One ``TableLine`` per cell, as the converter emits them from a PDF."""

    lines = []
    for x, value in zip(WIDE_COLUMNS, values):
        cell = Cell(
            text=value,
            box=Box(x0=x, y0=top, x1=x + WIDE_CELL_WIDTH, y1=top + ROW_HEIGHT),
        )
        lines.append(TableLine(text=value, box=cell.box, cells=(cell,)))
    return lines


def test_caption_below_wide_grid_keeps_its_header() -> None:
    # Ten rows of seven cells is 70 text lines, more than MAX_ROWS. The upward
    # walk starts at the caption, so a line-based cap would drop the header and
    # turn the first data row into the Markdown header.
    header = ("Model", "A", "B", "C", "D", "E", "F")
    data = [
        tuple([f"row{index}"] + [str(index * 6 + column) for column in range(6)])
        for index in range(9)
    ]
    rows = _wide_row_lines(header, 100.0)
    for index, values in enumerate(data):
        rows.extend(_wide_row_lines(values, 120.0 + index * ROW_STEP))
    assert len(rows) > 60
    caption = _caption(120.0 + len(data) * ROW_STEP)

    table = detect_text_table(caption, [*rows, caption])

    assert table is not None
    assert table.markdown is not None
    lines = table.markdown.splitlines()
    assert lines[0] == "| Model | A | B | C | D | E | F |"
    assert "| row0 | 0 | 1 | 2 | 3 | 4 | 5 |" in lines
    assert "| row8 | 48 | 49 | 50 | 51 | 52 | 53 |" in lines
