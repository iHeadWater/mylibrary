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


@dataclass(frozen=True)
class ConversionOptions:
    """Knobs a caller controls without changing the converter implementation."""

    mode: ConversionMode = "layout"
    extract_figures: bool = True
    table_mode: TableMode = "markdown"
    ocr: bool = False
    min_text_coverage: float = 0.60
    canaries: int = 3


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
    """Self-report of a converter, used by ``cards doctor`` in a later stage."""

    converter_id: str
    available: bool
    version: str | None
    capabilities: tuple[str, ...]
    error: str | None = None


class ConversionFailure(RuntimeError):
    """Raised when preparation fails with a ``ConversionError`` payload."""

    def __init__(self, error: ConversionError) -> None:
        super().__init__(f"{error.code}: {error.message}")
        self.error = error


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


__all__ = [
    "ConversionError",
    "ConversionFailure",
    "ConversionMode",
    "ConversionOptions",
    "ConversionRequest",
    "ConverterDoctor",
    "PaperConverter",
    "PaperStore",
    "TableMode",
]
