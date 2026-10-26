"""Plain-text fallback converter built on pypdf.

It exists so a broken or unusual PyMuPDF import does not leave the platform
with no converter at all. It has no layout model and no figure support, and it
says so in ``warnings`` instead of pretending otherwise.
"""
from __future__ import annotations

import hashlib
import json

import pypdf
from pypdf import PdfReader

from hydrolitagent.cards.domain.paper import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    MARKDOWN_FILENAME,
    PageAnchor,
    PreparedPaper,
    SourceIdentity,
)
from hydrolitagent.cards.ports.paper import (
    ConversionError,
    ConversionRequest,
    ConverterDoctor,
)

from .anchors import (
    canary_assignment,
    canary_marker,
    page_marker,
    text_coverage,
)

CONVERTER_ID = "pypdf"
WARNINGS = ("NO_FIGURES", "NO_LAYOUT")


class PypdfConverter:
    """Text-only fallback: one page marker and one paragraph per page."""

    converter_id = CONVERTER_ID

    def __init__(self) -> None:
        self.converter_version = str(getattr(pypdf, "__version__", "unknown"))

    def doctor(self) -> ConverterDoctor:
        return ConverterDoctor(
            converter_id=self.converter_id,
            available=True,
            version=self.converter_version,
            capabilities=("text",),
        )

    def convert(
        self, request: ConversionRequest
    ) -> tuple[PreparedPaper | None, ConversionError | None]:
        try:
            reader = PdfReader(str(request.pdf_path))
        except Exception as exc:  # pragma: no cover - depends on the input file
            return None, ConversionError(
                "CONVERTER_OPEN_FAILED",
                f"无法打开 PDF：{exc}",
                "确认文件完整且确实是 PDF；必要时从来源重新下载",
            )

        if reader.is_encrypted:
            return None, ConversionError(
                "CONVERTER_ENCRYPTED",
                "PDF 受密码保护，无法读取正文。",
                "先在来源处解除加密，或改用未加密的版本。",
            )
        page_texts: list[str] = []
        try:
            for page in reader.pages:
                page_texts.append(page.extract_text() or "")
        except Exception as exc:  # pragma: no cover - depends on the input file
            return None, ConversionError(
                "CONVERTER_OPEN_FAILED",
                f"读取 PDF 页面失败：{exc}",
                "确认文件完整；必要时从来源重新下载",
            )

        coverage = text_coverage(page_texts)
        if coverage < request.options.min_text_coverage:
            return None, ConversionError(
                "CONVERTER_LOW_TEXT",
                f"可读文本页只占 {coverage:.0%}，低于阈值 {request.options.min_text_coverage:.0%}。",
                "该 PDF 很可能是扫描件；请提供带文本层的版本，或另行启用可选的 OCR 流程。",
            )

        canaries = canary_assignment(
            len(page_texts), request.pdf_sha256, count=request.options.canaries
        )
        parts: list[str] = []
        offset = 0
        anchors: list[PageAnchor] = []
        for index, text in enumerate(page_texts):
            page_no = index + 1
            tokens = canaries.get(index, ())
            header = page_marker(page_no) + "\n"
            header += "".join(canary_marker(token) + "\n" for token in tokens)
            parts.append(header)
            offset += len(header)
            start = offset
            body = _normalize(text)
            content = body + "\n" if body else ""
            parts.append(content)
            offset += len(content)
            anchors.append(
                PageAnchor(
                    page=page_no,
                    char_start=start,
                    char_end=offset,
                    heading=None,
                    role="unknown",
                    canary=tokens[0] if tokens else None,
                )
            )
            parts.append("\n")
            offset += 1

        markdown_text = "".join(parts)
        source = SourceIdentity(
            pdf_sha256=request.pdf_sha256,
            size_bytes=request.size_bytes,
            page_count=len(page_texts),
            group_id=request.group_id,
            parent_key=request.parent_key,
            attachment_key=request.attachment_key,
        )
        output_dir = request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / MARKDOWN_FILENAME
        markdown_path.write_text(markdown_text, encoding="utf-8", newline="\n")
        markdown_sha256 = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()
        manifest_path = output_dir / MANIFEST_FILENAME
        manifest_path.write_text(
            json.dumps(
                {
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
                    "figures": [],
                    "text_coverage": round(coverage, 4),
                    "warnings": list(WARNINGS),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return (
            PreparedPaper(
                source=source,
                markdown_path=markdown_path,
                markdown_sha256=markdown_sha256,
                manifest_path=manifest_path,
                page_anchors=tuple(anchors),
                figures=(),
                converter_id=self.converter_id,
                converter_version=self.converter_version,
                text_coverage=round(coverage, 4),
                warnings=WARNINGS,
            ),
            None,
        )


def _normalize(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    normalized = "\n".join(line for line in lines if line).strip()
    return normalized


__all__ = [
    "CONVERTER_ID",
    "MARKDOWN_FILENAME",
    "MANIFEST_FILENAME",
    "PypdfConverter",
    "WARNINGS",
]
