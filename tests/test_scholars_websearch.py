from __future__ import annotations

import httpx
import pytest

from hydrolitagent.scholars.config import ScholarsConfig
from hydrolitagent.scholars.errors import ScholarsError
from hydrolitagent.scholars.models import PersonQuery
from hydrolitagent.scholars.websearch import load_supplement, search_firecrawl


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
