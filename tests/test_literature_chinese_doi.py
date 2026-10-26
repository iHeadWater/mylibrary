"""Offline tests for ``hydrolitagent.literature.chinese_doi``.

Every HTML fixture is inline; no test touches the network. ``fetch_page`` is
exercised against a fake ``urlopen`` and ``resolve_chinese_meta`` against a
monkeypatched ``fetch_page``.
"""

from __future__ import annotations

from hydrolitagent.literature import chinese_doi

DOI = "10.14042/j.cnki.32.1309.2026.06.001"
HANDLER_URL = "https://www.chndoi.org/Resolution/Handler?doi=10.14042%2Fj.cnki.32.1309.2026.06.001"
ARTICLE_URL = "https://journal.example.cn/article/doi/10.14042/j.cnki.32.1309.2026.06.001"

CHNDOI_HTML = """
<html><head><meta charset="utf-8"><title>中文DOI解析</title></head><body>
<table>
  <tr><td>题名：</td><td>黄河中游水沙变化归因分析</td></tr>
  <tr><td>作者：</td><td>王丽川；李四；张三</td></tr>
  <tr><td>出版机构：</td><td>《水科学进展》编辑部</td></tr>
  <tr><td>注册时间：</td><td>2026-06-15</td></tr>
</table>
<ul>
  <li>境内访问：<a href="https://journal.example.cn/article/doi/10.14042/j.cnki.32.1309.2026.06.001">刊社页面</a></li>
  <li>境外访问：<a href="https://www.chndoi.org/Resolution/Handler?doi=10.14042/j.cnki.32.1309.2026.06.001">解析页</a></li>
</ul>
</body></html>
"""

ARTICLE_HTML = """
<html><head>
<meta charset="utf-8">
<meta name="citation_title" content="黄河中游水沙变化归因分析">
<meta name="citation_journal_title" content="水科学进展">
<meta name="citation_issn" content="1001-6791">
<meta name="citation_author" content="王丽川">
<meta name="citation_author" content="李四">
<meta name="citation_author" content="张三">
<meta name="citation_publication_date" content="2026-06-01">
<meta name="citation_volume" content="37">
<meta name="citation_issue" content="6">
<meta name="citation_firstpage" content="993">
<meta name="citation_lastpage" content="1007">
<meta name="citation_doi" content="10.14042/j.cnki.32.1309.2026.06.001">
<meta name="citation_pdf_url" content="/article/exportPdf?id=abc123">
<meta name="citation_keywords" content="水沙变化;归因分析">
<meta name="dc.description" content="目的：分析黄河中游水沙变化的驱动因素。">
</head><body><h1>黄河中游水沙变化归因分析</h1></body></html>
"""


def _article_html_with(extra_head: str = "", body: str = "") -> str:
    return f"<html><head>{extra_head}</head><body>{body}</body></html>"


# ---------------------------------------------------------------------------
# parse_chndoi
# ---------------------------------------------------------------------------


class TestParseChndoi:
    def test_extracts_fields_and_landing_urls(self):
        info = chinese_doi.parse_chndoi(CHNDOI_HTML)

        assert info is not None
        assert info["title"] == "黄河中游水沙变化归因分析"
        assert info["authors"] == ["王丽川", "李四", "张三"]
        assert info["publisher"] == "《水科学进展》编辑部"
        assert info["registered"] == "2026-06-15"
        assert info["landing_urls"] == [ARTICLE_URL]

    def test_returns_none_for_an_unknown_doi_page(self):
        assert chinese_doi.parse_chndoi("<html><body>未注册的 DOI</body></html>") is None

    def test_handles_label_and_value_in_the_same_cell(self):
        page = '<table><tr><td>题名：同一单元格标题</td></tr><tr><td>作者：赵六</td></tr></table>'

        info = chinese_doi.parse_chndoi(page)

        assert info["title"] == "同一单元格标题"
        assert info["authors"] == ["赵六"]


# ---------------------------------------------------------------------------
# parse_citation_meta
# ---------------------------------------------------------------------------


