"""Tests for ``hydrolitagent/literature/download_pdf.py`` — PDF download helper."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from hydrolitagent.literature.download_pdf import (
    DEFAULT_OUT,
    PdfMetadata,
    Publisher,
    _clean_base64,
    classify_input,
    copernicus_pdf_url,
    decode_base64_file,
    default_pdf_dir,
    detect_publisher,
    doi_to_url,
    is_pdf_file,
    normalize_doi,
    output_path_for,
    pii_to_sciencedirect_url,
    setup_check,
    slug_from_doi,
    verify_pdf,
)


# ---------------------------------------------------------------------------
# normalize_doi
# ---------------------------------------------------------------------------


def test_normalize_doi_bare():
    """Bare DOI is returned as-is."""
    assert normalize_doi("10.1016/j.jhydrol.2024.132471") == "10.1016/j.jhydrol.2024.132471"


def test_normalize_doi_https_prefix():
    """HTTPS DOI URL is stripped to bare DOI."""
    assert (
        normalize_doi("https://doi.org/10.1016/j.jhydrol.2024.132471")
        == "10.1016/j.jhydrol.2024.132471"
    )


def test_normalize_doi_prefix():
    """``doi:`` prefix is stripped."""
    assert (
        normalize_doi("doi:10.1016/j.jhydrol.2024.132471")
        == "10.1016/j.jhydrol.2024.132471"
    )


def test_normalize_doi_whitespace():
    """Leading/trailing whitespace is stripped."""
    assert (
        normalize_doi("  10.1016/j.jhydrol.2024.132471  ")
        == "10.1016/j.jhydrol.2024.132471"
    )


# ---------------------------------------------------------------------------
# detect_publisher
# ---------------------------------------------------------------------------


def test_detect_elsevier_sciencedirect():
    """ScienceDirect URLs return ELSEVIER."""
    assert (
        detect_publisher("https://www.sciencedirect.com/science/article/pii/S0022169424018675")
        == Publisher.ELSEVIER
    )


def test_detect_elsevier_elsevier():
    """elsevier.com URLs return ELSEVIER."""
    assert detect_publisher("https://linkinghub.elsevier.com/retrieve/pii/S0022169424018675") == Publisher.ELSEVIER


def test_detect_springer():
    """Springer URLs return SPRINGER."""
    assert detect_publisher("https://link.springer.com/article/10.1007/s11269-024-04000-0") == Publisher.SPRINGER


def test_detect_wiley():
    """Wiley URLs return WILEY."""
    assert (
        detect_publisher("https://onlinelibrary.wiley.com/doi/10.1029/2023WR036500")
        == Publisher.WILEY
    )


def test_detect_taylor_francis():
    """Taylor & Francis URLs return TAYLOR_FRANCIS."""
    assert (
        detect_publisher("https://www.tandfonline.com/doi/full/10.1080/02626667.2024.1234567")
        == Publisher.TAYLOR_FRANCIS
    )


def test_detect_agu():
    """AGU URLs (on wiley.com) return AGU."""
    assert (
        detect_publisher("https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2023WR036500")
        == Publisher.AGU
    )


def test_detect_unknown():
    """Unrecognized URL returns UNKNOWN."""
    assert detect_publisher("https://example.com/paper.pdf") == Publisher.UNKNOWN


# ---------------------------------------------------------------------------
# classify_input
# ---------------------------------------------------------------------------


def test_classify_bare_doi():
    """Bare DOI is classified as 'doi'."""
    result = classify_input("10.1016/j.jhydrol.2024.132471")
    assert result["type"] == "doi"
    assert result["normalized"] == "10.1016/j.jhydrol.2024.132471"
    assert "doi.org" in result["url"]


def test_classify_doi_url():
    """Full doi.org URL is classified as 'doi'."""
    result = classify_input("https://doi.org/10.1016/j.jhydrol.2024.132471")
    assert result["type"] == "doi"
    assert result["normalized"] == "10.1016/j.jhydrol.2024.132471"


def test_classify_pii():
    """PII string is classified as 'pii'."""
    result = classify_input("S0022169424018675")
    assert result["type"] == "pii"
    assert result["normalized"] == "S0022169424018675"
    assert result["url"] == pii_to_sciencedirect_url("S0022169424018675")


def test_classify_url():
    """Full URL is classified as 'url'."""
    url = "https://www.sciencedirect.com/science/article/pii/S0022169424018675"
    result = classify_input(url)
    assert result["type"] == "url"
    assert result["url"] == url


def test_classify_unknown():
    """Unrecognizable input is classified as 'unknown'."""
    result = classify_input("random text not a doi or url")
    assert result["type"] == "unknown"
    assert result["url"] == ""


def test_classify_pii_case_insensitive():
    """PII detection is case-insensitive."""
    result = classify_input("s0022169424018675")
    assert result["type"] == "pii"
    assert result["normalized"] == "S0022169424018675"


# ---------------------------------------------------------------------------
# _clean_base64
# ---------------------------------------------------------------------------


def test_clean_base64_plain():
    """Plain base64 string passes through unchanged."""
    b64 = "JVBERi0xLjcKJYGBgYEKCjEgMCBvYmo="
    assert _clean_base64(b64) == b64


def test_clean_base64_data_url():
    """Data URL prefix is stripped."""
    raw = "data:application/pdf;base64,JVBERi0xLjcKJYGBgYEKCjEgMCBvYmo="
    expected = "JVBERi0xLjcKJYGBgYEKCjEgMCBvYmo="
    assert _clean_base64(raw) == expected


def test_clean_base64_with_whitespace():
    """Whitespace and newlines are stripped."""
    raw = "JVBERi0xLjcK\nJYGBgYEKCjEg MCBvYmo=\n"
    expected = "JVBERi0xLjcKJYGBgYEKCjEgMCBvYmo="
    assert _clean_base64(raw) == expected


def test_clean_base64_non_ascii_artifacts():
    """Non-base64 characters are removed."""
    raw = "JVBERi0xLjcK\xff\xfeJYGBgYEKCjEgMCBvYmo="
    expected = "JVBERi0xLjcKJYGBgYEKCjEgMCBvYmo="
    assert _clean_base64(raw) == expected


def test_clean_base64_json_wrapped():
    """JSON-wrapped base64 is extracted."""
    data = {"size": 100, "base64": "data:application/pdf;base64,JVBERi0xLjcK"}
    raw = json.dumps(data)
    expected = "JVBERi0xLjcK"
    assert _clean_base64(raw) == expected


# ---------------------------------------------------------------------------
# decode_base64_file
# ---------------------------------------------------------------------------


def test_decode_base64_json_file(tmp_path):
    """JSON-wrapped base64 decodes to the correct binary content."""
    original = b"hello pdf content here"
    b64 = base64.b64encode(original).decode("ascii")
    data = json.dumps({"size": len(original), "base64": f"data:application/pdf;base64,{b64}"})

    input_file = tmp_path / "input.json"
    input_file.write_text(data, encoding="utf-8")
    output_file = tmp_path / "output.bin"

    size = decode_base64_file(input_file, output_file)
    assert size == len(original)
    assert output_file.read_bytes() == original


def test_decode_base64_plain_file(tmp_path):
    """Plain base64 file decodes correctly."""
    original = b"plain pdf content"
    b64 = base64.b64encode(original).decode("ascii")

    input_file = tmp_path / "input.txt"
    input_file.write_text(b64, encoding="utf-8")
    output_file = tmp_path / "output.bin"

    size = decode_base64_file(input_file, output_file)
    assert size == len(original)
    assert output_file.read_bytes() == original


# ---------------------------------------------------------------------------
# verify_pdf
# ---------------------------------------------------------------------------


_MINIMAL_PDF = (
    b"%PDF-1.7\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF"
)


def test_verify_valid_pdf(tmp_path):
    """Valid PDF returns metadata with correct page count."""
    pdf_path = tmp_path / "valid.pdf"
    pdf_path.write_bytes(_MINIMAL_PDF)

    meta = verify_pdf(pdf_path)
    assert meta.version == "1.7"
    assert meta.pages == 1
    assert meta.file_size_bytes == len(_MINIMAL_PDF)


def test_verify_pdf_with_title_and_author(tmp_path):
    """PDF with /Title and /Author metadata extracts them."""
    pdf_with_meta = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"4 0 obj\n<< /Title (Test Paper Title) /Author (Smith; Jones) >>\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000170 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n260\n%%EOF"
    )
    pdf_path = tmp_path / "meta.pdf"
    pdf_path.write_bytes(pdf_with_meta)

    meta = verify_pdf(pdf_path)
    assert meta.title == "Test Paper Title"
    assert meta.authors == ["Smith", "Jones"]


def test_verify_pdf_with_doi(tmp_path):
    """PDF with /doi metadata extracts the DOI."""
    pdf_with_doi = (
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"4 0 obj\n<< /doi (10.1016/j.jhydrol.2024.132471) >>\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000170 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n260\n%%EOF"
    )
    pdf_path = tmp_path / "doi.pdf"
    pdf_path.write_bytes(pdf_with_doi)

    meta = verify_pdf(pdf_path)
    assert meta.doi == "10.1016/j.jhydrol.2024.132471"


def test_verify_nonexistent_file():
    """Missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        verify_pdf("/nonexistent/path.pdf")


