"""Ports for paper preparation and storage.

A converter turns a PDF into a ``PreparedPaper``; a store caches those results
by content hash. Both are Protocols, so neither the orchestration layer nor the
domain needs to know which concrete implementation is installed.

This module depends on ``domain`` only. It must not import ``adapters`` and must
not branch on any model provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from hydrolitagent.cards.domain.paper import PreparedPaper, SourceIdentity

TableMode = Literal["markdown", "text"]
ConversionMode = Literal["layout", "text"]
# ``auto`` engages recognition only for a document that is mostly unreadable
# from its own text layer, so a PDF that converts today keeps converting
# byte-for-byte; ``all`` recognises every page and exists for the odd file whose
# text layer is present but wrong (an OCR'd-then-reprinted scan).
OcrScope = Literal["auto", "all"]
# What to do with recognised text that falls inside a detected formula/table
# region. ``remove`` drops it (it is usually noise that would otherwise pass
# every verbatim check and become "evidence"); ``keep`` leaves it in place.
RegionText = Literal["remove", "keep"]

# ``(x0, y0, x1, y1)`` in PDF points. Kept as a plain tuple here because this
# module may not import the layout adapter that owns the richer ``Box`` type.
WordBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class OcrOptions:
    """How to recognise a page that carries no text layer."""

    engine: str = "rapidocr"
    lang: str = "ch"
    dpi: int = 300
    # A page whose text layer yields fewer characters than this is treated as a
    # picture of a page rather than a page of text.
    min_page_chars: int = 40
    scope: OcrScope = "auto"

    @property
    def signature(self) -> str:
        """Identity that changes whenever the recognised characters would change."""

        return f"{self.engine}-{self.lang}-dpi{self.dpi}"


@dataclass(frozen=True)
class RegionOptions:
    """Regional layout analysis on recognised pages (#72).

    Layout analysis is a *soft* capability: without it a scanned page still
    loses nothing that was readable -- it just keeps its formulas as noisy text
    instead of as a picture of the formula.
    """

    enabled: bool = True
    backend: str = "docling"
    text: RegionText = "remove"
    # Share of a text line that must fall inside a region before the line is
    # considered part of it. Above this, removing the line cannot silently eat
    # prose that merely touches the region.
    min_line_share: float = 0.70


@dataclass(frozen=True)
class RegionBox:
    """One detected formula, table or figure on a page, in PDF points."""

    page: int
    kind: str
    box: WordBox
    score: float = 1.0



@dataclass(frozen=True)
class RecognizedWord:
    """One recognised text run and where it sits on the page."""

    text: str
    box: WordBox
    confidence: float = 1.0


@dataclass(frozen=True)
class ConversionOptions:
    """Knobs a caller controls without changing the converter implementation."""

    mode: ConversionMode = "layout"
    extract_figures: bool = True
    table_mode: TableMode = "markdown"
    # ``None`` means "never recognise": a PDF without a usable text layer fails
    # with ``CONVERTER_LOW_TEXT`` exactly as before (#72).
    ocr: OcrOptions | None = None
    regions: RegionOptions | None = None
    min_text_coverage: float = 0.60
    canaries: int = 3

    @property
    def ocr_enabled(self) -> bool:
        return self.ocr is not None


@dataclass(frozen=True)
class ConversionRequest:
    """Everything a converter needs: the file, its identity and a target dir."""

    pdf_path: Path
    pdf_sha256: str
    size_bytes: int
    output_dir: Path
    options: ConversionOptions = field(default_factory=ConversionOptions)
    group_id: int | None = None
    parent_key: str | None = None
    attachment_key: str | None = None


@dataclass(frozen=True)
class ConversionError:
    """Structured failure: code for machines, message and fix for humans."""

    code: str
    message: str
    fix: str | None = None


@dataclass(frozen=True)
class ConverterDoctor:
    """Self-report of a converter, used by ``cards doctor``."""

    converter_id: str
    available: bool
    version: str | None
    capabilities: tuple[str, ...]
    error: str | None = None
    fix: str | None = None
    # Capability reports of the optional helpers behind the fallback. ``None``
    # means "not configured", which is a valid state, not a failure.
    recognizer: ConverterDoctor | None = None
    regions: ConverterDoctor | None = None


class ConversionFailure(RuntimeError):
    """Raised when preparation fails with a ``ConversionError`` payload."""

    def __init__(self, error: ConversionError) -> None:
        super().__init__(f"{error.code}: {error.message}")
        self.error = error


class TextRecognizer(Protocol):
    """Turns a rendered page image into positioned text runs.

    A recogniser never decides layout, reading order, headings or tables: it
    only answers "which characters are in this rectangle". Everything above that
    stays with the converter, so a recognised page goes through exactly the same
    layout rules as a native one.
    """

    engine_id: str
    engine_version: str

    def available(self) -> ConverterDoctor: ...

    def recognize(self, image_png: bytes, options: OcrOptions) -> tuple[RecognizedWord, ...]: ...


class RegionDetector(Protocol):
    """Locates formulas, tables and figures in a PDF, page by page.

    A detector answers only "which regions are not prose, and on which page".
    Cropping, placement and the decision to drop recognised text inside a region
    stay with the converter. It reads the PDF rather than a rendered image
    because a layout model already renders internally, and doing that twice would
    only introduce a second, avoidable source of disagreement.
    """

    backend_id: str
    backend_version: str

    def available(self) -> ConverterDoctor: ...

    def detect(self, pdf_path: Path) -> tuple[RegionBox, ...]: ...


class PaperConverter(Protocol):
    converter_id: str
    converter_version: str

    def doctor(self) -> ConverterDoctor: ...

    def convert(
        self, request: ConversionRequest
    ) -> tuple[PreparedPaper | None, ConversionError | None]: ...


class PaperStore(Protocol):
    """Content-addressed cache of prepared papers."""

    def get_or_prepare(
        self,
        pdf_path: Path,
        *,
        source: SourceIdentity,
        converter: PaperConverter,
        options: ConversionOptions,
    ) -> PreparedPaper: ...

    def get_cached(
        self,
        *,
        pdf_sha256: str,
        size_bytes: int,
        converter_id: str,
        converter_version: str,
        group_id: int | None = None,
        parent_key: str | None = None,
        attachment_key: str | None = None,
    ) -> PreparedPaper | None:
        """Reuse a stored conversion by content identity; never convert."""
        ...


__all__ = [
    "ConversionError",
    "ConversionFailure",
    "ConversionMode",
    "ConversionOptions",
    "ConversionRequest",
    "ConverterDoctor",
    "OcrOptions",
    "OcrScope",
    "PaperConverter",
    "PaperStore",
    "RecognizedWord",
    "RegionBox",
    "RegionDetector",
    "RegionOptions",
    "RegionText",
    "TableMode",
    "TextRecognizer",
    "WordBox",
]
