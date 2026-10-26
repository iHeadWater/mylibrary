from __future__ import annotations

from hydrolitagent.scholars.dedupe import dedupe_works, normalize_doi, normalize_title

from scholars_fixtures import make_record


def test_normalize_doi_and_title() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_title(" A  Paper! ") == "apaper"


def test_same_doi_merges() -> None:
    works = [
        make_record(work_id="W1", doi="10.1000/x"),
        make_record(work_id="W2", doi="https://doi.org/10.1000/X", title="Different title"),
    ]
    merged, _ = dedupe_works(works)
    assert len(merged) == 1
    assert merged[0].duplicate_ids == ("W2",)


def test_preprint_and_article_merge_prefers_article() -> None:
    works = [
        make_record(work_id="W1", work_type="preprint", doi="10.1000/pre", year=2023),
        make_record(work_id="W2", work_type="article", doi="10.1000/pub", year=2024),
    ]
    merged, _ = dedupe_works(works)
    assert len(merged) == 1
    assert merged[0].work_type == "article"
    assert "preprint_merged" in merged[0].flags


def test_same_title_different_first_author_not_merged() -> None:
    works = [
        make_record(work_id="W1", authors=("Alice",), doi="10.1000/a"),
        make_record(work_id="W2", authors=("Bob",), doi="10.1000/b"),
    ]
    merged, _ = dedupe_works(works)
    assert len(merged) == 2


def test_year_tolerance_prevents_far_apart_merge() -> None:
    works = [
        make_record(work_id="W1", year=2021, publication_date="2021-01-01", doi=""),
        make_record(work_id="W2", year=2025, publication_date="2025-01-01", doi=""),
    ]
    merged, _ = dedupe_works(works)
    assert len(merged) == 2


def test_version_position_differs_is_flagged() -> None:
    works = [
        make_record(work_id="W1", work_type="preprint", doi="", author_position="middle", year=2023),
        make_record(work_id="W2", work_type="article", doi="", author_position="first", year=2023),
    ]
    merged, _ = dedupe_works(works)
    assert len(merged) == 1
    assert "version_position_differs" in merged[0].flags


def test_retraction_merges_as_any() -> None:
    works = [
        make_record(work_id="W1", is_retracted=False),
        make_record(work_id="W2", doi="10.1000/test", is_retracted=True),
    ]
    merged, _ = dedupe_works(works)
    assert len(merged) == 1
    assert merged[0].is_retracted is True