def test_verify_empty_file(tmp_path):
    """Empty file raises ValueError."""
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")

    with pytest.raises(ValueError, match="empty"):
        verify_pdf(empty)


def test_verify_not_a_pdf(tmp_path):
    """Non-PDF file raises ValueError."""
    not_pdf = tmp_path / "not_pdf.txt"
    not_pdf.write_text("Hello, I am not a PDF", encoding="utf-8")

    with pytest.raises(ValueError, match="Not a valid PDF"):
        verify_pdf(not_pdf)


# ---------------------------------------------------------------------------
# PdfMetadata
# ---------------------------------------------------------------------------


def test_pdf_metadata_defaults():
    """New PdfMetadata has empty defaults."""
    meta = PdfMetadata()
    assert meta.title == ""
    assert meta.authors == []
    assert meta.doi == ""
    assert meta.pages == 0


def test_pdf_metadata_as_dict():
    """as_dict serializes all fields."""
    meta = PdfMetadata(
        title="Test",
        authors=["Alice", "Bob"],
        doi="10.1000/test",
        pages=5,
        version="1.7",
        file_size_bytes=1024,
    )
    d = meta.as_dict()
    assert d["title"] == "Test"
    assert d["authors"] == ["Alice", "Bob"]
    assert d["doi"] == "10.1000/test"
    assert d["pages"] == 5
    assert d["version"] == "1.7"
    assert d["file_size_bytes"] == 1024


# ---------------------------------------------------------------------------
# URL constructors
# ---------------------------------------------------------------------------


def test_doi_to_url():
    """DOI is converted to the correct resolver URL."""
    assert doi_to_url("10.1016/j.jhydrol.2024.132471") == "https://doi.org/10.1016/j.jhydrol.2024.132471"


def test_pii_to_sciencedirect_url():
    """PII is converted to the correct ScienceDirect URL."""
    assert (
        pii_to_sciencedirect_url("S0022169424018675")
        == "https://www.sciencedirect.com/science/article/pii/S0022169424018675"
    )


# ---------------------------------------------------------------------------
# Output path resolution
# ---------------------------------------------------------------------------


def test_slug_from_doi_elsevier():
    """Elsevier DOI produces a clean slug."""
    slug = slug_from_doi("10.1016/j.jhydrol.2024.132471")
    assert slug == "j.jhydrol.2024.132471"


def test_slug_from_doi_special_chars():
    """Hyphens are preserved in slugs; truly problematic chars become underscores."""
    slug = slug_from_doi("10.1007/s11269-024-04000-0")
    assert slug == "s11269-024-04000-0"


def test_slug_from_doi_slashes_replaced():
    """Slash-separated components are collapsed."""
    slug = slug_from_doi("10.1080/02626667.2024.1234567")
    assert slug == "02626667.2024.1234567"


def test_slug_from_doi_with_prefix():
    """DOI with https prefix is normalized before slugification."""
    slug = slug_from_doi("https://doi.org/10.1029/2023WR036500")
    assert slug == "2023WR036500"


def test_default_pdf_dir_respects_env(monkeypatch, tmp_path):
    """MYLIBRARY_PDF_ROOT overrides the default papers directory."""
    custom = tmp_path / "custom-papers"
    monkeypatch.setenv("MYLIBRARY_PDF_ROOT", str(custom))
    assert default_pdf_dir() == custom


def test_default_pdf_dir_uses_outputs_when_no_env(monkeypatch):
    """Without MYLIBRARY_PDF_ROOT, uses mylibrary/outputs/papers."""
    monkeypatch.delenv("MYLIBRARY_PDF_ROOT", raising=False)
    # 产物根也只测"未配置"这一支;开发者 shell 里若设了它,这条断言会随
    # OUTPUT_ROOT 一起漂移,读起来就不像是在测默认值了。
    monkeypatch.delenv("HYDROLITAGENT_LITERATURE_ROOT", raising=False)
    from hydrolitagent.literature._paths import OUTPUT_ROOT

    assert default_pdf_dir() == OUTPUT_ROOT / "papers"


def test_output_path_for_doi():
    """DOI input generates a slug-based filename."""
    path = output_path_for("10.1016/j.jhydrol.2024.132471")
    assert path.name == "j.jhydrol.2024.132471.pdf"
    assert str(default_pdf_dir()) in str(path)


def test_output_path_for_pii():
    """PII input generates a slug-based filename."""
    path = output_path_for("S0022169424018675")
    assert path.name == "S0022169424018675.pdf"


