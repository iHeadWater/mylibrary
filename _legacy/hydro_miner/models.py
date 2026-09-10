from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SheetData:
    workbook: str
    sheet: str
    rows: list[list[str]]


@dataclass
class SourceRef:
    workbook: str
    sheet: str
    row: int

    def label(self) -> str:
        return f"{self.workbook} / {self.sheet} / row {self.row}"


@dataclass
class Record:
    kind: str
    title: str
    people: list[str]
    matched_people: list[str]
    dates: list[date]
    date: date | None
    status: str
    venue_or_type: str
    identifier: str
    summary: str
    track: str
    source: SourceRef
    evidence_links: list[str] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    raw_text: str = ""
    track_scores: dict[str, int] = field(default_factory=dict)
    duplicate_sources: list[SourceRef] = field(default_factory=list)
    manual_decision: str = ""
    decision_reason: str = ""
    attachment: str = ""
    source_note: str = ""
    added_at: str = ""

    def all_sources(self) -> list[SourceRef]:
        return [self.source, *self.duplicate_sources]


@dataclass
class ExcludedRecord:
    reason: str
    kind: str
    source: SourceRef
    title: str
    raw_text: str
    decision_reason: str = ""
    source_note: str = ""
    added_at: str = ""
