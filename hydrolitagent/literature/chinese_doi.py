"""Metadata for Chinese journal DOIs that Crossref does not index.

CNKI-registered journals (prefixes such as ``10.14042``, ``10.13243``) are
absent from Crossref/DataCite, so ``crossref_meta`` returns 404. Two public
pages still describe them: the ``chndoi.org`` resolution page (title, authors,
publisher, registration date, links to the publisher) and the publisher's own
article page, which carries Highwire ``citation_*`` meta tags.

Every parser is pure and string-in/string-out; only :func:`fetch_page` touches
the network, so this module is unit-testable offline. ``resolve_chinese_meta``
returns a **Crossref-shaped** dict so ``paper_to_zotero.build_item`` reuses its
existing type/volume/date/creator mapping instead of growing a second one.

Must not import ``download_pdf`` (that module imports this one).
"""

from __future__ import annotations

import html as _html
import re
import urllib.parse
import urllib.request
from typing import Optional

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
CHNDOI_HANDLER = "https://www.chndoi.org/Resolution/Handler?doi={doi}"
_LABELS = {"题名": "title", "作者": "authors", "出版机构": "publisher", "注册时间": "registered"}


def fetch_page(url: str, timeout: int = 30) -> tuple[str, str, str]:
    """GET ``url``, returning ``(final_url, html, encoding)``.

    Encoding order: ``Content-Type`` charset, ``<meta charset>``, UTF-8, then
    ``gb18030`` — older Chinese journal platforms still serve GBK.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        final_url = resp.geturl() or url
        content_type = resp.headers.get("Content-Type", "")

    candidates: list[str] = []
    m = re.search(r"charset=[\"']?([\w-]+)", content_type or "", re.I)
    if m:
        candidates.append(m.group(1))
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates.extend(["utf-8", "gb18030"])

    for enc in candidates:
        try:
            return final_url, raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return final_url, raw.decode("utf-8", errors="replace"), "utf-8"


# ---------------------------------------------------------------------------
# Parsers (pure)
# ---------------------------------------------------------------------------


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", _html.unescape(text or ""))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_tags(text)).strip()


def _visible_lines(fragment: str) -> list[str]:
    """Split HTML into visible text lines (one per cell / block)."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    return [ln.strip() for ln in _html.unescape(text).splitlines()]


def parse_chndoi(page: str) -> Optional[dict]:
    """Parse a ``chndoi.org`` handler page.

    Returns ``{title, authors[], publisher, registered, landing_urls[]}`` or
    ``None`` when the page does not describe a paper (unknown DOI, error page).
    """
    lines = _visible_lines(page)
    fields: dict[str, str] = {}
    for i, line in enumerate(lines):
        for label, key in _LABELS.items():
            m = re.match(rf"^{label}\s*[:：]\s*(.*)$", line)
            if not m or key in fields:
                continue
            value = m.group(1).strip()
            if not value:  # label and value live in separate table cells
                for nxt in lines[i + 1:i + 4]:
                    if nxt and not re.match(r"^(题名|作者|出版机构|注册时间)\s*[:：]", nxt):
                        value = nxt
                        break
            fields[key] = value

    title = fields.get("title", "")
    if not title:
        return None
    authors = [a.strip() for a in re.split(r"[;；,，、]\s*", fields.get("authors", ""))
               if a.strip()]

    landing_urls: list[str] = []
    for href in re.findall(r"""href\s*=\s*["']([^"']+)["']""", page, re.I):
        href = _html.unescape(href.strip())
        if not href.startswith(("http://", "https://")):
            continue
        if "chndoi.org" in href:
            continue  # the resolver's own navigation, not the publisher
        if href not in landing_urls:
            landing_urls.append(href)

    return {
        "title": title,
        "authors": authors,
        "publisher": fields.get("publisher", ""),
        "registered": fields.get("registered", ""),
        "landing_urls": landing_urls,
    }


_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.S)


