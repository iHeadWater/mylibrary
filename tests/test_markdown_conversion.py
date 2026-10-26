"""Behaviour tests for deterministic PDF→Markdown conversion.

Fixtures are generated programmatically with PyMuPDF inside ``tmp_path``; no
binary PDF is committed. The tests cover the layout cases the converter claims
to handle (single column, two columns, tables, figures, Chinese text) and the
two fail-closed cases (scanned page, encrypted file), plus determinism.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import (
    WARNING_RUNNING_HEADER,
    WARNING_TABLE_IMAGE,
    WARNING_VECTOR_FIGURE,
    PymupdfConverter,
)
from hydrolitagent.cards.adapters.pdf.pypdf_converter import PypdfConverter
from hydrolitagent.cards.ports.paper import ConversionOptions, ConversionRequest

PAGE_WIDTH = 595
PAGE_HEIGHT = 842

BODY = (
    "Rainfall-runoff processes in small catchments are controlled by soil moisture, "
    "storm intensity and antecedent conditions. This study combines field observations "
    "with a simple bucket model to quantify those controls over three seasons. "
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(
    pdf_path: Path,
    output_dir: Path,
    options: ConversionOptions | None = None,
) -> ConversionRequest:
    return ConversionRequest(
        pdf_path=pdf_path,
        pdf_sha256=_sha256(pdf_path),
        size_bytes=pdf_path.stat().st_size,
        output_dir=output_dir,
        options=options or ConversionOptions(),
    )


def _convert(
    pdf_path: Path,
    output_dir: Path,
    options: ConversionOptions | None = None,
):
    return PymupdfConverter().convert(_request(pdf_path, output_dir, options))


def _page(doc: pymupdf.Document) -> pymupdf.Page:
    return doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)


def _text(page: pymupdf.Page, x: float, y: float, value: str, size: float = 10.0) -> None:
    page.insert_text((x, y), value, fontsize=size)


def _paragraph(page: pymupdf.Page, top: float, value: str, size: float = 10.0) -> None:
    result = page.insert_textbox(
        pymupdf.Rect(72, top, 523, top + 240), value, fontsize=size
    )
    assert result >= 0, "测试文本没有排进页面，fixture 需要更大的文本框"


def _single_column_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    first = _page(doc)
    _text(first, 72, 90, "Rainfall-Runoff Controls in Small Catchments", 18)
    _text(first, 72, 130, "Abstract", 14)
    _paragraph(first, 145, BODY * 2)
    _text(first, 72, 400, "Introduction", 14)
    _paragraph(first, 415, BODY * 3)

    second = _page(doc)
    _text(second, 72, 90, "Results", 14)
    _paragraph(second, 105, BODY * 4)

    third = _page(doc)
    _text(third, 72, 90, "References", 14)
    _paragraph(
        third,
        105,
        "Anderson, M. G. (2020). Hydrology in practice. Journal of Hydrology. " * 3,
        9,
    )

    path = tmp_path / "single-column.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _two_column_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    left = page.insert_textbox(
        pymupdf.Rect(50, 100, 280, 760), "LEFT COLUMN hydrology text. " * 20, fontsize=9
    )
    right = page.insert_textbox(
        pymupdf.Rect(315, 100, 545, 760), "RIGHT COLUMN hydrology text. " * 20, fontsize=9
    )
    assert left >= 0 and right >= 0, "双栏文本没有排进页面"
    path = tmp_path / "two-column.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _table_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    _text(page, 72, 80, "Runoff Summary", 16)
    _paragraph(page, 95, BODY)

    x0, y0 = 72, 220
    column_width, row_height = 100, 40
    x1, y1 = x0 + 3 * column_width, y0 + 3 * row_height
    page.draw_rect(pymupdf.Rect(x0, y0, x1, y1))
    for step in (1, 2):
        page.draw_line((x0 + step * column_width, y0), (x0 + step * column_width, y1))
        page.draw_line((x0, y0 + step * row_height), (x1, y0 + step * row_height))

    cells = [
        ("Site", "Rain", "Flow"),
        ("A", "12", "3"),
        ("B", "20", "5"),
    ]
    for row, values in enumerate(cells):
        for column, value in enumerate(values):
            _text(page, x0 + 8 + column * column_width, y0 + 25 + row * row_height, value)

    path = tmp_path / "table.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _figure_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    _text(page, 72, 80, "Figure Study", 16)
    _paragraph(page, 95, BODY)

    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), 0)
    pixmap.set_rect(pixmap.irect, (30, 120, 200))
    page.insert_image(pymupdf.Rect(72, 380, 272, 580), pixmap=pixmap)
    _text(page, 72, 600, "Figure 1. Observed hydrograph for the study catchment.", 9)
    _paragraph(page, 620, BODY, 9)

    path = tmp_path / "figure.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _chinese_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    page.insert_text((72, 100), "水文模型与降雨径流关系研究", fontname="china-s", fontsize=16)
    page.insert_text(
        (72, 130),
        "本文研究小流域降雨径流关系，并结合土壤湿度与前期条件分析洪水响应。",
        fontname="china-s",
        fontsize=10,
    )
    page.insert_text(
        (72, 150),
        "结果表明，短历时强降雨是控制洪峰流量的主要因素，模型在验证期表现稳定。",
        fontname="china-s",
        fontsize=10,
    )
    path = tmp_path / "chinese.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _scanned_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), 0)
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(pymupdf.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT), pixmap=pixmap)
    path = tmp_path / "scanned.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _encrypted_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    _text(page, 72, 100, "Encrypted Paper", 16)
    _paragraph(page, 120, BODY * 2)
    path = tmp_path / "encrypted.pdf"
    doc.save(
        str(path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    doc.close()
    return path


def _canary_count(markdown: str) -> int:
    return markdown.count("<!-- reading-canary: ")


# --------------------------------------------------------------------------------------
# Single column: anchors, markers, headings, determinism
# --------------------------------------------------------------------------------------


def test_single_column_anchors_and_markers(tmp_path: Path) -> None:
    pdf = _single_column_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None
    assert prepared is not None
    markdown = prepared.markdown_path.read_text(encoding="utf-8")

    page_count = prepared.source.page_count
    assert page_count == 3
    assert len(prepared.page_anchors) == page_count
    for page in range(1, page_count + 1):
        assert f"<!-- page: {page} -->" in markdown

    assert _canary_count(markdown) == 3
    assert prepared.text_coverage == 1.0
    assert prepared.converter_id == "pymupdf"
    assert prepared.markdown_sha256 == hashlib.sha256(
        markdown.encode("utf-8")
    ).hexdigest()

    # Every anchor must point at its own page slice, in order and non-overlapping.
    previous_end = 0
    for anchor in prepared.page_anchors:
        assert anchor.char_start >= previous_end
        assert anchor.char_end >= anchor.char_start
        previous_end = anchor.char_end
        slice_text = markdown[anchor.char_start:anchor.char_end]
        assert f"<!-- page: {anchor.page + 1} -->" not in slice_text
        if anchor.role != "references":
            assert slice_text.strip()

    # Heading detection hit both a front-matter section and the references
    # section; the anchor keeps the first (most prominent) heading per page.
    assert "## Abstract" in markdown
    assert "## Introduction" in markdown
    assert any(anchor.heading == "References" for anchor in prepared.page_anchors)
    assert prepared.page_anchors[-1].role == "references"


def test_conversion_is_deterministic(tmp_path: Path) -> None:
    pdf = _single_column_pdf(tmp_path)
    first, first_error = _convert(pdf, tmp_path / "first")
    second, second_error = _convert(pdf, tmp_path / "second")

    assert first_error is None and second_error is None
    assert first is not None and second is not None
    assert first.markdown_sha256 == second.markdown_sha256
    assert first.markdown_path.read_bytes() == second.markdown_path.read_bytes()


def test_manifest_is_written_with_relative_paths(tmp_path: Path) -> None:
    pdf = _figure_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    manifest = prepared.manifest_path.read_text(encoding="utf-8")
    assert "manifest_version" in manifest
    assert str(tmp_path) not in manifest
    assert '"path": "figures/' in manifest


# --------------------------------------------------------------------------------------
# Layout cases
# --------------------------------------------------------------------------------------


def test_two_columns_are_read_left_then_right(tmp_path: Path) -> None:
    pdf = _two_column_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert "LEFT COLUMN" in markdown
    assert "RIGHT COLUMN" in markdown
    assert markdown.index("LEFT COLUMN") < markdown.index("RIGHT COLUMN")


def test_table_cells_become_markdown(tmp_path: Path) -> None:
    pdf = _table_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert "| Site | Rain | Flow |" in markdown
    assert "| --- | --- | --- |" in markdown
    assert "| A | 12 | 3 |" in markdown
    assert "| B | 20 | 5 |" in markdown


def test_converter_keeps_stdout_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PyMuPDF prints a layout advertisement on first table detection.

    The cards CLIs emit JSON on stdout, so the converter must silence it. The
    library's global flag is forced back on to make the check meaningful even
    when another test already triggered the message.
    """

    if not hasattr(pymupdf, "_recommend_layout"):
        pytest.skip("当前 PyMuPDF 没有布局推荐开关")
    monkeypatch.setattr(pymupdf, "_recommend_layout", True)

    pdf = _table_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "quiet")

    assert error is None and prepared is not None
    assert "pymupdf_layout" not in capsys.readouterr().out


