"""Deterministic PDF→Markdown conversion built on PyMuPDF.

The converter is deliberately conservative: it extracts text, simple table
markup, page anchors and figure images, and it never guesses silently. When a
heuristic is shaky (two-column ordering, table extraction, figure rendering) it
emits a warning so later stages can downgrade the card instead of trusting a
wrong reading order.

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
    heading_level,
    normalize_heading,
    order_boxes,
    page_marker,
    text_coverage,
)
from .figures import CaptionBlock, FigurePlacement, select_figures

CONVERTER_ID = "pymupdf"
DEFAULT_RENDER_DPI = 150

_WHITESPACE = re.compile(r"\s+")
_CELL_PIPE = re.compile(r"\|")
_CJK_START = 0x2E80
_CJK_END = 0x9FFF
_BOLD_FLAG = 16

WARNING_READING_ORDER = "READING_ORDER_UNCERTAIN"
WARNING_TABLE = "TABLE_EXTRACTION_UNCERTAIN"
WARNING_FIGURE = "FIGURE_EXTRACTION_UNCERTAIN"
WARNING_OCR = "OCR_OPTIONAL_UNAVAILABLE"


@dataclass(frozen=True)
class _Line:
    text: str
    box: Box
    size: float
    bold: bool
    level: int | None
    block: int = 0


@dataclass(frozen=True)
class _Table:
    box: Box
    markdown: str


@dataclass(frozen=True)
class _PageData:
    lines: tuple[_Line, ...]
    tables: tuple[_Table, ...]
    images: tuple[Box, ...]
    table_failed: bool = False


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return _CELL_PIPE.sub(r"\|", text)


def markdown_table(rows: Sequence[Sequence[Any]]) -> str | None:
    """Render extracted table cells as a Markdown table.

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


def _box(*values: float) -> Box:
    x0, y0, x1, y1 = (float(value) for value in values)
    return Box(x0=x0, y0=y0, x1=x1, y1=y1)


