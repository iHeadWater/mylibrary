"""计数与人员级复核标记。纯函数，便于单测。"""

from __future__ import annotations

from typing import Iterable

from .models import IdentityResult, PersonStats, WorkRecord, WorksFetch


def summarize(
    works: Iterable[WorkRecord],
    *,
    include_retracted_in_total: bool = True,
) -> PersonStats:
    items = list(works)
    retracted = [work for work in items if work.is_retracted]
    kept = items if include_retracted_in_total else [work for work in items if not work.is_retracted]
    kept_not_retracted = [work for work in items if not work.is_retracted]

    years = [work.year for work in items if work.year]
    return PersonStats(
        paper_count=len(kept),
        first_or_corresponding_count=sum(1 for work in kept if work.counts_for_form),
        first_author_count=sum(1 for work in kept if work.is_first_author),
        corresponding_author_count=sum(1 for work in kept if work.is_corresponding),
        both_count=sum(1 for work in kept if work.is_first_author and work.is_corresponding),
        retracted_count=len(retracted),
        paper_count_excluding_retracted=len(kept_not_retracted),
        first_or_corresponding_count_excluding_retracted=sum(
            1 for work in kept_not_retracted if work.counts_for_form
        ),
        year_min=min(years) if years else None,
        year_max=max(years) if years else None,
        fetched_count=len(items),
        truncated=False,
    )


def person_review_flags(
    works: Iterable[WorkRecord],
    identity: IdentityResult,
    fetch: WorksFetch | None = None,
) -> tuple[str, ...]:
    items = list(works)
    flags: list[str] = list(identity.flags)
    if fetch is not None:
        if fetch.truncated:
            flags.append("works_truncated")
            if fetch.truncation_reason:
                flags.append(fetch.truncation_reason)
        if fetch.total_count is not None and fetch.total_count > len(items):
            flags.append("works_maybe_incomplete")
    for work in items:
        flags.extend(work.flags)
        if work.is_retracted:
            flags.append("retraction_record_present")
        if work.duplicate_ids:
            flags.append("duplicate_versions_merged")
        if work.work_type == "preprint":
            flags.append("preprint_only_work")
    if not items:
        flags.append("no_works_found")
    return tuple(dict.fromkeys(flags))
