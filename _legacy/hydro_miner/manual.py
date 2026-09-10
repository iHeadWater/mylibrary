from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from .config import AppConfig, _load_toml, _resolve_path
from .filtering import dedupe, normalize_for_match
from .models import ExcludedRecord, Record, SourceRef
from .normalize import dates_in_text


MANUAL_RESOLVED_FLAGS = {
    "platform_relevance_needs_review",
    "track_unclear",
    "track_tie_needs_review",
}


def _records_from_section(raw: dict[str, Any], section: str) -> list[dict[str, Any]]:
    table = raw.get(section, {})
    if not isinstance(table, dict):
        return []
    records = []
    for key, value in table.items():
        if isinstance(value, dict):
            item = dict(value)
            item["_key"] = str(key)
            records.append(item)
    return records


def load_manual_file(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {"include_overrides": [], "exclude_overrides": [], "supplemental_records": []}
    raw = _load_toml(path)
    return {
        "include_overrides": _records_from_section(raw, "include_overrides"),
        "exclude_overrides": _records_from_section(raw, "exclude_overrides"),
        "supplemental_records": _records_from_section(raw, "supplemental_records"),
    }


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_as_str(item) for item in value if _as_str(item)]
    text = _as_str(value)
    return [text] if text else []


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = _as_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        parsed = dates_in_text(text)
        return parsed[-1] if parsed else None


def _manual_attachment(raw: dict[str, Any], config: AppConfig) -> str:
    attachment = _as_str(raw.get("attachment"))
    if not attachment:
        return ""
    return str(_resolve_path(config.repo_root, attachment))


def _title_matches(rule_title: str, record: Record) -> bool:
    expected = normalize_for_match(rule_title)
    if not expected:
        return True
    title = normalize_for_match(record.title)
    return expected == title or expected in title


def _identifier_matches(rule_identifier: str, record: Record) -> bool:
    expected = normalize_for_match(rule_identifier)
    if not expected:
        return True
    haystack = normalize_for_match(" ".join([record.identifier, record.raw_text]))
    return expected in haystack


def _source_matches(raw: dict[str, Any], record: Record) -> bool:
    sheet = _as_str(raw.get("sheet") or raw.get("source_sheet"))
    row_value = raw.get("row") or raw.get("source_row")
    row = int(row_value) if isinstance(row_value, int) or _as_str(row_value).isdigit() else None
    if not sheet and row is None:
        return True
    for source in record.all_sources():
        if sheet and sheet not in source.sheet:
            continue
        if row is not None and source.row != row:
            continue
        return True
    return False


def record_matches(raw: dict[str, Any], record: Record) -> bool:
    kind = _as_str(raw.get("kind"))
    if kind and kind != record.kind:
        return False

    has_matcher = any(_as_str(raw.get(key)) for key in ["title", "identifier", "sheet", "source_sheet"])
    has_matcher = has_matcher or raw.get("row") is not None or raw.get("source_row") is not None
    if not has_matcher:
        return False

    return (
        _title_matches(_as_str(raw.get("title")), record)
        and _identifier_matches(_as_str(raw.get("identifier")), record)
        and _source_matches(raw, record)
    )


