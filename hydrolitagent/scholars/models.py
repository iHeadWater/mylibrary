"""数据模型。

全部使用 frozen dataclass：统计过程只读，避免同名/多作者场景下被就地改写。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class PersonQuery:
    name: str
    institute: str = ""
    aliases: tuple[str, ...] = ()
    orcid: str = ""
    openalex_ids: tuple[str, ...] = ()
    self_check: str = ""
    self_check_note: str = ""
    index: int = 0

    @property
    def all_names(self) -> tuple[str, ...]:
        values = [self.name, *self.aliases]
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorCandidate:
    openalex_id: str
    display_name: str = ""
    works_count: int = 0
    orcid: str = ""
    institutions: tuple[str, ...] = ()
    score: int = 0
    flags: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return f"https://openalex.org/{self.openalex_id}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["url"] = self.url
        return payload


@dataclass(frozen=True)
class IdentityResult:
    status: str  # resolved | ambiguous | not_found | invalid
    author_ids: tuple[str, ...] = ()
    candidate: AuthorCandidate | None = None
    candidates: tuple[AuthorCandidate, ...] = ()
    confidence: str = ""
    flags: tuple[str, ...] = ()
    message: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == "resolved" and bool(self.author_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "author_ids": list(self.author_ids),
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "confidence": self.confidence,
            "flags": list(self.flags),
            "message": self.message,
        }


@dataclass(frozen=True)
class WorkRecord:
    person_name: str
    author_id: str
    work_id: str
    title: str
    year: int | None
    publication_date: str
    work_type: str
    venue: str
    doi: str
    author_position: str
    is_first_author: bool
    is_corresponding: bool
    counts_for_form: bool
    is_retracted: bool
    authors: tuple[str, ...] = ()
    byline_name: str = ""
    author_index: int | None = None
    author_count: int = 0
    author_institutions: tuple[str, ...] = ()
    institution_matched: bool = False
    duplicate_ids: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    source: str = "openalex"
    url: str = ""

    @property
    def count_reason(self) -> str:
        if self.is_first_author and self.is_corresponding:
            return "both"
        if self.is_first_author:
            return "first"
        if self.is_corresponding:
            return "corresponding"
        return "none"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["count_reason"] = self.count_reason
        return payload


@dataclass(frozen=True)
class PersonStats:
    paper_count: int = 0
    first_or_corresponding_count: int = 0
    first_author_count: int = 0
    corresponding_author_count: int = 0
    both_count: int = 0
    retracted_count: int = 0
    paper_count_excluding_retracted: int = 0
    first_or_corresponding_count_excluding_retracted: int = 0
    year_min: int | None = None
    year_max: int | None = None
    fetched_count: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorksFetch:
    works: tuple[dict[str, Any], ...] = ()
    total_count: int | None = None
    pages: int = 0
    request_count: int = 0
    truncated: bool = False
    truncation_reason: str = ""


@dataclass(frozen=True)
class PersonResult:
    query: PersonQuery
    identity: IdentityResult
    stats: PersonStats = field(default_factory=PersonStats)
    works: tuple[WorkRecord, ...] = ()
    review_flags: tuple[str, ...] = ()
    status: str = "ok"  # ok | ambiguous | not_found | failed
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.query.index,
            "query": self.query.to_dict(),
            "identity": self.identity.to_dict(),
            "stats": self.stats.to_dict(),
            "works": [work.to_dict() for work in self.works],
            "review_flags": list(self.review_flags),
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class BatchResult:
    people: tuple[PersonResult, ...] = ()
    generated_at: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(person.status == "ok" for person in self.people)

    def totals(self) -> dict[str, int]:
        return {
            "people": len(self.people),
            "ok": sum(1 for person in self.people if person.status == "ok"),
            "ambiguous": sum(1 for person in self.people if person.status == "ambiguous"),
            "not_found": sum(1 for person in self.people if person.status == "not_found"),
            "failed": sum(1 for person in self.people if person.status == "failed"),
            "paper_count": sum(person.stats.paper_count for person in self.people),
            "first_or_corresponding_count": sum(
                person.stats.first_or_corresponding_count for person in self.people
            ),
            "retracted_count": sum(person.stats.retracted_count for person in self.people),
        }


@dataclass(frozen=True)
class WebCandidate:
    person_name: str
    title: str
    authors: tuple[str, ...] = ()
    source: str = ""
    year: int | None = None
    url: str = ""
    confidence: str = "low"
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def iso_date(value: date | None) -> str:
    return value.isoformat() if value else ""
