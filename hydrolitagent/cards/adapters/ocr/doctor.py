"""Capability probe for the optional OCR recogniser.

Mirrors ``adapters/pdf/doctor.py``: the probe never builds a converter and never
loads a model. It answers the only question ``cards doctor`` can answer cheaply --
"is a recogniser installed and does it ship the model this configuration asks
for" -- because recognising a real page belongs to a conversion, not to a
diagnostic.
"""
from __future__ import annotations

from hydrolitagent.cards.ports.paper import ConverterDoctor


def probe_recognizer(engine: str) -> ConverterDoctor:
    """Report whether ``engine`` is installed, without importing a model."""

    from hydrolitagent.cards.adapters.ocr import recognizer_for

    recognizer = recognizer_for(engine)
    if recognizer is None:
        return ConverterDoctor(
            converter_id=engine,
            available=False,
            version=None,
            capabilities=(),
            error=f"未知的 OCR 后端：{engine!r}",
            fix="在配置中改用 converter.ocr_engine 支持的引擎（当前仅 rapidocr）",
        )
    return recognizer.available()


__all__ = ["probe_recognizer"]
