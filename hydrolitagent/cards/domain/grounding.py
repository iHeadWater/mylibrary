"""Deterministic grounding of model claims in the prepared Markdown.

The Markdown-first pipeline replaces "the model read the PDF" with checkable
evidence: every fact must point at a verbatim quote, the quote must exist in
``paper.md``, and it must fall inside the character range of the page the model
claims. This module implements those rules as pure functions over text.

Deliberate limits:

* matching is exact after NFKC, case folding, whitespace folding and
  Markdown-marker removal; it is not fuzzy, so a paraphrase fails instead of
  sliding through;
* two layout artifacts are forgiven, because neither changes a word: a word
  hyphenated across a line break (``Typ-`` / ``ically``), and a sentence cut by
  a page break (the page marker and the next page's running header sit inside
  it). Both are repaired symmetrically on both sides of a match, and a quote
  may straddle at most one page break, so neither tolerance can turn a
  paraphrase into a match;
* a quote that only matches a heading, a running header or a HTML comment is
  treated as too weak, because such text is easy to guess without reading;
* canaries are found in the Markdown itself, not in a model-supplied list.

Passing these checks proves the output is *grounded in the prepared text*. It
does not prove the model understood the figures, the equations or the science.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hydrolitagent.cards.domain.paper import PageAnchor
from hydrolitagent.cards.domain.reading import (
    AnchorConflict,
    GroundingError,
    QuoteVerdict,
    ReadingCoverage,
    ReadingReceipt,
    SourceLocation,
    VerifiedReading,
)
from hydrolitagent.cards.domain.violations import Violation, violation_dicts

# A quote must be long enough that it cannot be a lucky heading match. A CJK
# character carries much more information than a Latin letter, so the two
# thresholds differ.
MIN_CJK_CHARACTERS = 12
MIN_TOTAL_CHARACTERS = 24
DEFAULT_MIN_COVERAGE = 0.8

_WHITESPACE = re.compile(r"\s+")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_MARKERS = re.compile(r"[*_`~]")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CANARY = re.compile(r"<!--\s*reading-canary:\s*(c-[0-9a-f]{8})\s*-->")
_PAGE_MARKER = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
_HEADING = re.compile(r"^ {0,3}#{1,6}\s+\S")
_ANCHOR_PAGE = re.compile(r"^(?:[Pp](?:age)?|页)?[\s:#_-]*(\d+)$")
# A hyphen that ends a line: the PDF keeps the hyphen and the line break becomes
# whitespace downstream. Rejoining it is symmetric for both sides of a match.
_SOFT_HYPHEN = re.compile(r"(?<=[^\W\d_])-\s+(?=[^\W\d_])")


def _is_cjk(character: str) -> bool:
    code = ord(character)
    return (
        0x2E80 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x4DBF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
    )


def count_cjk(text: str) -> int:
    return sum(1 for character in text if _is_cjk(character))


def normalize_quote(text: str) -> str:
    """Normalise text for literal comparison with the Markdown.

    NFKC folds full-width and compatibility forms; Markdown emphasis, inline
    code fences, backslash escapes and link targets are removed because they are
    rendering markers, not paper content; whitespace is folded so a quote that
    crosses a line break still matches.
    """

    if not isinstance(text, str):
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _MARKDOWN_LINK.sub(r"\1", normalized)
    normalized = _MARKDOWN_MARKERS.sub("", normalized)
    normalized = normalized.replace("\\", "")
    return _WHITESPACE.sub(" ", normalized).strip()


def search_form(text: str) -> str:
    """Normalise text and repair a word hyphenated across a line break."""

    return _SOFT_HYPHEN.sub("", normalize_quote(text))


def _quote_pattern(normalized: str) -> re.Pattern[str]:
    """Matcher for one normalised quote.

    A hyphen in the quote may stand for no hyphen at all, because a genuine
    compound broken across a line (``rainfall-`` / ``runoff``) is rejoined to
    ``rainfallrunoff`` in the page text. Every other character stays literal, so
    a paraphrase still cannot pass. Case is ignored: a model that lifts a
    fragment out of the middle of a sentence capitalises its first letter, and
    that is not a content difference.
    """

    parts: list[str] = []
    for character in normalized:
        if character == "-":
            parts.append("-?")
        elif character == " ":
            parts.append(" ")
        else:
            parts.append(re.escape(character))
    return re.compile("".join(parts), re.IGNORECASE)


def is_quote_too_short(normalized: str) -> bool:
    """True when a quote is too short to prove that the page was read."""

    if count_cjk(normalized) >= MIN_CJK_CHARACTERS:
        return False
    return len(normalized) < MIN_TOTAL_CHARACTERS


def markdown_sha256(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def expected_canaries(markdown: str) -> tuple[str, ...]:
    """Every canary the converter embedded in this Markdown, in document order."""

    return tuple(dict.fromkeys(_CANARY.findall(markdown)))


def page_markers(markdown: str) -> tuple[int, ...]:
    """Page numbers named by inline page markers; useful for diagnostics."""

    return tuple(int(value) for value in _PAGE_MARKER.findall(markdown))


@dataclass(frozen=True)
class _PageText:
    page: int
    # Normalised prose: comments and empty lines removed, remaining lines joined
    # by a space so a quote spanning a line break still matches.
    joined: str
    # Heading lines dropped. A running header ("Article") sits at the top of
    # every page, so only this text can be joined with the next page's.
    prose: str
    # (normalised line, is_heading) for single-line hits.
    lines: tuple[tuple[str, bool], ...]


class PageIndex:
    """Precomputed searchable text for each page anchor.

    Building this once per document keeps verification linear in the number of
    quotes instead of re-normalising every page for every quote.
    """

    def __init__(self, markdown: str, anchors: Sequence[PageAnchor]) -> None:
        self.pages: tuple[_PageText, ...] = tuple(
            self._page_text(markdown, anchor) for anchor in anchors
        )
        # A sentence that crosses a page break is split by the page marker and
        # by the running header of the next page, so it matches no single page.
        # Joining each adjacent pair of prose texts restores exactly one such
        # boundary; a quote that needs more than one page is still rejected.
        # ``boundary`` is where the left page's prose ends, in the joined text:
        # repairing a hyphen across the break shifts the right side by at most
        # two characters, which ``match.start() < boundary <= match.end()``
        # still brackets correctly.
        self._spans: tuple[tuple[int, int, str, int], ...] = tuple(
            (
                left.page,
                right.page,
                search_form(f"{left.prose} {right.prose}"),
                len(left.prose),
            )
            for left, right in zip(self.pages, self.pages[1:])
            if left.prose and right.prose
        )
        # Whole-document text for the "exists but not on this page" check.
        # Heading lines are dropped: a running header repeats at the top of
        # every page and would otherwise sit inside a sentence that crosses a
        # page break, making a present quote look invented.
        self._normalized_all = search_form(
            " ".join(
                line
                for line in _COMMENT.sub(" ", markdown).splitlines()
                if not _HEADING.match(line)
            )
        )

    @staticmethod
    def _page_text(markdown: str, anchor: PageAnchor) -> _PageText:
        raw = markdown[anchor.char_start:anchor.char_end]
        prose_lines: list[tuple[str, bool]] = []
        for line in raw.splitlines():
            if not line.strip() or not _COMMENT.sub("", line).strip():
                continue
            cleaned = _COMMENT.sub(" ", line)
            normalized = search_form(cleaned)
            if not normalized:
                continue
            prose_lines.append((normalized, bool(_HEADING.match(line))))
        return _PageText(
            page=anchor.page,
            # Join first, then repair: the hyphenation artifact spans two lines.
            joined=search_form(" ".join(normalized for normalized, _ in prose_lines)),
            prose=search_form(
                " ".join(normalized for normalized, is_heading in prose_lines if not is_heading)
            ),
            lines=tuple(prose_lines),
        )

    def locations(self, normalized_quote: str) -> tuple[tuple[int, bool], ...]:
        """(page, matched_in_prose) for every page containing the quote."""

        if not normalized_quote:
            return ()
        pattern = _quote_pattern(normalized_quote)
        found: list[tuple[int, bool]] = []
        for page in self.pages:
            if not page.joined or not pattern.search(page.joined):
                continue
            single_line_hits = [
                is_heading for line, is_heading in page.lines if pattern.search(line)
            ]
            # A quote that only matches heading lines is guessable from a table
            # of contents; a multi-line quote has no single-line hit at all and
            # is therefore treated as prose.
            heading_only = bool(single_line_hits) and all(single_line_hits)
            found.append((page.page, not heading_only))
        return tuple(found)

    def span_pages(self, normalized_quote: str) -> tuple[tuple[int, int], ...]:
        """(left, right) for each adjacent pair the quote genuinely straddles.

        A match lying wholly inside one side proves nothing about the page
        break: it would be a page-local quote interrupted by a heading, which
        ``locations`` already refused. Only a match that starts on the left page
        and ends on the right one crosses the boundary.
        """

        if not normalized_quote:
            return ()
        pattern = _quote_pattern(normalized_quote)
        found: list[tuple[int, int]] = []
        for left, right, text, boundary in self._spans:
            if any(
                match.start() < boundary <= match.end()
                for match in pattern.finditer(text)
            ):
                found.append((left, right))
        return tuple(found)

    def contains_anywhere(self, normalized_quote: str) -> bool:
        if not normalized_quote:
            return False
        return bool(_quote_pattern(normalized_quote).search(self._normalized_all))


def verify_quote(
    quote: Any, markdown: str, anchors: Sequence[PageAnchor]
) -> QuoteVerdict:
    """Check one quote against the Markdown and the page anchors."""

    return _verify_quote(PageIndex(markdown, anchors), quote)


def _verify_quote(index: PageIndex, quote: Any) -> QuoteVerdict:
    if not isinstance(quote, str):
        return QuoteVerdict(False, "QUOTE_TOO_WEAK", None)
    normalized = normalize_quote(quote)
    if not normalized or is_quote_too_short(normalized):
        return QuoteVerdict(False, "QUOTE_TOO_WEAK", None)
    searchable = search_form(quote)
    locations = index.locations(searchable)
    prose_pages = tuple(page for page, in_prose in locations if in_prose)
    if prose_pages:
        return QuoteVerdict(True, None, prose_pages[0], prose_pages)
    if locations:
        return QuoteVerdict(False, "QUOTE_TOO_WEAK", locations[0][0])
    spans = index.span_pages(searchable)
    if spans:
        # The quote is verbatim but crosses one page break. Both pages carry
        # part of it, so a claim of either page is satisfied.
        left, right = spans[0]
        return QuoteVerdict(True, None, left, (left, right))
    if index.contains_anywhere(searchable):
        # Present in the document but outside every page range: the reading
        # order or the anchor map is wrong, not the model's quote.
        return QuoteVerdict(False, "ANCHOR_MISMATCH", None)
    return QuoteVerdict(False, "QUOTE_NOT_FOUND", None)


def declared_page(location: SourceLocation) -> int | None:
    """Page number the model attached to a quote, if it named one."""

    if location.pdf_page is not None:
        return location.pdf_page
    if not location.anchor:
        return None
    match = _ANCHOR_PAGE.match(location.anchor.strip())
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class ReadingAudit:
    """Every grounding problem in one answer, plus the coverage it reached.

    ``reading`` is ``None`` whenever ``violations`` is non-empty: a receipt with
    a bad quote is not evidence, and a caller must not be able to read it as one
    by accident.
    """

    reading: VerifiedReading | None
    violations: tuple[Violation, ...] = ()
    coverage: ReadingCoverage | None = None
    # Legacy fields of the first violation, so the strict entry point keeps the
    # detail its callers already read (``location_index``, ``missing_canaries``).
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.violations


def audit_reading(
    receipt: Any,
    markdown: str,
    anchors: Sequence[PageAnchor],
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> ReadingAudit:
    """Collect every grounding problem instead of raising on the first one.

    A receipt that cannot be parsed, a digest mismatch or missing canaries stop
    the audit immediately: without them the quotes are checked against the wrong
    text, so every later result would be noise. Everything else -- each quote
    and the coverage the answer reaches -- is reported in full, because a repair
    step has to see all of it in one round.
    """

    if not 0.0 <= min_coverage <= 1.0:
        raise ValueError("min_coverage 必须在 0 到 1 之间")
    parsed = (
        ReadingReceipt.from_mapping(receipt)
        if isinstance(receipt, Mapping)
        else receipt if isinstance(receipt, ReadingReceipt) else None
    )
    if parsed is None:
        return _preflight(
            "INCOMPLETE_MARKDOWN_READ",
            "reading_receipt",
            "模型没有返回可解析的阅读回执（reading_receipt）",
        )
    if not anchors:
        return _preflight(
            "INCOMPLETE_MARKDOWN_READ", "paper.md", "转换结果没有页锚点，无法核对阅读范围"
        )
    actual_digest = markdown_sha256(markdown)
    if parsed.markdown_sha256 != actual_digest:
        return _preflight(
            "MARKDOWN_SHA_MISMATCH",
            "reading_receipt.markdown_sha256",
            "模型回显的 paper.md 摘要与本次转换结果不一致",
            actual_digest,
            parsed.markdown_sha256 or "未提供",
            {"declared": parsed.markdown_sha256, "actual": actual_digest},
        )
    expected = expected_canaries(markdown)
    if not expected:
        return _preflight(
            "INCOMPLETE_MARKDOWN_READ",
            "paper.md",
            "转换结果没有完整性 canary，无法证明模型读到了文档首尾",
        )
    seen = set(parsed.canaries_seen)
    missing = [token for token in expected if token not in seen]
    if missing:
        return _preflight(
            "INCOMPLETE_MARKDOWN_READ",
            "reading_receipt.canaries_seen",
            "模型没有回显全部完整性 canary，不能证明读到了全文",
            f"回显全部 {len(expected)} 个",
            "缺 " + "、".join(missing),
            {"missing_canaries": missing},
        )
    if not parsed.source_locations:
        return _preflight(
            "QUOTE_NOT_FOUND", "source_locations", "模型没有给出任何可核对的原文引文"
        )

    index = PageIndex(markdown, anchors)
    verified_pages: set[int] = set()
    conflicts: list[AnchorConflict] = []
    violations: list[Violation] = []
    first_detail: dict[str, Any] = {}
    verified_quotes = 0
    for position, location in enumerate(parsed.source_locations):
        # A location without a quote is rejected by ``_verify_quote`` as too
        # weak. Statements with no location simply omit the entry instead.
        verdict = _verify_quote(index, location.quote)
        if not verdict.ok or verdict.page is None:
            if not first_detail:
                first_detail = {
                    "location_index": position,
                    "quote_length": len(normalize_quote(location.quote)),
                    "declared_page": declared_page(location),
                    "found_page": verdict.page,
                }
            expected_text, actual_text = _quote_expectation(verdict, location)
            violations.append(
                Violation(
                    verdict.reason or "QUOTE_NOT_FOUND",
                    f"source_locations[{position}]",
                    _quote_message(verdict.reason, position),
                    expected_text,
                    actual_text,
                )
            )
            continue
        claimed = declared_page(location)
        if claimed is not None and claimed not in verdict.pages:
            # The quote is real but the page label is wrong. It is excluded from
            # the evidence -- it proves nothing about the claimed page -- and
            # recorded as a conflict instead of discarding the whole run.
            conflicts.append(
                AnchorConflict(
                    location_index=position,
                    declared_page=claimed,
                    found_page=verdict.page,
                )
            )
            continue
        verified_pages.add(claimed if claimed is not None else verdict.page)
        verified_quotes += 1

    coverage = _coverage(
        anchors,
        verified_pages,
        min_coverage=min_coverage,
        total_quotes=len(parsed.source_locations),
        verified_quotes=verified_quotes,
        failed_quotes=len(violations),
    )
    if violations:
        return ReadingAudit(None, tuple(violations), coverage, first_detail)
    status = "VERIFIED" if coverage.satisfied else "PARTIAL"
    return ReadingAudit(
        VerifiedReading(
            status=status,
            read_mode=parsed.read_mode,
            model_claimed_status=parsed.model_claimed_status,
            verified_pages=tuple(sorted(verified_pages)),
            verified_quotes=verified_quotes,
            quote_coverage=coverage.quote_coverage,
            canaries_ok=True,
            min_coverage=min_coverage,
            anchor_conflicts=tuple(conflicts),
            self_report=parsed.self_report,
        ),
        (),
        coverage,
        {},
    )


def verify_reading(
    receipt: Any,
    markdown: str,
    anchors: Sequence[PageAnchor],
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> VerifiedReading:
    """Accept or reject a runner's reading receipt.

    Raises ``GroundingError`` on a hard failure (digest, canaries, any quote) and
    carries the full violation list in ``detail["violations"]``. Returns a
    ``VerifiedReading`` whose ``status`` is ``PARTIAL`` when fewer than
    ``min_coverage`` of the body pages are backed by a verified quote.
    """

    audit = audit_reading(receipt, markdown, anchors, min_coverage=min_coverage)
    if audit.violations:
        raise _grounding_error(audit)
    assert audit.reading is not None  # no violations means the audit built one
    return audit.reading


def _preflight(
    code: str,
    path: str,
    message: str,
    expected: str | None = None,
    actual: str | None = None,
    detail: dict[str, Any] | None = None,
) -> ReadingAudit:
    """A failure that makes the quote checks meaningless, so they are not run."""

    return ReadingAudit(
        None, (Violation(code, path, message, expected, actual),), None, detail or {}
    )


def _coverage(
    anchors: Sequence[PageAnchor],
    verified_pages: set[int],
    *,
    min_coverage: float,
    total_quotes: int,
    verified_quotes: int,
    failed_quotes: int,
) -> ReadingCoverage:
    body_pages = [anchor.page for anchor in anchors if anchor.role == "body"]
    denominator = body_pages or [anchor.page for anchor in anchors]
    covered = tuple(page for page in denominator if page in verified_pages)
    # ``required_pages`` is the smallest count that clears the threshold under
    # the same rounding the status uses, so the number a repair step is told to
    # reach is exactly the number that flips the status.
    required = (
        next(
            (
                count
                for count in range(1, len(denominator) + 1)
                if round(count / len(denominator), 4) >= min_coverage
            ),
            len(denominator),
        )
        if denominator
        else 0
    )
    return ReadingCoverage(
        min_coverage=min_coverage,
        required_pages=required,
        quote_coverage=round(len(covered) / len(denominator), 4) if denominator else 0.0,
        covered_pages=covered,
        missing_pages=tuple(page for page in denominator if page not in verified_pages),
        total_quotes=total_quotes,
        verified_quotes=verified_quotes,
        failed_quotes=failed_quotes,
    )


def _quote_expectation(
    verdict: QuoteVerdict, location: SourceLocation
) -> tuple[str, str]:
    """The comparison a repair step needs to fix one rejected quote.

    The rejected text is quoted back: a model told only "第 32 条找不到" cannot
    tell which of its forty quotes that is, and a real run showed it answering
    with the same invented sentence three attempts in a row.
    """

    quote = normalize_quote(location.quote)
    snippet = quote[:60] + ("…" if len(quote) > 60 else "")
    if verdict.reason == "QUOTE_TOO_WEAK":
        return (
            f"至少 {MIN_TOTAL_CHARACTERS} 字的正文原文（中文至少 {MIN_CJK_CHARACTERS} 字）",
            f"{len(quote)} 字，或只命中标题/页眉：{snippet}",
        )
    if verdict.reason == "ANCHOR_MISMATCH":
        return (
            "引文落在所声称页面的正文范围内",
            f"文档里有这句但不在任何页锚点内（{len(quote)} 字）：{snippet}",
        )
    claimed = declared_page(location)
    where = f"声明第 {claimed} 页" if claimed else "未声明页"
    return ("原文中逐字存在的句子", f"未找到（{where}，{len(quote)} 字）：{snippet}")


def _grounding_error(audit: ReadingAudit) -> GroundingError:
    first = audit.violations[0]
    return GroundingError(
        first.code,
        first.message,
        detail={**audit.detail, "violations": violation_dicts(audit.violations)},
    )


_MESSAGES = {
    "QUOTE_NOT_FOUND": "引文在 paper.md 中找不到；不得引用转换结果之外的内容",
    "ANCHOR_MISMATCH": "引文所在页与页锚点不一致，无法确认它来自所声称的页面",
    "QUOTE_TOO_WEAK": "引文过短或只命中标题/页眉，不能证明该页已被阅读",
}


def _quote_message(reason: str | None, position: int) -> str:
    base = _MESSAGES.get(reason or "", "引文未被接受")
    return f"第 {position + 1} 条引文未通过接地校验：{base}"


__all__ = [
    "DEFAULT_MIN_COVERAGE",
    "ReadingAudit",
    "audit_reading",
    "MIN_CJK_CHARACTERS",
    "MIN_TOTAL_CHARACTERS",
    "PageIndex",
    "count_cjk",
    "declared_page",
    "expected_canaries",
    "is_quote_too_short",
    "markdown_sha256",
    "normalize_quote",
    "page_markers",
    "search_form",
    "verify_quote",
    "verify_reading",
]
