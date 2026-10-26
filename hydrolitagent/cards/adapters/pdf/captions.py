"""Caption label recognition shared by figure and table extraction.

A caption is only recognised when the line *starts* with a label and a number
followed by ``.``, ``:`` or a dash. Body prose such as "Figure 1 shows ..." is
therefore not a caption, and neither is a citation like "see Table 2)".
"""
from __future__ import annotations

import re
from typing import Literal

CaptionKind = Literal["figure", "table"]

_CAPTION = re.compile(
    r"^\s*(?:(?P<figure>fig(?:ure)?\.?)|(?P<table>table))\s+"
    r"(?P<number>\d{1,3})\s*(?:[.:—–-]|$)",
    re.IGNORECASE,
)


def caption_label(text: str) -> tuple[CaptionKind, int, str] | None:
    """Return ``(kind, number, canonical label)`` when ``text`` starts a caption."""

    match = _CAPTION.match(text)
    if match is None:
        return None
    if match.group("table"):
        kind: CaptionKind = "table"
        canonical = f"Table {int(match.group('number'))}"
    else:
        kind = "figure"
        canonical = f"Figure {int(match.group('number'))}"
    return kind, int(match.group("number")), canonical


def is_caption(text: str) -> bool:
    return caption_label(text) is not None


__all__ = ["CaptionKind", "caption_label", "is_caption"]