def test_output_path_for_with_output_dir(tmp_path):
    """Custom output_dir overrides the default."""
    path = output_path_for("10.1016/j.jhydrol.2024.132471", output_dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name == "j.jhydrol.2024.132471.pdf"


# ---------------------------------------------------------------------------
# is_pdf_file — the boolean download guard (distinct from verify_pdf)
# ---------------------------------------------------------------------------


def test_is_pdf_file_true(tmp_path):
    """A file starting with %PDF- is recognized."""
    p = tmp_path / "ok.pdf"
    p.write_bytes(b"%PDF-1.7\n1 0 obj\n")
    assert is_pdf_file(p) is True


def test_is_pdf_file_false_for_non_pdf(tmp_path):
    """Non-PDF content returns False."""
    p = tmp_path / "nope.txt"
    p.write_text("security-verification HTML", encoding="utf-8")
    assert is_pdf_file(p) is False


def test_is_pdf_file_false_when_missing(tmp_path):
    """A missing file returns False instead of raising (unlike verify_pdf)."""
    assert is_pdf_file(tmp_path / "missing.pdf") is False


def test_is_pdf_file_vs_verify_pdf_semantics(tmp_path):
    """is_pdf_file returns a bool and never raises; verify_pdf returns metadata."""
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")

    # Same input, two different contracts — the reason the two names must not collide.
    assert is_pdf_file(bad) is False
    with pytest.raises(ValueError):
        verify_pdf(bad)


# ---------------------------------------------------------------------------
# copernicus_pdf_url
# ---------------------------------------------------------------------------


def test_copernicus_published_article_url():
    """Published 10.5194 suffix maps to the /articles/ URL layout."""
    assert (
        copernicus_pdf_url("hess-30-5327-2026")
        == "https://hess.copernicus.org/articles/30/5327/2026/hess-30-5327-2026.pdf"
    )


def test_copernicus_preprint_url_without_year_dir():
    """essd preprint suffix maps to /preprints/<suffix>/ (no year segment)."""
    assert (
        copernicus_pdf_url("essd-2026-528")
        == "https://essd.copernicus.org/preprints/essd-2026-528/essd-2026-528.pdf"
    )


def test_copernicus_preprint_egusphere_needs_year_dir():
    """egusphere preprints require a year directory segment."""
    assert (
        copernicus_pdf_url("egusphere-2026-528")
        == "https://egusphere.copernicus.org/preprints/2026/egusphere-2026-528/egusphere-2026-528.pdf"
    )


def test_copernicus_unrecognized_suffix_raises():
    """An unrecognized suffix raises ValueError."""
    with pytest.raises(ValueError, match="Copernicus suffix"):
        copernicus_pdf_url("not-a-copernicus-suffix")


# ---------------------------------------------------------------------------
# sd_flow reuses the shared PII→URL builder (no second copy of the logic)
# ---------------------------------------------------------------------------


def test_sd_flow_uses_shared_pii_url_builder():
    """``download_browser`` imports the very same function, not a copy."""
    from hydrolitagent.literature import download_browser, download_pdf

    assert download_browser.pii_to_sciencedirect_url is download_pdf.pii_to_sciencedirect_url


def test_sd_flow_calls_shared_pii_builder(tmp_path, monkeypatch):
    """sd_flow builds its article URL through the shared builder."""
    from hydrolitagent.literature import download_browser

    seen: list[str] = []

    def spy(pii: str) -> str:
        seen.append(pii)
        return "https://sentinel.example/"

    class FakePage:
        url = "https://not-signed.example/"

        async def goto(self, *a, **k):
            raise RuntimeError("stop right after the URL is built")

    async def fake_new_page(ctx):
        return FakePage()

    monkeypatch.setattr(download_browser, "pii_to_sciencedirect_url", spy)
    monkeypatch.setattr(download_browser, "new_page", fake_new_page)

    with pytest.raises(RuntimeError):
        asyncio.run(
            download_browser.sd_flow(object(), "S0022169423001234", tmp_path / "x.pdf")
        )
    assert seen == ["S0022169423001234"]


# ---------------------------------------------------------------------------
# setup_check — check-item construction (no network)
# ---------------------------------------------------------------------------


def test_setup_check_missing_keys_returns_1(monkeypatch, capsys):
    """Missing .env keys make setup_check fail (rc=1) and say which are missing."""
    from hydrolitagent.literature import download_pdf

    monkeypatch.setattr(download_pdf, "_load_dotenv", lambda: None)
    for key in ("ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID", "GDRIVE_PAPERS_PATH"):
        monkeypatch.delenv(key, raising=False)

    assert setup_check() == 1
    out = capsys.readouterr().out
    assert "missing in .env" in out


def test_setup_check_gdrive_not_a_directory_returns_1(monkeypatch, tmp_path, capsys):
    """A non-directory GDRIVE_PAPERS_PATH fails, without touching the Zotero API."""
    from hydrolitagent.literature import download_pdf

    monkeypatch.setattr(download_pdf, "_load_dotenv", lambda: None)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", str(tmp_path / "does-not-exist"))

    assert setup_check() == 1
    assert "not a directory" in capsys.readouterr().out


def test_setup_check_success_returns_0(monkeypatch, tmp_path, capsys):
    """All keys present, GDrive writable, Zotero API stubbed → rc=0."""
    from hydrolitagent.literature import download_pdf

    monkeypatch.setattr(download_pdf, "_load_dotenv", lambda: None)
    gdrive = tmp_path / "papers"
    gdrive.mkdir()
    monkeypatch.setenv("ZOTERO_API_KEY", "dummy-key")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "1")
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", str(gdrive))

    class FakeZotero:
        def __init__(self, *a, **k):
            pass

        def items(self, limit=1):
            return []

    fake = types.ModuleType("pyzotero")
    fake.zotero = types.SimpleNamespace(Zotero=FakeZotero)
    monkeypatch.setitem(sys.modules, "pyzotero", fake)

    assert setup_check() == 0
    out = capsys.readouterr().out
    assert "env keys present" in out
    assert "credentials valid" in out


# ---------------------------------------------------------------------------
# download_paper — orchestration exit codes (curl mocked, no network/browser)
# ---------------------------------------------------------------------------


def test_download_paper_default_out_dir():
    """The default output directory is unchanged (.playwright-mcp)."""
    assert DEFAULT_OUT == Path(".playwright-mcp")


def test_download_paper_arxiv_success_returns_0(tmp_path, monkeypatch):
    """Successful arXiv curl → exit code 0."""
    from hydrolitagent.literature import download_pdf

    def fake_curl(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.7\n")
        return True

    monkeypatch.setattr(download_pdf, "curl_download", fake_curl)
    assert download_pdf.download_paper(arxiv="2608.18495", out_dir=tmp_path) == 0
    assert (tmp_path / "arXiv.2608.18495.pdf").exists()


def test_download_paper_arxiv_failure_returns_1(tmp_path, monkeypatch):
    """A failed arXiv curl → exit code 1."""
    from hydrolitagent.literature import download_pdf

    monkeypatch.setattr(download_pdf, "curl_download", lambda url, dest: False)
    assert download_pdf.download_paper(arxiv="2608.18495", out_dir=tmp_path) == 1


# ---------------------------------------------------------------------------
# Browser fallback: challenge detection, generic flow, headless-first routing
# (fake page/context only — no Playwright, no network)
# ---------------------------------------------------------------------------


class _FakeDownload:
    """Stand-in for a Playwright Download; ``save_as`` writes the payload."""

    def __init__(self, payload: bytes):
        self.payload = payload

    async def save_as(self, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(self.payload)


class _FakeDownloadInfo:
    """``await info.value`` resolves the next scripted outcome (or times out)."""

    def __init__(self, page):
        self._page = page

    @property
    def value(self):
        async def _resolve():
            outcome = self._page.pop_outcome()
            if outcome is None:
                raise TimeoutError("no download started")
            return _FakeDownload(outcome["payload"])

        return _resolve()


class _FakeExpectDownload:
    def __init__(self, page):
        self._page = page

    async def __aenter__(self):
        self._page.expecting = True
        return _FakeDownloadInfo(self._page)

    async def __aexit__(self, *exc):
        self._page.expecting = False
        return False


class FakePage:
    """Minimal Playwright Page: scripted outcomes, no I/O."""

    def __init__(self, outcomes=None, *, title="Article", challenge=False, url="https://doi.org/x",
                 pdf_candidates=None):
        self.outcomes = list(outcomes or [])
        self.title_text = title
        self.challenge = challenge
        self.pdf_candidates = pdf_candidates
        self.url = url
        self.expecting = False
        self.goto_calls: list[str] = []
        self.evaluate_calls: list[str] = []

    def pop_outcome(self):
        return self.outcomes.pop(0) if self.outcomes else None

    def peek_outcome(self):
        return self.outcomes[0] if self.outcomes else None

    def expect_download(self, timeout=None):
        return _FakeExpectDownload(self)

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        self.url = url
        outcome = self.peek_outcome()
        if outcome and outcome.get("goto_raises"):
            raise RuntimeError("Download is starting")
        return None

    async def title(self):
        return self.title_text

    async def evaluate(self, script, *args):
        self.evaluate_calls.append(script)
        if "citation_pdf_url" in script:
            if callable(self.pdf_candidates):
                return self.pdf_candidates()
            return self.pdf_candidates or []
        if isinstance(self.challenge, list):
            return self.challenge.pop(0) if self.challenge else False
        return self.challenge


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status
        self.url = ""

    async def body(self):
        return self._body


class _FakeRequest:
    """Stand-in for ``ctx.request`` (shares cookies, returns raw bytes)."""

    def __init__(self, body: bytes | None):
        self._body = body
        self.calls: list[str] = []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self._body is None:
            return _FakeResponse(b"<html>403</html>", status=403)
        return _FakeResponse(self._body)


class FakeContext:
    def __init__(self, page=None, *, pdf_bytes=None):
        self._page = page or FakePage()
        self.closed = 0
        self.request = _FakeRequest(pdf_bytes)
        self.response_handlers = []

    def on(self, event, handler):
        if event == "response":
            self.response_handlers.append(handler)

    def remove_listener(self, event, handler):
        if handler in self.response_handlers:
            self.response_handlers.remove(handler)

    def emit_response(self, resp):
        for handler in list(self.response_handlers):
            handler(resp)

    @property
    def pages(self):
        return [self._page]

    async def new_page(self):
        return self._page

    async def close(self):
        self.closed += 1


def _pdf_payload() -> bytes:
    return b"%PDF-1.7\nfake\n%%EOF\n"


def test_challenge_pending_detects_cloudflare_iframe():
    """A visible Cloudflare challenge node counts as pending."""
    from hydrolitagent.literature import download_browser

    page = FakePage(title="Article", challenge=True)
    assert asyncio.run(download_browser.challenge_pending(page)) is True


def test_challenge_pending_detects_verification_title():
    """A 'Just a moment' title counts as pending even without DOM nodes."""
    from hydrolitagent.literature import download_browser

    page = FakePage(title="Just a moment...", challenge=False)
    assert asyncio.run(download_browser.challenge_pending(page)) is True


def test_challenge_pending_ignores_normal_page():
    """An ordinary article page is not a challenge."""
    from hydrolitagent.literature import download_browser

    page = FakePage(title="A paper", challenge=False)
    assert asyncio.run(download_browser.challenge_pending(page)) is False


def test_wait_challenge_clear_returns_true_when_clear():
    """wait_challenge_clear reports success instead of returning None."""
    from hydrolitagent.literature import download_browser

    page = FakePage(title="A paper", challenge=False)
    assert asyncio.run(download_browser.wait_challenge_clear(page, timeout_s=1)) is True


def test_wait_challenge_clear_returns_false_on_timeout():
    """A timeout is distinguishable from success (the old code returned None)."""
    from hydrolitagent.literature import download_browser

    page = FakePage(title="请稍候...", challenge=True)
    assert asyncio.run(download_browser.wait_challenge_clear(page, timeout_s=0)) is False


def test_generic_pdf_flow_uses_citation_pdf_url(tmp_path, monkeypatch):
    """The first candidate that yields a PDF wins."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage([{"payload": _pdf_payload()}])
    ctx = FakeContext(page)

    async def candidates(p, doi):
        return ["https://example.org/citation.pdf", "https://example.org/other.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.1/x", {}, dest)) is True
    assert dest.read_bytes() == _pdf_payload()
    assert page.goto_calls[-1] == "https://example.org/citation.pdf"


def test_generic_pdf_flow_falls_back_to_doi_pdf_url(tmp_path, monkeypatch):
    """When the first candidate never downloads, the next one is tried."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage([None, {"payload": _pdf_payload()}])
    ctx = FakeContext(page)

    async def candidates(p, doi):
        return ["https://example.org/a.pdf", "https://example.org/b.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.1/x", {}, dest)) is True
    assert dest.read_bytes() == _pdf_payload()


def test_generic_pdf_flow_tolerates_download_started_goto_error(tmp_path, monkeypatch):
    """Navigation raising 'Download is starting' still yields the file."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage([{"payload": _pdf_payload(), "goto_raises": True}])
    ctx = FakeContext(page)

    async def candidates(p, doi):
        return ["https://example.org/paper.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.1/x", {}, dest)) is True
    assert dest.read_bytes() == _pdf_payload()


def test_generic_pdf_flow_rejects_html_and_removes_dest(tmp_path, monkeypatch):
    """An HTML page saved as .pdf is rejected and deleted."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage([{"payload": b"<html>not a pdf</html>"}, None])
    ctx = FakeContext(page)

    async def candidates(p, doi):
        return ["https://example.org/a.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.1/x", {}, dest)) is False
    assert not dest.exists()


