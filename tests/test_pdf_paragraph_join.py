"""Tests for rebuilding paragraphs when a PDF emits one block per visual line.

CNKI two-column Chinese journals do this: ``page.get_text("blocks")`` returns one
block per printed line, so a converter that treats every block change as a
paragraph break writes 24-character lines. No sentence splitter can index those,
which made a real 10-page paper yield zero citable sentences on its body pages.
"""

from __future__ import annotations

from hydrolitagent.cards.adapters.pdf.anchors import Box
from hydrolitagent.cards.adapters.pdf.pymupdf_converter import _Line, continues_line


def _line(text: str, *, y0: float, x0: float = 57.0, size: float = 10.5) -> _Line:
    return _Line(
        text=text,
        box=Box(x0=x0, y0=y0, x1=x0 + 230.0, y1=y0 + size * 1.07),
        size=size,
        bold=False,
        level=None,
        block=0,
    )


def test_adjacent_lines_of_one_paragraph_continue() -> None:
    first = _line("近年来，由于人类经济活动的扩展和气候变暖", y0=100.0)
    second = _line("等因素的影响，世界各国遭受洪水灾害而导致经济", y0=116.0)

    assert continues_line(first, second)


def test_a_closed_sentence_ends_the_paragraph() -> None:
    first = _line("灾害链的传递路径可以从事理图谱中读出。", y0=100.0)
    second = _line("第二段从另一个角度讨论系统性风险。", y0=116.0)

    assert not continues_line(first, second)


def test_paragraph_spacing_starts_a_new_paragraph() -> None:
    first = _line("损失的风险呈现增加的趋势", y0=100.0)
    # One extra line of leading means the author broke the paragraph.
    second = _line("下一段的开头", y0=133.0)

    assert not continues_line(first, second)


def test_a_column_switch_is_not_a_continuation() -> None:
    first = _line("左栏的最后一行文字", y0=100.0, x0=57.0)
    second = _line("右栏的第一行文字", y0=100.0, x0=305.0)

    assert not continues_line(first, second)


def test_a_first_line_indent_does_not_break_the_chain() -> None:
    indented = _line("　　近年来，由于人类经济活动", y0=100.0, x0=78.0)
    flush_left = _line("等因素的影响，世界各国", y0=116.0, x0=57.0)

    # A two-character indent (~21 pt at this size) is typography, not a
    # paragraph break: the previous line did not end a sentence, so the two
    # lines belong together.
    assert continues_line(indented, flush_left)


def test_a_heading_never_continues() -> None:
    first = _line("1 引言", y0=100.0)
    heading = _Line(
        text="2 方法",
        box=Box(x0=57.0, y0=116.0, x1=120.0, y1=127.0),
        size=12.0,
        bold=True,
        level=2,
        block=1,
    )

    assert not continues_line(first, heading)
    assert not continues_line(None, heading)
