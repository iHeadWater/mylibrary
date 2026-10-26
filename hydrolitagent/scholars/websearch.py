"""中文库网页检索与人工补充清单。

网页检索结果只作为低置信度候选，绝不自动计入统计；
人工确认后写进 supplement CSV，才以 source=manual 合入。
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import ScholarsConfig
from .errors import ScholarsError
from .models import PersonQuery, WebCandidate, WorkRecord

SUPPLEMENT_HEADERS = (
    "姓名",
    "标题",
    "年份",
    "期刊",
    "DOI",
    "作者位次",
    "是否通讯",
    "类型",
    "作者",
    "本人署名",
)


def _text(value: str | None) -> str:
    return (value or "").strip()


def _bool(value: str | None) -> bool:
    return _text(value).casefold() in {"是", "true", "1", "yes", "y"}


def _first_author(authors: tuple[str, ...]) -> str:
    return authors[0] if authors else ""


def _author_index(name: str, authors: tuple[str, ...]) -> int | None:
    target = name.strip().casefold()
    for index, author in enumerate(authors, start=1):
        if author.strip().casefold() == target:
            return index
    return None


def load_supplement(path: str | Path) -> dict[str, list[WorkRecord]]:
    """读取人工确认清单，按姓名分组。

    必需列：姓名、标题。其余列可选；没有作者位次/通讯标记时不计入第一通讯，
    并在复核标记中提示补全。
    """
    supplement_path = Path(path)
    if not supplement_path.is_file():
        raise ScholarsError(f"补充清单不存在：{supplement_path}")
    raw = supplement_path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ScholarsError(f"无法识别补充清单编码：{supplement_path}")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        raise ScholarsError("补充清单缺少表头")
    normalized = {name.strip(): name for name in reader.fieldnames if name}
    if "姓名" not in normalized or "标题" not in normalized:
        raise ScholarsError(f"补充清单至少需要「姓名」「标题」两列；当前表头：{reader.fieldnames}")

    grouped: dict[str, list[WorkRecord]] = {}
    for line_no, row in enumerate(reader, start=2):
        name = _text(row.get("姓名"))
        title = _text(row.get("标题"))
        if not name and not title:
            continue
        if not name or not title:
            raise ScholarsError(f"补充清单第 {line_no} 行缺少姓名或标题")
        year_raw = _text(row.get("年份"))
        if not year_raw:
            raise ScholarsError(f"补充清单第 {line_no} 行缺少年份；无法判断是否在统计窗口内")
        try:
            year = int(year_raw)
        except ValueError as exc:
            raise ScholarsError(f"补充清单第 {line_no} 行年份非法：{year_raw!r}") from exc
        authors = tuple(
            part.strip()
            for part in re.split(r"[|;；,，、]+", _text(row.get("作者")))
            if part.strip()
        )
        byline = _text(row.get("本人署名")) or name
        author_index = _author_index(byline, authors)
        position = _text(row.get("作者位次")).casefold()
        if position not in {"first", "middle", "last", "unknown", ""}:
            position = "unknown"
        if not position and author_index:
            if author_index == 1:
                position = "first"
            elif author_index == len(authors):
                position = "last"
            else:
                position = "middle"
        is_corr = _bool(row.get("是否通讯"))
        is_first = position == "first"
        doi = _text(row.get("DOI"))
        work_type = _text(row.get("类型")) or "article"
        flags: list[str] = ["manual_supplement"]
        if not position and not is_corr:
            flags.append("supplement_position_missing")
        digest = hashlib.sha1(f"{name}|{title}|{year}|{doi}".encode("utf-8")).hexdigest()[:12]
        record = WorkRecord(
            person_name=name,
            author_id="manual",
            work_id=f"manual:{digest}",
            title=title,
            year=year,
            publication_date=f"{year:04d}-01-01" if year else "",
            work_type=work_type,
            venue=_text(row.get("期刊")),
            doi=doi,
            author_position=position or "unknown",
            is_first_author=is_first,
            is_corresponding=is_corr,
            counts_for_form=is_first or is_corr,
            is_retracted=False,
            authors=authors,
            byline_name=byline,
            author_index=author_index,
            author_count=len(authors),
            source="manual",
            url=f"https://doi.org/{doi}" if doi else "",
            flags=tuple(flags),
        )
        grouped.setdefault(name, []).append(record)
    return grouped


DEEPSEEK_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"


def _year_from_date(value: str | None) -> int | None:
    text = (value or "").strip()
    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


def _deepseek_queries(
    query: PersonQuery,
    institutions: list[str],
) -> list[str]:
    name = query.name or (query.aliases[0] if query.aliases else "")
    queries: list[str] = []
    for institution in institutions:
        queries.append(f'"{name}" "{institution}" 论文')
        queries.append(f'"{name}" "{institution}"')
    return list(dict.fromkeys(queries))


def _is_academic_url(url: str, domains: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if not host:
        return False
    if not any(host == domain.casefold() or host.endswith("." + domain.casefold()) for domain in domains):
        return False
    path = parsed.path.casefold()
    if "/writer/" in path:
        return False
    if ("/paper" in path or "/periodical" in path) and "q=" in parsed.query:
        return False
    return True


def search_deepseek(
    query: PersonQuery,
    config: ScholarsConfig,
    *,
    client: httpx.Client | None = None,
) -> list[WebCandidate]:
    """用 DeepSeek 自研搜索查中文库；只返回候选，不参与计数。

    接口：``POST https://api.deepseek.com/v1/tools/search``，与 DeepSeek
    主 API 共用 ``DEEPSEEK_API_KEY``。按配置的域名逐个查，结果去重。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ScholarsError(
            "未设置 DEEPSEEK_API_KEY，无法用 DeepSeek 搜索；"
            "可改用 --web-search firecrawl，或直接用 --supplement 手动补充。"
        )
    institutions: list[str] = []
    for value in (config.identity.institution_name, query.institute):
        text = value.strip()
        if text and text not in institutions:
            institutions.append(text)
    if not institutions:
        institutions = [config.identity.institution_name]
    owns_client = client is None
    client = client or httpx.Client(timeout=config.openalex.timeout_seconds)
    candidates: list[WebCandidate] = []
    seen: set[str] = set()
    errors: list[str] = []
    try:
        for search_query in _deepseek_queries(query, institutions):
            payload = {
                "query": search_query,
                "count": config.web_search.max_results_per_person,
                "need_content": False,
            }
            try:
                response = client.post(
                    DEEPSEEK_SEARCH_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
            except httpx.HTTPError as exc:
                errors.append(f"{search_query[:40]}: {exc}")
                continue
            if response.status_code >= 400:
                errors.append(
                    f"{search_query[:40]}: HTTP {response.status_code} {response.text[:200]}"
                )
                continue
            try:
                data = response.json()
            except ValueError:
                errors.append(f"{search_query[:40]}: 返回了无法解析的 JSON")
                continue
            for item in (data.get("results") or []):
                if not isinstance(item, dict):
                    continue
                title = _text(item.get("title"))
                url = _text(item.get("url"))
                key = url or title
                if not title or key in seen:
                    continue
                if not _is_academic_url(url, config.web_search.domains):
                    continue
                # 搜索结果页/无关页面很多；人名或别名必须出现在标题/摘要里
                snippet = _text(item.get("snippet"))
                summary = _text(item.get("summary"))
                haystack = f"{title} {snippet} {summary}".casefold()
                names = [query.name, *query.aliases]
                if not any(
                    name.strip().casefold() in haystack
                    for name in names
                    if name.strip()
                ):
                    continue
                if "浏览器版本过低" in title:
                    continue
                seen.add(key)
                candidates.append(
                    WebCandidate(
                        person_name=query.name,
                        title=title,
                        source="deepseek",
                        year=(
                            _year_from_date(item.get("date"))
                            or _year_from_date(snippet)
                            or _year_from_date(summary)
                        ),
                        url=url,
                        confidence="low",
                        status="pending",
                    )
                )
    finally:
        if owns_client:
            client.close()

    if not candidates and errors:
        raise ScholarsError("DeepSeek 检索失败：" + "；".join(errors))
    return candidates[: config.web_search.max_results_per_person]


def search_web(
    query: PersonQuery,
    config: ScholarsConfig,
    provider: str,
    *,
    client: httpx.Client | None = None,
) -> list[WebCandidate]:
    """按 provider 分发；结果一律是候选，绝不自动计入。"""
    if provider == "deepseek":
        return search_deepseek(query, config, client=client)
    if provider == "firecrawl":
        return search_firecrawl(query, config, client=client)
    if provider in {"none", "manual"}:
        return []
    raise ScholarsError(f"未知网页检索 provider：{provider}")


def _firecrawl_api_key() -> str:
    return os.environ.get("FIRECRAWL_API_KEY", "").strip()


def search_firecrawl(
    query: PersonQuery,
    config: ScholarsConfig,
    *,
    client: httpx.Client | None = None,
) -> list[WebCandidate]:
    """用 Firecrawl 搜中文库；只返回候选，不参与计数。"""
    api_key = _firecrawl_api_key()
    if not api_key:
        raise ScholarsError(
            "未设置 FIRECRAWL_API_KEY，无法做中文库网页检索；可改用 --supplement 人工清单。"
        )
    aliases = " OR ".join(f'"{name}"' for name in query.all_names if name.strip())
    institution = query.institute or config.identity.institution_name
    sites = " OR ".join(f"site:{domain}" for domain in config.web_search.domains)
    search_query = f"({aliases}) {institution} 论文 {sites}"
    payload = {
        "query": search_query,
        "limit": config.web_search.max_results_per_person,
        "sources": ["web"],
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=config.openalex.timeout_seconds)
    try:
        response = client.post(
            "https://api.firecrawl.dev/v2/search",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    except httpx.HTTPError as exc:
        raise ScholarsError(f"Firecrawl 检索失败：{exc}") from exc
    finally:
        if owns_client:
            client.close()
    if response.status_code >= 400:
        raise ScholarsError(f"Firecrawl 检索失败（{response.status_code}）：{response.text[:500]}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ScholarsError("Firecrawl 返回了无法解析的 JSON") from exc

    results: list[dict[str, Any]] = []
    for key in ("data", "results"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list):
            results = [item for item in value if isinstance(item, dict)]
            break

    candidates: list[WebCandidate] = []
    for item in results[: config.web_search.max_results_per_person]:
        title = _text(item.get("title")) or _text(item.get("name"))
        url = _text(item.get("url"))
        text = " ".join(
            _text(item.get(key))
            for key in ("description", "markdown", "content", "snippet")
        )
        year_match = re.search(r"(20\d{2})", text)
        year = int(year_match.group(1)) if year_match else None
        if title:
            candidates.append(
                WebCandidate(
                    person_name=query.name,
                    title=title,
                    source="firecrawl",
                    year=year,
                    url=url,
                    confidence="low",
                    status="pending",
                )
            )
    return candidates
