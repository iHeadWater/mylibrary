from __future__ import annotations

from typing import Any, Iterable

from hydrolitagent.scholars.models import (
    AuthorCandidate,
    IdentityResult,
    PersonQuery,
    PersonResult,
    PersonStats,
    WorkRecord,
)

INSTITUTION = "I27357992"


def author_payload(
    author_id: str = "A1",
    *,
    name: str = "Zhang San",
    works_count: int = 10,
    orcid: str = "",
    institution_ids: Iterable[str] = (INSTITUTION,),
    past_institution_ids: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/{author_id}",
        "display_name": name,
        "display_name_alternatives": [name],
        "raw_author_names": [name],
        "orcid": f"https://orcid.org/{orcid}" if orcid else None,
        "works_count": works_count,
        "cited_by_count": 0,
        "counts_by_year": [{"year": 2024, "works_count": 3}],
        "last_known_institutions": [
            {"id": f"https://openalex.org/{value}", "display_name": value}
            for value in institution_ids
        ],
        "affiliations": [
            {
                "institution": {"id": f"https://openalex.org/{value}", "display_name": value},
                "years": [2024],
            }
            for value in past_institution_ids
        ],
    }


def work_payload(
    work_id: str = "W1",
    *,
    title: str = "A paper",
    year: int | None = 2024,
    publication_date: str | None = "2024-01-01",
    work_type: str = "article",
    author_ids: Iterable[str] = ("A1",),
    positions: Iterable[str] | None = None,
    corresponding_ids: Iterable[str] = (),
    is_retracted: bool = False,
    truncated: bool = False,
    institutions: Iterable[str] = (INSTITUTION,),
    doi: str = "10.1000/test",
) -> dict[str, Any]:
    ids = list(author_ids)
    pos_list = list(positions) if positions is not None else [
        "first" if index == 0 else "middle" for index in range(len(ids))
    ]
    corresponding = set(corresponding_ids)
    authorships = []
    for index, author_id in enumerate(ids):
        authorships.append(
            {
                "author": {
                    "id": f"https://openalex.org/{author_id}",
                    "display_name": f"Author {author_id}",
                },
                "author_position": pos_list[index] if index < len(pos_list) else "middle",
                "is_corresponding": author_id in corresponding,
                "institutions": [
                    {"id": f"https://openalex.org/{value}", "display_name": value}
                    for value in institutions
                ],
                "raw_author_name": f"Author {author_id}",
                "raw_affiliation_strings": [],
            }
        )
    return {
        "id": f"https://openalex.org/{work_id}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "display_name": title,
        "publication_year": year,
        "publication_date": publication_date,
        "type": work_type,
        "is_retracted": is_retracted,
        "is_authors_truncated": truncated,
        "authorships": authorships,
        "corresponding_author_ids": [
            f"https://openalex.org/{value}" for value in corresponding
        ],
        "primary_location": {"source": {"display_name": "Test Journal"}},
    }


def make_record(
    *,
    person_name: str = "张三",
    author_id: str = "A1",
    work_id: str = "W1",
    title: str = "A paper",
    year: int | None = 2024,
    publication_date: str = "2024-01-01",
    work_type: str = "article",
    doi: str = "10.1000/test",
    author_position: str = "first",
    is_first_author: bool | None = None,
    is_corresponding: bool = False,
    is_retracted: bool = False,
    authors: tuple[str, ...] = ("Author A1",),
    institution_matched: bool = True,
    flags: tuple[str, ...] = (),
) -> WorkRecord:
    first = author_position == "first" if is_first_author is None else is_first_author
    return WorkRecord(
        person_name=person_name,
        author_id=author_id,
        work_id=work_id,
        title=title,
        year=year,
        publication_date=publication_date,
        work_type=work_type,
        venue="Test Journal",
        doi=doi,
        author_position=author_position,
        is_first_author=first,
        is_corresponding=is_corresponding,
        counts_for_form=first or is_corresponding,
        is_retracted=is_retracted,
        authors=authors,
        author_institutions=(INSTITUTION,),
        institution_matched=institution_matched,
        flags=flags,
        url=f"https://openalex.org/{work_id}",
    )


def make_person(name: str = "张三", *, index: int = 1, **kwargs: Any) -> PersonQuery:
    return PersonQuery(name=name, index=index, **kwargs)


def make_result(
    *,
    name: str = "张三",
    status: str = "ok",
    days: int = 0,
    works: tuple[WorkRecord, ...] = (),
    identity_status: str = "resolved",
    message: str = "",
    **query_kwargs: Any,
) -> PersonResult:
    identity = IdentityResult(
        status=identity_status,
        author_ids=("A1",) if identity_status == "resolved" else (),
        candidate=AuthorCandidate(openalex_id="A1", display_name="Zhang San") if identity_status == "resolved" else None,
        message=message,
    )
    stats = PersonStats(
        paper_count=len(works),
        first_or_corresponding_count=sum(1 for work in works if work.counts_for_form),
        fetched_count=len(works),
    )
    return PersonResult(
        query=make_person(name, **query_kwargs),
        identity=identity,
        stats=stats,
        works=works,
        status=status,
        error=None if status == "ok" else message,
    )
