"""Acceptance test against one real two-column AGU paper.

The synthetic fixtures in ``test_markdown_conversion.py`` are generated with
PyMuPDF, so they are too clean to expose the problems a publisher PDF has:
spaces stored as positioning-only spans, running headers repeated on every
page, unbordered tables and vector-drawn figures. This module converts a real
file when it is available on this machine and skips visibly otherwise.

Override the path with ``HYDROLITAGENT_REAL_PAPER`` when the paper lives
elsewhere (for example on another machine or in CI).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import (
    WARNING_RUNNING_HEADER,
    WARNING_TABLE_IMAGE,
    PymupdfConverter,
)
from hydrolitagent.cards.ports.paper import ConversionRequest

DEFAULT_PDF = Path(
    r"G:\我的云端硬盘\Documents\Papers\Zotero_Papers"
    r"\Bartlett 等 - 2016 - Framework for event-based semidistributed modeling"
    r" that unifies the SCS-CN method, VIC, PDM, and TOP.pdf"
)
LONG_TOKEN = re.compile(r"[A-Za-z]{31,}")
TABLE_SEPARATOR = re.compile(r"^\|(?: --- \|)+$")

PAGE_COUNT = 17
MIN_FIGURES = 4


def _target() -> Path:
    override = os.environ.get("HYDROLITAGENT_REAL_PAPER")
    return Path(override) if override else DEFAULT_PDF


def _convert(pdf: Path, output_dir: Path):
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    return PymupdfConverter().convert(
        ConversionRequest(
            pdf_path=pdf,
            pdf_sha256=sha,
            size_bytes=pdf.stat().st_size,
            output_dir=output_dir,
        )
    )


@pytest.fixture(scope="module")
def prepared_pair(tmp_path_factory: pytest.TempPathFactory):
    pdf = _target()
    if not pdf.is_file():
        pytest.skip(f"真实论文不在本机：{pdf}")
    root = tmp_path_factory.mktemp("real-paper")
    results = []
    for name in ("first", "second"):
        prepared, error = _convert(pdf, root / name)
        assert error is None, error
        assert prepared is not None
        results.append(prepared)
    return results


@pytest.fixture(scope="module")
def prepared(prepared_pair):
    return prepared_pair[0]


@pytest.fixture(scope="module")
def markdown(prepared) -> str:
    return prepared.markdown_path.read_text(encoding="utf-8")


def test_page_count_matches_the_source(prepared) -> None:
    assert prepared.source.page_count == PAGE_COUNT
    assert len(prepared.page_anchors) == PAGE_COUNT


def test_words_keep_their_spaces(markdown: str) -> None:
    """Publisher PDFs position words instead of storing space glyphs.

    A missing-space regression shows up as long concatenations such as
    ``Previousstudieshaveexploreddifferentwaterstorage``. URLs and DOIs are not
    affected because the pattern only matches runs of Latin letters.
    """

    offenders = sorted(set(LONG_TOKEN.findall(markdown)))
    assert offenders == [], f"正文出现连写词：{offenders[:5]}"


def test_running_matter_is_removed(markdown: str, prepared) -> None:
    assert "Water Resources Research" not in markdown
    assert "Downloaded from" not in markdown
    assert "BARTLETT ET AL." not in markdown
    assert WARNING_RUNNING_HEADER in prepared.warnings


def test_vector_figures_are_extracted(prepared) -> None:
    assert len(prepared.figures) >= MIN_FIGURES
    identifiers = [figure.figure_id for figure in prepared.figures]
    assert len(identifiers) == len(set(identifiers))
    for figure in prepared.figures:
        assert figure.path.is_file()
        assert figure.path.stat().st_size > 0
        assert figure.caption and figure.caption.startswith("Figure ")


def test_tables_are_not_silently_dropped(markdown: str, prepared) -> None:
    has_markdown_table = any(
        TABLE_SEPARATOR.match(line) for line in markdown.splitlines()
    )
    has_rendered_table = WARNING_TABLE_IMAGE in prepared.warnings
    assert has_markdown_table or has_rendered_table
    # The paper has four tables; a caption that produces neither a grid nor an
    # image would be a silent loss.
    for number in (1, 2, 3, 4):
        # Only a line that *starts* with the label is a caption; body prose
        # such as "listed in Table 1." must not satisfy the check.
        match = re.search(rf"^Table {number}\.", markdown, re.MULTILINE)
        assert match is not None, f"缺少 Table {number}. 标题"
        following = markdown[match.end() : match.end() + 400]
        assert "| ---" in following or f"![Table {number}]" in following, (
            f"Table {number}. 既没有表格也没有图片"
        )


def test_conversion_is_deterministic(prepared_pair) -> None:
    first, second = prepared_pair
    assert first.markdown_sha256 == second.markdown_sha256
    assert first.markdown_path.read_bytes() == second.markdown_path.read_bytes()
    assert [figure.figure_id for figure in first.figures] == [
        figure.figure_id for figure in second.figures
    ]


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
