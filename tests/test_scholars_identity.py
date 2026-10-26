from __future__ import annotations

import pytest

from hydrolitagent.scholars.config import IdentitySettings
from hydrolitagent.scholars.errors import IdentityError
from hydrolitagent.scholars.identity import resolve_identity
from hydrolitagent.scholars.models import PersonQuery

from scholars_fixtures import INSTITUTION, author_payload

SETTINGS = IdentitySettings(
    institution_id=INSTITUTION,
    institution_name="大连理工大学",
    max_author_works_count=3000,
)


class FakeClient:
    def __init__(
        self,
        *,
        search_results=None,
        past_results=None,
        orcid_results=None,
        by_id=None,
    ) -> None:
        self.search_results = search_results or []
        self.past_results = past_results or []
        self.orcid_results = orcid_results or []
        self.by_id = by_id or {}

    def search_authors(self, search, *, past_only=False, **kwargs):
        return list(self.past_results if past_only else self.search_results)

    def find_authors_by_orcid(self, orcid):
        return list(self.orcid_results)

    def get_author(self, author_id):
        return self.by_id[author_id]


def test_explicit_openalex_id_resolves() -> None:
    client = FakeClient(by_id={"A1": author_payload("A1", name="Zhang San")})
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",), openalex_ids=("A1",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "resolved"
    assert result.author_ids == ("A1",)
    assert result.confidence == "high"


def test_explicit_id_name_mismatch_lowers_confidence() -> None:
    client = FakeClient(by_id={"A1": author_payload("A1", name="Someone Else")})
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",), openalex_ids=("A1",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "resolved"
    assert result.confidence == "medium"
    assert "explicit_id_name_mismatch" in result.flags


def test_chinese_only_name_raises() -> None:
    with pytest.raises(IdentityError):
        resolve_identity(
            FakeClient(),
            PersonQuery(name="张三"),
            SETTINGS,
            from_year=2021,
        )


def test_single_candidate_resolves_medium() -> None:
    client = FakeClient(search_results=[author_payload("A1", name="Zhang San")])
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "resolved"
    assert result.confidence == "medium"
    assert "single_candidate_confirm" in result.flags


def test_multiple_candidates_are_ambiguous() -> None:
    client = FakeClient(
        search_results=[
            author_payload("A1", name="Zhang San"),
            author_payload("A2", name="Zhang San"),
        ]
    )
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "ambiguous"
    assert len(result.candidates) == 2


def test_suspected_conflation_is_ambiguous() -> None:
    client = FakeClient(
        search_results=[author_payload("A1", name="Zhang San", works_count=5000)]
    )
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "ambiguous"
    assert "suspected_conflation" in result.flags


def test_orcid_multiple_profiles_are_merged() -> None:
    client = FakeClient(
        orcid_results=[
            author_payload("A1", name="Zhang San", orcid="0000-0002-1825-0097"),
            author_payload("A2", name="Zhang San", orcid="0000-0002-1825-0097"),
        ]
    )
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",), orcid="0000-0002-1825-0097"),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "resolved"
    assert set(result.author_ids) == {"A1", "A2"}
    assert "multiple_openalex_profiles" in result.flags


def test_past_affiliation_fallback() -> None:
    client = FakeClient(
        search_results=[],
        past_results=[
            author_payload(
                "A1",
                name="Zhang San",
                institution_ids=(),
                past_institution_ids=(INSTITUTION,),
            )
        ],
    )
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "resolved"
    assert "past_affiliation" in result.flags


def test_no_candidates_is_not_found() -> None:
    result = resolve_identity(
        FakeClient(),
        PersonQuery(name="张三", aliases=("Zhang San",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "not_found"


def test_institution_mismatch_diagnostic_is_not_selected() -> None:
    client = FakeClient(
        search_results=[],
        past_results=[],
    )
    # 诊断查询用空 institution_id 仍返回候选；不能用它自动解析
    client.search_results = []
    client.past_results = []
    result = resolve_identity(
        client,
        PersonQuery(name="张三", aliases=("Zhang San",)),
        SETTINGS,
        from_year=2021,
    )
    assert result.status == "not_found"