class PymupdfConverter:
    """Layout-aware converter: page anchors, tables, figures and canaries."""

    converter_id = CONVERTER_ID

    def __init__(self, *, render_dpi: int = DEFAULT_RENDER_DPI) -> None:
        self.converter_version = str(getattr(pymupdf, "__version__", "unknown"))
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

            pages = self._read_pages(document, options)
            markdown_text, anchors, figures, warnings = self._render(
                document, request, pages
            )
            return self._write(
                request, document, markdown_text, anchors, figures, coverage, warnings
            )
        finally:
            document.close()

    # -- reading ----------------------------------------------------------------------

    def _read_pages(
        self, document: pymupdf.Document, options: ConversionOptions
    ) -> list[_PageData]:
        raw_spans: list[tuple[str, float, bool]] = []
        collected: list[tuple[_Line, ...]] = []
        for index in range(document.page_count):
            page = document.load_page(index)
            data = page.get_text("dict")
            raw_spans.extend(self._spans(data))
            collected.append(self._lines(data))

        body_size = body_font_size(raw_spans)
        tables_enabled = options.mode == "layout" and options.table_mode == "markdown"
        figures_enabled = options.mode == "layout" and options.extract_figures

        pages: list[_PageData] = []
        for index, lines in enumerate(collected):
            page = document.load_page(index)
            enriched = tuple(
                _Line(
                    text=line.text,
                    box=line.box,
                    size=line.size,
                    bold=line.bold,
                    level=heading_level(line.text, line.size, line.bold, body_size),
                    block=line.block,
                )
                for line in lines
            )
            tables, table_failed = self._tables(page) if tables_enabled else ((), False)
            images = self._image_boxes(page) if figures_enabled else ()
            pages.append(
                _PageData(
                    lines=enriched,
                    tables=tables,
                    images=images,
                    table_failed=table_failed,
                )
            )
        return pages

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
                spans = [
                    span for span in line.get("spans", []) if span.get("text", "").strip()
                ]
                if not spans:
                    continue
                text = _WHITESPACE.sub(
                    " ", "".join(span.get("text", "") for span in spans)
                ).strip()
                if not text:
                    continue
                lines.append(
                    _Line(
                        text=text,
                        box=_box(*line.get("bbox", (0, 0, 0, 0))),
                        size=max(float(span.get("size", 0)) for span in spans),
                        bold=any(
                            bool(span.get("flags", 0) & _BOLD_FLAG) for span in spans
                        ),
                        level=None,
                        block=block_index,
                    )
                )
            block_index += 1
        return tuple(lines)

    @staticmethod
    def _tables(page: pymupdf.Page) -> tuple[tuple[_Table, ...], bool]:
        try:
            found = page.find_tables()
            tables: list[_Table] = []
            for table in found.tables:
                markdown = markdown_table(table.extract())
                if markdown:
                    tables.append(_Table(box=_box(*table.bbox), markdown=markdown))
            return tuple(tables), False
        except Exception:  # pragma: no cover - depends on the input page
            return (), True

    @staticmethod
    def _image_boxes(page: pymupdf.Page) -> tuple[Box, ...]:
        try:
            return tuple(_box(*info["bbox"]) for info in page.get_image_info(xrefs=True))
        except Exception:  # pragma: no cover - depends on the input page
            return ()

    # -- rendering --------------------------------------------------------------------

    def _render(
        self,
        document: pymupdf.Document,
        request: ConversionRequest,
        pages: Sequence[_PageData],
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
        warnings: set[str] = set()
        if any(page.table_failed for page in pages):
            warnings.add(WARNING_TABLE)
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
            layout = SINGLE_COLUMN
            if options.mode == "layout":
                layout = detect_columns(
                    [line.box for line in page_data.lines], page.rect.width
                )
                if layout.uncertain:
                    warnings.add(WARNING_READING_ORDER)

            content = self._render_page(page_data, layout)
            if options.mode == "layout" and options.extract_figures and page_data.images:
                figure_blocks, placements = self._extract_figures(
                    page, page_no, page_data, figures_dir, warnings
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

    def _render_page(self, page_data: _PageData, layout: ColumnLayout) -> str:
        items: list[tuple[str, Any]] = [("line", line) for line in page_data.lines]
        items.extend(("table", table) for table in page_data.tables)
        boxes = [line.box for line in page_data.lines] + [
            table.box for table in page_data.tables
        ]
        if not boxes:
            return ""
        order = order_boxes(boxes, layout)
        table_boxes = [table.box for table in page_data.tables]
        blocks: list[str] = []
        paragraph: list[str] = []
        last_block: int | None = None

        def flush() -> None:
            if paragraph:
                blocks.append(paragraph[0])
                paragraph.clear()

        for position in order:
            kind, payload = items[position]
            if kind == "table":
                flush()
                last_block = None
                blocks.append(payload.markdown)
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

    def _extract_figures(
        self,
        page: pymupdf.Page,
        page_no: int,
        page_data: _PageData,
        figures_dir: Path,
        warnings: set[str],
    ) -> tuple[list[str], tuple[FigurePlacement, ...]]:
        captions = [
            CaptionBlock(box=line.box, text=line.text) for line in page_data.lines
        ]
        placements = select_figures(page_no, page_data.images, captions)
        if not placements:
            return [], ()
        figures_dir.mkdir(parents=True, exist_ok=True)
        blocks: list[str] = []
        written: list[FigurePlacement] = []
        for placement in placements:
            target = figures_dir / placement.filename
            try:
                pixmap = page.get_pixmap(
                    clip=pymupdf.Rect(*placement.box_tuple()), dpi=self.render_dpi
                )
                pixmap.save(str(target))
            except Exception:  # pragma: no cover - depends on the image
                warnings.add(WARNING_FIGURE)
                continue
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
    "clean_cell",
    "join_line_text",
    "markdown_table",
]
