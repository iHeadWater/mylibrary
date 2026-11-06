"""The ``pymupdf-ocr`` converter id: identity, dispatch and no side effects (#72).

Step 1 covers the wiring only. Recognition itself arrives in the next step, so
the guarantee these tests protect is narrow and exact: choosing the new id must
produce the *same* conversion as today's id for a PDF that has a text layer, and
must be visible everywhere an operator looks (registry, factory, doctor).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import (
    OCR_CONVERTER_ID,
    PymupdfConverter,
    PymupdfOcrConverter,
)
from hydrolitagent.cards.composition import (
    KNOWN_CONVERTERS,
    _default_converter,
    build_markdown_pipeline,
)
from hydrolitagent.cards.ports.paper import ConversionOptions, ConversionRequest

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
BODY = (
    "Rainfall-runoff processes in small catchments are controlled by soil moisture, "
    "storm intensity and antecedent conditions. This study combines field observations "
    "with a simple bucket model to quantify those controls over three seasons. "
)


def _text_pdf(path: Path) -> Path:
    document = pymupdf.open()
    for _ in range(2):
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_textbox(
            pymupdf.Rect(72, 72, PAGE_WIDTH - 72, PAGE_HEIGHT - 72),
            BODY * 3,
            fontsize=11,
        )
    document.save(str(path))
    document.close()
    return path


def _convert(converter, pdf: Path, output_dir: Path):
    return converter.convert(
        ConversionRequest(
            pdf_path=pdf,
            pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
            size_bytes=pdf.stat().st_size,
            output_dir=output_dir,
            options=ConversionOptions(),
        )
    )


def test_both_ids_are_registered():
    assert {"pymupdf", "pymupdf-ocr"} <= KNOWN_CONVERTERS


def test_the_factory_dispatches_on_the_id():
    from hydrolitagent.cards.config.models import ConverterConfig

    assert _default_converter(ConverterConfig(converter_id="pymupdf")).converter_id == "pymupdf"
    ocr = _default_converter(ConverterConfig(converter_id="pymupdf-ocr"))
    assert ocr.converter_id == OCR_CONVERTER_ID
    assert isinstance(ocr, PymupdfOcrConverter)


def test_choosing_the_new_id_changes_nothing_for_a_readable_pdf(tmp_path: Path):
    """The id must not alter a conversion that the plain converter can already do."""

    pdf = _text_pdf(tmp_path / "text.pdf")

    plain, plain_error = _convert(PymupdfConverter(), pdf, tmp_path / "plain")
    armed, armed_error = _convert(PymupdfOcrConverter(), pdf, tmp_path / "armed")

    assert plain_error is None and armed_error is None
    assert armed.markdown_sha256 == plain.markdown_sha256
    assert armed.markdown_path.read_bytes() == plain.markdown_path.read_bytes()


def test_the_new_id_reports_itself_in_doctor():
    report = PymupdfOcrConverter().doctor()

    assert report.converter_id == OCR_CONVERTER_ID
    assert report.available is True
    assert "text" in report.capabilities


def _app_config(tmp_path: Path, converter_id: str):
    return SimpleNamespace(
        converter=SimpleNamespace(
            converter_id=converter_id,
            mode="layout",
            extract_figures=True,
            table_mode="markdown",
            ocr=False,
            min_text_coverage=0.6,
            cache_dir=None,
        ),
        card_generator=SimpleNamespace(
            runner="in_session", model=None, reasoning_effort=None
        ),
        paths=SimpleNamespace(runtime_dir=tmp_path / ".runtime"),
        runner_options=None,
    )


def test_the_pipeline_builds_the_converter_the_config_names(tmp_path: Path):
    pipeline = build_markdown_pipeline(_app_config(tmp_path, "pymupdf-ocr"))

    assert pipeline.converter.converter_id == OCR_CONVERTER_ID

    plain = build_markdown_pipeline(_app_config(tmp_path, "pymupdf"))
    assert plain.converter.converter_id == "pymupdf"
