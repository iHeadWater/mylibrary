from __future__ import annotations

from hydrolitagent.scholars.collect import record_from_work
from hydrolitagent.scholars.config import ScholarsConfig
from hydrolitagent.scholars.models import PersonQuery

from scholars_fixtures import work_payload

CONFIG = ScholarsConfig()
QUERY = PersonQuery(name="张三", institute="测试所")


def test_first_author_counts() -> None:
    record, _ = record_from_work(
        work_payload(author_ids=("A1",), positions=("first",)),
        QUERY,
        ["A1"],
        CONFIG,
    )
    assert record is not None
    assert record.is_first_author is True
    assert record.counts_for_form is True
    assert record.byline_name == "Author A1"
    assert record.author_index == 1
    assert record.author_count == 1


def test_corresponding_only_counts() -> None:
    record, _ = record_from_work(
        work_payload(
            author_ids=("A1", "A2"),
            positions=("first", "last"),
            corresponding_ids=("A2",),
        ),
        QUERY,
        ["A2"],
        CONFIG,
    )
    assert record is not None
    assert record.is_first_author is False
    assert record.is_corresponding is True
    assert record.counts_for_form is True
    assert record.byline_name == "Author A2"
    assert record.author_index == 2
    assert record.author_count == 2


def test_middle_without_corresponding_flagged_not_counted() -> None:
    record, _ = record_from_work(
        work_payload(author_ids=("A1", "A2"), positions=("first", "middle")),
        QUERY,
        ["A2"],
        CONFIG,
    )
    assert record is not None
    assert record.counts_for_form is False
    assert "corresponding_info_missing_nonfirst" in record.flags


def test_date_boundary_included_and_excluded() -> None:
    included, _ = record_from_work(
        work_payload(publication_date="2021-01-01", year=2021),
        QUERY,
        ["A1"],
        CONFIG,
    )
    excluded, _ = record_from_work(
        work_payload(publication_date="2020-12-31", year=2020),
        QUERY,
        ["A1"],
        CONFIG,
    )
    assert included is not None
    assert excluded is None


def test_year_only_date_is_included_with_flag() -> None:
    record, _ = record_from_work(
        work_payload(publication_date=None, year=2022),
        QUERY,
        ["A1"],
        CONFIG,
    )
    assert record is not None
    assert record.publication_date == "2022-01-01"
    assert "year_only_date" in record.flags


def test_missing_date_and_year_excluded() -> None:
    record, _ = record_from_work(
        work_payload(publication_date=None, year=None),
        QUERY,
        ["A1"],
        CONFIG,
    )
    assert record is None


def test_type_filter_excludes_preprint() -> None:
    record, _ = record_from_work(
        work_payload(work_type="preprint"),
        QUERY,
        ["A1"],
        CONFIG,
    )
    assert record is None


def test_retraction_flag() -> None:
    record, _ = record_from_work(
        work_payload(is_retracted=True),
        QUERY,
        ["A1"],
        CONFIG,
    )
    assert record is not None
    assert record.is_retracted is True


def test_institution_mismatch_is_flagged_not_dropped() -> None:
    record, _ = record_from_work(
        work_payload(institutions=("I999",)),
        QUERY,
        ["A1"],
        CONFIG,
    )
    assert record is not None
    assert record.institution_matched is False
    assert "institution_mismatch_work" in record.flags


def test_truncated_authorship_uses_corresponding_ids() -> None:
    record, _ = record_from_work(
        work_payload(
            author_ids=("A1",),
            truncated=True,
            corresponding_ids=("A2",),
        ),
        QUERY,
        ["A2"],
        CONFIG,
    )
    assert record is not None
    assert record.is_corresponding is True
    assert record.counts_for_form is True
    assert "authorship_truncated" in record.flags


def test_truncated_without_evidence_is_not_counted() -> None:
    record, _ = record_from_work(
        work_payload(author_ids=("A1",), truncated=True),
        QUERY,
        ["A2"],
        CONFIG,
    )
    assert record is not None
    assert record.counts_for_form is False
    assert "authorship_truncated_manual_review" in record.flags


def test_author_not_in_authorship_returns_none() -> None:
    record, _ = record_from_work(
        work_payload(author_ids=("A1",)),
        QUERY,
        ["A9"],
        CONFIG,
    )
    assert record is None
