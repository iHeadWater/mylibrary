"""Behaviour tests for the content-addressed prepared-paper cache.

The cache key is ``(pdf_sha256, converter_id, converter_version)``. These tests
prove that a second request reuses the stored reading, that a different
converter version does not, that corruption forces a rebuild instead of being
served, and that a failed conversion leaves no cache entry behind.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.application.prepare_paper import prepare_paper
from hydrolitagent.cards.domain.paper import SourceIdentity
from hydrolitagent.cards.ports.paper import (
    ConversionError,
    ConversionFailure,
    ConversionOptions,
    ConverterDoctor,
)

BODY = (
    "Rainfall-runoff processes in small catchments are controlled by soil moisture "
    "and storm intensity. This paragraph exists so the page has a readable text layer."
)


def _text_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hydrology Notes", fontsize=16)
    page.insert_textbox(pymupdf.Rect(72, 120, 523, 400), BODY, fontsize=10)
    path = tmp_path / "paper.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _source(pdf: Path, **identity: object) -> SourceIdentity:
    return SourceIdentity(
        pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        size_bytes=pdf.stat().st_size,
        page_count=0,
        **identity,  # type: ignore[arg-type]
    )


class RecordingConverter:
    """Concrete converter with a controllable version and a call counter."""

    def __init__(self, version: str = "test-1") -> None:
        inner = PymupdfConverter()
        inner.converter_version = version
        self._inner = inner
        self.converter_id = inner.converter_id
        self.converter_version = version
        self.calls = 0

    def doctor(self) -> ConverterDoctor:
        return self._inner.doctor()

    def convert(self, request):
        self.calls += 1
        return self._inner.convert(request)


class FailingConverter:
    converter_id = "failing"
    converter_version = "0"

    def doctor(self) -> ConverterDoctor:
        return ConverterDoctor("failing", False, "0", (), "not available")

    def convert(self, request):
        return None, ConversionError("CONVERTER_LOW_TEXT", "no text", "provide text")


def test_second_request_reuses_cached_reading(tmp_path: Path) -> None:
    pdf = _text_pdf(tmp_path)
    store = PaperStore(tmp_path / "cache")
    converter = RecordingConverter()

    first = store.get_or_prepare(
        pdf,
        source=_source(pdf),
        converter=converter,
        options=ConversionOptions(),
    )
    second = store.get_or_prepare(
        pdf,
        source=_source(pdf),
        converter=converter,
        options=ConversionOptions(),
    )

    assert converter.calls == 1
    assert second.markdown_sha256 == first.markdown_sha256
    assert second.source.page_count == first.source.page_count == 1
    assert first.markdown_path.is_file()
    assert first.manifest_path.is_file()


def test_different_converter_version_is_not_reused(tmp_path: Path) -> None:
    pdf = _text_pdf(tmp_path)
    store = PaperStore(tmp_path / "cache")
    first_converter = RecordingConverter(version="v1")
    second_converter = RecordingConverter(version="v2")

    store.get_or_prepare(
        pdf, source=_source(pdf), converter=first_converter, options=ConversionOptions()
    )
    store.get_or_prepare(
        pdf, source=_source(pdf), converter=second_converter, options=ConversionOptions()
    )

    assert first_converter.calls == 1
    assert second_converter.calls == 1
    directory = store.paper_dir(_source(pdf).pdf_sha256, first_converter).parent
    directories = sorted(path.name for path in directory.iterdir())
    assert directories == ["pymupdf-v1", "pymupdf-v2"]


def test_corrupted_manifest_forces_reconversion(tmp_path: Path) -> None:
    pdf = _text_pdf(tmp_path)
    store = PaperStore(tmp_path / "cache")
    converter = RecordingConverter()

    prepared = store.get_or_prepare(
        pdf, source=_source(pdf), converter=converter, options=ConversionOptions()
    )
    manifest_path = prepared.manifest_path
    original = manifest_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["markdown"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    rebuilt = store.get_or_prepare(
        pdf, source=_source(pdf), converter=converter, options=ConversionOptions()
    )

    assert converter.calls == 2
    assert rebuilt.markdown_sha256 != "0" * 64
    assert rebuilt.markdown_sha256 == prepared.markdown_sha256
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["markdown"]["sha256"] == (
        rebuilt.markdown_sha256
    )


def test_corrupted_markdown_forces_reconversion(tmp_path: Path) -> None:
    pdf = _text_pdf(tmp_path)
    store = PaperStore(tmp_path / "cache")
    converter = RecordingConverter()

    prepared = store.get_or_prepare(
        pdf, source=_source(pdf), converter=converter, options=ConversionOptions()
    )
    prepared.markdown_path.write_text("tampered\n", encoding="utf-8")

    rebuilt = store.get_or_prepare(
        pdf, source=_source(pdf), converter=converter, options=ConversionOptions()
    )

    assert converter.calls == 2
    assert rebuilt.markdown_sha256 != hashlib.sha256(b"tampered\n").hexdigest()
    assert "Hydrology Notes" in rebuilt.markdown_path.read_text(encoding="utf-8")


def test_failed_conversion_leaves_no_cache_entry(tmp_path: Path) -> None:
    pdf = _text_pdf(tmp_path)
    store = PaperStore(tmp_path / "cache")
    converter = FailingConverter()
    source = _source(pdf)

    with pytest.raises(ConversionFailure) as error:
        store.get_or_prepare(pdf, source=source, converter=converter, options=ConversionOptions())

    assert error.value.error.code == "CONVERTER_LOW_TEXT"
    target = store.paper_dir(source.pdf_sha256, converter)
    assert not target.exists()
    assert list(target.parent.glob(".preparing-*")) == []


def test_prepare_paper_derives_source_identity(tmp_path: Path) -> None:
    pdf = _text_pdf(tmp_path)
    store = PaperStore(tmp_path / "cache")
    converter = RecordingConverter()

    prepared = prepare_paper(
        pdf,
        converter=converter,
        store=store,
        group_id=42,
        parent_key="PARENT01",
        attachment_key="ATTACH01",
    )
    again = prepare_paper(
        pdf,
        converter=converter,
        store=store,
        group_id=42,
        parent_key="PARENT01",
        attachment_key="ATTACH01",
    )

    assert converter.calls == 1
    assert prepared.source.pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert prepared.source.size_bytes == pdf.stat().st_size
    assert prepared.source.page_count == 1
    assert prepared.source.group_id == 42
    assert prepared.source.parent_key == "PARENT01"
    assert prepared.source.attachment_key == "ATTACH01"
    assert again.markdown_path == prepared.markdown_path


def test_missing_pdf_is_a_structured_failure(tmp_path: Path) -> None:
    store = PaperStore(tmp_path / "cache")

    with pytest.raises(ConversionFailure) as error:
        prepare_paper(
            tmp_path / "missing.pdf",
            converter=RecordingConverter(),
            store=store,
        )

    assert error.value.error.code == "SOURCE_PDF_MISSING"
    assert error.value.error.fix


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
