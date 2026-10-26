"""把 OpenAlex work 转成 ``WorkRecord``。

只做字段提取与本人 authorship 判定；去重与计数在 dedupe/stats。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Sequence

from .config import ScholarsConfig
from .models import PersonQuery, WorkRecord
from .openalex import OpenAlexClient


def _short_id(value: str | None) -> str:
    text = (value or "").strip()
    return text.rsplit("/", 1)[-1] if text else ""


def _doi(value: str | None) -> str:
    text = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()


def _work_date(work: dict[str, Any]) -> tuple[date | None, int | None, tuple[str, ...]]:
    flags: list[str] = []
    raw = work.get("publication_date")
    if raw:
        try:
            return date.fromisoformat(str(raw)), None, ()
        except ValueError:
            pass
    year = work.get("publication_year")
    if year:
        try:
            parsed = int(year)
        except (TypeError, ValueError):
            return None, None, ("missing_publication_date",)
        flags.append("year_only_date")
        return date(parsed, 1, 1), parsed, tuple(flags)
    return None, None, ("missing_publication_date",)


def _venue(work: dict[str, Any]) -> str:
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    if isinstance(source, dict):
        return str(source.get("display_name") or "")
    return ""


def _authors(work: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        name = authorship.get("raw_author_name") or (authorship.get("author") or {}).get("display_name")
        if name:
            names.append(str(name))
    return tuple(names)


def _authorship_institutions(authorship: dict[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for institution in authorship.get("institutions") or []:
        if isinstance(institution, dict) and institution.get("id"):
            ids.append(_short_id(institution["id"]))
    return tuple(dict.fromkeys(ids))


def _matching_authorships(work: dict[str, Any], author_ids: set[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        if _short_id(author.get("id")) in author_ids:
            matches.append(authorship)
    return matches


def _corresponding_ids(work: dict[str, Any]) -> set[str]:
    return {_short_id(value) for value in work.get("corresponding_author_ids") or [] if value}


def _expand_truncated(
    client: OpenAlexClient,
    work: dict[str, Any],
    *,
    remaining: int,
) -> tuple[dict[str, Any], bool]:
    if remaining <= 0:
        return work, False
    work_id = _short_id(work.get("id"))
    if not work_id:
        return work, False
    try:
        expanded = client.get_work(work_id)
    except Exception:  # noqa: BLE001 - 展开失败不应中断整批
        return work, False
    return expanded, True


def record_from_work(
    work: dict[str, Any],
    query: PersonQuery,
    author_ids: Sequence[str],
    config: ScholarsConfig,
    *,
    client: OpenAlexClient | None = None,
    expand_remaining: int = 5,
) -> tuple[WorkRecord | None, int]:
    """返回 (记录或 None, 本次消耗的展开次数)。"""
    targets = {_short_id(value) for value in author_ids if value}
    if not targets:
        return None, 0

    expanded_count = 0
    matches = _matching_authorships(work, targets)
    truncated = bool(work.get("is_authors_truncated"))
    if not matches and truncated and client is not None:
        work, expanded_count = _expand_truncated(client, work, remaining=expand_remaining)
        matches = _matching_authorships(work, targets)
        truncated = bool(work.get("is_authors_truncated"))

    work_date, year, date_flags = _work_date(work)
    if work_date is None:
        return None, expanded_count
    if work_date < config.query.from_date:
        return None, expanded_count
    if config.query.to_date is not None and work_date > config.query.to_date:
        return None, expanded_count

    work_type = str(work.get("type") or "")
    if config.query.work_types and work_type not in config.query.work_types:
        return None, expanded_count

    flags: list[str] = list(date_flags)
    corresponding_ids = _corresponding_ids(work)
    has_any_corresponding = bool(corresponding_ids) or any(
        bool(item.get("is_corresponding"))
        for item in (work.get("authorships") or [])
        if isinstance(item, dict)
    )

    authors = _authors(work)
    author_count = len(authors)
    byline_name = ""
    author_index: int | None = None
    if matches:
        matched = matches[0]
        is_first = any(item.get("author_position") == "first" for item in matches)
        is_corr = any(item.get("is_corresponding") is True for item in matches) or bool(
            targets & corresponding_ids
        )
        position = "first" if is_first else (
            "last" if any(item.get("author_position") == "last" for item in matches) else "middle"
        )
        author_id = _short_id((matched.get("author") or {}).get("id"))
        institutions = _authorship_institutions(matched)
        byline_name = str(
            matched.get("raw_author_name")
            or (matched.get("author") or {}).get("display_name")
            or ""
        )
        for index, authorship in enumerate(work.get("authorships") or [], start=1):
            if authorship is matched:
                author_index = index
                break
    else:
        if truncated:
            # 作者列表被截断，且本人只可能通过 corresponding_author_ids 出现
            is_corr = bool(targets & corresponding_ids)
            is_first = False
            position = "unknown"
            author_id = next(iter(sorted(targets)))
            institutions = ()
            flags.append("authorship_truncated")
            if not is_corr:
                flags.append("authorship_truncated_manual_review")
        else:
            # 理论上 OpenAlex 的 author 过滤已保证存在；没有则记录可疑，不猜
            flags.append("author_not_in_authorship")
            return None, expanded_count

    if not is_first and not has_any_corresponding:
        flags.append("corresponding_info_missing_nonfirst")
    if truncated:
        flags.append("authorship_truncated")

    institution_matched = bool(
        config.identity.institution_id
        and config.identity.institution_id in set(institutions)
    )
    if config.identity.institution_id and not institution_matched:
        flags.append("institution_mismatch_work")

    title = str(work.get("title") or work.get("display_name") or "").strip()
    if not title:
        flags.append("title_missing")
    doi = _doi(work.get("doi"))
    if not doi:
        flags.append("doi_missing")
    venue = _venue(work)
    if not venue:
        flags.append("venue_missing")

    record = WorkRecord(
        person_name=query.name,
        author_id=author_id,
        work_id=_short_id(work.get("id")),
        title=title,
        year=year or work_date.year,
        publication_date=work_date.isoformat(),
        work_type=work_type,
        venue=venue,
        doi=doi,
        author_position=position,
        is_first_author=is_first,
        is_corresponding=is_corr,
        counts_for_form=is_first or is_corr,
        is_retracted=bool(work.get("is_retracted")),
        authors=authors,
        byline_name=byline_name,
        author_index=author_index,
        author_count=author_count,
        author_institutions=institutions,
        institution_matched=institution_matched,
        flags=tuple(dict.fromkeys(flags)),
        url=f"https://openalex.org/{_short_id(work.get('id'))}",
    )
    return record, expanded_count


def collect_records(
    works: Iterable[dict[str, Any]],
    query: PersonQuery,
    author_ids: Sequence[str],
    config: ScholarsConfig,
    *,
    client: OpenAlexClient | None = None,
) -> list[WorkRecord]:
    records: list[WorkRecord] = []
    expand_budget = 5
    for work in works:
        record, used = record_from_work(
            work,
            query,
            author_ids,
            config,
            client=client,
            expand_remaining=expand_budget,
        )
        expand_budget -= used
        if record is not None:
            records.append(record)
    return records