def test_launch_mcp_passes_headless(tmp_path, monkeypatch):
    """launch_mcp forwards the headless flag to Playwright."""
    from hydrolitagent.literature import download_browser

    seen = {}

    class FakeChromium:
        async def launch_persistent_context(self, **kwargs):
            seen.update(kwargs)
            return object()

    class FakePW:
        chromium = FakeChromium()

    monkeypatch.setattr(download_browser, "find_mcp_profile", lambda: tmp_path)

    asyncio.run(download_browser.launch_mcp(FakePW(), tmp_path, headless=True))
    assert seen["headless"] is True


def test_wiley_flow_uses_shared_goto_download(tmp_path, monkeypatch):
    """wiley_flow delegates to the shared primitive instead of duplicating it."""
    from hydrolitagent.literature import download_browser

    calls = []

    async def spy(page, url, dest, timeout_ms=150_000):
        calls.append(url)
        return True

    async def fake_new_page(ctx):
        return FakePage()

    monkeypatch.setattr(download_browser, "goto_download", spy)
    monkeypatch.setattr(download_browser, "new_page", fake_new_page)

    ok = asyncio.run(
        download_browser.wiley_flow(FakeContext(), "10.1029/2025WR042530", tmp_path / "x.pdf")
    )

    assert ok is True
    assert calls == [
        "https://agupubs.onlinelibrary.wiley.com/doi/pdfdirect/10.1029/2025WR042530?download=true"
    ]


def _patch_router(monkeypatch, *, attempts, curl_ok=False):
    """Wire download_with_browser's seams for routing tests."""
    from hydrolitagent.literature import download_browser

    recorded = {"headless": []}

    def fake_curl(article, pdf, dest):
        if curl_ok:
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(_pdf_payload())
        return curl_ok

    async def fake_attempt(*, headless, out_dir, prefix, doi, meta, dest):
        recorded["headless"].append(headless)
        result = attempts.pop(0) if attempts else (False, False)
        if result[0]:
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(_pdf_payload())
        return result

    monkeypatch.setattr(download_browser, "curl_with_cookies", fake_curl)
    monkeypatch.setattr(download_browser, "_attempt", fake_attempt)
    return recorded


def test_download_with_browser_unknown_prefix_uses_generic_flow(tmp_path, monkeypatch):
    """An unscripted prefix is attempted instead of raising SystemExit."""
    from hydrolitagent.literature import download_browser

    recorded = _patch_router(monkeypatch, attempts=[(True, False)])
    meta = {"prefix": "10.1080", "suffix": "x"}

    dest = asyncio.run(download_browser.download_with_browser("10.1080/0000000", meta, tmp_path))

    assert dest is not None and dest.exists()
    assert recorded["headless"] == [True]


def test_download_with_browser_1126_curl_failure_falls_back_to_browser(tmp_path, monkeypatch):
    """science.org curl failure no longer ends the attempt."""
    from hydrolitagent.literature import download_browser

    recorded = _patch_router(monkeypatch, attempts=[(True, False)], curl_ok=False)
    meta = {"prefix": "10.1126", "suffix": "sciadv.aeb1692"}

    dest = asyncio.run(
        download_browser.download_with_browser("10.1126/sciadv.aeb1692", meta, tmp_path)
    )

    assert dest is not None and dest.exists()
    assert recorded["headless"] == [True]


def test_download_with_browser_1126_curl_success_skips_browser(tmp_path, monkeypatch):
    """A working curl path never launches a browser."""
    from hydrolitagent.literature import download_browser

    recorded = _patch_router(monkeypatch, attempts=[], curl_ok=True)
    meta = {"prefix": "10.1126", "suffix": "sciadv.aeb1692"}

    dest = asyncio.run(
        download_browser.download_with_browser("10.1126/sciadv.aeb1692", meta, tmp_path)
    )

    assert dest is not None and dest.exists()
    assert recorded["headless"] == []


def test_download_with_browser_escalates_to_headed_when_challenge_persists(
    tmp_path, monkeypatch, capsys
):
    """A pending challenge triggers one headed retry and an auto-continue notice."""
    from hydrolitagent.literature import download_browser

    recorded = _patch_router(monkeypatch, attempts=[(False, True), (True, False)])
    meta = {"prefix": "10.1080", "suffix": "x"}

    dest = asyncio.run(download_browser.download_with_browser("10.1080/0000000", meta, tmp_path))

    assert dest is not None and dest.exists()
    assert recorded["headless"] == [True, False]
    assert "自动继续" in capsys.readouterr().out


def test_download_with_browser_retries_headed_after_headless_failure(tmp_path, monkeypatch, capsys):
    """A headless failure is not proof the paper is unavailable — retry visible.

    The visible pass may also be needed when no challenge was shown at all, so
    "no challenge" must not short-circuit the retry.
    """
    from hydrolitagent.literature import download_browser

    recorded = _patch_router(monkeypatch, attempts=[(False, False), (True, False)])
    meta = {"prefix": "10.1080", "suffix": "x"}

    dest = asyncio.run(download_browser.download_with_browser("10.1080/0000000", meta, tmp_path))

    assert dest is not None and dest.exists()
    assert recorded["headless"] == [True, False]
    out = capsys.readouterr().out
    # No challenge was seen, so do not tell the user to pass verification.
    assert "人机验证" not in out


