"""Escape bare ``<TOKEN>`` literals for the generated reading layer.

The model sometimes writes a placeholder such as ``<CLASS>`` in its prose. A
Markdown reader treats an unknown HTML tag as the start of an HTML block, so
Obsidian Live Preview stops rendering Markdown for every line after it (Reading
view is more tolerant, which makes the flaw look intermittent). The drafts are
hash-bound machine artifacts, so the fix belongs to the generated layer only:
the reader sees ``&lt;CLASS&gt;``, the machine keeps exactly what the model
wrote.
"""
from __future__ import annotations

import re

from hydrolitagent.cards.application.reading_citations import (
    LITERAL_RE,
    fence_marker,
)

# An inline HTML tag the reading layer may pass through unchanged. Anything else
# is a literal the model wrote, not markup.
ALLOWED_TAGS = frozenset({
    "br", "code", "details", "kbd", "mark", "span", "sub", "summary", "sup",
})

_TAG_RE = re.compile(r"<([A-Za-z][A-Za-z0-9_-]*)>")
# A link or image destination: ``[text](<path with spaces>)``. The shared
# literal pattern already covers a whole link, but only when its text is
# bracket-free; the destination is protected on its own as well.
_DESTINATION_RE = re.compile(r"\]\(<[^>\n]*>\)")
# Everything that must survive untouched: inline code, maths, finished links,
# bare URLs, and destinations. Built from the shared pattern so the two layers
# cannot disagree about what is literal.
_PROTECTED_RE = re.compile(
    f"(?:{LITERAL_RE.pattern})|(?:{_DESTINATION_RE.pattern})"
)


def escape_html_like(text: str) -> str:
    """Escape bare ``<NAME>`` tags in prose; leave code, maths and links alone.

    Fenced code blocks (``` and ~~~) and ``$$`` display-maths blocks are copied
    verbatim, matching :func:`reading_citations.humanize_evidence`. The result
    is idempotent: ``&lt;NAME&gt;`` contains no bare ``<``, so a second pass
    cannot escape it again.
    """

    lines = text.split("\n")
    fence: str | None = None
    in_math = False
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        marker = fence_marker(stripped)
        if fence is not None:
            if marker == fence:
                fence = None
            continue
        if marker is not None:
            fence = marker
            continue
        if in_math:
            if stripped.startswith("$$") and stripped.count("$$") % 2 == 1:
                in_math = False
            continue
        if stripped.startswith("$$"):
            # An odd count opens a multi-line display-maths block, whose lines
            # are copied verbatim. An even count is a complete ``$$ ... $$`` on
            # this line: let _escape_line protect the maths span and still
            # escape any prose after it.
            if stripped.count("$$") % 2 == 1:
                in_math = True
                continue
        lines[index] = _escape_line(line)
    return "\n".join(lines)


def _escape_line(line: str) -> str:
    """Escape the prose between protected spans, keeping the spans verbatim."""

    result: list[str] = []
    position = 0
    for match in _PROTECTED_RE.finditer(line):
        result.append(_escape_text(line[position:match.start()]))
        result.append(match.group(0))
        position = match.end()
    result.append(_escape_text(line[position:]))
    return "".join(result)


def _escape_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name.lower() in ALLOWED_TAGS:
            return match.group(0)
        return f"&lt;{name}&gt;"

    return _TAG_RE.sub(replace, text)


__all__ = ["ALLOWED_TAGS", "escape_html_like"]
