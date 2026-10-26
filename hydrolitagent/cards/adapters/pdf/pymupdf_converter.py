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
    PreparedPaper,
    SourceIdentity,
)
from hydrolitagent.cards.ports.paper import (
    ConversionError,
    ConversionOptions,
    ConversionRequest,
    ConverterDoctor,
)

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
# Extraction rules, not just the library version. Bumping this invalidates the
# content-addressed cache for every PDF, which is exactly what a layout fix needs.
CONVERTER_REVISION = "layout-2"
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
WARNING_OCR = "OCR_OPTIONAL_UNAVAILABLE"


@dataclass(frozen=True)
class _Line:
    text: str
    box: Box
    size: float
    bold: bool
    level: int | None
    block: int = 0
    cells: tuple[Cell, ...] = ()


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


class PymupdfConverter:
    """Layout-aware converter: page anchors, tables, figures and canaries."""

    converter_id = CONVERTER_ID

    def __init__(self, *, render_dpi: int = DEFAULT_RENDER_DPI) -> None:
        self.converter_version = (
            f"{getattr(pymupdf, '__version__', 'unknown')}+{CONVERTER_REVISION}"
        )
        self.render_dpi = render_dpi
        # Newer PyMuPDF releases print an advertisement to stdout the first
        # time tables are detected. This library feeds JSON-producing CLIs, so
        # that message must never leak into a command's output.
        silence = getattr(pymupdf, "no_recommend_layout", None)
        if callable(silence):
            silence()

    def doctor(self) -> ConverterDoctor:
        return ConverterDoctor(
            converter_id=self.converter_id,
            available=True,
            version=self.converter_version,
            capabilities=("text", "layout", "tables", "figures"),
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
            coverage = text_coverage(raw_texts)
            if coverage < options.min_text_coverage:
                return None, ConversionError(
                    "CONVERTER_LOW_TEXT",
                    f"可读文本页只占 {coverage:.0%}，低于阈值 {options.min_text_coverage:.0%}。",
                    "该 PDF 很可能是扫描件；请提供带文本层的版本，或另行启用可选的 OCR 流程。",
                )

            pages, read_warnings = self._read_pages(document, options)
            markdown_text, anchors, figures, warnings = self._render(
                document, request, pages, read_warnings
            )
            return self._write(
                request, document, markdown_text, anchors, figures, coverage, warnings
            )
        finally:
            document.close()

    # -- reading ----------------------------------------------------------------------

    def _read_pages(
        self, document: pymupdf.Document, options: ConversionOptions
    ) -> tuple[list[_PageData], set[str]]:
        raw_spans: list[tuple[str, float, bool]] = []
        raw_lines: list[tuple[_Line, ...]] = []
        page_heights: list[float] = []
        for index in range(document.page_count):
            page = document.load_page(index)
            data = page.get_text("dict")
            raw_spans.extend(self._spans(data))
            raw_lines.append(self._lines(data))
            page_heights.append(page.rect.height)

        body_size = body_font_size(raw_spans)
        warnings: set[str] = set()

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

            enriched = tuple(
                _Line(
                    text=line.text,
                    box=line.box,
                    size=line.size,
                    bold=line.bold,
                    level=heading_level(line.text, line.size, line.bold, body_size),
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
            images = self._image_boxes(page) if figures_enabled else ()
            pages.append(
                _PageData(
                    lines=enriched,
                    tables=tables,
                    images=images,
                    layout=layout,
                    drawings=drawings,
                    table_failed=table_failed,
                )
            )
        return pages, warnings

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
            tuple(line.text for line in page.lines if line.level) for page in pages
        ]
        roles, primaries = assign_page_roles(headings_per_page)
        options = request.options
        canaries = canary_assignment(
            page_count, request.pdf_sha256, count=options.canaries
        )
        figures_dir = request.output_dir / FIGURES_DIRNAME
        warnings: set[str] = set(read_warnings)
        if options.ocr:
            # OCR is an optional external step and is not part of stage 2.
            warnings.add(WARNING_OCR)

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

            if options.mode == "layout" and options.extract_figures:
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
        boxes = [line.box for line in page_data.lines] + [
            table.box for table in page_data.tables
        ]
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
            ),
            None,
        )


__all__ = [
    "CONVERTER_ID",
    "FIGURES_DIRNAME",
    "MARKDOWN_FILENAME",
    "MANIFEST_FILENAME",
    "PymupdfConverter",
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