def test_download_with_browser_goes_straight_to_headed_for_sciencedirect(
    tmp_path, monkeypatch
):
    """ScienceDirect always needs a visible session with a human click."""
    from hydrolitagent.literature import download_browser

    recorded = _patch_router(monkeypatch, attempts=[(True, False)])
    meta = {"prefix": "10.1016", "suffix": "x", "pii": "S0022169426016069"}

    dest = asyncio.run(download_browser.download_with_browser("10.1016/x", meta, tmp_path))

    assert dest is not None and dest.exists()
    assert recorded["headless"] == [False]


def test_download_with_browser_removes_non_pdf_dest_on_failure(tmp_path, monkeypatch):
    """A leftover non-PDF file is deleted rather than reported as success."""
    from hydrolitagent.literature import download_browser

    _patch_router(monkeypatch, attempts=[(False, False)])
    dest = tmp_path / "10.1080.0000000.pdf"
    dest.write_bytes(b"<html>nope</html>")
    meta = {"prefix": "10.1080", "suffix": "x"}

    assert (
        asyncio.run(download_browser.download_with_browser("10.1080/0000000", meta, tmp_path))
        is None
    )
    assert not dest.exists()


def test_attempt_headless_uses_short_challenge_grace(tmp_path, monkeypatch):
    """A headless attempt must not stall on a challenge nobody can solve."""
    from hydrolitagent.literature import download_browser

    recorded = {}

    class FakePW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_import():
        return FakePW

    async def fake_launch(pw, out, *, headless):
        return FakeContext()

    async def fake_scripted(ctx, prefix, doi, meta, dest):
        return False

    async def fake_generic(ctx, doi, meta, dest, *, challenge_timeout_s=None):
        recorded["timeout"] = challenge_timeout_s
        return False

    async def no_challenge(ctx):
        return False

    monkeypatch.setattr(download_browser, "_import_playwright", fake_import)
    monkeypatch.setattr(download_browser, "_launch_context", fake_launch)
    monkeypatch.setattr(download_browser, "_run_scripted", fake_scripted)
    monkeypatch.setattr(download_browser, "generic_flow", fake_generic)
    monkeypatch.setattr(download_browser, "_any_challenge_pending", no_challenge)

    asyncio.run(
        download_browser._attempt(
            headless=True,
            out_dir=tmp_path,
            prefix="10.1080",
            doi="10.1080/x",
            meta={"suffix": "x"},
            dest=tmp_path / "x.pdf",
        )
    )

    assert recorded["timeout"] == download_browser.HEADLESS_CHALLENGE_GRACE_S


def test_attempt_falls_back_to_generic_when_scripted_flow_crashes(tmp_path, monkeypatch):
    """A crashing scripted flow must not skip the generic fallback."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "x.pdf"

    class FakePW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_import():
        return FakePW

    async def fake_launch(pw, out, *, headless):
        return FakeContext()

    async def boom(ctx, prefix, doi, meta, dest):
        raise RuntimeError("no pdf link")

    async def fake_generic(ctx, doi, meta, d, *, challenge_timeout_s=None):
        Path(d).write_bytes(_pdf_payload())
        return True

    async def no_challenge(ctx):
        return False

    monkeypatch.setattr(download_browser, "_import_playwright", fake_import)
    monkeypatch.setattr(download_browser, "_launch_context", fake_launch)
    monkeypatch.setattr(download_browser, "_run_scripted", boom)
    monkeypatch.setattr(download_browser, "generic_flow", fake_generic)
    monkeypatch.setattr(download_browser, "_any_challenge_pending", no_challenge)

    ok, challenged = asyncio.run(
        download_browser._attempt(
            headless=True,
            out_dir=tmp_path,
            prefix="10.1038",
            doi="10.1038/x",
            meta={"suffix": "x"},
            dest=dest,
        )
    )

    assert ok is True and challenged is False
    assert dest.exists()


def test_download_paper_browser_crash_returns_1(tmp_path, monkeypatch, capsys):
    """A crashing browser flow becomes exit code 1, not a traceback."""
    from hydrolitagent.literature import download_browser, download_pdf

    monkeypatch.setattr(
        download_pdf,
        "crossref_meta",
        lambda doi: {
            "title": "T",
            "container": "C",
            "type": "article",
            "pii": None,
            "prefix": "10.1080",
            "suffix": "x",
        },
    )

    async def boom(doi, meta, out_dir):
        raise RuntimeError("browser exploded")

    monkeypatch.setattr(download_browser, "download_with_browser", boom)

    assert download_pdf.download_paper(doi="10.1080/0000000", out_dir=tmp_path) == 1
    assert "browser exploded" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Review follow-ups: false positives, repeated challenges, real coverage
# ---------------------------------------------------------------------------


def test_ensure_utf8_stdio_reconfigures_both_streams(monkeypatch):
    """Windows defaults to GBK; unicode log lines must not crash the run."""
    from hydrolitagent.literature import download_pdf

    class FakeStream:
        def __init__(self):
            self.kwargs = None

        def reconfigure(self, **kwargs):
            self.kwargs = kwargs

    out, err = FakeStream(), FakeStream()
    monkeypatch.setattr(download_pdf.sys, "stdout", out)
    monkeypatch.setattr(download_pdf.sys, "stderr", err)

    download_pdf._ensure_utf8_stdio()

    assert out.kwargs["encoding"] == "utf-8"
    assert err.kwargs["encoding"] == "utf-8"


def test_curl_with_cookies_does_not_print_the_article_body(monkeypatch, tmp_path):
    """The cookie-setting request must not dump the Cloudflare page to stdout."""
    import os

    from hydrolitagent.literature import download_pdf

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return None

    monkeypatch.setattr(download_pdf.subprocess, "run", fake_run)
    download_pdf.curl_with_cookies("https://example.org/a", "https://example.org/a.pdf",
                                   tmp_path / "x.pdf")

    first = calls[0]
    assert "-o" in first
    assert first[first.index("-o") + 1] == os.devnull


def test_verify_pdf_decodes_utf16_literal_title(tmp_path):
    """A UTF-16 /Title inside a literal string must not become 'þÿ E v a l...'."""
    from hydrolitagent.literature import download_pdf

    text = "Evaluating space-based methane detection"
    raw = b"\xfe\xff" + text.encode("utf-16-be")
    pdf = tmp_path / "utf16.pdf"
    pdf.write_bytes(
        b"%PDF-1.7\n1 0 obj << /Title (" + raw + b") /Author (\xfe\xff"
        + "Reuland, Frances E.".encode("utf-16-be") + b") >> endobj\n%%EOF\n"
    )

    meta = download_pdf.verify_pdf(pdf)

    assert meta.title == text
    assert meta.authors == ["Reuland, Frances E."]


def test_fetch_crossref_retries_once_before_giving_up(monkeypatch):
    """A transient Crossref hiccup must not silently corrupt the item."""
    from hydrolitagent.zotero import paper_to_zotero as p2z

    calls = {"n": 0}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"message": {"title": ["Recovered"], "author": []}}'

    def flaky(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection reset")
        return FakeResp()

    monkeypatch.setattr(p2z.urllib.request, "urlopen", flaky)

    assert p2z.fetch_crossref("10.1038/x") == {"title": ["Recovered"], "author": []}
    assert calls["n"] == 2


class _FakeControl:
    """Stands in for a Playwright locator for the page's PDF button."""

    def __init__(self, ctx, response=None):
        self._ctx = ctx
        self._response = response
        self.clicked = 0

    async def click(self, timeout=None, **kwargs):
        self.clicked += 1
        if self._response is not None:
            self._ctx.emit_response(self._response)


class _FakePlaywrightResponse:
    def __init__(self, body: bytes, content_type="application/pdf", url="https://x/y.pdf",
                 status=200):
        self.headers = {"content-type": content_type}
        self.url = url
        self.status = status
        self._body = body

    async def body(self):
        return self._body