def test_figures_are_extracted_with_captions(tmp_path: Path) -> None:
    pdf = _figure_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    assert len(prepared.figures) == 1
    figure = prepared.figures[0]
    assert figure.page == 1
    assert figure.figure_id == "page-001-fig-1"
    assert figure.path.is_file()
    assert figure.caption and figure.caption.startswith("Figure 1.")
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert "![page-001-fig-1](figures/page-001-fig-1.png)" in markdown


def test_chinese_text_round_trips(tmp_path: Path) -> None:
    pdf = _chinese_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert "水文模型与降雨径流关系研究" in markdown
    assert "短历时强降雨" in markdown


# --------------------------------------------------------------------------------------
# Fail-closed cases
# --------------------------------------------------------------------------------------


def test_scanned_pdf_fails_closed_as_low_text(tmp_path: Path) -> None:
    pdf = _scanned_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert prepared is None
    assert error is not None
    assert error.code == "CONVERTER_LOW_TEXT"
    assert error.fix


def test_encrypted_pdf_fails_closed(tmp_path: Path) -> None:
    pdf = _encrypted_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert prepared is None
    assert error is not None
    assert error.code == "CONVERTER_ENCRYPTED"
    assert error.fix


def test_text_mode_skips_tables_and_figures(tmp_path: Path) -> None:
    pdf = _table_pdf(tmp_path)
    prepared, error = _convert(
        pdf,
        tmp_path / "out",
        ConversionOptions(mode="text"),
    )

    assert error is None and prepared is not None
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert "| --- |" not in markdown
    assert prepared.figures == ()


