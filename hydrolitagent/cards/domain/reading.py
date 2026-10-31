"""Reading receipts and the verdicts computed from them.

A runner that claims it read a prepared paper has to prove it. The proof is a
``ReadingReceipt``: the Markdown digest it saw, the integrity canaries it echoed
and the verbatim quotes it used. Python -- never the model -- decides whether
that evidence is acceptable, and records the outcome as a ``VerifiedReading``.

Nothing here performs I/O, calls a model or knows which runner produced the
receipt. ``verified`` means "the program's checks passed"; it never means the
science is correct.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

GroundingErrorCode = Literal[
    "MARKDOWN_SHA_MISMATCH",
    "INCOMPLETE_MARKDOWN_READ",
    "QUOTE_NOT_FOUND",
    "ANCHOR_MISMATCH",
    "QUOTE_TOO_WEAK",
]

GROUNDING_ERROR_CODES: frozenset[str] = frozenset(
    {
        "MARKDOWN_SHA_MISMATCH",
        "INCOMPLETE_MARKDOWN_READ",
        "QUOTE_NOT_FOUND",
        "ANCHOR_MISMATCH",
        "QUOTE_TOO_WEAK",
    }
)

ReadingStatus = Literal["VERIFIED", "PARTIAL"]


class GroundingError(RuntimeError):
    """A reading receipt that cannot be accepted, with a machine-readable code.

    ``detail`` carries structured context (the offending quote index, the
    declared and the found page). It never carries model output or local paths.
    """

    def __init__(
        self, code: str, message: str, *, detail: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail: dict[str, Any] = dict(detail or {})


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _page(value: Any) -> int | None:
    return value if type(value) is int and value >= 1 else None


@dataclass(frozen=True)
class SourceLocation:
    """One verbatim quote the model attributes to one place in the paper."""

    quote: str
    anchor: str | None = None
    pdf_page: int | None = None
    section: str | None = None
    figure: str | None = None
    table: str | None = None


@dataclass(frozen=True)
class ReadingReceipt:
    """What the runner reports about its reading of the prepared Markdown.

    Parsing is deliberately tolerant: a malformed field becomes ``None`` (or an
    empty tuple) so the verifier can reject the receipt with a specific code
    instead of crashing on an unexpected shape.
    """

    markdown_sha256: str | None = None
    read_mode: str | None = None
    model_claimed_status: str | None = None
    model_claimed_pages: tuple[int, ...] = ()
    canaries_seen: tuple[str, ...] = ()
    self_report: str | None = None
    source_locations: tuple[SourceLocation, ...] = ()

    @classmethod
    def from_output(cls, output: Any) -> "ReadingReceipt | None":
        """Decode the model answer's two wire blocks into one receipt.

        The output schema keeps the reading metadata in ``reading_receipt`` and
        the quotes in a top-level ``source_locations`` array, so both must be
        read together. ``None`` means the answer carried no receipt at all.
        """

        if not isinstance(output, Mapping):
            return None
        raw = output.get("reading_receipt")
        if not isinstance(raw, Mapping):
            return None
        merged = dict(raw)
        # The output schema puts the quotes at the top level, so that block is
        # authoritative whenever it is present at all.
        if output.get("source_locations") is not None:
            merged["source_locations"] = output.get("source_locations")
        return cls.from_mapping(merged)

    @classmethod
    def from_mapping(cls, raw: Any) -> "ReadingReceipt | None":
        """Decode a receipt, or return ``None`` when it is not an object."""

        if not isinstance(raw, Mapping):
            return None
        pages = raw.get("model_claimed_pages")
        canaries = raw.get("canaries_seen")
        locations = raw.get("source_locations")
        return cls(
            markdown_sha256=_text(raw.get("markdown_sha256")),
            read_mode=_text(raw.get("read_mode")),
            model_claimed_status=_text(raw.get("model_claimed_status")),
            model_claimed_pages=tuple(
                page for page in (_page(item) for item in pages or ()) if page
            )
            if isinstance(pages, (list, tuple))
            else (),
            canaries_seen=tuple(
                item.strip()
                for item in canaries or ()
                if isinstance(item, str) and item.strip()
            )
            if isinstance(canaries, (list, tuple))
            else (),
            self_report=_text(raw.get("self_report")),
            source_locations=tuple(
                SourceLocation(
                    quote=item.get("quote") if isinstance(item.get("quote"), str) else "",
                    anchor=_text(item.get("anchor")),
                    pdf_page=_page(item.get("pdf_page")),
                    section=_text(item.get("section")),
                    figure=_text(item.get("figure")),
                    table=_text(item.get("table")),
                )
                for item in locations or ()
                if isinstance(item, Mapping)
            )
            if isinstance(locations, (list, tuple))
            else (),
        )


@dataclass(frozen=True)
class QuoteVerdict:
    """Outcome of checking one quote against the prepared Markdown.

    ``pages`` lists every page the quote can be attributed to: the pages whose
    prose contains it, or both sides of a page break the quote straddles. A
    sentence can legitimately repeat (abstract and body, results and
    conclusion), so a page claim is satisfied when the declared page is *one of*
    them.
    """

    ok: bool
    reason: str | None
    page: int | None
    pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class AnchorConflict:
    """A quote that exists, but not on the page the model claimed."""

    location_index: int
    declared_page: int
    found_page: int


@dataclass(frozen=True)
class VerifiedReading:
    """Program-computed reading evidence, ready to be written into a draft."""

    status: ReadingStatus
    read_mode: str | None
    model_claimed_status: str | None
    verified_pages: tuple[int, ...]
    verified_quotes: int
    quote_coverage: float
    canaries_ok: bool
    min_coverage: float
    anchor_conflicts: tuple[AnchorConflict, ...] = ()
    self_report: str | None = None
    # Pages that carry quotable prose and therefore count towards coverage. A
    # page outside this set (a full-page figure, a reference list) can be
    # mentioned by the card body without evidence, because there is none to
    # quote there (#65).
    content_pages: tuple[int, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status == "VERIFIED"

    @property
    def full_read_verified(self) -> bool:
        """Coverage is the only completeness evidence the program can compute."""

        return self.verified

    @property
    def scientific_correctness_verified(self) -> bool:
        """Reserved: only a human review may ever set this to true."""

        return False

    def as_dict(self) -> dict[str, Any]:
        """Wire projection used inside ``source_access.reading``."""

        return {
            "read_mode": self.read_mode,
            "model_claimed_status": self.model_claimed_status,
            "verified_pages": list(self.verified_pages),
            "verified_quotes": self.verified_quotes,
            "quote_coverage": self.quote_coverage,
            "canaries_ok": self.canaries_ok,
            # A quote that exists on another page is excluded from the evidence
            # and listed here; it never counts toward coverage.
            "anchor_conflicts": [
                {
                    "location_index": conflict.location_index,
                    "declared_page": conflict.declared_page,
                    "found_page": conflict.found_page,
                }
                for conflict in self.anchor_conflicts
            ],
            "content_pages": list(self.content_pages),
            "verified": self.verified,
            "full_read_verified": self.full_read_verified,
            "scientific_correctness_verified": self.scientific_correctness_verified,
        }


@dataclass(frozen=True)
class ReadingCoverage:
    """How far the answer's quotes got towards proving a full read.

    Reported even when the run is rejected: a repair step has to know that
    fixing one quote still leaves the card below ``min_coverage``, otherwise it
    spends a whole round discovering that.
    """

    min_coverage: float
    required_pages: int
    quote_coverage: float = 0.0
    covered_pages: tuple[int, ...] = ()
    missing_pages: tuple[int, ...] = ()
    total_quotes: int = 0
    verified_quotes: int = 0
    failed_quotes: int = 0

    @property
    def satisfied(self) -> bool:
        """Reached the threshold with every quote valid -- the only honest pass."""

        return self.failed_quotes == 0 and self.quote_coverage >= self.min_coverage

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_coverage": self.min_coverage,
            "required_pages": self.required_pages,
            "quote_coverage": self.quote_coverage,
            "covered_pages": list(self.covered_pages),
            "missing_pages": list(self.missing_pages),
            "total_quotes": self.total_quotes,
            "verified_quotes": self.verified_quotes,
            "failed_quotes": self.failed_quotes,
            "satisfied": self.satisfied,
        }


__all__ = [
    "GROUNDING_ERROR_CODES",
    "AnchorConflict",
    "GroundingError",
    "GroundingErrorCode",
    "QuoteVerdict",
    "ReadingCoverage",
    "ReadingReceipt",
    "ReadingStatus",
    "SourceLocation",
    "VerifiedReading",
]
