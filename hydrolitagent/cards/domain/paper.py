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

# On-disk contract shared by every converter and the paper store. Keeping the
# names here means the writer and the reader cannot drift apart silently.
MANIFEST_VERSION = 2
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
    embedded in it (``None`` when the page carries none).
    """

    page: int
    char_start: int
    char_end: int
    heading: str | None
    role: PageRole
    canary: str | None


@dataclass(frozen=True)
class FigureAsset:
    """A figure extracted from a page, stored beside the Markdown file."""

    page: int
    figure_id: str
    path: Path
    caption: str | None


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

    @property
    def page_count(self) -> int:
        return len(self.page_anchors)


__all__ = [
    "FIGURES_DIRNAME",
    "FigureAsset",
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "MARKDOWN_FILENAME",
    "PageAnchor",
    "PageRole",
    "PreparedPaper",
    "SourceIdentity",
]
