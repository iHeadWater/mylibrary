"""Content-addressed cache for prepared papers.

Preparing a paper is the expensive part of the Markdown-first pipeline, so the
result is stored under ``<cache_dir>/papers/<pdf_sha256>/<converter>-<version>/``.
The layout is a pure function of content and converter identity: the same PDF
is never converted twice by the same converter, and a new converter version
gets its own directory instead of overwriting the old reading.

Writes are atomic at directory granularity. The converter writes into a
temporary sibling directory; only a fully written result is renamed onto the
final path, so a crash never leaves a half-written ``paper.md`` that later
looks like a cache hit.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydrolitagent.cards.domain.paper import (
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
    ConversionFailure,
    ConversionOptions,
    ConversionRequest,
    PaperConverter,
)

_CACHE_SUBDIR = "papers"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_child(root: Path, relative: Any) -> Path | None:
    """Resolve a manifest-relative path, rejecting absolute or escaping values."""

    if not isinstance(relative, str) or not relative.strip():
        return None
    candidate = Path(relative)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        return None
    return resolved


class PaperStore:
    """Cache of ``PreparedPaper`` results keyed by PDF hash and converter."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    def paper_dir(self, pdf_sha256: str, converter: PaperConverter) -> Path:
        return (
            self.cache_dir
            / _CACHE_SUBDIR
            / pdf_sha256
            / f"{converter.converter_id}-{converter.converter_version}"
        )

    def get_or_prepare(
        self,
        pdf_path: Path,
        *,
        source: SourceIdentity,
        converter: PaperConverter,
        options: ConversionOptions,
    ) -> PreparedPaper:
        target = self.paper_dir(source.pdf_sha256, converter)
        cached = self._load_cached(target, source)
        if cached is not None:
            return cached

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=".preparing-", dir=str(target.parent))
        )
        try:
            prepared, error = converter.convert(
                ConversionRequest(
                    pdf_path=Path(pdf_path),
                    pdf_sha256=source.pdf_sha256,
                    size_bytes=source.size_bytes,
                    output_dir=staging,
                    options=options,
                    group_id=source.group_id,
                    parent_key=source.parent_key,
                    attachment_key=source.attachment_key,
                )
            )
            if error is not None or prepared is None:
                raise ConversionFailure(
                    error
                    or ConversionError(
                        "CONVERTER_FAILED", "转换器没有返回任何结果。", "检查转换器实现"
                    )
                )
            if target.exists():
                shutil.rmtree(target)
            staging.replace(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        rebuilt = self._load_cached(target, source)
        if rebuilt is None:
            raise ConversionFailure(
                ConversionError(
                    "CONVERTER_MANIFEST_INVALID",
                    "转换结果写入后无法通过清单校验。",
                    "删除该 PDF 的缓存目录后重试",
                )
            )
        return rebuilt

    # -- cache reads ------------------------------------------------------------------

    def _load_cached(self, paper_dir: Path, source: SourceIdentity) -> PreparedPaper | None:
        manifest_path = paper_dir / MANIFEST_FILENAME
        markdown_path = paper_dir / MARKDOWN_FILENAME
        if not manifest_path.is_file() or not markdown_path.is_file():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("manifest_version") != MANIFEST_VERSION:
            return None

        cached_source = payload.get("source")
        if not isinstance(cached_source, dict):
            return None
        if cached_source.get("pdf_sha256") != source.pdf_sha256:
            return None
        if cached_source.get("size_bytes") != source.size_bytes:
            return None
        page_count = cached_source.get("page_count")
        if type(page_count) is not int or page_count < 1:
            return None

        markdown_meta = payload.get("markdown")
        if not isinstance(markdown_meta, dict):
            return None
        if markdown_meta.get("file") != MARKDOWN_FILENAME:
            return None
        expected_markdown_sha = markdown_meta.get("sha256")
        if not isinstance(expected_markdown_sha, str):
            return None
        if _sha256_file(markdown_path) != expected_markdown_sha:
            return None

        converter_meta = payload.get("converter")
        if not isinstance(converter_meta, dict):
            return None
        converter_id = converter_meta.get("id")
        converter_version = converter_meta.get("version")
        if not isinstance(converter_id, str) or not isinstance(converter_version, str):
            return None
        if paper_dir.name != f"{converter_id}-{converter_version}":
            return None

        anchors = self._read_anchors(payload.get("page_anchors"), page_count)
        if anchors is None:
            return None
        figures = self._read_figures(payload.get("figures"), paper_dir)
        if figures is None:
            return None
        warnings = payload.get("warnings")
        if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            return None
        coverage = payload.get("text_coverage")
        if not isinstance(coverage, (int, float)) or isinstance(coverage, bool):
            return None

        return PreparedPaper(
            source=SourceIdentity(
                pdf_sha256=source.pdf_sha256,
                size_bytes=source.size_bytes,
                page_count=page_count,
                group_id=source.group_id,
                parent_key=source.parent_key,
                attachment_key=source.attachment_key,
            ),
            markdown_path=markdown_path,
            markdown_sha256=expected_markdown_sha,
            manifest_path=manifest_path,
            page_anchors=anchors,
            figures=figures,
            converter_id=converter_id,
            converter_version=converter_version,
            text_coverage=float(coverage),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _read_anchors(raw: Any, page_count: int) -> tuple[PageAnchor, ...] | None:
        if not isinstance(raw, list) or len(raw) != page_count:
            return None
        anchors: list[PageAnchor] = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, Mapping):
                return None
            page = item.get("page")
            start = item.get("char_start")
            end = item.get("char_end")
            if page != index or type(start) is not int or type(end) is not int:
                return None
            if start < 0 or end < start:
                return None
            heading = item.get("heading")
            role = item.get("role")
            canary = item.get("canary")
            if heading is not None and not isinstance(heading, str):
                return None
            if canary is not None and not isinstance(canary, str):
                return None
            if role not in {"front_matter", "body", "references", "appendix", "unknown"}:
                return None
            anchors.append(
                PageAnchor(
                    page=page,
                    char_start=start,
                    char_end=end,
                    heading=heading,
                    role=role,
                    canary=canary,
                )
            )
        return tuple(anchors)

    @staticmethod
    def _read_figures(raw: Any, paper_dir: Path) -> tuple[FigureAsset, ...] | None:
        if not isinstance(raw, list):
            return None
        figures: list[FigureAsset] = []
        for item in raw:
            if not isinstance(item, Mapping):
                return None
            page = item.get("page")
            figure_id = item.get("figure_id")
            path = _safe_child(paper_dir, item.get("path"))
            caption = item.get("caption")
            if type(page) is not int or page < 1:
                return None
            if not isinstance(figure_id, str) or not figure_id:
                return None
            if path is None or not path.is_file():
                return None
            if caption is not None and not isinstance(caption, str):
                return None
            figures.append(
                FigureAsset(page=page, figure_id=figure_id, path=path, caption=caption)
            )
        return tuple(figures)


__all__ = ["MANIFEST_FILENAME", "MANIFEST_VERSION", "PaperStore"]
