"""Optional recognisers used as the fallback for pages without a text layer.

Recognition is an optional capability with its own dependency, while the PDF
converter is a required one. Importing this package must therefore stay cheap and
must never import a machine-learning runtime at module level -- ``cards doctor``
would otherwise pay for the fallback even when nobody uses it.
"""
from __future__ import annotations

from .rapidocr import RapidOcrRecognizer, recognizer_for

__all__ = ["RapidOcrRecognizer", "recognizer_for"]
