"""Capability probe for the optional layout backend.

Cheap by construction: it checks that the package resolves, never that a model
runs. A missing backend is a warning in ``cards doctor``, not a failure, because
prose is still readable without it (#72).
"""
from __future__ import annotations

from hydrolitagent.cards.ports.paper import ConverterDoctor


def probe_regions(backend: str) -> ConverterDoctor:
    """Report whether ``backend`` is installed, without loading a model."""

    from hydrolitagent.cards.adapters.layout import region_detector_for

    detector = region_detector_for(backend)
    if detector is None:
        return ConverterDoctor(
            converter_id=backend,
            available=False,
            version=None,
            capabilities=(),
            error=f"未知的版面分析后端：{backend!r}",
            fix="在配置中改用 converter.region_backend 支持的后端（当前仅 docling）",
        )
    return detector.available()


__all__ = ["probe_regions"]
