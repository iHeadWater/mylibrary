from __future__ import annotations

import json

import httpx
import pytest

from hydrolitagent.scholars.config import ScholarsConfig
from hydrolitagent.scholars.errors import ScholarsError
from hydrolitagent.scholars.models import PersonQuery
from hydrolitagent.scholars.websearch import (
    load_supplement,
    search_deepseek,
    search_firecrawl,
    search_web,
)


def test_load_supplement_creates_records(tmp_path) -> None:
    path = tmp_path / "confirmed.csv"
    path.write_text(
        "姓名,标题,年份,期刊,DOI,作者位次,是否通讯,类型,作者\n"
        "张三,中文论文,2023,水利学报,10.1000/cn,first,否,article,张三|李四\n",
        encoding="utf-8-sig",
    )
    grouped = load_supplement(path)
    record = grouped["张三"][0]
    assert record.title == "中文论文"
    assert record.year == 2023
    assert record.counts_for_form is True
    assert record.source == "manual"
    assert record.is_first_author is True
    assert record.byline_name == "张三"
    assert record.author_index == 1
    assert record.author_count == 2


def test_load_supplement_uses_byline_for_author_index(tmp_path) -> None:
    path = tmp_path / "confirmed.csv"
    path.write_text(
        "姓名,标题,年份,期刊,DOI,作者位次,是否通讯,类型,作者,本人署名\n"
        "张三,English paper,2021,ERL,10.1000/x,middle,否,article,"
        "Alice Smith|Zhang San|Bob Lee,Zhang San\n",
        encoding="utf-8-sig",
    )
    record = load_supplement(path)["张三"][0]
    assert record.author_index == 2
    assert record.author_count == 3
    assert record.byline_name == "Zhang San"
    assert record.is_first_author is False


def test_load_supplement_requires_year(tmp_path) -> None:
    path = tmp_path / "confirmed.csv"
    path.write_text("姓名,标题\n张三,中文论文\n", encoding="utf-8")
    with pytest.raises(ScholarsError, match="年份"):
        load_supplement(path)


def test_load_supplement_requires_headers(tmp_path) -> None:
    path = tmp_path / "confirmed.csv"
    path.write_text("姓名\n张三\n", encoding="utf-8")
    with pytest.raises(ScholarsError, match="标题"):
        load_supplement(path)


def test_load_supplement_gb18030(tmp_path) -> None:
    path = tmp_path / "confirmed.csv"
    path.write_bytes("姓名,标题,年份\n王五,中文论文,2022\n".encode("gb18030"))
    grouped = load_supplement(path)
    assert grouped["王五"][0].year == 2022


def test_search_deepseek_without_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ScholarsError, match="DEEPSEEK_API_KEY"):
        search_deepseek(PersonQuery(name="张三"), ScholarsConfig())


def test_search_deepseek_maps_and_dedupes(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["query"].startswith('"张三"')
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "张三 某中文论文",
                        "url": "https://opaj.napstic.cn/periodicalArticle/1",
                        "snippet": "张三等人的论文",
                        "date": "2023-05-01T00:00:00Z",
                    },
                    {
                        "title": "张三 重复结果",
                        "url": "https://opaj.napstic.cn/periodicalArticle/1",
                        "snippet": "张三",
                        "date": None,
                    },
                    {
                        "title": "无关论文",
                        "url": "https://opaj.napstic.cn/periodicalArticle/2",
                        "snippet": "李四",
                    },
                    {
                        "title": "万方检索页",
                        "url": "https://s.wanfangdata.com.cn/paper?q=张三",
                        "snippet": "张三",
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    candidates = search_deepseek(
        PersonQuery(name="张三", institute="水利所"),
        ScholarsConfig(),
        client=client,
    )
    client.close()
    assert len(calls) == 4  # 两个单位 × 带/不带「论文」
    assert len(candidates) == 1  # 同一 URL 去重，且只保留学术站点
    assert candidates[0].source == "deepseek"
    assert candidates[0].year == 2023
    assert candidates[0].confidence == "low"


def test_search_web_none_returns_empty() -> None:
    assert search_web(PersonQuery(name="张三"), ScholarsConfig(), "none") == []


def test_firecrawl_without_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    with pytest.raises(ScholarsError, match="FIRECRAWL_API_KEY"):
        search_firecrawl(PersonQuery(name="张三", aliases=("Zhang San",)), ScholarsConfig())


def test_firecrawl_returns_candidates(monkeypatch) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"title": "某中文论文", "url": "https://example.com/1", "description": "2023 水利学报"},
                    {"title": "", "url": "https://example.com/2"},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    candidates = search_firecrawl(
        PersonQuery(name="张三", aliases=("Zhang San",)),
        ScholarsConfig(),
        client=client,
    )
    client.close()
    assert len(candidates) == 1
    assert candidates[0].title == "某中文论文"
    assert candidates[0].year == 2023
    assert candidates[0].confidence == "low"