def test_capture_pdf_response_saves_first_pdf_response(tmp_path, monkeypatch):
    """The PDF arrives as a normal response; capture it as soon as it does."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    ctx = FakeContext(pdf_bytes=_pdf_payload())
    control = _FakeControl(ctx, _FakePlaywrightResponse(_pdf_payload()))

    async def find(p):
        return control

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    assert asyncio.run(
        download_browser.capture_pdf_response(ctx, FakePage(), dest, timeout_s=10)
    ) is True
    assert dest.read_bytes() == _pdf_payload()
    # The bytes come from re-fetching the recorded URL, not from resp.body().
    assert ctx.request.calls == ["https://x/y.pdf"]
    assert control.clicked == 1
    assert ctx.response_handlers == []  # listener removed


def test_capture_pdf_response_ignores_non_pdf_responses(tmp_path, monkeypatch):
    """An HTML response must not be written as the PDF."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    ctx = FakeContext()
    control = _FakeControl(
        ctx, _FakePlaywrightResponse(b"<html>nope</html>", content_type="text/html")
    )

    async def find(p):
        return control

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    assert asyncio.run(
        download_browser.capture_pdf_response(ctx, FakePage(), dest, timeout_s=0.3)
    ) is False
    assert not dest.exists()


def test_capture_pdf_response_rejects_partial_pdf(tmp_path, monkeypatch):
    """A 206 range response is a fragment; saving it would corrupt the file."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    ctx = FakeContext()
    control = _FakeControl(
        ctx, _FakePlaywrightResponse(_pdf_payload(), status=206)
    )

    async def find(p):
        return control

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    assert asyncio.run(
        download_browser.capture_pdf_response(ctx, FakePage(), dest, timeout_s=0.3)
    ) is False
    assert not dest.exists()


def test_capture_pdf_response_rejects_truncated_pdf(tmp_path, monkeypatch):
    """Without %%EOF the body is incomplete even though it starts with %PDF-."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    half = b"%PDF-1.7\nhalf a file\n"
    ctx = FakeContext(pdf_bytes=half)
    control = _FakeControl(ctx, _FakePlaywrightResponse(half))

    async def find(p):
        return control

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    assert asyncio.run(
        download_browser.capture_pdf_response(ctx, FakePage(), dest, timeout_s=0.3)
    ) is False
    assert not dest.exists()


def test_generic_flow_only_waits_for_a_control_on_spa_prefixes(tmp_path, monkeypatch):
    """Non-SPA publishers must not pay the toolbar-render wait."""
    from hydrolitagent.literature import download_browser

    waits = []

    async def capture(ctx, page, dest, *, timeout_s=None, control_wait_s=0, settle_s=None):
        waits.append((control_wait_s, timeout_s, settle_s))
        return False

    async def candidates(p, doi):
        return []

    monkeypatch.setattr(download_browser, "capture_pdf_response", capture)
    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    asyncio.run(download_browser.generic_flow(
        FakeContext(), "10.1080/x", {"prefix": "10.1080"}, tmp_path / "a.pdf"))
    asyncio.run(download_browser.generic_flow(
        FakeContext(), "10.3724/x", {"prefix": "10.3724"}, tmp_path / "b.pdf"))

    assert waits == [
        (0, download_browser.PDF_RESPONSE_TIMEOUT_S, download_browser.PDF_CONTROL_SETTLE_S),
        (download_browser.PDF_CONTROL_WAIT_S, download_browser.PDF_RESPONSE_TIMEOUT_SPA_S,
         download_browser.PDF_SPA_SETTLE_S),
    ]
    # A slow SPA (sciengine can take minutes) gets a longer budget than the rest.
    assert download_browser.PDF_RESPONSE_TIMEOUT_SPA_S > download_browser.PDF_RESPONSE_TIMEOUT_S


def test_capture_pdf_response_returns_false_without_a_control(tmp_path, monkeypatch):
    """No PDF control on the page → return at once, do not burn the timeout."""
    from hydrolitagent.literature import download_browser

    async def find(p):
        return None

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    started = time.monotonic()
    assert asyncio.run(
        download_browser.capture_pdf_response(
            FakeContext(), FakePage(), tmp_path / "x.pdf", timeout_s=30
        )
    ) is False
    assert time.monotonic() - started < 2


def test_capture_pdf_response_times_out(tmp_path, monkeypatch):
    """No response within the budget → False, cleanly."""
    from hydrolitagent.literature import download_browser

    ctx = FakeContext()
    control = _FakeControl(ctx, None)  # clicks, but no PDF ever arrives

    async def find(p):
        return control

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    assert asyncio.run(
        download_browser.capture_pdf_response(ctx, FakePage(), tmp_path / "x.pdf",
                                              timeout_s=0.3)
    ) is False
    assert ctx.response_handlers == []


def test_capture_pdf_response_early_exit_does_not_wait_for_timeout(tmp_path, monkeypatch):
    """A PDF that arrives immediately must not wait out the 120s budget."""
    from hydrolitagent.literature import download_browser

    ctx = FakeContext(pdf_bytes=_pdf_payload())
    control = _FakeControl(ctx, _FakePlaywrightResponse(_pdf_payload()))

    async def find(p):
        return control

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    started = time.monotonic()
    assert asyncio.run(
        download_browser.capture_pdf_response(ctx, FakePage(), tmp_path / "x.pdf",
                                              timeout_s=120)
    ) is True
    assert time.monotonic() - started < 5


class _RetryControl:
    """First click does nothing (handler not bound yet), second one works."""

    def __init__(self, ctx, response):
        self._ctx = ctx
        self._response = response
        self.clicked = 0

    async def click(self, timeout=None, **kwargs):
        self.clicked += 1
        if self.clicked >= 2:
            self._ctx.emit_response(self._response)


def test_capture_pdf_response_reclicks_when_nothing_arrives(tmp_path, monkeypatch):
    """A click sent before the SPA bound its handler must not sink the run."""
    from hydrolitagent.literature import download_browser

    monkeypatch.setattr(download_browser, "PDF_CONTROL_SETTLE_S", 0)
    monkeypatch.setattr(download_browser, "PDF_RESPONSE_RECLICK_S", 0.2)

    ctx = FakeContext(pdf_bytes=_pdf_payload())
    control = _RetryControl(ctx, _FakePlaywrightResponse(_pdf_payload()))

    async def find(p):
        return control

    monkeypatch.setattr(download_browser, "_find_pdf_control", find)

    assert asyncio.run(
        download_browser.capture_pdf_response(ctx, FakePage(), tmp_path / "x.pdf",
                                              timeout_s=5)
    ) is True
    assert control.clicked == 2


def test_generic_flow_tries_response_capture_before_url_candidates(tmp_path, monkeypatch):
    """The control-driven path is authoritative when the page offers it."""
    from hydrolitagent.literature import download_browser

    order = []

    async def capture(ctx, page, dest, *, timeout_s=None, control_wait_s=0, settle_s=None):
        order.append("capture")
        Path(dest).write_bytes(_pdf_payload())
        return True

    async def candidates(p, doi):
        order.append("candidates")
        return ["https://example.org/a.pdf"]

    monkeypatch.setattr(download_browser, "capture_pdf_response", capture)
    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    dest = tmp_path / "out.pdf"
    assert asyncio.run(
        download_browser.generic_flow(FakeContext(), "10.1/x", {}, dest)
    ) is True
    assert order == ["capture"]


def test_headless_only_prefixes_include_3724():
    """sciengine answers headless with 403; do not waste an attempt."""
    from hydrolitagent.literature import download_browser

    assert "10.3724" in download_browser.HEADED_ONLY_PREFIXES


