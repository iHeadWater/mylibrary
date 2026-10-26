"""论文去重：DOI 优先，其次标题 + 首作者 + 年份；预印本与正式版合并。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from .models import WorkRecord


def normalize_doi(value: str | None) -> str:
    text = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
    return text.strip().casefold()


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.casefold()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _first_author(work: WorkRecord) -> str:
    if not work.authors:
        return ""
    name = work.authors[0]
    return normalize_title(name)


def _title_key(work: WorkRecord) -> tuple[str, str]:
    title = normalize_title(work.title)
    if not title:
        return ("@id", work.work_id)
    return (title, _first_author(work))


def _is_preprint(work: WorkRecord) -> bool:
    return work.work_type == "preprint"


def _compatible(left: WorkRecord, right: WorkRecord, year_tolerance: int) -> bool:
    if left.year and right.year and abs(left.year - right.year) > year_tolerance:
        return False
    if _is_preprint(left) or _is_preprint(right):
        return True
    # 两篇都是正式版：只有一方缺 DOI 时才尝试合并，避免把同题不同论文并掉
    return not left.doi or not right.doi


def _representative(group: list[WorkRecord]) -> WorkRecord:
    def sort_key(work: WorkRecord) -> tuple[int, int, str, str]:
        return (
            1 if _is_preprint(work) else 0,
            0 if work.doi else 1,
            work.publication_date or "",
            work.work_id,
        )

    return sorted(group, key=sort_key)[0]


def _merge_group(group: list[WorkRecord]) -> WorkRecord:
    representative = _representative(group)
    others = [work for work in group if work.work_id != representative.work_id]
    flags: list[str] = list(representative.flags)
    for work in others:
        flags.extend(work.flags)
        if work.counts_for_form != representative.counts_for_form:
            flags.append("version_position_differs")
    duplicate_ids = tuple(dict.fromkeys(work.work_id for work in others if work.work_id))
    if duplicate_ids and "duplicate_versions_merged" not in flags:
        flags.append("duplicate_versions_merged")
    if others and any(_is_preprint(work) for work in others):
        flags.append("preprint_merged")

    title = representative.title or next((work.title for work in others if work.title), "")
    doi = representative.doi or next((work.doi for work in others if work.doi), "")
    venue = representative.venue or next((work.venue for work in others if work.venue), "")

    return replace(
        representative,
        title=title,
        doi=doi,
        venue=venue,
        is_retracted=any(work.is_retracted for work in group),
        duplicate_ids=duplicate_ids,
        flags=tuple(dict.fromkeys(flags)),
    )


def dedupe_works(
    works: list[WorkRecord],
    *,
    merge_preprints: bool = True,
    year_tolerance: int = 2,
) -> tuple[list[WorkRecord], tuple[str, ...]]:
    if not works:
        return [], ()

    parent = list(range(len(works)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    doi_seen: dict[str, int] = {}
    title_groups: dict[tuple[str, str], list[int]] = {}
    for index, work in enumerate(works):
        doi = normalize_doi(work.doi)
        if doi:
            if doi in doi_seen:
                union(index, doi_seen[doi])
            else:
                doi_seen[doi] = index
        key = _title_key(work)
        for other_index in title_groups.get(key, []):
            if not merge_preprints and (_is_preprint(work) or _is_preprint(works[other_index])):
                continue
            if _compatible(work, works[other_index], year_tolerance):
                union(index, other_index)
        title_groups.setdefault(key, []).append(index)

    grouped: dict[int, list[WorkRecord]] = {}
    for index, work in enumerate(works):
        grouped.setdefault(find(index), []).append(work)

    merged = [_merge_group(group) for group in grouped.values()]
    merged.sort(key=lambda work: (work.publication_date or "", work.title), reverse=True)
    return merged, ()
