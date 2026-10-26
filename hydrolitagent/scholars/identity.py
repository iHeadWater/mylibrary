"""同名作者消歧。

原则：显式 ID > ORCID > 姓名+单位；多个候选时只列候选，绝不自动猜。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from .config import IdentitySettings
from .errors import IdentityError
from .models import AuthorCandidate, IdentityResult, PersonQuery
from .openalex import OpenAlexClient
from .roster import normalize_orcid

CJK_RE = re.compile(r"[一-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]")


def normalize_for_match(text: str) -> str:
    """NFKC + casefold + 去标点/空白。

    迁移自 ``_legacy/hydro_miner/filtering.py::normalize_for_match``；
    它仍是本仓库处理中英文姓名变体最稳的归一化方式。
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    return re.sub(r"[\s,.;:;，。；：、'\"`’‘“”()\[\]{}\-_/]+", "", text)


def _tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(token for token in re.split(r"[\s,.;:，。；、\-_/]+", normalized) if token)


def _short_id(value: str | None) -> str:
    text = (value or "").strip()
    return text.rsplit("/", 1)[-1] if text else ""


def _institution_ids(author: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for institution in author.get("last_known_institutions") or []:
        if isinstance(institution, dict) and institution.get("id"):
            ids.add(_short_id(institution["id"]))
    for affiliation in author.get("affiliations") or []:
        if not isinstance(affiliation, dict):
            continue
        institution = affiliation.get("institution") or {}
        if isinstance(institution, dict) and institution.get("id"):
            ids.add(_short_id(institution["id"]))
    return ids


def _last_known_ids(author: dict[str, Any]) -> set[str]:
    return {
        _short_id(institution["id"])
        for institution in author.get("last_known_institutions") or []
        if isinstance(institution, dict) and institution.get("id")
    }


def _institution_names(author: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for institution in author.get("last_known_institutions") or []:
        if isinstance(institution, dict) and institution.get("display_name"):
            names.append(str(institution["display_name"]))
    for affiliation in author.get("affiliations") or []:
        if not isinstance(affiliation, dict):
            continue
        institution = affiliation.get("institution") or {}
        if isinstance(institution, dict) and institution.get("display_name"):
            names.append(str(institution["display_name"]))
    return tuple(dict.fromkeys(names))


def _name_variants(author: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("display_name",):
        if author.get(key):
            values.append(str(author[key]))
    for key in ("display_name_alternatives", "raw_author_names"):
        for item in author.get(key) or []:
            if item:
                values.append(str(item))
    return tuple(dict.fromkeys(values))


def _recent_works(author: dict[str, Any], from_year: int) -> int:
    total = 0
    for item in author.get("counts_by_year") or []:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year") or 0)
        except (TypeError, ValueError):
            continue
        if year >= from_year:
            try:
                total += int(item.get("works_count") or 0)
            except (TypeError, ValueError):
                pass
    return total


def score_candidate(
    author: dict[str, Any],
    query_names: Iterable[str],
    *,
    institution_id: str,
    max_author_works_count: int,
    from_year: int,
    orcid: str = "",
) -> tuple[int, tuple[str, ...]]:
    flags: list[str] = []
    score = 0
    variants = [normalize_for_match(value) for value in _name_variants(author)]
    query_norms = [normalize_for_match(value) for value in query_names if value.strip()]
    best_name_score = 0
    for query_norm in query_norms:
        query_tokens = set(_tokens(query_norm))
        for variant in variants:
            if query_norm == variant:
                best_name_score = max(best_name_score, 50)
                continue
            variant_tokens = set(_tokens(variant))
            if query_tokens and query_tokens == variant_tokens:
                best_name_score = max(best_name_score, 40)
            elif query_tokens and query_tokens <= variant_tokens:
                best_name_score = max(best_name_score, 25)
    score += best_name_score

    institution_ids = _institution_ids(author)
    last_known = _last_known_ids(author)
    if institution_id:
        if institution_id in last_known:
            score += 30
            flags.append("institution_matched")
        elif institution_id in institution_ids:
            score += 15
            flags.append("past_affiliation")
        else:
            flags.append("institution_not_matched")

    candidate_orcid = ""
    if author.get("orcid"):
        try:
            candidate_orcid = normalize_orcid(str(author["orcid"]).replace("https://orcid.org/", ""))
        except Exception:  # noqa: BLE001 - 非法 ORCID 不应中断检索
            candidate_orcid = ""
    if orcid and candidate_orcid and normalize_orcid(orcid) == candidate_orcid:
        score += 10
        flags.append("orcid_matched")

    if _recent_works(author, from_year) > 0:
        score += 10

    try:
        works_count = int(author.get("works_count") or 0)
    except (TypeError, ValueError):
        works_count = 0
    if works_count > max_author_works_count:
        score -= 100
        flags.append("suspected_conflation")

    return score, tuple(dict.fromkeys(flags))


def candidate_from_author(
    author: dict[str, Any],
    *,
    score: int = 0,
    flags: tuple[str, ...] = (),
) -> AuthorCandidate:
    return AuthorCandidate(
        openalex_id=_short_id(author.get("id")),
        display_name=str(author.get("display_name") or ""),
        works_count=int(author.get("works_count") or 0),
        orcid=str(author.get("orcid") or "").replace("https://orcid.org/", ""),
        institutions=_institution_names(author),
        score=score,
        flags=flags,
    )


def _has_latin(value: str) -> bool:
    return bool(LATIN_RE.search(value))


def _merge_ids(candidates: Iterable[AuthorCandidate]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(candidate.openalex_id for candidate in candidates if candidate.openalex_id))


def _resolved_from_candidates(
    candidates: list[AuthorCandidate],
    *,
    confidence: str,
    flags: tuple[str, ...],
    message: str = "",
) -> IdentityResult:
    ordered = sorted(candidates, key=lambda item: (-item.score, item.works_count))
    primary = ordered[0]
    return IdentityResult(
        status="resolved",
        author_ids=_merge_ids(ordered),
        candidate=primary,
        candidates=tuple(ordered),
        confidence=confidence,
        flags=tuple(dict.fromkeys([*flags, *(flag for item in ordered for flag in item.flags)])),
        message=message,
    )


def resolve_identity(
    client: OpenAlexClient,
    query: PersonQuery,
    settings: IdentitySettings,
    *,
    from_year: int,
) -> IdentityResult:
    orcid = ""
    if query.orcid:
        try:
            orcid = normalize_orcid(query.orcid)
        except Exception as exc:  # noqa: BLE001 - 统一转 IdentityError
            raise IdentityError(str(exc)) from exc

    # 1) 显式 OpenAlex ID
    if query.openalex_ids:
        candidates: list[AuthorCandidate] = []
        flags: list[str] = []
        for author_id in query.openalex_ids:
            author = client.get_author(author_id)
            score, candidate_flags = score_candidate(
                author,
                query.all_names,
                institution_id=settings.institution_id,
                max_author_works_count=settings.max_author_works_count,
                from_year=from_year,
                orcid=orcid,
            )
            candidates.append(candidate_from_author(author, score=score, flags=candidate_flags))
        if len(candidates) > 1:
            flags.append("multiple_openalex_profiles")
        if all("institution_not_matched" in candidate.flags for candidate in candidates):
            flags.append("institution_not_matched")
        names = {normalize_for_match(value) for value in query.all_names}
        matched = any(
            normalize_for_match(candidate.display_name) in names for candidate in candidates
        )
        confidence = "high" if matched else "medium"
        if not matched:
            flags.append("explicit_id_name_mismatch")
        return _resolved_from_candidates(candidates, confidence=confidence, flags=tuple(flags))

    # 2) ORCID
    if orcid:
        authors = client.find_authors_by_orcid(orcid)
        if not authors:
            return IdentityResult(
                status="not_found",
                message=f"OpenAlex 没有找到 ORCID {orcid} 对应的作者。",
            )
        candidates = []
        for author in authors:
            score, candidate_flags = score_candidate(
                author,
                query.all_names,
                institution_id=settings.institution_id,
                max_author_works_count=settings.max_author_works_count,
                from_year=from_year,
                orcid=orcid,
            )
            candidates.append(candidate_from_author(author, score=score, flags=candidate_flags))
        flags = ("multiple_openalex_profiles",) if len(candidates) > 1 else ()
        return _resolved_from_candidates(candidates, confidence="high", flags=flags)

    # 3) 姓名
    search_names = [name for name in query.all_names if _has_latin(name)]
    if not search_names:
        raise IdentityError(
            "姓名只有中文，OpenAlex 无法检索；请在名单里补充英文名/别名，或提供 ORCID / OpenAlex ID。"
        )

    def plausible(candidate: AuthorCandidate) -> bool:
        if "suspected_conflation" in candidate.flags:
            return False
        if settings.institution_id and "institution_not_matched" in candidate.flags:
            return False
        return candidate.score >= 25

    def collect(*, past_only: bool) -> dict[str, AuthorCandidate]:
        found: dict[str, AuthorCandidate] = {}
        for name in search_names:
            authors = client.search_authors(
                name,
                institution_id=settings.institution_id,
                include_past=settings.include_past_affiliations,
                past_only=past_only,
                limit=settings.max_candidates,
                works_count_cap=settings.max_author_works_count + 1,
            )
            for author in authors:
                score, candidate_flags = score_candidate(
                    author,
                    query.all_names,
                    institution_id=settings.institution_id,
                    max_author_works_count=settings.max_author_works_count,
                    from_year=from_year,
                    orcid=orcid,
                )
                candidate = candidate_from_author(author, score=score, flags=candidate_flags)
                existing = found.get(candidate.openalex_id)
                if existing is None or candidate.score > existing.score:
                    found[candidate.openalex_id] = candidate
        return found

    by_id = collect(past_only=False)
    if settings.include_past_affiliations and not any(plausible(candidate) for candidate in by_id.values()):
        for key, candidate in collect(past_only=True).items():
            existing = by_id.get(key)
            if existing is None or candidate.score > existing.score:
                by_id[key] = candidate

    ordered = sorted(by_id.values(), key=lambda item: (-item.score, item.works_count))
    plausible_candidates = [candidate for candidate in ordered if plausible(candidate)]

    if not plausible_candidates:
        conflated = [
            candidate
            for candidate in ordered
            if "suspected_conflation" in candidate.flags
            and not (
                settings.institution_id
                and "institution_not_matched" in candidate.flags
            )
        ]
        if conflated:
            return IdentityResult(
                status="ambiguous",
                candidates=tuple(conflated),
                confidence="low",
                flags=("suspected_conflation",),
                message=(
                    "候选作品数超过阈值，疑似 OpenAlex 过度合并；请用 ORCID 或 OpenAlex ID 指定。"
                ),
            )
        # 没加单位过滤再查一次，只为诊断展示，不自动采用
        diagnostic: dict[str, AuthorCandidate] = {}
        for name in search_names:
            for author in client.search_authors(
                name,
                institution_id="",
                include_past=False,
                limit=settings.max_candidates,
                works_count_cap=None,
            ):
                score, candidate_flags = score_candidate(
                    author,
                    query.all_names,
                    institution_id="",
                    max_author_works_count=settings.max_author_works_count,
                    from_year=from_year,
                    orcid=orcid,
                )
                candidate = candidate_from_author(
                    author,
                    score=score,
                    flags=tuple(dict.fromkeys([*candidate_flags, "institution_not_matched"])),
                )
                diagnostic.setdefault(candidate.openalex_id, candidate)
        return IdentityResult(
            status="not_found",
            candidates=tuple(sorted(diagnostic.values(), key=lambda item: -item.score)),
            flags=("institution_not_matched",),
            message=(
                f"未找到同时满足姓名与单位（{settings.institution_name} / {settings.institution_id}）的作者；"
                "候选仅供参考，请用 ORCID 或 OpenAlex ID 指定。"
            ),
        )

    if len(plausible_candidates) > 1:
        shared_orcids = {candidate.orcid for candidate in plausible_candidates}
        if len(shared_orcids) == 1 and "" not in shared_orcids:
            return _resolved_from_candidates(
                plausible_candidates,
                confidence="high",
                flags=("multiple_openalex_profiles",),
                message="多个 OpenAlex profile 共用同一 ORCID，已合并统计。",
            )
        return IdentityResult(
            status="ambiguous",
            candidates=tuple(plausible_candidates),
            confidence="low",
            flags=("multiple_candidates",),
            message="找到多个可能作者，未自动选择；请用 ORCID 或 OpenAlex ID 指定。",
        )

    only = plausible_candidates[0]
    if "suspected_conflation" in only.flags:
        return IdentityResult(
            status="ambiguous",
            candidates=(only,),
            confidence="low",
            flags=("suspected_conflation",),
            message=(
                f"候选作品数 {only.works_count} 超过阈值 {settings.max_author_works_count}，"
                "疑似 OpenAlex 过度合并；请用 ORCID 或 OpenAlex ID 指定。"
            ),
        )
    if settings.auto_resolve_single_candidate:
        return _resolved_from_candidates(
            [only],
            confidence="medium",
            flags=("single_candidate_confirm",),
            message="姓名+单位只命中唯一候选，已自动采用；建议用 ORCID 固化。",
        )
    return IdentityResult(
        status="ambiguous",
        candidates=(only,),
        confidence="low",
        flags=("single_candidate_not_auto",),
        message="只命中一个候选，但配置未允许自动采用；请确认后再跑。",
    )
