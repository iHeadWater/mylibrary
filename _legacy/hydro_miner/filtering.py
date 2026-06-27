from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import date

from .config import AppConfig, RecordTypeConfig
from .models import ExcludedRecord, Record


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s,.;:;，。；：、'\"`’‘“”()\[\]{}\-_/]+", "", text)


def match_people(text: str, config: AppConfig) -> list[str]:
    normalized = normalize_for_match(text)
    matched: list[str] = []
    for canonical, aliases in config.people_allowlist.items():
        for alias in [canonical, *aliases]:
            alias_norm = normalize_for_match(alias)
            if alias_norm and alias_norm in normalized:
                matched.append(canonical)
                break
    return matched


def is_platform_relevant(record: Record, config: AppConfig) -> bool:
    normalized = " ".join([record.title, record.summary, record.raw_text]).casefold()
    return any(keyword.casefold() in normalized for keyword in config.platform_keywords)


def is_year_only_date(record: Record) -> bool:
    return bool(record.dates) and all(d.month == 1 and d.day == 1 for d in record.dates)


def passes_time_rule(record: Record, rule: RecordTypeConfig) -> tuple[bool, list[str]]:
    flags: list[str] = []
    dates = record.dates
    start = rule.time.start_date
    status_hit = any(term in record.status or term in record.raw_text for term in rule.time.status_terms)
    bypass_status_hit = any(
        term in record.status or term in record.raw_text for term in rule.time.status_can_bypass_date_terms
    )

    if dates and any(d >= start for d in dates):
        if is_year_only_date(record) and rule.time.keep_year_only_if_year_at_least:
            flags.append("year_only_date_needs_review")
        return True, flags

    if rule.time.keep_year_only_if_year_at_least and dates:
        if any(d.year >= rule.time.keep_year_only_if_year_at_least for d in dates):
            flags.append("year_only_date_needs_review")
            return True, flags

    if rule.time.date_policy == "coverage_overlap" and dates:
        if max(dates) >= start:
            return True, flags

    if bypass_status_hit and rule.time.date_policy == "record_or_status":
        flags.append("kept_by_status_without_recent_date")
        return True, flags

    if bypass_status_hit and not dates:
        flags.append("kept_by_status_without_date")
        return True, flags

    return False, flags


def score_track(record: Record, config: AppConfig) -> tuple[str, dict[str, int], list[str]]:
    text = record.raw_text.casefold()
    scores = {
        name: sum(1 for keyword in track.keywords if keyword.casefold() in text)
        for name, track in config.tracks.items()
    }
    if not scores or max(scores.values()) == 0:
        return "待判断", scores, ["track_unclear"]
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if len(sorted_scores) > 1 and sorted_scores[0][1] == sorted_scores[1][1]:
        return "待判断", scores, ["track_tie_needs_review"]
    return sorted_scores[0][0], scores, []


def dedupe_key(record: Record) -> str:
    return dedupe_keys(record)[0]


def dedupe_keys(record: Record) -> list[str]:
    title = normalize_for_match(record.title)
    identifier = normalize_for_match(record.identifier)
    keys: list[str] = []
    if record.kind == "project" and title:
        keys.append(f"{record.kind}:title:{title}")
    if identifier:
        keys.append(f"{record.kind}:id:{identifier}")
    if title:
        keys.append(f"{record.kind}:title:{title}")
    if not keys:
        keys.append(f"{record.kind}:source:{record.source.label()}")
    return list(dict.fromkeys(keys))


def merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item and item not in merged:
            merged.append(item)
    return merged


def merge_text(left: str, right: str, separator: str = "、") -> str:
    values = [value.strip() for value in [left, right] if value.strip()]
    if not values:
        return ""
    merged: list[str] = []
    for value in values:
        for part in value.split(separator):
            part = part.strip()
            if part and part not in merged:
                merged.append(part)
    return separator.join(merged)


def merge_dates(left: list[date], right: list[date]) -> list[date]:
    return sorted(set([*left, *right]))