def _first_matching_rule(record: Record, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in rules:
        if record_matches(rule, record):
            return rule
    return None


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item and item not in merged:
            merged.append(item)
    return merged


def _manual_decision(raw: dict[str, Any], value: str) -> dict[str, str]:
    return {
        "manual_decision": value,
        "decision_reason": _as_str(raw.get("decision_reason")),
        "source_note": _as_str(raw.get("source_note")),
        "added_at": _as_str(raw.get("added_at")),
    }


def apply_include_override(record: Record, raw: dict[str, Any], config: AppConfig) -> Record:
    decision = _manual_decision(raw, "include")
    clear_flags = set(_as_str_list(raw.get("clear_flags"))) or MANUAL_RESOLVED_FLAGS
    review_flags = [flag for flag in record.review_flags if flag not in clear_flags]
    review_flags = _merge_unique(review_flags, _as_str_list(raw.get("review_flags")))
    evidence_links = _merge_unique(record.evidence_links, _as_str_list(raw.get("evidence_links")))

    return replace(
        record,
        title=_as_str(raw.get("title_override")) or record.title,
        summary=_as_str(raw.get("summary")) or record.summary,
        track=_as_str(raw.get("track")) or record.track,
        evidence_links=evidence_links,
        review_flags=review_flags,
        manual_decision=decision["manual_decision"],
        decision_reason=decision["decision_reason"],
        attachment=_manual_attachment(raw, config) or record.attachment,
        source_note=decision["source_note"],
        added_at=decision["added_at"],
    )


def make_supplemental_record(raw: dict[str, Any], config: AppConfig) -> Record:
    date_value = _as_date(raw.get("date"))
    dates = [date_value] if date_value else []
    people = _as_str_list(raw.get("people"))
    matched_people = _as_str_list(raw.get("matched_people")) or people
    evidence_links = _as_str_list(raw.get("evidence_links"))
    attachment = _manual_attachment(raw, config)
    text_parts = [
        _as_str(raw.get("title")),
        " ".join(people),
        _as_str(raw.get("status")),
        _as_str(raw.get("venue_or_type")),
        _as_str(raw.get("identifier")),
        _as_str(raw.get("summary")),
        " ".join(evidence_links),
        attachment,
    ]
    decision = _manual_decision(raw, "supplemental")

    return Record(
        kind=_as_str(raw.get("kind")),
        title=_as_str(raw.get("title")),
        people=people,
        matched_people=matched_people,
        dates=dates,
        date=date_value,
        status=_as_str(raw.get("status")),
        venue_or_type=_as_str(raw.get("venue_or_type")),
        identifier=_as_str(raw.get("identifier")),
        summary=_as_str(raw.get("summary")),
        track=_as_str(raw.get("track")) or "待判断",
        source=SourceRef(config.manual_records_path.name, _as_str(raw.get("_key")), 0),
        evidence_links=evidence_links,
        review_flags=_as_str_list(raw.get("review_flags")),
        raw_text=" ".join(part for part in text_parts if part),
        manual_decision=decision["manual_decision"],
        decision_reason=decision["decision_reason"],
        attachment=attachment,
        source_note=decision["source_note"],
        added_at=decision["added_at"],
    )


def _manual_excluded(record: Record, raw: dict[str, Any]) -> ExcludedRecord:
    return ExcludedRecord(
        reason="manual_excluded_for_science_writing",
        kind=record.kind,
        source=record.source,
        title=record.title,
        raw_text=record.raw_text,
        decision_reason=_as_str(raw.get("decision_reason")),
        source_note=_as_str(raw.get("source_note")),
        added_at=_as_str(raw.get("added_at")),
    )


def _remove_excluded(
    records: list[Record],
    rules: list[dict[str, Any]],
    excluded: list[ExcludedRecord],
) -> list[Record]:
    kept = []
    for record in records:
        rule = _first_matching_rule(record, rules)
        if rule:
            excluded.append(_manual_excluded(record, rule))
        else:
            kept.append(record)
    return kept


def apply_manual_records(
    main: list[Record],
    review: list[Record],
    excluded: list[ExcludedRecord],
    config: AppConfig,
) -> tuple[list[Record], list[Record], list[ExcludedRecord]]:
    manual = load_manual_file(config.manual_records_path)
    include_rules = manual["include_overrides"]
    exclude_rules = manual["exclude_overrides"]
    supplements = [make_supplemental_record(raw, config) for raw in manual["supplemental_records"]]

    excluded = list(excluded)
    main = _remove_excluded(main, exclude_rules, excluded)
    review = _remove_excluded(review, exclude_rules, excluded)

    updated_main = []
    for record in main:
        rule = _first_matching_rule(record, include_rules)
        updated_main.append(apply_include_override(record, rule, config) if rule else record)

    remaining_review = []
    for record in review:
        rule = _first_matching_rule(record, include_rules)
        if rule:
            updated_main.append(apply_include_override(record, rule, config))
        else:
            remaining_review.append(record)

    return dedupe([*updated_main, *supplements]), remaining_review, excluded
