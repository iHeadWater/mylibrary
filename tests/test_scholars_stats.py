from __future__ import annotations

from hydrolitagent.scholars.models import IdentityResult, WorksFetch
from hydrolitagent.scholars.stats import person_review_flags, summarize

from scholars_fixtures import make_record


def test_first_author_counts_even_without_corresponding_flag() -> None:
    stats = summarize([make_record(author_position="first", is_corresponding=False)])
    assert stats.paper_count == 1
    assert stats.first_or_corresponding_count == 1
    assert stats.first_author_count == 1
    assert stats.corresponding_author_count == 0


def test_corresponding_only_counts() -> None:
    stats = summarize([make_record(author_position="last", is_corresponding=True)])
    assert stats.first_or_corresponding_count == 1
    assert stats.first_author_count == 0
    assert stats.corresponding_author_count == 1


def test_first_and_corresponding_counts_once() -> None:
    stats = summarize([make_record(author_position="first", is_corresponding=True)])
    assert stats.first_or_corresponding_count == 1
    assert stats.both_count == 1


def test_middle_author_without_corresponding_does_not_count() -> None:
    stats = summarize([make_record(author_position="middle", is_corresponding=False)])
    assert stats.paper_count == 1
    assert stats.first_or_corresponding_count == 0


def test_retracted_included_by_default_and_excluded_variant() -> None:
    works = [
        make_record(work_id="W1", is_retracted=True),
        make_record(work_id="W2", is_corresponding=True, author_position="middle"),
    ]
    stats = summarize(works)
    assert stats.paper_count == 2
    assert stats.first_or_corresponding_count == 2
    assert stats.retracted_count == 1
    assert stats.paper_count_excluding_retracted == 1
    assert stats.first_or_corresponding_count_excluding_retracted == 1


def test_retracted_excluded_when_configured() -> None:
    stats = summarize([make_record(is_retracted=True)], include_retracted_in_total=False)
    assert stats.paper_count == 0
    assert stats.first_or_corresponding_count == 0
    assert stats.retracted_count == 1


def test_year_range_and_empty() -> None:
    stats = summarize(
        [
            make_record(work_id="W1", year=2021, publication_date="2021-01-01"),
            make_record(work_id="W2", year=2025, publication_date="2025-01-01"),
        ]
    )
    assert (stats.year_min, stats.year_max) == (2021, 2025)
    empty = summarize([])
    assert empty.paper_count == 0
    assert empty.year_min is None


def test_review_flags_include_retraction_and_truncation() -> None:
    works = [make_record(is_retracted=True, flags=("corresponding_info_missing_nonfirst",))]
    flags = person_review_flags(
        works,
        IdentityResult(status="resolved", author_ids=("A1",)),
        WorksFetch(total_count=10, truncated=True, truncation_reason="no_api_key_page_limit"),
    )
    assert "retraction_record_present" in flags
    assert "works_truncated" in flags
    assert "corresponding_info_missing_nonfirst" in flags
    assert "works_maybe_incomplete" in flags


def test_review_flags_no_works() -> None:
    flags = person_review_flags([], IdentityResult(status="resolved", author_ids=("A1",)))
    assert "no_works_found" in flags
