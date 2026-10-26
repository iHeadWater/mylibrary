"""Capability probe for the PyMuPDF converter.

The converter module imports ``pymupdf`` at module level, so importing it is
exactly the failure being diagnosed. This probe keeps the import inside a
function and returns a ``ConverterDoctor`` instead of raising, which lets
``cards doctor`` explain a missing dependency instead of crashing with an
ImportError traceback.

The self-test builds a one-page PDF in memory, reopens it and reads the text
back. That proves the library is not merely importable but can open and read a
document, which is the capability the pipeline actually needs.
"""
from __future__ import annotations

from hydrolitagent.cards.ports.paper import ConverterDoctor

_PROBE_TEXT = "doctor probe"
_FIX = "uv add pymupdf（PyMuPDF 是 AGPL-3.0，与本项目许可兼容）"


def probe_pymupdf() -> ConverterDoctor:
    """Return the converter capability without importing its adapter module."""

    try:
        import pymupdf
    except Exception as exc:  # noqa: BLE001 - a broken install must not crash doctor
        return ConverterDoctor(
            converter_id="pymupdf",
            available=False,
            version=None,
            capabilities=(),
            error=f"缺少 PyMuPDF：{exc}",
            fix=_FIX,
        )

    version = str(getattr(pymupdf, "__version__", "unknown"))
    try:
        document = pymupdf.open()
        page = document.new_page(width=200, height=200)
        page.insert_text((20, 60), _PROBE_TEXT)
        payload = document.tobytes()
        document.close()

        reopened = pymupdf.open(stream=payload, filetype="pdf")
        try:
            text = "".join(item.get_text() for item in reopened)
        finally:
            reopened.close()
    except Exception as exc:  # noqa: BLE001 - any library failure is a doctor fact
        return ConverterDoctor(
            converter_id="pymupdf",
            available=False,
            version=version,
            capabilities=(),
            error=f"PyMuPDF 无法完成最小读写自检：{type(exc).__name__}: {exc}",
            fix="重装 PyMuPDF（uv add --force-reinstall pymupdf），确认平台与 wheel 匹配",
        )

    if _PROBE_TEXT not in text:
        return ConverterDoctor(
            converter_id="pymupdf",
            available=False,
            version=version,
            capabilities=(),
            error="PyMuPDF 自检无法读回写入的文本",
            fix="重装 PyMuPDF（uv add --force-reinstall pymupdf）",
        )
    return ConverterDoctor(
        converter_id="pymupdf",
        available=True,
        version=version,
        capabilities=("text", "layout", "tables", "figures"),
    )


__all__ = ["probe_pymupdf"]
