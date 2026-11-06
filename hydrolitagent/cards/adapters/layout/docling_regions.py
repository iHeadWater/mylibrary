"""Docling as a region *detector* only: no OCR, no table structure.

Why only detection (#72, decision 7d-1b): Docling can transcribe characters and
reconstruct tables, but it would then compete with the converter for the same
decisions -- reading order, page anchors, canaries -- and two owners of one
decision is how a pipeline starts disagreeing with itself. What the converter is
genuinely missing on a scanned page is "which rectangle is a formula, a table or
a figure", so Docling is asked only that.

Consequences that are deliberate:

* ``do_ocr=False`` and ``do_table_structure=False``; the characters still come
  from the configured recogniser, so the text of a recognised page does not
  depend on which layout backend happens to be installed;
* the PDF is analysed once per document rather than once per page image;
* region boxes come back in PDF points with a top-left origin, the same
  convention the rest of the converter uses.
"""
from __future__ import annotations

from importlib import metadata
from pathlib import Path

from hydrolitagent.cards.ports.paper import ConverterDoctor, RegionBox

BACKEND_ID = "docling"
_PACKAGE = "docling"
_FIX = (
    "安装可选依赖：uv sync --extra layout；首次使用还要下载版面模型，"
    "若 huggingface 不可达，先设 HF_ENDPOINT=https://hf-mirror.com。"
    "不装也能识别文字，只是不贴公式/表格区域图"
)
# Docling labels that describe a region the converter cannot read as prose.
_REGION_LABELS = {
    "formula": "formula",
    "table": "table",
    "picture": "figure",
    "chart": "figure",
}

# Below this many points a box is more likely a stray rule than a region.
_MIN_SIDE = 8.0

_converter = None
_converter_error: str | None = None


def _version() -> str | None:
    try:
        return metadata.version(_PACKAGE)
    except metadata.PackageNotFoundError:
        return None


def _load_converter():
    """Build the Docling converter once per process, layout only."""

    global _converter, _converter_error
    if _converter is not None or _converter_error is not None:
        return _converter
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = False
        options.do_table_structure = False
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
    except Exception as exc:  # noqa: BLE001 - optional dependency, any failure is a report
        _converter_error = f"{type(exc).__name__}: {exc}"
    return _converter


class DoclingRegionDetector:
    """Adapter for the ``RegionDetector`` port backed by Docling."""

    backend_id = BACKEND_ID

    @property
    def backend_version(self) -> str:
        return _version() or "unknown"

    def available(self) -> ConverterDoctor:
        version = _version()
        if version is None:
            return ConverterDoctor(
                converter_id=BACKEND_ID,
                available=False,
                version=None,
                capabilities=(),
                error=f"缺少版面分析后端：{_PACKAGE} 未安装",
                fix=_FIX,
            )
        if _converter_error is not None:
            return ConverterDoctor(
                converter_id=BACKEND_ID,
                available=False,
                version=version,
                capabilities=(),
                error=f"版面分析加载失败：{_converter_error}",
                fix="重装可选依赖：uv sync --extra layout --reinstall-package docling",
            )
        return ConverterDoctor(
            converter_id=BACKEND_ID,
            available=True,
            version=version,
            capabilities=("formula", "table", "figure"),
        )

    def detect(self, pdf_path: Path) -> tuple[RegionBox, ...]:
        converter = _load_converter()
        if converter is None:
            raise RuntimeError(_converter_error or "版面分析后端不可用")
        result = converter.convert(str(pdf_path))
        document = result.document
        # Page sizes live on the document, not on each item's provenance.
        heights = {
            int(number): float(page.size.height)
            for number, page in document.pages.items()
        }
        regions: list[RegionBox] = []
        for item, _level in document.iterate_items():
            kind = _REGION_LABELS.get(str(getattr(item, "label", "")))
            if kind is None:
                continue
            for prov in getattr(item, "prov", ()) or ():
                page_no = int(prov.page_no)
                box = self._region_box(prov, heights.get(page_no))
                if box is not None:
                    regions.append(
                        RegionBox(
                            page=page_no,
                            kind=kind,
                            box=box,
                            score=float(getattr(item, "confidence", 1.0) or 1.0),
                        )
                    )
        return tuple(regions)

    @staticmethod
    def _region_box(
        prov, page_height: float | None
    ) -> tuple[float, float, float, float] | None:
        """Convert Docling's provenance bbox to top-left PDF points."""

        bbox = getattr(prov, "bbox", None)
        if bbox is None:
            return None
        left = float(bbox.l)
        right = float(bbox.r)
        top_raw = float(bbox.t)
        bottom_raw = float(bbox.b)
        origin = str(getattr(bbox, "coord_origin", "bottomleft")).lower()
        if "top" in origin:
            top, bottom = top_raw, bottom_raw
        else:
            if page_height is None:
                return None
            # Docling reports a bottom-left origin; the converter works top-left.
            top, bottom = page_height - top_raw, page_height - bottom_raw
        if bottom < top:
            top, bottom = bottom, top
        if right - left < _MIN_SIDE or bottom - top < _MIN_SIDE:
            return None
        return (left, top, right, bottom)


def region_detector_for(backend: str):
    """Return the detector registered under ``backend``, or ``None``."""

    if backend == BACKEND_ID:
        return DoclingRegionDetector()
    return None


__all__ = ["BACKEND_ID", "DoclingRegionDetector", "region_detector_for"]