def test_pypdf_fallback_declares_missing_capabilities(tmp_path: Path) -> None:
    pdf = _single_column_pdf(tmp_path)
    prepared, error = PypdfConverter().convert(_request(pdf, tmp_path / "fallback"))

    assert error is None and prepared is not None
    assert prepared.warnings == ("NO_FIGURES", "NO_LAYOUT")
    assert prepared.figures == ()
    assert len(prepared.page_anchors) == 3
    assert _canary_count(prepared.markdown_path.read_text(encoding="utf-8")) == 3


# --------------------------------------------------------------------------------------
# Real-layout regressions: running matter, borderless tables, vector figures
# --------------------------------------------------------------------------------------


def _running_matter_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    for page_number in range(1, 4):
        page = _page(doc)
        _text(page, 72, 30, "Journal of Test Hydrology", 14)
        _text(page, 72, 60, "Volume 12, Issue 3", 9)
        _paragraph(page, 95, BODY * 2)
        # A numeric body line must survive: only margin page numbers are
        # removed, even though both normalise to "#".
        _text(page, 72, 400, "42", 9)
        _text(page, 72, 812, "SMITH ET AL. RUNNING MATTER FIXTURE", 8)
        _text(page, 500, 812, str(900 + page_number), 8)
    path = tmp_path / "running-matter.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _borderless_table_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    _text(page, 72, 80, "Catchment Summary", 16)
    _paragraph(page, 95, BODY)
    _text(page, 72, 380, "Table 1. Sites and measured values", 9)
    rows = (
        ("Site", "Rain", "Flow"),
        ("A", "12", "3"),
        ("B", "20", "5"),
        ("C", "18", "4"),
    )
    for row, values in enumerate(rows):
        top = 405 + row * 20
        for column, value in enumerate(values):
            _text(page, 72 + column * 100, top, value, 9)
    path = tmp_path / "borderless-table.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _vector_figure_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = _page(doc)
    _paragraph(page, 95, BODY)
    page.draw_rect(pymupdf.Rect(72, 300, 400, 500))
    page.draw_line((72, 500), (400, 500))
    for step in range(1, 4):
        page.draw_line((72 + step * 80, 300), (72 + step * 80, 500))
    _text(page, 72, 530, "Figure 1. Simulated hydrograph for the study catchment.", 9)
    _paragraph(page, 555, BODY, 9)
    path = tmp_path / "vector-figure.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_running_headers_and_footers_are_removed(tmp_path: Path) -> None:
    pdf = _running_matter_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert "Journal of Test Hydrology" not in markdown
    assert "SMITH ET AL. RUNNING MATTER FIXTURE" not in markdown
    # Page numbers differ per page but normalise to the same running text.
    assert "901" not in markdown and "902" not in markdown
    assert WARNING_RUNNING_HEADER in prepared.warnings
    # The body survives the filter, including a line that is only a number:
    # page-number removal must be position-bound.
    assert "Rainfall-runoff processes" in markdown
    assert "\n42\n" in markdown


def test_borderless_table_is_recovered_as_markdown(tmp_path: Path) -> None:
    pdf = _borderless_table_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert "| Site | Rain | Flow |" in markdown
    assert "| A | 12 | 3 |" in markdown
    assert WARNING_TABLE_IMAGE not in prepared.warnings


def test_vector_figure_is_rendered_from_caption(tmp_path: Path) -> None:
    pdf = _vector_figure_pdf(tmp_path)
    prepared, error = _convert(pdf, tmp_path / "out")

    assert error is None and prepared is not None
    assert len(prepared.figures) == 1
    figure = prepared.figures[0]
    assert figure.caption and figure.caption.startswith("Figure 1.")
    assert figure.path.is_file() and figure.path.stat().st_size > 0
    assert WARNING_VECTOR_FIGURE in prepared.warnings
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    assert f"![{figure.figure_id}]" in markdown


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
