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
    # Three ways a caption label ends, all seen in the wild:
    #   "Fig. 1 | Wadi Derna ..."   pipe (Nature, Communications, Elsevier)
    #   "Figure 3. Disruptions ..." punctuation
    #   "Fig. 1 Pipeline for ..."   no separator, title follows
    # The bare-space form additionally requires the next word to start a title,
    # so body prose such as "Figure 5 shows population-averaged ..." is not
    # mistaken for a caption.
    r"(?P<number>\d{1,3})(?:\s*[.:—–|｜-]|(?=\s+(?-i:[A-Z])|\s*[\u4e00-\u9fff(])|$)",
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