def merge_records(existing: Record, incoming: Record) -> None:
    existing.duplicate_sources.extend(incoming.all_sources())
    existing.people = merge_unique(existing.people, incoming.people)
    existing.matched_people = merge_unique(existing.matched_people, incoming.matched_people)
    existing.dates = merge_dates(existing.dates, incoming.dates)
    existing.date = existing.dates[-1] if existing.dates else existing.date or incoming.date
    existing.status = merge_text(existing.status, incoming.status)
    existing.venue_or_type = merge_text(existing.venue_or_type, incoming.venue_or_type, " / ")
    existing.evidence_links = merge_unique(existing.evidence_links, incoming.evidence_links)
    if incoming.manual_decision:
        existing.manual_decision = merge_text(existing.manual_decision, incoming.manual_decision)
    if incoming.decision_reason:
        existing.decision_reason = merge_text(existing.decision_reason, incoming.decision_reason)
    if incoming.attachment:
        existing.attachment = merge_text(existing.attachment, incoming.attachment)
    if incoming.source_note:
        existing.source_note = merge_text(existing.source_note, incoming.source_note)
    if incoming.added_at and not existing.added_at:
        existing.added_at = incoming.added_at

    if incoming.summary and len(incoming.summary) > len(existing.summary):
        existing.summary = incoming.summary
    if incoming.raw_text and len(incoming.raw_text) > len(existing.raw_text):
        existing.raw_text = incoming.raw_text

    if incoming.identifier and not existing.identifier:
        existing.identifier = incoming.identifier
    elif incoming.identifier and incoming.identifier != existing.identifier:
        existing.identifier = merge_text(existing.identifier, incoming.identifier, "；")
        if "identifier_conflict_needs_review" not in existing.review_flags:
            existing.review_flags.append("identifier_conflict_needs_review")

    if existing.track == "待判断" and incoming.track != "待判断":
        existing.track = incoming.track
    elif incoming.track not in {"", "待判断", existing.track}:
        if "track_conflict_needs_review" not in existing.review_flags:
            existing.review_flags.append("track_conflict_needs_review")

    for name, score in incoming.track_scores.items():
        existing.track_scores[name] = max(existing.track_scores.get(name, 0), score)
    existing.review_flags = merge_unique(existing.review_flags, incoming.review_flags)


def dedupe(records: list[Record]) -> list[Record]:
    by_key: dict[str, Record] = {}
    key_aliases: dict[str, str] = {}
    for record in records:
        keys = dedupe_keys(record)
        primary = next((key_aliases[key] for key in keys if key in key_aliases), keys[0])
        if primary not in by_key:
            by_key[primary] = record
            for key in keys:
                key_aliases[key] = primary
            continue
        existing = by_key[primary]
        merge_records(existing, record)
        for key in keys:
            key_aliases[key] = primary
    return list(by_key.values())


def filter_records(
    records: list[Record], config: AppConfig
) -> tuple[list[Record], list[Record], list[ExcludedRecord]]:
    main: list[Record] = []
    review: list[Record] = []
    excluded: list[ExcludedRecord] = []

    for record in records:
        rule = config.record_types.get(record.kind)
        if rule is None or not rule.enabled:
            excluded.append(ExcludedRecord("record_type_disabled", record.kind, record.source, record.title, record.raw_text))
            continue

        matched = match_people(record.raw_text, config)
        if not matched:
            excluded.append(ExcludedRecord("no_allowlisted_person", record.kind, record.source, record.title, record.raw_text))
            continue

        kept_by_time, time_flags = passes_time_rule(record, rule)
        if not kept_by_time:
            excluded.append(ExcludedRecord("outside_time_rule", record.kind, record.source, record.title, record.raw_text))
            continue

        track, scores, track_flags = score_track(record, config)
        updated = replace(
            record,
            matched_people=matched,
            track=track,
            track_scores=scores,
            review_flags=[*record.review_flags, *time_flags, *track_flags],
        )

        if not is_platform_relevant(updated, config):
            updated.review_flags.append("platform_relevance_needs_review")
            review.append(updated)
            continue
        if updated.track == "待判断":
            review.append(updated)
            continue
        main.append(updated)

    return dedupe(main), dedupe(review), excluded
