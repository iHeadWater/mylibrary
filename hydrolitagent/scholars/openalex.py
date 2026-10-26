"""OpenAlex HTTP 客户端。

只读、带重试与磁盘缓存；cursor 翻页需要 API key，无 key 时退回 page 翻页。
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from .config import OpenAlexSettings
from .errors import OpenAlexAuthError, OpenAlexBudgetError, OpenAlexError
from .models import WorksFetch

WORK_SELECT = (
    "id,doi,title,display_name,publication_year,publication_date,type,is_retracted,"
    "is_authors_truncated,authorships,corresponding_author_ids,primary_location"
)

AUTHOR_SELECT = (
    "id,display_name,display_name_alternatives,raw_author_names,orcid,"
    "last_known_institutions,affiliations,works_count,cited_by_count,counts_by_year"
)


def _short_id(value: str | None) -> str:
    text = (value or "").strip()
    return text.rsplit("/", 1)[-1] if text else ""


class OpenAlexClient:
    def __init__(
        self,
        settings: OpenAlexSettings,
        *,
        api_key: str = "",
        cache_dir: str | Path | None = None,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = api_key.strip()
        self.refresh = refresh
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        user_agent = "hydrolitagent-scholars/1"
        if settings.mailto:
            user_agent += f" (mailto:{settings.mailto})"
        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            headers=headers,
            follow_redirects=True,
            transport=transport,
        )
        self.request_count = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenAlexClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------ HTTP

    def _cache_path(self, path: str, params: Mapping[str, Any]) -> Path | None:
        if not self.cache_dir:
            return None
        payload = json.dumps(
            {"base": self.settings.base_url, "path": path, "params": params},
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, cache_path: Path | None) -> dict[str, Any] | None:
        if not cache_path or self.refresh or not cache_path.is_file():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None

    def _write_cache(self, cache_path: Path | None, path: str, params: Mapping[str, Any], data: dict[str, Any]) -> None:
        if not cache_path:
            return
        payload = {
            "url": f"{self.settings.base_url}{path}",
            "params": dict(params),
            "data": data,
        }
        temp = cache_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, cache_path)

    def _sleep_backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self.settings.backoff_base_seconds * (2**attempt)
        else:
            delay = self.settings.backoff_base_seconds * (2**attempt)
        delay = min(max(delay, 0.0), 60.0)
        delay += random.uniform(0, delay * 0.1)
        if delay > 0:
            time.sleep(delay)

    def _request(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        cache_path = self._cache_path(path, params)
        cached = self._read_cache(cache_path)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self._client.get(path, params=dict(params))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    raise OpenAlexError(f"OpenAlex 请求失败（网络）：{exc}") from exc
                self._sleep_backoff(attempt)
                continue

            self.request_count += 1
            status = response.status_code
            if status == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    last_error = exc
                    if attempt >= self.settings.max_retries:
                        raise OpenAlexError("OpenAlex 返回了无法解析的 JSON") from exc
                    self._sleep_backoff(attempt, response)
                    continue
                if not isinstance(data, dict):
                    raise OpenAlexError("OpenAlex 返回的 JSON 不是对象")
                self._write_cache(cache_path, path, params, data)
                if self.settings.request_interval_ms:
                    time.sleep(self.settings.request_interval_ms / 1000.0)
                return data

            body = response.text[:2000]
            if status == 429:
                lowered = body.casefold()
                if any(term in lowered for term in ("budget", "credit", "not_enough", "insufficient")):
                    raise OpenAlexBudgetError(
                        "OpenAlex 每日额度已用尽；请设置并激活 OPENALEX_API_KEY，或等待额度重置。"
                    )
                last_error = OpenAlexError(f"OpenAlex 限流（429）：{body}")
                if attempt >= self.settings.max_retries:
                    raise last_error
                self._sleep_backoff(attempt, response)
                continue
            if status in (500, 502, 503, 504):
                last_error = OpenAlexError(f"OpenAlex 服务端错误（{status}）：{body}")
                if attempt >= self.settings.max_retries:
                    raise last_error
                self._sleep_backoff(attempt, response)
                continue
            if status in (401, 403):
                raise OpenAlexAuthError(
                    f"OpenAlex 鉴权失败（{status}）：请检查 OPENALEX_API_KEY 是否有效/已激活。{body}"
                )
            if status == 400:
                raise OpenAlexError(f"OpenAlex 查询参数错误（400）：{body}")
            if status == 404:
                raise OpenAlexError(f"OpenAlex 资源不存在（404）：{path}")
            raise OpenAlexError(f"OpenAlex 请求失败（{status}）：{body}")

        raise OpenAlexError(f"OpenAlex 请求失败：{last_error}")

    # --------------------------------------------------------------- Authors

    def _author_params(self, search: str, *, institution_id: str, past_only: bool, limit: int, works_count_cap: int | None) -> dict[str, Any]:
        filters: list[str] = []
        scope = "affiliations.institution.id" if past_only else "last_known_institutions.id"
        if institution_id:
            filters.append(f"{scope}:{institution_id}")
        if works_count_cap:
            filters.append(f"works_count:<{works_count_cap}")
        params: dict[str, Any] = {
            "search": search,
            "per_page": min(max(limit, 1), 100),
            "select": AUTHOR_SELECT,
        }
        if filters:
            params["filter"] = ",".join(filters)
        return params

    def search_authors(
        self,
        search: str,
        *,
        institution_id: str = "",
        include_past: bool = False,
        past_only: bool = False,
        limit: int = 20,
        works_count_cap: int | None = None,
    ) -> list[dict[str, Any]]:
        data = self._request(
            "/authors",
            self._author_params(
                search,
                institution_id=institution_id,
                past_only=past_only,
                limit=limit,
                works_count_cap=works_count_cap,
            ),
        )
        results = data.get("results") or []
        if results or not (include_past and institution_id) or past_only:
            return [item for item in results if isinstance(item, dict)]
        # 历史单位兜底：有些人的 last_known_institutions 缺失，但 affiliations 仍有本校
        data = self._request(
            "/authors",
            self._author_params(
                search,
                institution_id=institution_id,
                past_only=True,
                limit=limit,
                works_count_cap=works_count_cap,
            ),
        )
        return [item for item in (data.get("results") or []) if isinstance(item, dict)]

    def find_authors_by_orcid(self, orcid: str) -> list[dict[str, Any]]:
        data = self._request(
            "/authors",
            {
                "filter": f"orcid:{orcid}",
                "per_page": 100,
                "select": AUTHOR_SELECT,
            },
        )
        return [item for item in (data.get("results") or []) if isinstance(item, dict)]

    def get_author(self, author_id: str) -> dict[str, Any]:
        data = self._request(f"/authors/{_short_id(author_id)}", {"select": AUTHOR_SELECT})
        if not isinstance(data, dict) or not data.get("id"):
            raise OpenAlexError(f"作者不存在：{author_id}")
        return data

    # ----------------------------------------------------------------- Works

    def _works_params(
        self,
        author_ids: Sequence[str],
        *,
        from_date: str,
        to_date: str | None,
        work_types: Sequence[str],
        page_mode: bool,
    ) -> dict[str, Any]:
        filters = [
            "authorships.author.id:" + "|".join(author_ids),
            f"from_publication_date:{from_date}",
        ]
        if to_date:
            filters.append(f"to_publication_date:{to_date}")
        if work_types:
            filters.append("type:" + "|".join(work_types))
        params: dict[str, Any] = {
            "filter": ",".join(filters),
            "per_page": self.settings.per_page,
            "select": WORK_SELECT,
        }
        if not page_mode:
            params["cursor"] = "*"
        return params

    def fetch_works(
        self,
        author_ids: Sequence[str],
        *,
        from_date: str,
        to_date: str | None = None,
        work_types: Sequence[str] = (),
        max_works: int = 5000,
    ) -> WorksFetch:
        if not author_ids:
            return WorksFetch()
        author_ids = [_short_id(author_id) for author_id in author_ids if _short_id(author_id)]
        if not author_ids:
            return WorksFetch()

        works: dict[str, dict[str, Any]] = {}
        pages = 0
        requests = 0
        total_count: int | None = None
        truncated = False
        truncation_reason = ""

        if self.api_key:
            cursor = "*"
            while cursor:
                params = self._works_params(
                    author_ids, from_date=from_date, to_date=to_date, work_types=work_types, page_mode=False
                )
                params["cursor"] = cursor
                data = self._request("/works", params)
                requests += 1
                pages += 1
                meta = data.get("meta") or {}
                total_count = meta.get("count", total_count)
                for work in data.get("results") or []:
                    work_id = _short_id(work.get("id")) if isinstance(work, dict) else ""
                    if work_id:
                        works[work_id] = work
                if len(works) >= max_works:
                    truncated = True
                    truncation_reason = "max_works"
                    break
                cursor = meta.get("next_cursor")
                if not data.get("results"):
                    break
        else:
            page = 1
            while True:
                params = self._works_params(
                    author_ids, from_date=from_date, to_date=to_date, work_types=work_types, page_mode=True
                )
                params["page"] = page
                data = self._request("/works", params)
                requests += 1
                pages += 1
                meta = data.get("meta") or {}
                count = int(meta.get("count") or 0)
                total_count = count
                results = data.get("results") or []
                for work in results:
                    work_id = _short_id(work.get("id")) if isinstance(work, dict) else ""
                    if work_id:
                        works[work_id] = work
                if len(works) >= max_works:
                    truncated = True
                    truncation_reason = "max_works"
                    break
                if count > 10_000:
                    truncated = True
                    truncation_reason = "no_api_key_page_limit"
                if not results or page * self.settings.per_page >= min(count, 10_000):
                    break
                page += 1

        return WorksFetch(
            works=tuple(works.values()),
            total_count=total_count,
            pages=pages,
            request_count=requests,
            truncated=truncated,
            truncation_reason=truncation_reason,
        )

    def get_work(self, work_id: str) -> dict[str, Any]:
        data = self._request(f"/works/{_short_id(work_id)}", {"select": WORK_SELECT})
        if not isinstance(data, dict) or not data.get("id"):
            raise OpenAlexError(f"作品不存在：{work_id}")
        return data