def test_generic_pdf_flow_uses_context_request_bytes(tmp_path, monkeypatch):
    """An inline PDF opens the viewer instead of downloading — fetch bytes."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage(url="https://www.sciengine.com/JHE/doi/x")
    ctx = FakeContext(page, pdf_bytes=_pdf_payload())

    async def candidates(p, doi):
        return ["https://www.sciengine.com/0559-9350/x.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.3724/x", {}, dest)) is True
    assert dest.read_bytes() == _pdf_payload()
    # No navigation to the PDF was needed.
    assert page.goto_calls == []


def test_pdf_url_candidates_polls_until_the_spa_renders():
    """sciengine injects citation_pdf_url only after its JS runs."""
    from hydrolitagent.literature import download_browser

    seq = [[], ["https://www.sciengine.com/0559-9350/x.pdf"]]
    page = FakePage(
        url="https://www.sciengine.com/JHE/doi/10.3724/x",
        pdf_candidates=lambda: seq.pop(0) if len(seq) > 1 else seq[0],
    )

    urls = asyncio.run(download_browser._pdf_url_candidates(page, "10.3724/x", wait_s=5))

    assert urls[0] == "https://www.sciengine.com/0559-9350/x.pdf"


def test_generic_flow_skips_navigation_when_page_is_already_loaded(tmp_path, monkeypatch):
    """A second goto on the same page aborts the first redirect chain."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage([{"payload": _pdf_payload()}], url="https://publisher.example/paper")
    ctx = FakeContext(page)

    async def candidates(p, doi):
        return ["https://publisher.example/paper.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.1/x", {}, dest)) is True
    assert page.goto_calls == ["https://publisher.example/paper.pdf"]


def test_fetch_crossref_unescapes_double_escaped_entities(monkeypatch):
    """Crossref sometimes returns &amp;ldquo; — the item title must not show it."""
    from hydrolitagent.zotero import paper_to_zotero as p2z

    title = "Causation of the &amp;ldquo;8&amp;middot;26&amp;rdquo; chain"
    payload = json.dumps({"message": {"title": [title], "author": []}}).encode()

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(p2z.urllib.request, "urlopen", lambda *a, **k: FakeResp())

    msg = p2z.fetch_crossref("10.3724/x")

    assert msg["title"] == ["Causation of the “8·26” chain"]


def test_pick_doi_by_title_prefers_an_exact_normalized_match():
    """Punctuation/case differences must not stop an exact title match."""
    from hydrolitagent.literature import download_pdf

    items = [
        {"DOI": "10.1/other", "title": ["Something else entirely"]},
        {"DOI": "10.1/exact", "title": ["Baseflow Separation: Methods & Evaluation"]},
    ]

    doi, _ = download_pdf.pick_doi_by_title("baseflow separation methods evaluation", items)

    assert doi == "10.1/exact"


def test_pick_doi_by_title_prefers_the_published_version():
    """Same title in a journal and as a preprint → take the journal one."""
    from hydrolitagent.literature import download_pdf

    items = [
        {"DOI": "10.22541/preprint", "type": "posted-content",
         "title": ["Quantitative Evaluation of Baseflow Separation Methods"]},
        {"DOI": "10.1029/journal", "type": "journal-article",
         "title": ["Quantitative evaluation of baseflow separation methods"]},
    ]

    doi, _ = download_pdf.pick_doi_by_title(
        "Quantitative Evaluation of Baseflow Separation Methods", items
    )

    assert doi == "10.1029/journal"


def test_pick_doi_by_title_prefers_published_when_scores_tie():
    """A journal paper and its preprint score identically — take the journal."""
    from hydrolitagent.literature import download_pdf

    items = [
        {"DOI": "10.5194/egusphere", "type": "posted-content",
         "title": ["The need for uncertainty: why probabilistic LSTMs are key to "
                   "improving flood prediction"]},
        {"DOI": "10.5194/hess", "type": "journal-article",
         "title": ["The need for uncertainty: why probabilistic LSTMs are key to "
                   "improving flood prediction"]},
    ]

    doi, _ = download_pdf.pick_doi_by_title("Probabilistic LSTMs for flood prediction", items)

    assert doi == "10.5194/hess"


def test_pick_doi_by_title_refuses_an_ambiguous_field():
    """Two near-identical candidates → return None rather than guessing."""
    from hydrolitagent.literature import download_pdf

    # The real Crossref field for this query: two different papers whose titles
    # both contain every word the user typed.
    items = [
        {"DOI": "10.1/a",
         "title": ["Comprehensive evaluation of baseflow separation methods for India"]},
        {"DOI": "10.1/b",
         "title": ["Quantitative evaluation of baseflow separation methods with a model"]},
    ]

    doi, candidates = download_pdf.pick_doi_by_title(
        "Baseflow Separation Methods Evaluation", items
    )

    assert doi is None
    assert len(candidates) == 2


def test_pick_doi_by_title_accepts_a_clear_winner():
    """One candidate overlaps strongly and leads the runner-up by a margin."""
    from hydrolitagent.literature import download_pdf

    items = [
        {"DOI": "10.1/win", "title": ["Baseflow separation methods evaluation for India"]},
        {"DOI": "10.1/lose", "title": ["Groundwater modelling in Denmark"]},
    ]

    doi, _ = download_pdf.pick_doi_by_title("Baseflow Separation Methods Evaluation", items)

    assert doi == "10.1/win"


def test_pick_doi_by_title_returns_none_without_items():
    from hydrolitagent.literature import download_pdf

    assert download_pdf.pick_doi_by_title("anything", [])[0] is None


def test_download_paper_title_resolves_then_downloads(tmp_path, monkeypatch):
    """A title is resolved to a DOI and the normal DOI path is used."""
    from hydrolitagent.literature import download_browser, download_pdf

    monkeypatch.setattr(download_pdf, "search_crossref_by_title",
                        lambda t: [{"DOI": "10.1/x", "title": ["The Real Title"]}])
    monkeypatch.setattr(download_pdf, "pick_doi_by_title", lambda t, i: ("10.1/x", i))
    monkeypatch.setattr(download_pdf, "crossref_meta", lambda doi: {
        "title": "T", "container": "C", "type": "article", "pii": None,
        "prefix": "10.1", "suffix": "x",
    })

    async def fake_dl(doi, meta, out_dir):
        p = Path(out_dir) / "x.pdf"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_pdf_payload())
        return p

    monkeypatch.setattr(download_browser, "download_with_browser", fake_dl)

    assert download_pdf.download_paper(title="The Real Title", out_dir=tmp_path) == 0


def test_download_paper_title_ambiguous_returns_2_without_downloading(tmp_path, monkeypatch, capsys):
    """Never guess: list the candidates and stop."""
    from hydrolitagent.literature import download_browser, download_pdf

    monkeypatch.setattr(download_pdf, "search_crossref_by_title", lambda t: [{"DOI": "x"}])
    monkeypatch.setattr(download_pdf, "pick_doi_by_title", lambda t, i: (
        None, [{"DOI": "10.1/a", "title": ["A"]}, {"DOI": "10.1/b", "title": ["B"]}],
    ))

    async def must_not_run(*a, **k):
        raise AssertionError("must not download on an ambiguous title")

    monkeypatch.setattr(download_browser, "download_with_browser", must_not_run)

    assert download_pdf.download_paper(title="Baseflow Evaluation", out_dir=tmp_path) == 2
    out = capsys.readouterr().out
    assert "10.1/a" in out and "10.1/b" in out


def test_entry_gate_ignores_weak_markers_that_match_paper_titles():
    """'Security check of levee systems' must not gate the entry check."""
    from hydrolitagent.literature import download_browser

    page = FakePage(title="Security check of levee systems", challenge=False)

    # The full marker set still treats it as suspicious once a flow is running…
    assert asyncio.run(download_browser.challenge_pending(page)) is True
    # …but the entry gate only trusts interstitial copy, so it proceeds at once.
    assert asyncio.run(
        download_browser.wait_challenge_clear(
            page, timeout_s=1, markers=download_browser.ENTRY_TITLE_MARKERS
        )
    ) is True


def test_challenge_pending_does_not_flag_paper_titles_with_verification():
    """'Verification of a streamflow model' is a title, not a challenge."""
    from hydrolitagent.literature import download_browser

    page = FakePage(title="Verification of a streamflow model", challenge=False)
    assert asyncio.run(download_browser.challenge_pending(page)) is False