class TestParseCitationMeta:
    def test_extracts_highwire_fields(self):
        meta = chinese_doi.parse_citation_meta(ARTICLE_HTML)

        assert meta["title"] == "黄河中游水沙变化归因分析"
        assert meta["journal"] == "水科学进展"
        assert meta["issn"] == "1001-6791"
        assert meta["authors"] == ["王丽川", "李四", "张三"]
        assert meta["volume"] == "37"
        assert meta["issue"] == "6"
        assert meta["pages"] == "993-1007"
        assert meta["doi"] == DOI
        assert meta["pdf_url"] == "/article/exportPdf?id=abc123"
        assert meta["keywords"] == ["水沙变化", "归因分析"]
        assert meta["date"] == "2026-06-01"

    def test_abstract_falls_back_to_dc_description(self):
        meta = chinese_doi.parse_citation_meta(ARTICLE_HTML)

        assert "水沙变化" in meta["abstract"]
        assert "<" not in meta["abstract"]

    def test_citation_abstract_wins_over_dc_description(self):
        page = _article_html_with(
            '<meta name="citation_abstract" content="citation 摘要">'
            '<meta name="dc.description" content="dc 摘要">'
        )

        assert chinese_doi.parse_citation_meta(page)["abstract"] == "citation 摘要"

    def test_abstract_falls_back_to_the_abstract_div(self):
        page = _article_html_with(
            '<meta name="citation_title" content="T">',
            '<div class="x" id="abstract"><p>正文 <b>摘要</b> 段落。</p></div>',
        )

        assert chinese_doi.parse_citation_meta(page)["abstract"] == "正文 摘要 段落。"

    def test_single_page_uses_one_number(self):
        page = _article_html_with('<meta name="citation_firstpage" content="993">')

        assert chinese_doi.parse_citation_meta(page)["pages"] == "993"

    def test_parses_content_before_name_attribute_order(self):
        page = _article_html_with('<meta content="倒序标题" name="citation_title">')

        assert chinese_doi.parse_citation_meta(page)["title"] == "倒序标题"

    def test_returns_empty_dict_without_citation_meta(self):
        assert chinese_doi.parse_citation_meta("<html><body>nothing</body></html>") == {}


# ---------------------------------------------------------------------------
# fetch_page
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes, *, url: str, content_type: str):
        self._body = body
        self._url = url
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_page_decodes_gbk_from_meta_charset(monkeypatch):
    """Old journal platforms declare gb2312 in <meta> and serve GBK bytes."""
    title = "水科学进展"
    body = f'<html><head><meta charset="gbk"><title>{title}</title></head></html>'.encode("gb18030")
    response = _FakeResponse(body, url="https://journal.example.cn/a", content_type="text/html")

    monkeypatch.setattr(chinese_doi.urllib.request, "urlopen", lambda *a, **k: response)

    final_url, text, encoding = chinese_doi.fetch_page("https://journal.example.cn/a")

    assert final_url == "https://journal.example.cn/a"
    assert encoding.lower() in {"gbk", "gb2312", "gb18030"}
    assert title in text


def test_fetch_page_prefers_the_content_type_charset(monkeypatch):
    body = "<html><body>正文</body></html>".encode("gb18030")
    response = _FakeResponse(
        body, url="https://journal.example.cn/a", content_type="text/html; charset=gb18030"
    )

    monkeypatch.setattr(chinese_doi.urllib.request, "urlopen", lambda *a, **k: response)

    _, text, encoding = chinese_doi.fetch_page("https://journal.example.cn/a")

    assert encoding == "gb18030"
    assert "正文" in text


# ---------------------------------------------------------------------------
# resolve_chinese_meta / to_download_meta / fetch_chinese_crossref
# ---------------------------------------------------------------------------


def _patch_pages(monkeypatch, pages: dict[str, tuple[str, str, str]]):
    calls: list[str] = []

    def fake_fetch(url, timeout=30):
        calls.append(url)
        if url not in pages:
            raise OSError(f"unexpected URL {url}")
        return pages[url]

    monkeypatch.setattr(chinese_doi, "fetch_page", fake_fetch)
    return calls


def test_resolve_chinese_meta_walks_chndoi_then_the_landing_page(monkeypatch):
    calls = _patch_pages(monkeypatch, {
        HANDLER_URL: (HANDLER_URL, CHNDOI_HTML, "utf-8"),
        ARTICLE_URL: (ARTICLE_URL, ARTICLE_HTML, "utf-8"),
    })

    meta = chinese_doi.resolve_chinese_meta(DOI)

    assert calls == [HANDLER_URL, ARTICLE_URL]
    assert meta["source"] == "chndoi"
    assert meta["type"] == "journal-article"
    assert meta["title"] == ["黄河中游水沙变化归因分析"]
    assert meta["container-title"] == ["水科学进展"]
    assert meta["author"] == [
        {"family": "王丽川", "given": ""},
        {"family": "李四", "given": ""},
        {"family": "张三", "given": ""},
    ]
    assert meta["volume"] == "37"
    assert meta["issue"] == "6"
    assert meta["page"] == "993-1007"
    assert meta["prefix"] == "10.14042"
    assert meta["suffix"] == "j.cnki.32.1309.2026.06.001"
    assert meta["landing_url"] == ARTICLE_URL
    # Relative citation_pdf_url is resolved against the article page.
    assert meta["pdf_url"] == "https://journal.example.cn/article/exportPdf?id=abc123"
    assert meta["published-print"] == {"date-parts": [[2026, 6, 1]]}


