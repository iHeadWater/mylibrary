"""Pure data describing a paper that has been prepared for reading.

``PreparedPaper`` is the hand-off object between the converter and any card
runner: it points at a Markdown rendering (plus page anchors and figure assets)
instead of a raw PDF. Nothing here performs I/O, and no concrete converter or
model provider is named -- this module is the shared vocabulary of the
Markdown-first pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PageRole = Literal["front_matter", "body", "references", "appendix", "unknown"]
# Where a page's characters came from. ``native`` means the PDF carries a real
# text layer and the converter read it; ``ocr``/``vlm`` mean a machine looked at
# a picture of the page (#72). The distinction is not cosmetic: a native page can
# prove "the paper says this", a recognised page can only prove "the recogniser
# thinks the paper says this", so a quote taken from it is reported separately.
PageSource = Literal["native", "ocr", "vlm"]

# On-disk contract shared by every converter and the paper store. Keeping the
# names here means the writer and the reader cannot drift apart silently.
#
# Version 3 adds per-page provenance (§``PageAnchor.source``). Version 2
# manifests stay readable and are read as all-``native``: they were written
# before any recogniser existed, so that is what they are.
MANIFEST_VERSION = 3
READABLE_MANIFEST_VERSIONS = (2, MANIFEST_VERSION)
MANIFEST_FILENAME = "manifest.json"
MARKDOWN_FILENAME = "paper.md"
FIGURES_DIRNAME = "figures"


@dataclass(frozen=True)
class SourceIdentity:
    """Identity of the original PDF a prepared paper was derived from."""

    pdf_sha256: str
    size_bytes: int
    page_count: int
    group_id: int | None = None
    parent_key: str | None = None
    attachment_key: str | None = None


@dataclass(frozen=True)
class PageAnchor:
    """Character range of one page inside the Markdown document.

    ``char_start``/``char_end`` are offsets into ``paper.md`` (``char_end``
    exclusive). ``heading`` is the most prominent heading found on the page,
    ``role`` classifies the page and ``canary`` records the integrity marker
    embedded in it (``None`` when the page carries none). ``source`` records
    where the characters came from; it defaults to ``native`` so a caller that
    only cares about layout never has to mention it.
    """

    page: int
    char_start: int
    char_end: int
    heading: str | None
    role: PageRole
    canary: str | None
    source: PageSource = "native"


@dataclass(frozen=True)
class FigureAsset:
    """A figure extracted from a page, stored beside the Markdown file."""

    page: int
    figure_id: str
    path: Path
    caption: str | None


@dataclass(frozen=True)
class RecognitionInfo:
    """Which recogniser produced which pages, and with what settings.

    Recorded because a recognised page is reproducible only for the same engine,
    version, language and rasterisation density: changing any of them changes the
    characters. The converter version carries the same settings, so a cache
    lookup cannot even find a conversion built with different ones.
    """

    engine: str
    version: str
    lang: str
    dpi: int
    pages: tuple[int, ...] = ()

    @property
    def signature(self) -> str:
        return f"{self.engine}-{self.version}-{self.lang}-dpi{self.dpi}"


@dataclass(frozen=True)
class PreparedPaper:
    """A deterministic Markdown rendering of a PDF, ready for a runner."""

    source: SourceIdentity
    markdown_path: Path
    markdown_sha256: str
    manifest_path: Path
    page_anchors: tuple[PageAnchor, ...]
    figures: tuple[FigureAsset, ...]
    converter_id: str
    converter_version: str
    text_coverage: float
    warnings: tuple[str, ...]
    recognition: RecognitionInfo | None = None

    @property
    def page_count(self) -> int:
        return len(self.page_anchors)

    @property
    def recognised_pages(self) -> tuple[int, ...]:
        """Pages whose characters came from a recogniser, not from the text layer."""

        return tuple(
            anchor.page for anchor in self.page_anchors if anchor.source != "native"
        )


__all__ = [
    "FIGURES_DIRNAME",
    "FigureAsset",
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "MARKDOWN_FILENAME",
    "PageAnchor",
    "PageRole",
    "PageSource",
    "PreparedPaper",
    "READABLE_MANIFEST_VERSIONS",
    "RecognitionInfo",
    "SourceIdentity",
]
