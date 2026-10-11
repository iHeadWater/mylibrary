"""Tests for ``hydrolitagent/literature/download_pdf.py`` — PDF download helper."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
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

