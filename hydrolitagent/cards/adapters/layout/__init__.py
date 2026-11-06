"""Optional layout analysis: where are the formulas, tables and figures?

Layout analysis is a *soft* capability (#72): a recognised page without it keeps
its formula text as noise instead of a picture of the formula. Nothing about
reading the prose depends on it, so importing this package must stay cheap and
must never import a model runtime at module level.
"""
from __future__ import annotations

from .docling_regions import DoclingRegionDetector, region_detector_for

__all__ = ["DoclingRegionDetector", "region_detector_for"]