def test_resolve_chinese_meta_falls_back_to_the_advertised_link(monkeypatch):
    """When the publisher page resists urllib, the browser still gets a URL."""
    _patch_pages(monkeypatch, {
        HANDLER_URL: (HANDLER_URL, CHNDOI_HTML, "utf-8"),
        ARTICLE_URL: (ARTICLE_URL, "<html><body>app shell</body></html>", "utf-8"),
    })

    meta = chinese_doi.resolve_chinese_meta(DOI)

    assert meta["landing_url"] == ARTICLE_URL
    assert meta["pdf_url"] == ""
    assert meta["title"] == ["黄河中游水沙变化归因分析"]  # chndoi still describes it
    # chndoi's 出版机构 is the CNKI registrant, not the journal, and 注册时间 is a
    # deposit date — neither may fill container-title / published-print.
    assert meta["container-title"] == []
    assert "published-print" not in meta


def test_resolve_chinese_meta_returns_none_when_chndoi_knows_nothing(monkeypatch):
    _patch_pages(monkeypatch, {
        HANDLER_URL: (HANDLER_URL, "<html><body>未注册的 DOI</body></html>", "utf-8"),
    })

    assert chinese_doi.resolve_chinese_meta(DOI) is None


def test_resolve_chinese_meta_honours_an_explicit_landing_url_without_meta(monkeypatch):
    """A JS-rendered article page has no meta for urllib; the browser may still work."""
    calls = _patch_pages(monkeypatch, {
        "https://journal.example.org/js": (
            "https://journal.example.org/js", "<html><body>app shell</body></html>", "utf-8"
        ),
    })

    meta = chinese_doi.resolve_chinese_meta(DOI, landing_url="https://journal.example.org/js")

    assert calls == ["https://journal.example.org/js"]
    assert meta["landing_url"] == "https://journal.example.org/js"
    assert meta["title"] == []


def test_resolve_chinese_meta_returns_none_when_chndoi_is_unreachable(monkeypatch):
    def boom(url, timeout=30):
        raise OSError("connection reset")

    monkeypatch.setattr(chinese_doi, "fetch_page", boom)

    assert chinese_doi.resolve_chinese_meta(DOI) is None


def test_resolve_chinese_meta_honours_explicit_landing_url(monkeypatch):
    calls = _patch_pages(monkeypatch, {
        "https://journal.example.org/handmade": (
            "https://journal.example.org/handmade", ARTICLE_HTML, "utf-8"
        ),
    })

    meta = chinese_doi.resolve_chinese_meta(DOI, landing_url="https://journal.example.org/handmade")

    assert calls == ["https://journal.example.org/handmade"]
    assert meta["landing_url"] == "https://journal.example.org/handmade"


def test_resolve_chinese_meta_accepts_an_explicit_pdf_url(monkeypatch):
    _patch_pages(monkeypatch, {HANDLER_URL: (HANDLER_URL, CHNDOI_HTML, "utf-8")})

    meta = chinese_doi.resolve_chinese_meta(DOI, pdf_url="https://journal.example.cn/pdf/1.pdf")

    assert meta["pdf_url"] == "https://journal.example.cn/pdf/1.pdf"
    assert meta["title"] == ["黄河中游水沙变化归因分析"]  # chndoi fallback


def test_to_download_meta_flattens_to_the_crossref_meta_shape(monkeypatch):
    _patch_pages(monkeypatch, {
        HANDLER_URL: (HANDLER_URL, CHNDOI_HTML, "utf-8"),
        ARTICLE_URL: (ARTICLE_URL, ARTICLE_HTML, "utf-8"),
    })

    meta = chinese_doi.to_download_meta(chinese_doi.resolve_chinese_meta(DOI))

    assert meta["title"] == "黄河中游水沙变化归因分析"
    assert meta["container"] == "水科学进展"
    assert meta["prefix"] == "10.14042"
    assert meta["suffix"] == "j.cnki.32.1309.2026.06.001"
    assert meta["source"] == "chndoi"
    assert meta["landing_url"] == ARTICLE_URL
    assert meta["pdf_url"] == "https://journal.example.cn/article/exportPdf?id=abc123"
    assert meta["authors"] == ["王丽川", "李四", "张三"]
    assert meta["volume"] == "37"
    assert meta["year"] == "2026"


def test_fetch_chinese_crossref_is_the_zotero_facing_entry(monkeypatch):
    _patch_pages(monkeypatch, {
        HANDLER_URL: (HANDLER_URL, CHNDOI_HTML, "utf-8"),
        ARTICLE_URL: (ARTICLE_URL, ARTICLE_HTML, "utf-8"),
    })

    meta = chinese_doi.fetch_chinese_crossref(DOI)

    assert meta["type"] == "journal-article"
    assert meta["title"] == ["黄河中游水沙变化归因分析"]
