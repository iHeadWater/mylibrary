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
    search_query = (
        f"({aliases}) {institution} 论文 2021..2026 "
        "site:cnki.net OR site:wanfangdata.com.cn OR site:xueshu.baidu.com"
    )
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
