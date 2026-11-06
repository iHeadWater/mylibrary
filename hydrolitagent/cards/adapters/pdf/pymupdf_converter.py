"""Deterministic PDF→Markdown conversion built on PyMuPDF.

The converter is deliberately conservative: it extracts text, simple table
markup, page anchors and figure images, and it never guesses silently. When a
heuristic is shaky (two-column ordering, table extraction, figure rendering) it
emits a warning so later stages can downgrade the card instead of trusting a
wrong reading order.

Real journal layouts need four things that synthetic one-line fixtures do not
exercise, and all four are handled here:

* word spaces are sometimes encoded as separate positioning spans or omitted
  entirely, so line text is rebuilt from geometry instead of raw concatenation;
* running headers, running footers and publisher download stamps repeat on
  almost every page and must be removed before heading detection;
* many tables are drawn without rules, so a text-alignment fallback rebuilds
  the grid and falls back to an image when the grid is not trustworthy;
* many figures are vector drawings, so the caption anchors a render of the
  drawing region above it.

Determinism: the same PDF produces the same ``paper.md`` byte for byte. No
timestamps, no absolute paths and no iteration-order-dependent output are
written into the Markdown or the manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pymupdf

from hydrolitagent.cards.domain.paper import (
    FIGURES_DIRNAME,
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    MARKDOWN_FILENAME,
    FigureAsset,
    PageAnchor,
    PageSource,
    PreparedPaper,
    RecognitionInfo,
    SourceIdentity,
)
from hydrolitagent.cards.ports.paper import (
    ConversionError,
    ConversionFailure,
    ConversionOptions,
    ConversionRequest,
    ConverterDoctor,
    OcrOptions,
    RecognizedWord,
    RegionBox,
    RegionDetector,
    RegionOptions,
    TextRecognizer,
)

from ..ocr import recognizer_for
from ..layout import region_detector_for

from .anchors import (
    Box,
    ColumnLayout,
    SINGLE_COLUMN,
    assign_page_roles,
    body_font_size,
    canary_assignment,
    canary_marker,
    detect_columns,
    dominant_size,
    heading_level,
    is_download_stamp,
    is_margin_line,
    normalize_heading,
    normalize_margin_text,
    order_boxes,
    page_marker,
    repeated_margin_texts,
    text_coverage,
)
from .figures import (
    CaptionBlock,
    FigurePlacement,
    select_figures,
    select_vector_figures,
)
from .tables import (
    Cell,
    TableLine,
    TextTable,
    clean_cell,
    detect_text_table,
    find_captions,
    markdown_table,
    split_cells,
)

CONVERTER_ID = "pymupdf"
# The id of the variant that may recognise pages without a text layer (#72).
OCR_CONVERTER_ID = "pymupdf-ocr"
# Extraction rules, not just the library version. Bumping this invalidates the
# content-addressed cache for every PDF, which is exactly what a layout fix needs.
CONVERTER_REVISION = "layout-3"
DEFAULT_RENDER_DPI = 150

_WHITESPACE = re.compile(r"\s+")
# Some publishers draw italic variables with a symbol font whose glyph is mapped
# to an invisible control character. It is not text, and keeping it would split
# a word or make a verbatim quote impossible; a space keeps tokens apart.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CJK_START = 0x2E80
_CJK_END = 0x9FFF
_BOLD_FLAG = 16
# A gap wider than this fraction of the font size is a word space even when the
# PDF omits the space glyph (some typesetters position words instead).
_SPACE_GAP_FACTOR = 0.25
_SPACE_GAP_MIN = 2.0
# Uncatalogued images in the publisher header band are logos, not figures.
_LOGO_BAND_SHARE = 0.10

WARNING_READING_ORDER = "READING_ORDER_UNCERTAIN"
WARNING_TABLE = "TABLE_EXTRACTION_UNCERTAIN"
WARNING_TABLE_IMAGE = "TABLE_RENDERED_AS_IMAGE"
WARNING_FIGURE = "FIGURE_EXTRACTION_UNCERTAIN"
WARNING_VECTOR_FIGURE = "VECTOR_FIGURE_RENDERED"
WARNING_RUNNING_HEADER = "RUNNING_HEADER_REMOVED"
WARNING_DOWNLOAD_STAMP = "DOWNLOADS_STAMP_REMOVED"
# The page has no usable text layer, so its characters were recognised from a
# picture of the page. Downstream must treat its quotes as "the recogniser thinks
# the paper says this", not as the paper's own text (#72).
WARNING_OCR_PAGE = "OCR_PAGE_RECOGNIZED"
# Layout analysis is optional: without it a recognised page keeps its formulas as
# noisy text instead of as a picture of the formula.
WARNING_LAYOUT_UNAVAILABLE = "LAYOUT_REGIONS_UNAVAILABLE"
# Recognised text inside a formula/table region was dropped because it cannot be
# read reliably; the region is kept as an image instead (#72, 8b).
WARNING_REGION_REMOVED = "OCR_REGION_REMOVED"
# A page the recogniser read gets no outline: its box heights are not font sizes.
WARNING_OCR_NO_HEADINGS = "OCR_PAGE_OUTLINE_UNAVAILABLE"


@dataclass(frozen=True)
class _Line:
    text: str
    box: Box
    size: float
    bold: bool
    level: int | None
    block: int = 0
    cells: tuple[Cell, ...] = ()
    # Share of this line that fell inside a formula/table region, when that made
    # the line unusable. ``None`` means "not measured", which is the native path.
    region_share: float | None = None


@dataclass(frozen=True)
class _Table:
    box: Box
    markdown: str | None
    caption: str | None = None
    label: str | None = None

    @property
    def rendered_as_image(self) -> bool:
        return self.markdown is None


@dataclass(frozen=True)
class _PageData:
    lines: tuple[_Line, ...]
    tables: tuple[_Table, ...]
    images: tuple[Box, ...]
    layout: ColumnLayout = SINGLE_COLUMN
    drawings: tuple[Box, ...] = ()
    table_failed: bool = False
    source: PageSource = "native"
    # Formula/table/figure regions found on a recognised page (#72).
    regions: tuple[RegionBox, ...] = ()
    removed_lines: int = 0
    removed_chars: int = 0


@dataclass(frozen=True)
class _FigureBox:
    box: Box
    caption: str | None
    vector: bool


def _is_cjk(character: str) -> bool:
    return _CJK_START <= ord(character) <= _CJK_END


def join_line_text(left: str, right: str) -> str:
    """Join two extracted lines without inserting a space between CJK glyphs."""

    if not left:
        return right
    if not right:
        return left
    if _is_cjk(left[-1]) or _is_cjk(right[0]) or left[-1] in "，。；：、！？）":
        return left + right
    return f"{left} {right}"


def join_spans(fragments: Sequence[tuple[str, Box, float]]) -> str:
    """Rebuild one line's text from span fragments.

    Two sources of missing spaces are repaired here rather than by a
    post-processing regex: whitespace-only spans are preserved, and a span that
    starts after a wide geometric gap gets a space even if the PDF stored no
    space glyph. The geometric rule is what keeps formulas readable without
    splitting hyphenated compounds.
    """

    parts: list[str] = []
    previous_x1: float | None = None
    previous_size = 0.0

    for text, box, size in fragments:
        if not text:
            continue
        if not text.strip():
            if parts and not parts[-1].endswith(" "):
                parts.append(" ")
            previous_x1 = box.x1
            previous_size = size or previous_size
            continue
        if parts and not parts[-1].endswith(" ") and previous_x1 is not None:
            gap = box.x0 - previous_x1
            threshold = max(_SPACE_GAP_MIN, _SPACE_GAP_FACTOR * (size or previous_size))
            if gap > threshold:
                parts.append(" ")
        parts.append(text)
        previous_x1 = box.x1
        previous_size = size or previous_size

    return _WHITESPACE.sub(" ", _CONTROL.sub(" ", "".join(parts))).strip()


# Recognised words arrive as loose runs with a box each: no line, no paragraph,
# no column. These thresholds rebuild that structure from geometry alone, so a
# recognised page goes through the same renderer as a native one.
_ROW_OVERLAP_SHARE = 0.5
_RUN_GAP_FACTOR = 1.2
_PARAGRAPH_GAP_FACTOR = 0.8
_COLUMN_GAP_FACTOR = 3.0
_COLUMN_GAP_MIN = 8.0


def _split_row(
    row: Sequence[RecognizedWord], factor: float = _RUN_GAP_FACTOR
) -> list[list[RecognizedWord]]:
    """Cut one visual row where the horizontal gap is too wide to be a space.

    Two columns of a scanned page very often share a baseline, and keeping them
    in one "line" joins unrelated sentences -- ``... costly natu-`` followed by
    the other column's ``code``. Note the items here are whole *lines* (the
    recogniser returns one box per text line), so the gap between them is either
    a small layout artifact or a column gutter: 1.2 character heights separates
    the two, where the previous 2.0 kept a 17 pt gutter (against an 11 pt line)
    glued together.
    """

    runs: list[list[RecognizedWord]] = [[row[0]]]
    for word in row[1:]:
        previous = runs[-1][-1]
        height = max(word.box[3] - word.box[1], previous.box[3] - previous.box[1], 1.0)
        if word.box[0] - previous.box[2] > factor * height:
            runs.append([word])
        else:
            runs[-1].append(word)
    return runs


def _column_index(lefts: Sequence[float], tolerance: float) -> list[int]:
    """Group run start positions into columns, left to right."""

    ordered = sorted(lefts)
    breaks = [
        current
        for previous, current in zip(ordered, ordered[1:])
        if current - previous > tolerance
    ]
    return [sum(1 for edge in breaks if left >= edge) for left in lefts]


def lines_from_words(words: Sequence[RecognizedWord]) -> tuple[_Line, ...]:
    """Rebuild lines, paragraphs and columns from recognised word boxes.

    This is the whole of the OCR adapter's contribution to layout: the converter
    owns every structural decision, as it does for native text. Sizes are the
    recognised box heights, which is enough to weigh a line against its
    neighbours but never claims font metadata the picture does not carry --
    ``bold`` is always false and headings are not inferred from it.
    """

    if not words:
        return ()

    ordered = sorted(
        words, key=lambda word: ((word.box[1] + word.box[3]) / 2.0, word.box[0])
    )
    rows: list[list[RecognizedWord]] = []
    for word in ordered:
        for row in reversed(rows):
            top = min(item.box[1] for item in row)
            bottom = max(item.box[3] for item in row)
            overlap = min(bottom, word.box[3]) - max(top, word.box[1])
            height = min(bottom - top, word.box[3] - word.box[1])
            if height > 0 and overlap >= _ROW_OVERLAP_SHARE * height:
                row.append(word)
                break
        else:
            rows.append([word])

    runs: list[list[RecognizedWord]] = []
    for row in rows:
        row.sort(key=lambda word: word.box[0])
        runs.extend(_split_row(row))
    if not runs:
        return ()

    heights = [max(word.box[3] - word.box[1] for word in run) for run in runs]
    median_height = sorted(heights)[len(heights) // 2]
    tolerance = max(_COLUMN_GAP_MIN, _COLUMN_GAP_FACTOR * median_height)
    columns = _column_index([run[0].box[0] for run in runs], tolerance)

    lines: list[_Line] = []
    block = -1
    previous_bottom: float | None = None
    previous_column: int | None = None
    # Column-major block ids: a new id whenever the column changes or the vertical
    # gap is wider than a paragraph break. The renderer only compares ids for
    # equality, so two paragraphs never merge across a column boundary.
    for run, column, height in zip(runs, columns, heights):
        typed = [(word.text, _box(*word.box), word.box[3] - word.box[1]) for word in run]
        cells = split_cells(typed)
        text = join_spans(typed)
        if not text or not cells:
            continue
        top = min(word.box[1] for word in run)
        if (
            previous_bottom is None
            or column != previous_column
            or top - previous_bottom > _PARAGRAPH_GAP_FACTOR * height
        ):
            block += 1
        lines.append(
            _Line(
                text=text,
                box=_box(
                    min(word.box[0] for word in run),
                    top,
                    max(word.box[2] for word in run),
                    max(word.box[3] for word in run),
                ),
                size=dominant_size(
                    (word.text, word.box[3] - word.box[1], False) for word in run
                ),
                bold=False,
                level=None,
                block=block,
                cells=cells,
            )
        )
        previous_bottom = max(word.box[3] for word in run)
        previous_column = column
    return tuple(lines)


def _leading_section_lines(page: _PageData, limit: int = 3) -> tuple[str, ...]:
    """Short leading lines, used only to classify a page's role.

    A recognised page has no heading levels, so ``assign_page_roles`` would never
    see "References" and every back-matter page would count as body, inflating
    the coverage denominator. Role classification only needs the *words*, not a
    level, so the first few short lines are offered as candidates. They are not
    turned into Markdown headings.
    """

    if page.source == "native":
        return ()
    candidates: list[str] = []
    for line in page.lines[:limit]:
        text = line.text.strip()
        if not text or len(text) > 60 or text.endswith("."):
            continue
        candidates.append(text)
    return tuple(candidates)


def _overlap_share(box: Box, region: Box) -> float:
    """Share of ``box`` that falls inside ``region``, by area."""

    width = min(box.x1, region.x1) - max(box.x0, region.x0)
    height = min(box.y1, region.y1) - max(box.y0, region.y0)
    if width <= 0 or height <= 0:
        return 0.0
    area = max(box.area, 1.0)
    return (width * height) / area


def _drop_region_lines(
    lines: Sequence[_Line], regions: Sequence[RegionBox], min_share: float
) -> tuple[tuple[_Line, ...], int, int]:
    """Remove recognised lines that belong to a formula/table region (#72, 8b).

    A line only goes when it is *mostly* inside the region. Recognised text in a
    formula is unusable, and keeping it is actively harmful: every verbatim check
    would pass on characters the paper does not carry, so the noise would be
    promoted to "evidence". The region itself is kept as a picture instead.
    """

    kept: list[_Line] = []
    dropped_lines = 0
    dropped_chars = 0
    boxes = [_box(*region.box) for region in regions]
    for line in lines:
        if any(_overlap_share(line.box, box) >= min_share for box in boxes):
            dropped_lines += 1
            dropped_chars += len(line.text)
            continue
        kept.append(line)
    return tuple(kept), dropped_lines, dropped_chars


def _box(*values: float) -> Box:
    x0, y0, x1, y1 = (float(value) for value in values)
    return Box(x0=x0, y0=y0, x1=x1, y1=y1)


def _enclosing_frame(box: Box, drawings: Sequence[Box]) -> Box | None:
    """Smallest drawn rectangle that covers most of ``box``.

    Publishers often draw a frame around a table. Using it as the table region
    keeps the neighbouring text column out of the rendered image and makes the
    line-removal pass cover every cell line.
    """

    area = max(box.area, 1.0)
    best: Box | None = None
    for candidate in drawings:
        if candidate.width <= 4 or candidate.height <= 4:
            continue
        overlap_width = max(0.0, min(box.x1, candidate.x1) - max(box.x0, candidate.x0))
        overlap_height = max(0.0, min(box.y1, candidate.y1) - max(box.y0, candidate.y0))
        if overlap_width * overlap_height / area < 0.85:
            continue
        if best is None or candidate.area < best.area:
            best = candidate
    return best


def _table_number(label: str | None, fallback: int) -> str:
    if label:
        match = re.search(r"(\d+)", label)
        if match:
            return match.group(1)
    return str(fallback)


def _unknown_backend(name: str, label: str, key: str) -> ConverterDoctor:
    return ConverterDoctor(
        converter_id=str(name),
        available=False,
        version=None,
        capabilities=(),
        error=f"未知的{label}后端：{name!r}",
        fix=f"在配置中改用 converter.{key} 支持的后端",
    )


class PymupdfConverter:
    """Layout-aware converter: page anchors, tables, figures and canaries."""

    converter_id = CONVERTER_ID

    def __init__(
        self,
        *,
        render_dpi: int = DEFAULT_RENDER_DPI,
        ocr: OcrOptions | None = None,
        regions: RegionOptions | None = None,
        recognizer: TextRecognizer | None = None,
        region_detector: RegionDetector | None = None,
    ) -> None:
        self.render_dpi = render_dpi
        # Defaults for ``doctor`` and for callers that do not build options per
        # request; a conversion always reads ``request.options``.
        self.ocr = ocr
        self.regions = regions
        self._recognizer = recognizer
        self._region_detector = region_detector
        self.converter_version = self._version()
        # Newer PyMuPDF releases print an advertisement to stdout the first
        # time tables are detected. This library feeds JSON-producing CLIs, so
        # that message must never leak into a command's output.
        silence = getattr(pymupdf, "no_recommend_layout", None)
        if callable(silence):
            silence()

    def _version(self) -> str:
        return f"{getattr(pymupdf, '__version__', 'unknown')}+{CONVERTER_REVISION}"

    def _resolved_recognizer(self, options: OcrOptions) -> TextRecognizer | None:
        if self._recognizer is not None:
            return self._recognizer
        return recognizer_for(options.engine)

    def _resolved_regions(self, options: RegionOptions) -> RegionDetector | None:
        if self._region_detector is not None:
            return self._region_detector
        return region_detector_for(options.backend)

    def doctor(self) -> ConverterDoctor:
        capabilities = ["text", "layout", "tables", "figures"]
        recognizer_report = None
        if self.ocr is not None:
            capabilities.append("ocr")
            recognizer = self._resolved_recognizer(self.ocr)
            recognizer_report = (
                recognizer.available()
                if recognizer is not None
                else _unknown_backend(self.ocr.engine, "OCR", "ocr_engine")
            )
        regions_report = None
        if self.regions is not None and self.regions.enabled:
            capabilities.append("regions")
            detector = self._resolved_regions(self.regions)
            regions_report = (
                detector.available()
                if detector is not None
                else _unknown_backend(self.regions.backend, "版面分析", "region_backend")
            )
        return ConverterDoctor(
            converter_id=self.converter_id,
            available=True,
            version=self.converter_version,
            capabilities=tuple(capabilities),
            recognizer=recognizer_report,
            regions=regions_report,
        )

    # -- conversion -------------------------------------------------------------------

    def convert(
        self, request: ConversionRequest
    ) -> tuple[PreparedPaper | None, ConversionError | None]:
        try:
            document = pymupdf.open(str(request.pdf_path))
        except Exception as exc:  # pragma: no cover - depends on the input file
            return None, ConversionError(
                "CONVERTER_OPEN_FAILED",
                f"无法打开 PDF：{exc}",
                "确认文件完整且确实是 PDF；必要时从来源重新下载",
            )

        try:
            if document.needs_pass:
                return None, ConversionError(
                    "CONVERTER_ENCRYPTED",
                    "PDF 受密码保护，无法读取正文。",
                    "先在来源处解除加密，或改用未加密的版本。",
                )
            if document.page_count < 1:
                return None, ConversionError(
                    "CONVERTER_LOW_TEXT",
                    "PDF 没有可读取的页面。",
                    "确认文件未被截断；必要时从来源重新下载。",
                )

            options = request.options
            raw_texts = [
                document.load_page(index).get_text("text")
                for index in range(document.page_count)
            ]
            native_coverage = text_coverage(raw_texts)

            # Recognition is a fallback, not a second pipeline. ``auto`` engages
            # it only for a document that is mostly unreadable from its own text
            # layer, so a PDF that converts today keeps converting byte for byte
            # (#72, acceptance 2); ``all`` is the explicit opt-out for the rare
            # file whose text layer is present but wrong.
            ocr = options.ocr
            scope = ocr.scope if ocr is not None else "auto"
            needs_ocr = (
                (
                    list(range(len(raw_texts)))
                    if ocr.scope == "all"
                    else [
                        index
                        for index, text in enumerate(raw_texts)
                        if len(text.strip()) < ocr.min_page_chars
                    ]
                )
                if ocr is not None
                else []
            )
            active: TextRecognizer | None = None
            if ocr is not None and (scope == "all" or native_coverage < options.min_text_coverage):
                recognizer = self._resolved_recognizer(ocr)
                if recognizer is None:
                    return None, ConversionError(
                        "CONVERTER_LOW_TEXT",
                        f"可读文本页只占 {native_coverage:.0%}，低于阈值 "
                        f"{options.min_text_coverage:.0%}，且配置的 OCR 后端未知："
                        f"{ocr.engine!r}",
                        "在配置中改用 converter.ocr_engine 支持的后端（当前仅 rapidocr）。",
                    )
                report = recognizer.available()
                if not report.available:
                    # Offline or misconfigured: degrade to exactly the old
                    # behaviour, with the reason attached (#72, acceptance 4).
                    return None, ConversionError(
                        "CONVERTER_LOW_TEXT",
                        f"可读文本页只占 {native_coverage:.0%}，低于阈值 "
                        f"{options.min_text_coverage:.0%}，且 OCR 后端不可用："
                        f"{report.error or '未知原因'}",
                        report.fix or "安装 OCR 可选依赖，或提供带文本层的 PDF 版本。",
                    )
                active = recognizer
            elif native_coverage < options.min_text_coverage:
                return None, ConversionError(
                    "CONVERTER_LOW_TEXT",
                    f"可读文本页只占 {native_coverage:.0%}，低于阈值 "
                    f"{options.min_text_coverage:.0%}。",
                    "该 PDF 很可能是扫描件；请提供带文本层的版本，"
                    "或改用 converter_id=pymupdf-ocr 并安装 OCR 可选依赖。",
                )

            # Layout regions are detected once per document, and only when some
            # page will actually be recognised: a page read from its text layer
            # has real tables and figures of its own, and a second opinion on
            # them would only disagree with the rules that already work.
            regions_by_page: dict[int, tuple[RegionBox, ...]] = {}
            regions_warning: str | None = None
            if active is not None and needs_ocr and options.regions is not None:
                regions_by_page, regions_warning = self._detect_regions(
                    request, options.regions
                )

            try:
                pages, read_warnings = self._read_pages(
                    document, options, active, raw_texts, regions_by_page
                )
            except ConversionFailure as failure:
                return None, failure.error
            if regions_warning is not None:
                read_warnings.add(regions_warning)

            recognised = any(page.source != "native" for page in pages)
            coverage = (
                text_coverage([" ".join(line.text for line in page.lines) for page in pages])
                if recognised
                else native_coverage
            )
            if coverage < options.min_text_coverage:
                return None, ConversionError(
                    "CONVERTER_LOW_TEXT",
                    f"可读文本页只占 {coverage:.0%}，低于阈值 {options.min_text_coverage:.0%}。",
                    "已尝试 OCR，仍有页面读不出文字；请确认该页是空白页，"
                    "或提高 converter.ocr_dpi 后重试。",
                )

            markdown_text, anchors, figures, warnings = self._render(
                document, request, pages, read_warnings
            )
            recognition = None
            if recognised and ocr is not None and active is not None:
                recognition = RecognitionInfo(
                    engine=ocr.engine,
                    version=active.engine_version,
                    lang=ocr.lang,
                    dpi=ocr.dpi,
                    pages=tuple(
                        anchor.page for anchor in anchors if anchor.source != "native"
                    ),
                )
            return self._write(
                request,
                document,
                markdown_text,
                anchors,
                figures,
                coverage,
                warnings,
                recognition,
                pages,
            )
        finally:
            document.close()

    def _detect_regions(
        self, request: ConversionRequest, options: RegionOptions
    ) -> tuple[dict[int, tuple[RegionBox, ...]], str | None]:
        """Return regions per page, or a warning when the backend is unusable."""

        detector = self._resolved_regions(options)
        if detector is None:
            return {}, WARNING_LAYOUT_UNAVAILABLE
        report = detector.available()
        if not report.available:
            return {}, WARNING_LAYOUT_UNAVAILABLE
        try:
            found = detector.detect(request.pdf_path)
        except Exception:  # noqa: BLE001 - a soft capability must not fail the page
            return {}, WARNING_LAYOUT_UNAVAILABLE
        grouped: dict[int, list[RegionBox]] = {}
        for region in found:
            grouped.setdefault(region.page, []).append(region)
        return {page: tuple(items) for page, items in grouped.items()}, None

    # -- reading ----------------------------------------------------------------------

    def _read_pages(
        self,
        document: pymupdf.Document,
        options: ConversionOptions,
        recognizer: TextRecognizer | None = None,
        raw_texts: Sequence[str] = (),
        regions_by_page: dict[int, tuple[RegionBox, ...]] | None = None,
    ) -> tuple[list[_PageData], set[str]]:
        raw_spans: list[tuple[str, float, bool]] = []
        raw_lines: list[tuple[_Line, ...]] = []
        sources: list[PageSource] = []
        page_regions: list[tuple[RegionBox, ...]] = []
        cropped: list[tuple[int, int]] = []
        page_heights: list[float] = []
        warnings: set[str] = set()
        ocr = options.ocr
        regions_by_page = regions_by_page or {}

        for index in range(document.page_count):
            page = document.load_page(index)
            page_heights.append(page.rect.height)
            native_text = raw_texts[index] if index < len(raw_texts) else ""
            wants = recognizer is not None and (
                (ocr is not None and ocr.scope == "all")
                or len(native_text.strip()) < (ocr.min_page_chars if ocr else 40)
            )
            if wants:
                assert ocr is not None and recognizer is not None
                recognised = self._recognised_lines(page, ocr, recognizer, warnings)
                found = regions_by_page.get(index + 1, ())
                dropped_lines = dropped_chars = 0
                if found and options.regions is not None:
                    if options.regions.text == "remove":
                        recognised, dropped_lines, dropped_chars = _drop_region_lines(
                            recognised, found, options.regions.min_line_share
                        )
                        if dropped_lines:
                            warnings.add(WARNING_REGION_REMOVED)
                raw_lines.append(recognised)
                page_regions.append(found)
                cropped.append((dropped_lines, dropped_chars))
                sources.append("ocr")
                continue
            data = page.get_text("dict")
            raw_spans.extend(self._spans(data))
            raw_lines.append(self._lines(data))
            page_regions.append(())
            cropped.append((0, 0))
            sources.append("native")

        body_size = (
            body_font_size(raw_spans)
            if raw_spans
            else dominant_size(
                (line.text, line.size, False) for lines in raw_lines for line in lines
            )
        )

        margin_lines = [
            [(line.text, line.box) for line in lines] for lines in raw_lines
        ]
        running = set(repeated_margin_texts(margin_lines, page_heights))
        if running:
            warnings.add(WARNING_RUNNING_HEADER)

        kept_pages: list[tuple[_Line, ...]] = []
        for index, lines in enumerate(raw_lines):
            height = page_heights[index]
            kept: list[_Line] = []
            for line in lines:
                key = normalize_margin_text(line.text)
                if running and key in running:
                    # The title page usually repeats the masthead lower than
                    # the page-2 copy, so text matches remove every copy. Purely
                    # numeric keys ("7036") are page numbers: those must only be
                    # removed inside the margin band, otherwise a table cell
                    # whose whole line is "1" would disappear with them.
                    if any(character.isalpha() for character in key) or is_margin_line(
                        line.box, height
                    ):
                        continue
                if is_download_stamp(line.text):
                    warnings.add(WARNING_DOWNLOAD_STAMP)
                    continue
                kept.append(line)
            kept_pages.append(tuple(kept))

        tables_enabled = options.mode == "layout" and options.table_mode == "markdown"
        figures_enabled = options.mode == "layout" and options.extract_figures

        pages: list[_PageData] = []
        for index, lines in enumerate(kept_pages):
            page = document.load_page(index)
            layout = SINGLE_COLUMN
            if options.mode == "layout":
                layout = detect_columns([line.box for line in lines], page.rect.width)
                if layout.uncertain:
                    warnings.add(WARNING_READING_ORDER)

            native_page = sources[index] == "native"
            if not native_page and lines:
                # A recognised line carries no font size, only the height of the
                # box drawn around it. That height tracks ascenders more than
                # point size, so inferring levels from it promotes prose to
                # ``##``. The page keeps its text and loses its outline.
                warnings.add(WARNING_OCR_NO_HEADINGS)
            enriched = tuple(
                _Line(
                    text=line.text,
                    box=line.box,
                    size=line.size,
                    bold=line.bold,
                    level=(
                        heading_level(line.text, line.size, line.bold, body_size)
                        if native_page
                        else None
                    ),
                    block=line.block,
                    cells=line.cells,
                )
                for line in lines
            )
            drawings = (
                self._drawing_boxes(page)
                if options.mode == "layout" and (figures_enabled or tables_enabled)
                else ()
            )
            tables, table_failed = (
                self._tables(page, enriched, drawings, layout)
                if tables_enabled
                else ((), False)
            )
            if table_failed:
                warnings.add(WARNING_TABLE)
            # A recognised page is one big picture of a page: extracting its
            # "images" would turn every scan into a full-page figure, and its
            # "tables" would be a picture of the page rendered as a table.
            images = self._image_boxes(page) if figures_enabled and native_page else ()
            removed_lines, removed_chars = cropped[index]
            pages.append(
                _PageData(
                    lines=enriched,
                    tables=tables if native_page else (),
                    images=images,
                    layout=layout,
                    drawings=drawings,
                    table_failed=table_failed,
                    source=sources[index],
                    regions=page_regions[index],
                    removed_lines=removed_lines,
                    removed_chars=removed_chars,
                )
            )
        return pages, warnings

    def _recognised_lines(
        self,
        page: pymupdf.Page,
        ocr: OcrOptions,
        recognizer: TextRecognizer,
        warnings: set[str],
    ) -> tuple[_Line, ...]:
        """Rasterise one page and turn the recogniser's words into lines."""

        try:
            image = page.get_pixmap(dpi=ocr.dpi).tobytes("png")
            words = recognizer.recognize(image, ocr)
        except ConversionFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken backend must be reported
            raise ConversionFailure(
                ConversionError(
                    "CONVERTER_OCR_FAILED",
                    f"第 {page.number + 1} 页 OCR 失败：{type(exc).__name__}: {exc}",
                    "确认 OCR 可选依赖已正确安装（uv sync --extra ocr）；"
                    "若只是个别页面失败，可改用带文本层的 PDF。",
                )
            ) from exc
        warnings.add(WARNING_OCR_PAGE)
        return lines_from_words(words)

    @staticmethod
    def _spans(data: dict[str, Any]) -> list[tuple[str, float, bool]]:
        spans: list[tuple[str, float, bool]] = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if text.strip():
                        spans.append(
                            (
                                text,
                                float(span.get("size", 0)),
                                bool(span.get("flags", 0) & _BOLD_FLAG),
                            )
                        )
        return spans

    @staticmethod
    def _lines(data: dict[str, Any]) -> tuple[_Line, ...]:
        lines: list[_Line] = []
        block_index = 0
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                typed: list[tuple[str, Box, float]] = []
                for span in spans:
                    text = span.get("text", "")
                    if not text:
                        continue
                    typed.append(
                        (
                            text,
                            _box(*span.get("bbox", (0, 0, 0, 0))),
                            float(span.get("size", 0)),
                        )
                    )
                if not typed:
                    continue
                text = join_spans(typed)
                if not text:
                    continue
                cells = split_cells(typed)
                if not cells:
                    continue
                lines.append(
                    _Line(
                        text=text,
                        box=_box(*line.get("bbox", (0, 0, 0, 0))),
                        # Character-weighted, not the largest span: a run-in
                        # label must not promote a whole paragraph to a heading.
                        size=dominant_size(
                            (text, span_size, False) for text, _, span_size in typed
                        ),
                        bold=any(
                            bool(span.get("flags", 0) & _BOLD_FLAG) for span in spans
                        ),
                        level=None,
                        block=block_index,
                        cells=cells,
                    )
                )
            block_index += 1
        return tuple(lines)

    @staticmethod
    def _find_tables(page: pymupdf.Page) -> tuple[tuple[_Table, ...], bool]:
        try:
            found = page.find_tables()
        except Exception:  # pragma: no cover - depends on the input page
            return (), True
        tables: list[_Table] = []
        for table in found.tables:
            markdown = markdown_table(table.extract())
            if markdown:
                tables.append(_Table(box=_box(*table.bbox), markdown=markdown))
        return tuple(tables), False

    def _tables(
        self,
        page: pymupdf.Page,
        lines: Sequence[_Line],
        drawings: Sequence[Box],
        layout: ColumnLayout,
    ) -> tuple[tuple[_Table, ...], bool]:
        """Ruled tables first, then the borderless text-alignment fallback."""

        ruled, failed = self._find_tables(page)
        if failed:
            return (), True

        table_lines = [
            TableLine(text=line.text, box=line.box, cells=line.cells, size=line.size)
            for line in lines
        ]
        captions = find_captions(table_lines)
        if not captions:
            return ruled, False

        gutter = layout.gutter_x if layout.kind == "two" else None
        tables: list[_Table] = list(ruled)
        incomplete = False
        for caption in captions:
            if any(
                table.box.contains_point(caption.box.center_x, caption.box.center_y)
                or (
                    table.box.horizontal_overlap(caption.box) > 20
                    and abs(table.box.y0 - caption.box.y0) < 12
                )
                for table in tables
            ):
                continue
            detected = detect_text_table(caption, table_lines, gutter=gutter)
            if detected is None:
                # A caption with nothing recoverable under it must not vanish
                # silently; report the page instead of claiming zero tables.
                incomplete = True
                continue
            tables.append(self._as_table(detected, drawings))
        tables.sort(key=lambda table: (round(table.box.y0, 2), table.box.x0))
        return tuple(tables), incomplete

    @staticmethod
    def _as_table(detected: TextTable, drawings: Sequence[Box]) -> _Table:
        box = detected.box
        if detected.markdown is None:
            # An image table must claim every text line inside its frame;
            # otherwise those lines leak into the body as a duplicate, garbled
            # copy of the table.
            frame = _enclosing_frame(box, drawings)
            if frame is not None:
                box = frame
        return _Table(
            box=box,
            markdown=detected.markdown,
            caption=detected.caption,
            label=detected.label,
        )

    @staticmethod
    def _image_boxes(page: pymupdf.Page) -> tuple[Box, ...]:
        try:
            return tuple(_box(*info["bbox"]) for info in page.get_image_info(xrefs=True))
        except Exception:  # pragma: no cover - depends on the input page
            return ()

    @staticmethod
    def _drawing_boxes(page: pymupdf.Page) -> tuple[Box, ...]:
        try:
            return tuple(_box(*drawing["rect"]) for drawing in page.get_drawings())
        except Exception:  # pragma: no cover - depends on the input page
            return ()

    # -- rendering --------------------------------------------------------------------

    def _render(
        self,
        document: pymupdf.Document,
        request: ConversionRequest,
        pages: Sequence[_PageData],
        read_warnings: set[str],
    ) -> tuple[str, tuple[PageAnchor, ...], tuple[FigureAsset, ...], tuple[str, ...]]:
        page_count = len(pages)
        headings_per_page = [
            tuple(line.text for line in page.lines if line.level)
            or _leading_section_lines(page)
            for page in pages
        ]
        roles, primaries = assign_page_roles(headings_per_page)
        options = request.options
        canaries = canary_assignment(
            page_count, request.pdf_sha256, count=options.canaries
        )
        figures_dir = request.output_dir / FIGURES_DIRNAME
        warnings: set[str] = set(read_warnings)

        parts: list[str] = []
        offset = 0
        anchors: list[PageAnchor] = []
        figures: list[FigureAsset] = []

        for index, page_data in enumerate(pages):
            page_no = index + 1
            canary_tokens = canaries.get(index, ())
            header = page_marker(page_no) + "\n"
            header += "".join(canary_marker(token) + "\n" for token in canary_tokens)
            parts.append(header)
            offset += len(header)
            char_start = offset

            page = document.load_page(index)
            drawings = page_data.drawings

            content = self._render_page(
                page, page_no, page_data, drawings, figures_dir, warnings
            )

            if (
                options.mode == "layout"
                and options.extract_figures
                and page_data.source == "native"
            ):
                figure_blocks, placements = self._extract_figures(
                    page, page_no, page_data, drawings, figures_dir, warnings
                )
                if figure_blocks:
                    content += "\n" + "\n\n".join(figure_blocks) + "\n"
                for placement in placements:
                    figures.append(
                        FigureAsset(
                            page=page_no,
                            figure_id=placement.figure_id,
                            path=figures_dir / placement.filename,
                            caption=placement.caption,
                        )
                    )

            parts.append(content)
            offset += len(content)
            anchors.append(
                PageAnchor(
                    page=page_no,
                    char_start=char_start,
                    char_end=offset,
                    heading=primaries[index] if index < len(primaries) else None,
                    role=roles[index] if index < len(roles) else "unknown",
                    canary=canary_tokens[0] if canary_tokens else None,
                    source=page_data.source,
                )
            )
            parts.append("\n")
            offset += 1

        return "".join(parts), tuple(anchors), tuple(figures), tuple(sorted(warnings))

    def _render_page(
        self,
        page: pymupdf.Page,
        page_no: int,
        page_data: _PageData,
        drawings: Sequence[Box],
        figures_dir: Path,
        warnings: set[str],
    ) -> str:
        items: list[tuple[str, Any]] = [("line", line) for line in page_data.lines]
        items.extend(("table", table) for table in page_data.tables)
        items.extend(
            ("region", (number, region))
            for number, region in enumerate(page_data.regions, start=1)
        )
        boxes = (
            [line.box for line in page_data.lines]
            + [table.box for table in page_data.tables]
            + [_box(*region.box) for region in page_data.regions]
        )
        if not boxes:
            return ""
        order = order_boxes(boxes, page_data.layout)
        table_boxes = [table.box for table in page_data.tables]
        blocks: list[str] = []
        paragraph: list[str] = []
        last_block: int | None = None
        table_index = 0

        def flush() -> None:
            if paragraph:
                blocks.append(paragraph[0])
                paragraph.clear()

        for position in order:
            kind, payload = items[position]
            if kind == "region":
                flush()
                last_block = None
                number, region = payload
                blocks.append(
                    self._region_block(
                        page, page_no, number, region, figures_dir, warnings
                    )
                )
                continue
            if kind == "table":
                flush()
                last_block = None
                table_index += 1
                blocks.append(
                    self._table_block(
                        page,
                        page_no,
                        payload,
                        table_index,
                        drawings,
                        figures_dir,
                        warnings,
                    )
                )
                continue
            line: _Line = payload
            if any(
                box.contains_point(line.box.center_x, line.box.center_y)
                for box in table_boxes
            ):
                continue
            if line.level:
                flush()
                last_block = None
                blocks.append("#" * line.level + " " + normalize_heading(line.text))
                continue
            if last_block is not None and line.block != last_block:
                flush()
            if paragraph:
                paragraph[0] = join_line_text(paragraph[0], line.text)
            else:
                paragraph.append(line.text)
            last_block = line.block
        flush()
        return "\n\n".join(blocks) + "\n" if blocks else ""

    def _table_block(
        self,
        page: pymupdf.Page,
        page_no: int,
        table: _Table,
        ordinal: int,
        drawings: Sequence[Box],
        figures_dir: Path,
        warnings: set[str],
    ) -> str:
        caption = (table.caption or "").strip()
        if table.markdown:
            return f"{caption}\n\n{table.markdown}".strip()
        warnings.add(WARNING_TABLE_IMAGE)
        number = _table_number(table.label, ordinal)
        filename = f"page-{page_no:03d}-table-{number}.png"
        clip = self._table_clip(table.box, drawings)
        ok = self._render_region(page, clip, figures_dir / filename)
        if not ok:
            warnings.add(WARNING_TABLE)
            return caption
        return f"{caption}\n\n![Table {number}]({FIGURES_DIRNAME}/{filename})".strip()

    def _region_block(
        self,
        page: pymupdf.Page,
        page_no: int,
        number: int,
        region: RegionBox,
        figures_dir: Path,
        warnings: set[str],
    ) -> str:
        """Render a formula/table/figure region as a picture, not as text.

        The characters inside it were either dropped (``remove``) or are noise
        (``keep``); either way the reader should see the formula itself.
        """

        figures_dir.mkdir(parents=True, exist_ok=True)
        filename = f"page-{page_no:03d}-region-{number}.png"
        label = {"formula": "Formula", "table": "Table", "figure": "Figure"}.get(
            region.kind, "Region"
        )
        box = _box(*region.box)
        if not self._render_region(page, box, figures_dir / filename):
            warnings.add(WARNING_FIGURE)
            return ""
        return f"![{label} {number}]({FIGURES_DIRNAME}/{filename})"

    @staticmethod
    def _table_clip(box: Box, drawings: Sequence[Box]) -> Box:
        """Prefer the drawn table frame; it excludes the neighbouring column."""

        best = _enclosing_frame(box, drawings)
        if best is None:
            return box
        return Box(
            x0=max(0.0, best.x0 - 2),
            y0=max(0.0, best.y0 - 2),
            x1=best.x1 + 2,
            y1=best.y1 + 2,
        )

    def _render_region(self, page: pymupdf.Page, box: Box, target: Path) -> bool:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            pixmap = page.get_pixmap(
                clip=pymupdf.Rect(box.x0, box.y0, box.x1, box.y1),
                dpi=self.render_dpi,
            )
            pixmap.save(str(target))
        except Exception:  # pragma: no cover - depends on the image
            return False
        return True

    def _extract_figures(
        self,
        page: pymupdf.Page,
        page_no: int,
        page_data: _PageData,
        drawings: Sequence[Box],
        figures_dir: Path,
        warnings: set[str],
    ) -> tuple[list[str], tuple[FigurePlacement, ...]]:
        captions = [
            CaptionBlock(box=line.box, text=line.text) for line in page_data.lines
        ]
        raster = select_figures(page_no, page_data.images, captions)
        logo_band = page.rect.height * _LOGO_BAND_SHARE
        raster = tuple(
            placement
            for placement in raster
            if placement.caption or placement.box.y0 >= logo_band
        )
        vector = select_vector_figures(
            page_no,
            captions,
            drawings,
            captions,
            page.rect.width,
            page.rect.height,
            raster_boxes=[placement.box for placement in raster],
        )
        if not raster and not vector:
            return [], ()

        combined: list[_FigureBox] = [
            _FigureBox(box=placement.box, caption=placement.caption, vector=False)
            for placement in raster
        ]
        combined.extend(
            _FigureBox(box=figure.box, caption=figure.caption, vector=True)
            for figure in vector
        )
        combined.sort(key=lambda item: (round(item.box.y0, 2), round(item.box.x0, 2)))

        figures_dir.mkdir(parents=True, exist_ok=True)
        blocks: list[str] = []
        written: list[FigurePlacement] = []
        for ordinal, item in enumerate(combined, start=1):
            placement = FigurePlacement(
                page=page_no,
                ordinal=ordinal,
                box=item.box,
                caption=item.caption,
            )
            if not self._render_region(
                page, item.box, figures_dir / placement.filename
            ):
                warnings.add(WARNING_FIGURE)
                continue
            if item.vector:
                warnings.add(WARNING_VECTOR_FIGURE)
            written.append(placement)
            blocks.append(
                f"![{placement.figure_id}]({FIGURES_DIRNAME}/{placement.filename})"
            )
        return blocks, tuple(written)

    # -- writing ----------------------------------------------------------------------

    def _write(
        self,
        request: ConversionRequest,
        document: pymupdf.Document,
        markdown_text: str,
        anchors: tuple[PageAnchor, ...],
        figures: tuple[FigureAsset, ...],
        coverage: float,
        warnings: tuple[str, ...],
        recognition: RecognitionInfo | None = None,
        pages: Sequence[_PageData] = (),
    ) -> tuple[PreparedPaper | None, ConversionError | None]:
        output_dir = request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / MARKDOWN_FILENAME
        markdown_path.write_text(markdown_text, encoding="utf-8", newline="\n")
        markdown_sha256 = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()

        source = SourceIdentity(
            pdf_sha256=request.pdf_sha256,
            size_bytes=request.size_bytes,
            page_count=document.page_count,
            group_id=request.group_id,
            parent_key=request.parent_key,
            attachment_key=request.attachment_key,
        )
        manifest_path = output_dir / MANIFEST_FILENAME
        payload = {
            "manifest_version": MANIFEST_VERSION,
            "source": {
                "pdf_sha256": source.pdf_sha256,
                "size_bytes": source.size_bytes,
                "page_count": source.page_count,
                "group_id": source.group_id,
                "parent_key": source.parent_key,
                "attachment_key": source.attachment_key,
            },
            "markdown": {"file": MARKDOWN_FILENAME, "sha256": markdown_sha256},
            "converter": {
                "id": self.converter_id,
                "version": self.converter_version,
            },
            "page_anchors": [
                {
                    "page": anchor.page,
                    "char_start": anchor.char_start,
                    "char_end": anchor.char_end,
                    "heading": anchor.heading,
                    "role": anchor.role,
                    "canary": anchor.canary,
                    "source": anchor.source,
                }
                for anchor in anchors
            ],
            "figures": [
                {
                    "page": figure.page,
                    "figure_id": figure.figure_id,
                    "path": figure.path.relative_to(output_dir).as_posix(),
                    "caption": figure.caption,
                }
                for figure in figures
            ],
            "text_coverage": round(coverage, 4),
            "warnings": list(warnings),
        }
        if recognition is not None:
            payload["recognition"] = {
                "engine": recognition.engine,
                "version": recognition.version,
                "lang": recognition.lang,
                "dpi": recognition.dpi,
                "pages": list(recognition.pages),
            }
        removed_lines = sum(page.removed_lines for page in pages)
        region_pages = [
            index + 1 for index, page in enumerate(pages) if page.regions
        ]
        if region_pages:
            payload["regions"] = {
                "pages": region_pages,
                "removed_lines": removed_lines,
                "removed_chars": sum(page.removed_chars for page in pages),
            }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        return (
            PreparedPaper(
                source=source,
                markdown_path=markdown_path,
                markdown_sha256=markdown_sha256,
                manifest_path=manifest_path,
                page_anchors=anchors,
                figures=figures,
                converter_id=self.converter_id,
                converter_version=self.converter_version,
                text_coverage=round(coverage, 4),
                warnings=warnings,
                recognition=recognition,
            ),
            None,
        )


class PymupdfOcrConverter(PymupdfConverter):
    """The same deterministic converter, able to read pages without text (#72).

    A separate class exists for the *identity*, not for a second implementation:
    every layout rule, anchor and canary below is shared with ``PymupdfConverter``,
    so a document converted by either id has the same structure. What differs is
    that this id is allowed to rasterise a page that carries no text layer and
    read it with an OCR engine, recording per page where the characters came
    from.

    Declaring it as a distinct id (rather than a boolean on the same id) keeps
    three things honest: the cache directory names the converter that produced
    it, a document never has to be "all recognised or none", and choosing it is
    a visible decision in configuration rather than a toggle nobody notices.
    """

    converter_id = OCR_CONVERTER_ID

    def _version(self) -> str:
        """Base version plus the recognition settings.

        The settings belong in the version, not only in the manifest: the cache
        is looked up by ``<id>-<version>``, so a change of engine, language or
        density must land in a different directory. Otherwise a theme run --
        which reads a cache without knowing any conversion options -- would
        happily reuse characters produced by settings nobody asked for.
        """

        base = f"{getattr(pymupdf, '__version__', 'unknown')}+{CONVERTER_REVISION}"
        ocr = self.ocr or OcrOptions()
        return f"{base}+ocr.{ocr.signature}"


__all__ = [
    "CONVERTER_ID",
    "OCR_CONVERTER_ID",
    "FIGURES_DIRNAME",
    "MARKDOWN_FILENAME",
    "MANIFEST_FILENAME",
    "PymupdfConverter",
    "PymupdfOcrConverter",
    "WARNING_DOWNLOAD_STAMP",
    "WARNING_FIGURE",
    "WARNING_READING_ORDER",
    "WARNING_RUNNING_HEADER",
    "WARNING_TABLE",
    "WARNING_TABLE_IMAGE",
    "WARNING_VECTOR_FIGURE",
    "clean_cell",
    "join_line_text",
    "join_spans",
    "markdown_table",
]
