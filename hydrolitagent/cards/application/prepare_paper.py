"""Orchestrate paper preparation: hash the source, then ask the store.

The application layer knows the ports, not the implementations: it receives a
converter and a store from ``composition`` and never imports ``adapters``.
That keeps the "prepare a paper" step independent of which PDF library or which
cache implementation is installed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from hydrolitagent.cards.domain.paper import PreparedPaper, SourceIdentity
from hydrolitagent.cards.ports.paper import (
    ConversionError,
    ConversionFailure,
    ConversionOptions,
    PaperConverter,
    PaperStore,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_paper(
    pdf_path: Path,
    *,
    converter: PaperConverter,
    store: PaperStore,
    options: ConversionOptions | None = None,
    group_id: int | None = None,
    parent_key: str | None = None,
    attachment_key: str | None = None,
) -> PreparedPaper:
    """Return a prepared paper for ``pdf_path``, converting only when needed.

    The source identity is derived here, so a caller cannot claim one hash while
    pointing at a different file. Failures carry a structured error through
    ``ConversionFailure`` (see ``ports.paper``).
    """

    path = Path(pdf_path)
    if not path.is_file():
        raise ConversionFailure(
            ConversionError(
                "SOURCE_PDF_MISSING",
                f"PDF 不存在：{path}",
                "确认 paper-input 记录里的本地 PDF 路径仍然有效，或重新解析该附件",
            )
        )
    source = SourceIdentity(
        pdf_sha256=_sha256_file(path),
        size_bytes=path.stat().st_size,
        page_count=0,
        group_id=group_id,
        parent_key=parent_key,
        attachment_key=attachment_key,
    )
    return store.get_or_prepare(
        path,
        source=source,
        converter=converter,
        options=options or ConversionOptions(),
    )


__all__ = ["prepare_paper"]
