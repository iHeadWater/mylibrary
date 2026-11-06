"""RapidOCR (ONNX) recogniser: characters and boxes only, never layout.

Why this engine first (#72): it installs as an ordinary Python dependency
(``uv sync --extra ocr``), runs offline on CPU, and is reproducible for a pinned
package version -- the three properties the deterministic conversion contract
needs. A hosted vision model would fail all three, so it is not used to
transcribe characters at all.

Deliberate limits:

* only the bundled Chinese + English model is wired up. ``ocr_lang`` exists so
  the manifest can record the choice and a future engine can honour it; asking
  for a language this adapter does not ship is rejected at configuration time
  rather than silently downgraded;
* the engine loads ~15 MB of models on first use, so it is created once per
  process and reused across pages and papers;
* boxes come back in raster pixels and are converted to PDF points with the
  configured ``dpi``. Both sides use the same number, so the only error is
  pixmap rounding, far below any layout threshold.
"""
from __future__ import annotations

import threading
from importlib import metadata

from hydrolitagent.cards.ports.paper import (
    ConverterDoctor,
    OcrOptions,
    RecognizedWord,
)

ENGINE_ID = "rapidocr"
SUPPORTED_LANGS = ("ch",)
_FIX = (
    "安装可选依赖：uv sync --extra ocr；"
    "或改用 converter_id=pymupdf 只处理带文字层的 PDF"
)
_PACKAGE = "rapidocr-onnxruntime"

_lock = threading.Lock()
_engine = None
_engine_error: str | None = None


def _version() -> str | None:
    try:
        return metadata.version(_PACKAGE)
    except metadata.PackageNotFoundError:
        return None


def _load_engine():
    """Create the OCR engine once per process; report the failure on reuse."""

    global _engine, _engine_error
    with _lock:
        if _engine is not None or _engine_error is not None:
            return _engine
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        except Exception as exc:  # noqa: BLE001 - optional dependency, any failure is a report
            _engine_error = f"{type(exc).__name__}: {exc}"
        return _engine


class RapidOcrRecognizer:
    """Adapter for the ``TextRecognizer`` port backed by RapidOCR."""

    engine_id = ENGINE_ID

    @property
    def engine_version(self) -> str:
        return _version() or "unknown"

    def available(self) -> ConverterDoctor:
        """Cheap probe: the package resolves and ships the model we need.

        Constructing the engine here would load the models inside ``cards
        doctor``, which is a diagnostic command; the first conversion reports a
        load failure instead.
        """

        version = _version()
        if version is None:
            return ConverterDoctor(
                converter_id=ENGINE_ID,
                available=False,
                version=None,
                capabilities=(),
                error=f"缺少 OCR 后端：{_PACKAGE} 未安装",
                fix=_FIX,
            )
        if _engine_error is not None:
            return ConverterDoctor(
                converter_id=ENGINE_ID,
                available=False,
                version=version,
                capabilities=(),
                error=f"OCR 引擎加载失败：{_engine_error}",
                fix="重装可选依赖：uv sync --extra ocr --reinstall-package rapidocr-onnxruntime",
            )
        return ConverterDoctor(
            converter_id=ENGINE_ID,
            available=True,
            version=version,
            capabilities=("words", *SUPPORTED_LANGS),
        )

    def recognize(
        self, image_png: bytes, options: OcrOptions
    ) -> tuple[RecognizedWord, ...]:
        engine = _load_engine()
        if engine is None:
            raise RuntimeError(_engine_error or "OCR 引擎不可用")
        result, _elapsed = engine(image_png)
        scale = 72.0 / options.dpi
        words: list[RecognizedWord] = []
        for item in result or ():
            points, text, score = item[0], item[1], item[2]
            if not str(text).strip():
                continue
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            words.append(
                RecognizedWord(
                    text=str(text),
                    box=(
                        min(xs) * scale,
                        min(ys) * scale,
                        max(xs) * scale,
                        max(ys) * scale,
                    ),
                    confidence=float(score),
                )
            )
        return tuple(words)


def recognizer_for(engine: str):
    """Return the recogniser registered under ``engine``, or ``None``."""

    if engine == ENGINE_ID:
        return RapidOcrRecognizer()
    return None


__all__ = ["ENGINE_ID", "RapidOcrRecognizer", "SUPPORTED_LANGS", "recognizer_for"]