def test_generic_flow_waits_again_when_challenge_reappears(tmp_path, monkeypatch):
    """A challenge on the PDF hop is waited out, not treated as a hard failure."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage([None, {"payload": _pdf_payload()}], challenge=[False, True, False])
    ctx = FakeContext(page)

    async def candidates(p, doi):
        return ["https://example.org/a.pdf", "https://example.org/b.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.1/x", {}, dest, challenge_timeout_s=1))
    assert dest.read_bytes() == _pdf_payload()


def test_generic_pdf_flow_anchor_fallback(tmp_path, monkeypatch):
    """When no candidate downloads, the injected anchor is the last resort."""
    from hydrolitagent.literature import download_browser

    dest = tmp_path / "out.pdf"
    page = FakePage([None, None, {"payload": _pdf_payload()}])
    ctx = FakeContext(page)

    async def candidates(p, doi):
        return ["https://example.org/a.pdf", "https://example.org/b.pdf"]

    monkeypatch.setattr(download_browser, "_pdf_url_candidates", candidates)

    assert asyncio.run(download_browser.generic_flow(ctx, "10.1/x", {}, dest)) is True
    assert dest.read_bytes() == _pdf_payload()


def test_pdf_url_candidates_keeps_doi_fallbacks_when_page_is_chatty():
    """A page full of PDF links must not crowd out the DOI-layout fallbacks."""
    from hydrolitagent.literature import download_browser

    page = FakePage(
        url="https://www.science.org/doi/10.1126/x",
        pdf_candidates=[f"https://example.org/a{i}.pdf" for i in range(6)],
    )

    urls = asyncio.run(download_browser._pdf_url_candidates(page, "10.1126/x"))

    assert len(urls) == 4
    assert "https://www.science.org/doi/pdf/10.1126/x?download=true" in urls
    assert "https://www.science.org/doi/pdfdirect/10.1126/x?download=true" in urls


def test_run_scripted_unknown_prefix_returns_false(tmp_path):
    """An unscripted prefix is a plain miss — never SystemExit."""
    from hydrolitagent.literature import download_browser

    ok = asyncio.run(
        download_browser._run_scripted(
            FakeContext(), "10.1080", "10.1080/x", {"suffix": "x"}, tmp_path / "x.pdf"
        )
    )
    assert ok is False


def test_run_scripted_missing_pii_returns_false(tmp_path):
    """A Crossref record without PII degrades to False instead of exiting."""
    from hydrolitagent.literature import download_browser

    ok = asyncio.run(
        download_browser._run_scripted(
            FakeContext(), "10.1016", "10.1016/x", {"suffix": "x", "pii": None},
            tmp_path / "x.pdf",
        )
    )
    assert ok is False


def test_launch_context_falls_back_to_stealth(monkeypatch, tmp_path):
    """A locked MCP profile degrades to the stealth profile."""
    from hydrolitagent.literature import download_browser

    async def locked(pw, out, *, headless):
        raise RuntimeError("profile is in use")

    async def stealth(pw, out, *, headless):
        return FakeContext()

    monkeypatch.setattr(download_browser, "launch_mcp", locked)
    monkeypatch.setattr(download_browser, "launch_stealth", stealth)

    ctx = asyncio.run(download_browser._launch_context(object(), tmp_path, headless=True))
    assert isinstance(ctx, FakeContext)


def test_attempt_closes_context(tmp_path, monkeypatch):
    """The browser context is closed before any retry can grab the profile."""
    from hydrolitagent.literature import download_browser

    ctx = FakeContext()

    class FakePW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_import():
        return FakePW

    async def fake_launch(pw, out, *, headless):
        return ctx

    async def fake_scripted(*a):
        return False

    async def fake_generic(ctx, doi, meta, dest, *, challenge_timeout_s=None):
        return False

    async def no_challenge(c):
        return False

    monkeypatch.setattr(download_browser, "_import_playwright", fake_import)
    monkeypatch.setattr(download_browser, "_launch_context", fake_launch)
    monkeypatch.setattr(download_browser, "_run_scripted", fake_scripted)
    monkeypatch.setattr(download_browser, "generic_flow", fake_generic)
    monkeypatch.setattr(download_browser, "_any_challenge_pending", no_challenge)

    asyncio.run(
        download_browser._attempt(
            headless=True, out_dir=tmp_path, prefix="10.1080", doi="10.1080/x",
            meta={"suffix": "x"}, dest=tmp_path / "x.pdf",
        )
    )

    assert ctx.closed == 1


def _wire_attempt(monkeypatch, page, ctx, *, scripted=None, generic=None):
    """Point _attempt at fake plumbing; returns a dict recording what ran."""

    class FakePW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_import():
        return FakePW

    async def fake_launch(pw, out, *, headless):
        return ctx

    record = {"scripted": 0, "generic": 0}

    async def default_scripted(*a):
        record["scripted"] += 1
        return False

    async def default_generic(ctx, doi, meta, dest, *, challenge_timeout_s=None):
        record["generic"] += 1
        return False

    async def no_challenge(c):
        return False

    monkeypatch.setattr(download_browser_module(), "_import_playwright", fake_import)
    monkeypatch.setattr(download_browser_module(), "_launch_context", fake_launch)
    monkeypatch.setattr(download_browser_module(), "_run_scripted", scripted or default_scripted)
    monkeypatch.setattr(download_browser_module(), "generic_flow", generic or default_generic)
    monkeypatch.setattr(download_browser_module(), "_any_challenge_pending", no_challenge)
    return record


def download_browser_module():
    from hydrolitagent.literature import download_browser

    return download_browser


def test_attempt_escalates_without_running_flows_when_headless_challenge_persists(
    tmp_path, monkeypatch
):
    """A headless entry challenge short-circuits straight to escalation."""
    db = download_browser_module()
    monkeypatch.setattr(db, "HEADLESS_CHALLENGE_GRACE_S", 0)
    page = FakePage(title="Just a moment...", challenge=True)
    record = _wire_attempt(monkeypatch, page, FakeContext(page))

    ok, challenged = asyncio.run(
        db._attempt(
            headless=True, out_dir=tmp_path, prefix="10.1080", doi="10.1080/x",
            meta={"suffix": "x"}, dest=tmp_path / "x.pdf",
        )
    )

    assert (ok, challenged) == (False, True)
    assert record == {"scripted": 0, "generic": 0}


def test_attempt_runs_flows_when_headed_challenge_persists(tmp_path, monkeypatch):
    """Headed never aborts at the entry check — AMS needs its own button press."""
    db = download_browser_module()
    monkeypatch.setattr(db, "HEADED_CHALLENGE_TIMEOUT_S", 0)
    page = FakePage(title="Just a moment...", challenge=True)
    record = _wire_attempt(monkeypatch, page, FakeContext(page))

    asyncio.run(
        db._attempt(
            headless=False, out_dir=tmp_path, prefix="10.1175", doi="10.1175/x",
            meta={"suffix": "x"}, dest=tmp_path / "x.pdf",
        )
    )

    assert record["scripted"] == 1
    assert record["generic"] == 1


def test_attempt_does_not_pre_navigate_scripted_prefixes(tmp_path, monkeypatch):
    """Pre-navigating would abort the flow's own goto (ERR_ABORTED on Elsevier)."""
    from hydrolitagent.literature import download_browser

    page = FakePage()
    _wire_attempt(monkeypatch, page, FakeContext(page))

    asyncio.run(
        download_browser._attempt(
            headless=False, out_dir=tmp_path, prefix="10.1016", doi="10.1016/x",
            meta={"suffix": "x", "pii": "S0022169426016069"}, dest=tmp_path / "x.pdf",
        )
    )

    assert page.goto_calls == []


def test_attempt_propagates_no_access_without_generic_fallback(tmp_path, monkeypatch):
    """Nature 'no entitlement' stops the run; no fallback, no second window."""
    import pytest

    from hydrolitagent.literature import download_browser

    class FakePW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_import():
        return FakePW

    async def fake_launch(pw, out, *, headless):
        return FakeContext()

    async def no_access(*a):
        raise download_browser._NoAccess("subscription required")

    async def generic_must_not_run(*a, **k):
        raise AssertionError("generic_flow must not run when there is no access")

    monkeypatch.setattr(download_browser, "_import_playwright", fake_import)
    monkeypatch.setattr(download_browser, "_launch_context", fake_launch)
    monkeypatch.setattr(download_browser, "_run_scripted", no_access)
    monkeypatch.setattr(download_browser, "generic_flow", generic_must_not_run)

    with pytest.raises(download_browser._NoAccess):
        asyncio.run(
            download_browser._attempt(
                headless=True, out_dir=tmp_path, prefix="10.1038", doi="10.1038/x",
                meta={"suffix": "x"}, dest=tmp_path / "x.pdf",
            )
        )

