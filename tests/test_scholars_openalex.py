from __future__ import annotations

import httpx
import pytest

from hydrolitagent.scholars.config import OpenAlexSettings
from hydrolitagent.scholars.errors import (
    OpenAlexAuthError,
    OpenAlexBudgetError,
    OpenAlexError,
)
from hydrolitagent.scholars.openalex import OpenAlexClient

from scholars_fixtures import author_payload, work_payload


def make_client(handler, *, api_key: str = "", **kwargs):
    settings = OpenAlexSettings(
        backoff_base_seconds=0,
        request_interval_ms=0,
        max_retries=2,
        per_page=100,
    )
    return OpenAlexClient(
        settings,
        api_key=api_key,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_author_search_params_and_auth_header() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"results": [author_payload()]})

    client = make_client(handler, api_key="test-key")
    authors = client.search_authors(
        "Zhang San",
        institution_id="I27357992",
        works_count_cap=3001,
    )
    client.close()
    assert len(authors) == 1
    assert seen["path"] == "/authors"
    assert seen["params"]["search"] == "Zhang San"
    assert "last_known_institutions.id:I27357992" in seen["params"]["filter"]
    assert "works_count:<3001" in seen["params"]["filter"]
    assert seen["auth"] == "Bearer test-key"


def test_orcid_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filter"] == "orcid:0000-0002-1825-0097"
        return httpx.Response(200, json={"results": [author_payload(orcid="0000-0002-1825-0097")]})

    client = make_client(handler)
    authors = client.find_authors_by_orcid("0000-0002-1825-0097")
    client.close()
    assert authors[0]["orcid"] == "https://orcid.org/0000-0002-1825-0097"


def test_cursor_paging_with_api_key() -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor == "*":
            return httpx.Response(
                200,
                json={
                    "meta": {"count": 2, "next_cursor": "next"},
                    "results": [work_payload("W1")],
                },
            )
        return httpx.Response(
            200,
            json={
                "meta": {"count": 2, "next_cursor": None},
                "results": [work_payload("W2")],
            },
        )

    client = make_client(handler, api_key="test-key")
    fetch = client.fetch_works(
        ["A1"],
        from_date="2021-01-01",
        work_types=("article",),
    )
    client.close()
    assert calls == ["*", "next"]
    assert len(fetch.works) == 2
    assert fetch.total_count == 2
    assert fetch.truncated is False


def test_page_paging_without_api_key() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages.append(page)
        if page == 1:
            return httpx.Response(
                200,
                json={
                    "meta": {"count": 150},
                    "results": [work_payload(f"W{index}") for index in range(100)],
                },
            )
        return httpx.Response(
            200,
            json={
                "meta": {"count": 150},
                "results": [work_payload(f"W{index}") for index in range(100, 150)],
            },
        )

    client = make_client(handler)
    fetch = client.fetch_works(["A1"], from_date="2021-01-01")
    client.close()
    assert pages == [1, 2]
    assert len(fetch.works) == 150
    assert fetch.truncated is False


def test_max_works_truncation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "meta": {"count": 500, "next_cursor": "next"},
                "results": [work_payload(f"W{index}") for index in range(100)],
            },
        )

    client = make_client(handler, api_key="test-key")
    fetch = client.fetch_works(["A1"], from_date="2021-01-01", max_works=100)
    client.close()
    assert fetch.truncated is True
    assert fetch.truncation_reason == "max_works"


def test_429_retry_then_success() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="rate limited")
        return httpx.Response(200, json={"results": [author_payload()]})

    client = make_client(handler)
    authors = client.search_authors("Zhang San")
    client.close()
    assert attempts["count"] == 2
    assert len(authors) == 1


def test_budget_429_is_not_retried() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(429, text="not_enough_credits: daily budget exhausted")

    client = make_client(handler)
    with pytest.raises(OpenAlexBudgetError):
        client.search_authors("Zhang San")
    client.close()
    assert attempts["count"] == 1


def test_401_raises_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid key")

    client = make_client(handler)
    with pytest.raises(OpenAlexAuthError):
        client.search_authors("Zhang San")
    client.close()


def test_400_raises_query_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad filter")

    client = make_client(handler)
    with pytest.raises(OpenAlexError) as exc:
        client.search_authors("Zhang San")
    client.close()
    assert "400" in str(exc.value)


def test_cache_hit_avoids_second_request(tmp_path) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"results": [author_payload()]})

    client = make_client(handler, cache_dir=tmp_path)
    first = client.search_authors("Zhang San")
    second = client.search_authors("Zhang San")
    client.close()
    assert calls["count"] == 1
    assert first == second


def test_cache_refresh_bypasses(tmp_path) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"results": [author_payload()]})

    client = make_client(handler, cache_dir=tmp_path)
    client.search_authors("Zhang San")
    client.close()
    client = make_client(handler, cache_dir=tmp_path, refresh=True)
    client.search_authors("Zhang San")
    client.close()
    assert calls["count"] == 2


def test_get_author_normalizes_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/authors/A1"
        return httpx.Response(200, json=author_payload())

    client = make_client(handler)
    author = client.get_author("https://openalex.org/A1")
    client.close()
    assert author["id"].endswith("/A1")