def _meta_map(page: str) -> dict[str, list[str]]:
    """Map lowercased meta name/property → all content values (repeats kept)."""
    out: dict[str, list[str]] = {}
    for tag in _META_TAG_RE.findall(page):
        attrs = {}
        for m in _ATTR_RE.finditer(tag):
            attrs[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
        key = (attrs.get("name") or attrs.get("property") or "").strip().lower()
        value = _html.unescape(attrs.get("content") or "").strip()
        if key and value:
            out.setdefault(key, []).append(value)
    return out


def _abstract_div(page: str) -> str:
    m = re.search(
        r'<(?P<tag>div|section|p)[^>]*\bid\s*=\s*["\'](?:abstract|abstracts|摘要)["\'][^>]*>'
        r"(?P<body>.*?)</(?P=tag)>",
        page, re.S | re.I,
    )
    return _clean(m.group("body")) if m else ""


def parse_citation_meta(page: str) -> dict:
    """Extract Highwire ``citation_*`` metadata plus an abstract.

    Missing fields are absent rather than empty strings. Abstract priority:
    ``citation_abstract`` → ``dc.description`` → a ``id="abstract"`` block.
    """
    metas = _meta_map(page)

    def first(*keys: str) -> str:
        for key in keys:
            values = metas.get(key.lower())
            if values:
                return values[0].strip()
        return ""

    authors: list[str] = []
    for value in metas.get("citation_author", []):
        for part in re.split(r"[;；、]\s*", value):
            if part.strip() and part.strip() not in authors:
                authors.append(part.strip())

    firstpage, lastpage = first("citation_firstpage"), first("citation_lastpage")
    pages = ""
    if firstpage:
        pages = firstpage if not lastpage or lastpage == firstpage else f"{firstpage}-{lastpage}"

    result = {
        "title": first("citation_title", "dc.title"),
        "journal": first("citation_journal_title", "citation_conference_title",
                         "prism.publicationname"),
        "issn": first("citation_issn", "citation_eissn"),
        "authors": authors,
        "date": first("citation_publication_date", "citation_date", "citation_year"),
        "volume": first("citation_volume"),
        "issue": first("citation_issue"),
        "pages": pages,
        "doi": first("citation_doi", "dc.identifier"),
        "pdf_url": first("citation_pdf_url"),
        "keywords": [k.strip() for k in re.split(r"[;；,，]\s*", first("citation_keywords"))
                     if k.strip()],
        "abstract": (_clean(first("citation_abstract", "dc.description", "description"))
                     or _abstract_div(page)),
    }
    return {k: v for k, v in result.items() if v}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _normalize_doi(doi: str) -> str:
    doi = re.sub(r"^https?://doi\.org/", "", (doi or "").strip())
    return re.sub(r"^doi:", "", doi).strip()


def _date_parts(value: str) -> Optional[dict]:
    nums = [int(x) for x in re.findall(r"\d{1,4}", value or "")][:3]
    return {"date-parts": [nums]} if nums else None


def _crossref_shape(doi: str, article: dict, chndoi: Optional[dict],
                    landing_url: str, pdf_url: str) -> dict:
    """Merge both sources into the dict shape ``build_item`` already reads."""
    chndoi = chndoi or {}
    title = article.get("title") or chndoi.get("title") or ""
    authors = article.get("authors") or chndoi.get("authors") or []
    # Never fall back to chndoi's 出版机构: that is the *registrant* (e.g.
    # 同方知网（北京）技术有限公司), not the journal, and writing it as
    # publicationTitle poisons the Zotero record. Same for 注册时间 — a DOI can
    # be registered years after publication, so it is not the publication date.
    journal = article.get("journal") or ""
    date = article.get("date") or ""
    prefix, _, suffix = doi.partition("/")

    shaped: dict = {
        "type": "journal-article",
        "title": [title] if title else [],
        "author": [{"family": name, "given": ""} for name in authors],
        "container-title": [journal] if journal else [],
        "volume": article.get("volume", ""),
        "issue": article.get("issue", ""),
        "page": article.get("pages", ""),
        "prefix": prefix,
        "suffix": suffix,
        "landing_url": landing_url,
        "pdf_url": pdf_url,
        "source": "chndoi",
    }
    for src_key, dst_key in (("issn", "ISSN"), ("abstract", "abstract"),
                             ("keywords", "keyword")):
        if article.get(src_key):
            shaped[dst_key] = article[src_key]
    date_parts = _date_parts(date)
    if date_parts:
        shaped["published-print"] = date_parts
    return shaped


def resolve_chinese_meta(doi: str, *, landing_url: str | None = None,
                         pdf_url: str | None = None) -> Optional[dict]:
    """Resolve a Chinese DOI via chndoi.org + the publisher's article page.

    Returns a Crossref-shaped dict (plus ``landing_url`` / ``pdf_url`` /
    ``source``) or ``None`` when no landing page could be read. Network
    failures are swallowed on purpose: the caller decides whether that is a
    hard error, and retrying a throttled journal server is not useful.
    """
    doi = _normalize_doi(doi)

    chndoi: Optional[dict] = None
    if not landing_url:
        handler = CHNDOI_HANDLER.format(doi=urllib.parse.quote(doi, safe=""))
        try:
            _, page, _ = fetch_page(handler)
            chndoi = parse_chndoi(page)
        except Exception:
            chndoi = None

    candidates = [landing_url] if landing_url else list(
        (chndoi or {}).get("landing_urls") or []
    )
    article: dict = {}
    landing = ""
    for candidate in candidates[:4]:
        try:
            final_url, page, _ = fetch_page(candidate)
        except Exception:
            continue
        parsed = parse_citation_meta(page)
        if not parsed.get("title"):
            continue  # error page, slider captcha, or a JS-only shell
        article, landing = parsed, (final_url or candidate)
        break

    if not article.get("title"):
        # Nothing could be parsed over plain HTTP. Trust an explicit URL, or
        # the first link chndoi advertised, and let the browser flow try it —
        # a 403 to urllib or a JS-rendered page often still works in a real
        # browser. Only "no page to open at all" is a hard failure.
        fallback = landing_url or (candidates[0] if candidates else "")
        if not (pdf_url or fallback):
            return None
        article, landing = {}, fallback

    resolved_pdf = pdf_url or article.get("pdf_url") or ""
    if resolved_pdf and not resolved_pdf.startswith("http"):
        base = landing or (candidates[0] if candidates else "")
        resolved_pdf = urllib.parse.urljoin(base, resolved_pdf)
    if landing_url and not landing:
        landing = landing_url

    return _crossref_shape(doi, article, chndoi, landing, resolved_pdf)


def to_download_meta(shaped: dict) -> dict:
    """Flatten a Crossref-shaped dict into ``crossref_meta``'s shape."""
    def first(value):
        return value[0] if isinstance(value, list) and value else (value or "")

    date_parts = shaped.get("published-print") or shaped.get("issued") or {}
    year = str(date_parts["date-parts"][0][0]) if date_parts.get("date-parts") else ""
    authors = [(a.get("family") or a.get("name") or "").strip()
               for a in shaped.get("author", [])]

    return {
        "title": first(shaped.get("title")),
        "container": first(shaped.get("container-title")),
        "type": shaped.get("type") or "journal-article",
        "pii": None,
        "prefix": shaped.get("prefix") or "",
        "suffix": shaped.get("suffix") or "",
        "landing_url": shaped.get("landing_url") or "",
        "pdf_url": shaped.get("pdf_url") or "",
        "source": shaped.get("source") or "chndoi",
        "authors": [a for a in authors if a],
        "volume": shaped.get("volume") or "",
        "issue": shaped.get("issue") or "",
        "page": shaped.get("page") or "",
        "issn": first(shaped.get("ISSN")),
        "year": year,
    }


def fetch_chinese_crossref(doi: str) -> Optional[dict]:
    """Crossref-shaped metadata for ``build_item``; ``None`` when unavailable."""
    return resolve_chinese_meta(doi)
