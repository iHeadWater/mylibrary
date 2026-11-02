"""Turn machine evidence ids into references a reader can follow.

The theme body is the model's text stored verbatim. An older prompt asked it to
"逐项关联 evidence_id", so a body cites ``EV-86N8CEZ5``; a newer one asks for
author-year. The reading layer rewrites the first mention into a link to the
evidence card and leaves a plain author-year behind, so a reader never has to
decode an id or scroll to a footer to find the paper.

Nothing here is invented: a source with no card, or a same-author-same-year label
the text does not disambiguate, keeps the wording it already had.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from hydrolitagent.cards.application.reading_links import file_link


_EVIDENCE_ID_RE = re.compile(r"EV-([A-Z0-9]{8})")
_PAREN_YEAR_RE = re.compile(r"\s*[（(]\s*(\d{4})[a-z]?\s*[）)]")
_TITLE_QUOTE_RE = re.compile(r"\s*《([^》]+)》")
# Inline code, maths, and an existing link/URL: a reference written inside one
# is literal. Skipping whole Markdown links also keeps the rewrite idempotent --
# a second pass must not nest a fresh link inside the one it already wrote.
_LITERAL_RE = re.compile(
    r"(`+)(?:(?!\1).)*?\1"                    # inline code, any backtick run
    r"|\$\$.*?\$\$"                            # display maths on one line
    r"|\$[^$\n]*\$"                            # inline maths
    r"|!?\[[^\]]*\]\((?:<[^>]*>|[^)\s]*)\)"    # a finished Markdown link/image
    r"|https?://[^\s)>\]}]+"                   # a bare URL
)
SHORT_TITLE_LIMIT = 48
TITLE_OVERLAP_MIN = 8


@dataclass(frozen=True)
class EvidenceLabel:
    """What a reader needs to recognise one source, taken from its card."""

    key: str
    authors: str | None
    year: int | None
    title: str | None
    doi: str | None
    card: Path | None
    ambiguous: bool = False

    @property
    def evidence_id(self) -> str:
        return f"EV-{self.key}"

    @property
    def short_title(self) -> str:
        return short_title(self.title)

    @property
    def name(self) -> str:
        """``Bartlett 等（2016）`` -- what later mentions may shrink to."""

        if self.authors and self.year:
            return f"{self.authors}（{self.year}）"
        if self.authors:
            return self.authors
        if self.short_title:
            return f"《{self.short_title}》"
        return self.evidence_id

    @property
    def display(self) -> str:
        """The first-mention caption: ``Bartlett 等（2016）《Beyond the SCS-CN method》``."""

        if not self.short_title or self.short_title in self.name:
            return self.name
        return f"{self.name}《{self.short_title}》"


def short_title(title: str | None) -> str:
    if not isinstance(title, str):
        return ""
    text = " ".join(title.split())
    head = re.split(r"[:：]", text, maxsplit=1)[0].strip()
    text = head or text
    if len(text) <= SHORT_TITLE_LIMIT:
        return text
    cut = text[:SHORT_TITLE_LIMIT]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;，。；") + "…"


def labels_for_entries(entries: Sequence[dict[str, Any]],
                     card_paths: dict[str, Path]) -> dict[str, EvidenceLabel]:
    """One label per card. Ambiguity is decided per theme, not per library."""

    labels: dict[str, EvidenceLabel] = {}
    for entry in entries:
        key = entry.get("parent_key")
        if not isinstance(key, str):
            continue
        authors = entry.get("authors")
        year = entry.get("year")
        title = entry.get("title")
        doi = entry.get("doi")
        authors = authors if isinstance(authors, str) and authors.strip() else None
        year = year if isinstance(year, int) else None
        labels[key] = EvidenceLabel(
            key=key,
            authors=authors,
            year=year,
            title=title if isinstance(title, str) else None,
            doi=doi if isinstance(doi, str) and doi.strip() else None,
            card=card_paths.get(key),
        )
    return labels


def labels_for_theme(labels: dict[str, EvidenceLabel],
                     readings: Sequence[dict[str, Any]]) -> dict[str, EvidenceLabel]:
    """Mark the labels this theme cannot tell apart by author and year alone.

    Two papers by the same authors in the same year (Bartlett 2016a/2016b) must
    keep the short title -- shrinking them would silently merge two sources.
    Only sources this theme cites can collide in its prose.
    """

    keys = [ref["source"].get("parent_key") for ref in readings
            if isinstance(ref.get("source"), dict)]
    keys = [key for key in keys if isinstance(key, str) and key in labels]
    collisions: dict[tuple[str, int | None], int] = {}
    for key in keys:
        label = labels[key]
        if label.authors and label.year:
            collisions[(label.authors, label.year)] = collisions.get((label.authors, label.year), 0) + 1
    return {
        key: replace(label, ambiguous=bool(
            label.authors and label.year
            and collisions.get((label.authors, label.year), 0) > 1
        ))
        for key, label in labels.items()
    }


def _name_patterns(labels: dict[str, EvidenceLabel]) -> list[tuple[str, re.Pattern[str]]]:
    """Author-year matchers, for bodies written with the newer prompt."""

    patterns: list[tuple[str, re.Pattern[str]]] = []
    for key in sorted(labels):
        label = labels[key]
        if not (label.authors and label.year):
            continue
        patterns.append((key, re.compile(
            re.escape(label.authors) + r"\s*[（(]\s*" + str(label.year) + r"[a-z]?\s*[）)]"
        )))
    return patterns


def humanize_evidence(body: str, labels: dict[str, EvidenceLabel],
                      page_dir: Path) -> tuple[str, list[str]]:
    """Link the first mention of each source and shrink later ones.

    Returns ``(new_body, order)`` where ``order`` lists source keys by first
    mention, so the bibliography follows the prose instead of a sort order.
    Nothing is invented: a source with no card, or a same-author-same-year label
    the text does not disambiguate, keeps the wording it already had.
    """

    if not labels:
        return body, []
    seen: set[str] = set()
    order: list[str] = []
    patterns = _name_patterns(labels)
    lines = body.split("\n")
    fence: str | None = None
    in_math = False
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        marker = _fence_marker(stripped)
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
            # A display-maths block (``$$`` on its own line) runs to the next
            # ``$$``; a single-line ``$$ ... $$`` is handled by _LITERAL_RE.
            if stripped.count("$$") % 2 == 1:
                in_math = True
            continue
        if stripped.startswith("|"):
            continue
        lines[index] = _humanize_line(line, labels, patterns, page_dir, seen, order)
    return "\n".join(lines), order


def _fence_marker(stripped: str) -> str | None:
    """The CommonMark fence that opens this line (triple backtick or tilde)."""

    for marker in ("```", "~~~"):
        if stripped.startswith(marker):
            return marker
    return None


def _humanize_line(line: str, labels: dict[str, EvidenceLabel],
                   patterns: list[tuple[str, re.Pattern[str]]], page_dir: Path,
                   seen: set[str], order: list[str]) -> str:
    """Inline code and maths are literal; only the prose between them is rewritten."""

    result: list[str] = []
    position = 0
    for match in _LITERAL_RE.finditer(line):
        result.append(_humanize_text(line[position:match.start()], labels, patterns,
                                     page_dir, seen, order))
        result.append(match.group(0))
        position = match.end()
    result.append(_humanize_text(line[position:], labels, patterns, page_dir, seen, order))
    return "".join(result)


def _humanize_text(text: str, labels: dict[str, EvidenceLabel],
                   patterns: list[tuple[str, re.Pattern[str]]], page_dir: Path,
                   seen: set[str], order: list[str]) -> str:
    result: list[str] = []
    position = 0
    while position < len(text):
        found = _next_reference(text, position, labels, patterns)
        if found is None:
            break
        key, start, end, from_id = found
        if key is None:
            # Two papers share this author-year and the text names no title:
            # keep the wording, because a link would pick one at random.
            result.append(text[position:end])
            position = end
            continue
        # "与 EV-X 两篇": the space on either side of a Latin token has no place
        # in Chinese prose once the token becomes 作者（年份）.
        if start - 1 >= position and text[start - 1] == " " and start >= 2 and _is_cjk(text[start - 2]):
            start -= 1
        label = labels[key]
        # A same-author-same-year label is only linkable when the text names the
        # paper; otherwise the link would point at a coin flip.
        if not from_id and label.ambiguous and not _title_confirms(text, end, label):
            result.append(text[position:end])
            position = end
            continue
        result.append(text[position:start])
        if key in seen:
            end = _consume_reference_tail(text, end, label)
            caption = label.display if label.ambiguous else label.name
            result.append(caption)
            position = end
            continue
        if label.card is None:
            # Nothing to link to: keep the reference exactly as written.
            result.append(text[start:end])
            position = end
            continue
        end = _consume_reference_tail(text, end, label)
        result.append(file_link(label.display, label.card, page_dir))
        seen.add(key)
        order.append(key)
        position = end
    result.append(text[position:])
    return "".join(result)


def _next_reference(text: str, position: int, labels: dict[str, EvidenceLabel],
                    patterns: list[tuple[str, re.Pattern[str]]]) -> tuple[str | None, int, int, bool] | None:
    """The earliest evidence reference at or after ``position``.

    The fourth item says the match came from an ``EV-`` id, which is exact and
    therefore linkable even when two papers share an author and a year. A
    ``None`` key means two author-year labels match at the same place and the
    text names neither title: the caller leaves it verbatim instead of guessing.
    """

    candidates: list[tuple[str, int, int, bool]] = []
    for match in _EVIDENCE_ID_RE.finditer(text, position):
        key = match.group(1)
        if key in labels:
            candidates.append((key, match.start(), match.end(), True))
            break
    for key, pattern in patterns:
        match = pattern.search(text, position)
        if match is not None:
            candidates.append((key, match.start(), match.end(), False))
    if not candidates:
        return None
    earliest = min(candidate[1] for candidate in candidates)
    at = [candidate for candidate in candidates if candidate[1] == earliest]
    exact = [candidate for candidate in at if candidate[3]]
    if exact:
        # An exact id wins a tie: it names one source unambiguously.
        return exact[0]
    if len({candidate[0] for candidate in at}) == 1:
        return at[0]
    confirmed = [candidate for candidate in at
                 if _title_confirms(text, candidate[2], labels[candidate[0]])]
    if len(confirmed) == 1:
        return confirmed[0]
    return (None, at[0][1], max(candidate[2] for candidate in at), False)


def _title_confirms(text: str, end: int, label: EvidenceLabel) -> bool:
    match = _TITLE_QUOTE_RE.match(text, end)
    return bool(match and _same_title(match.group(1), label.title))


def _consume_reference_tail(text: str, end: int, label: EvidenceLabel) -> int:
    """Eat a redundant year or an adjacent title the new caption already carries."""

    if label.year is not None:
        match = _PAREN_YEAR_RE.match(text, end)
        if match and int(match.group(1)) == label.year:
            end = match.end()
    match = _TITLE_QUOTE_RE.match(text, end)
    if match and _same_title(match.group(1), label.title):
        end = match.end()
    # Chinese prose does not space around a reference; the model often writes
    # "EV-X 的..." because the id is Latin.
    if end < len(text) and text[end] == " " and end + 1 < len(text) and _is_cjk(text[end + 1]):
        end += 1
    return end


def _is_cjk(character: str) -> bool:
    code = ord(character)
    return (
        0x3000 <= code <= 0x303F      # CJK punctuation
        or 0x3400 <= code <= 0x4DBF   # extension A
        or 0x4E00 <= code <= 0x9FFF   # unified ideographs
        or 0xF900 <= code <= 0xFAFF   # compatibility ideographs
        or 0xFF00 <= code <= 0xFFEF   # full-width forms
    )


def _same_title(quoted: str, title: str | None) -> bool:
    """A quoted 《title》 names this paper, allowing a shortened form."""

    if not isinstance(title, str):
        return False
    left = " ".join(quoted.split()).casefold()
    right = " ".join(title.split()).casefold()
    if len(left) < TITLE_OVERLAP_MIN or len(right) < TITLE_OVERLAP_MIN:
        return False
    return right.startswith(left) or left.startswith(right)


