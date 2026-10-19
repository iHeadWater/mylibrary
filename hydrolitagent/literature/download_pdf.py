#!/usr/bin/env python3
"""PDF download helper for academic papers via institutional access.

Provides publisher detection, DOI resolution, base64 decoding, and PDF
verification. Used by the ``download-pdf`` Claude Code skill (mylibrary) and
as a standalone module within ``hydrolitagent.literature``.

Usage (standalone)::

    python scripts/download_pdf.py detect <url>
    python scripts/download_pdf.py decode <input_file> <output_path>
    python scripts/download_pdf.py verify <pdf_path>
    python scripts/download_pdf.py doi <doi>
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from hydrolitagent.literature._paths import PAPERS_DIR, PROJECT_ROOT


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Publisher(Enum):
    """Academic publisher identifiers."""

    ELSEVIER = auto()  # ScienceDirect
    SPRINGER = auto()  # Springer Link
    WILEY = auto()  # Wiley Online Library
    TAYLOR_FRANCIS = auto()  # Taylor & Francis Online
    AGU = auto()  # AGU/Wiley
    UNKNOWN = auto()


@dataclass
class PdfMetadata:
    """Metadata extracted from a downloaded PDF."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str = ""
    pages: int = 0
    version: str = ""
    file_size_bytes: int = 0

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "doi": self.doi,
            "pages": self.pages,
            "version": self.version,
            "file_size_bytes": self.file_size_bytes,
        }


# ---------------------------------------------------------------------------
# Publisher detection
# ---------------------------------------------------------------------------

# Order matters: more specific patterns must come before general ones.
# e.g. "agupubs.onlinelibrary.wiley.com" before "wiley.com"
PUBLISHER_PATTERNS: dict[str, Publisher] = {
    "sciencedirect.com": Publisher.ELSEVIER,
    "elsevier.com": Publisher.ELSEVIER,
    "nature.com": Publisher.SPRINGER,  # Nature is part of Springer Nature
    "link.springer.com": Publisher.SPRINGER,
    "springer.com": Publisher.SPRINGER,
    "agupubs.onlinelibrary.wiley.com": Publisher.AGU,
    "onlinelibrary.wiley.com": Publisher.WILEY,
    "wiley.com": Publisher.WILEY,
    "tandfonline.com": Publisher.TAYLOR_FRANCIS,
}


def detect_publisher(url: str) -> Publisher:
    """Detect the academic publisher from a URL.

    Returns:
        The matching Publisher enum value, or Publisher.UNKNOWN.

    Example:
        >>> detect_publisher("https://www.sciencedirect.com/science/article/pii/S0022169424018675")
        <Publisher.ELSEVIER: 1>
    """
    for pattern, publisher in PUBLISHER_PATTERNS.items():
        if pattern in url:
            return publisher
    return Publisher.UNKNOWN


# ---------------------------------------------------------------------------
# DOI resolution
# ---------------------------------------------------------------------------

DOI_PREFIX = "https://doi.org/"


def normalize_doi(doi: str) -> str:
    """Strip common DOI prefixes and whitespace.

    Accepts::

        "10.1016/j.jhydrol.2024.132471"
        "https://doi.org/10.1016/j.jhydrol.2024.132471"
        "doi:10.1016/j.jhydrol.2024.132471"

    Returns bare DOI (e.g. "10.1016/j.jhydrol.2024.132471").
    """
    doi = doi.strip()
    doi = re.sub(r"^https?://doi\.org/", "", doi)
    doi = re.sub(r"^doi:", "", doi)
    return doi.strip()


def doi_to_url(doi: str) -> str:
    """Convert a DOI to its resolver URL."""
    return f"{DOI_PREFIX}{normalize_doi(doi)}"


def pii_to_sciencedirect_url(pii: str) -> str:
    """Convert a PII to a ScienceDirect article URL.

    PII format: ``S0022169424018675`` (starts with 'S', ~17 chars).
    """
    pii = pii.strip().upper()
    return f"https://www.sciencedirect.com/science/article/pii/{pii}"


def classify_input(user_input: str) -> dict:
    """Classify user input as DOI, PII, URL, or unknown.

    Returns:
        dict with keys:
        - ``type``: "doi", "pii", "url", "unknown"
        - ``normalized``: cleaned value
        - ``url``: article page URL (if resolvable without HTTP)
    """
    user_input = user_input.strip()

    # DOI with full URL prefix — check before generic URL
    doi_match = re.match(r"^https?://doi\.org/(10\.\d{4,}/.+)", user_input)
    if doi_match:
        return {
            "type": "doi",
            "normalized": doi_match.group(1),
            "url": user_input,
        }

    # Direct URL
    if user_input.startswith(("http://", "https://")):
        return {"type": "url", "normalized": user_input, "url": user_input}

    # DOI (starts with 10.)
    if re.match(r"^10\.\d{4,}/", user_input):
        return {
            "type": "doi",
            "normalized": user_input,
            "url": doi_to_url(user_input),
        }

    # DOI with doi: prefix
    doi_prefix_match = re.match(r"^doi:(10\.\d{4,}/.+)", user_input)
    if doi_prefix_match:
        return {
            "type": "doi",
            "normalized": doi_prefix_match.group(1),
            "url": doi_to_url(doi_prefix_match.group(1)),
        }

    # PII (starts with S followed by digits)
    if re.match(r"^S\d{10,}$", user_input, re.IGNORECASE):
        return {
            "type": "pii",
            "normalized": user_input.upper(),
            "url": pii_to_sciencedirect_url(user_input),
        }

    return {"type": "unknown", "normalized": user_input, "url": ""}


# ---------------------------------------------------------------------------
# Output path resolution
# ---------------------------------------------------------------------------

DEFAULT_PDF_ROOT = PAPERS_DIR


def default_pdf_dir(root: Path | None = None) -> Path:
    """下载 PDF 的默认目录。

    优先级:``MYLIBRARY_PDF_ROOT``(旧名,仍兼容) → 显式 ``root`` →
    精读产物根下的 ``papers/``。产物根见 ``uv run hydrolitagent paths``。

    ``MYLIBRARY_PDF_ROOT`` 只对这一个目录生效,是过渡期的第二个答案;
    新代码请用产物根,别再加第三个。
    """
    data_root = os.environ.get("MYLIBRARY_PDF_ROOT", "")
    if data_root:
        return Path(data_root)
    return root or DEFAULT_PDF_ROOT


def slug_from_doi(doi: str) -> str:
    """Generate a filename-safe slug from a DOI.

    Example: ``10.1016/j.jhydrol.2024.132471`` → ``j.jhydrol.2024.132471``
    """
    doi = normalize_doi(doi)
    # Drop the publisher prefix (everything before the first '/')
    if "/" in doi:
        doi = doi.split("/", 1)[1]
    # Replace remaining non-alphanumeric chars with underscores
    slug = re.sub(r"[^a-zA-Z0-9._-]", "_", doi)
    return slug


def output_path_for(input_ref: str, output_dir: str | Path | None = None) -> Path:
    """Compute the default output path for a given input reference.

    If the input contains a DOI, the filename is derived from it.
    Otherwise, falls back to a timestamped name.

    Args:
        input_ref: DOI, PII, or URL.
        output_dir: Override output directory. Defaults to ``default_pdf_dir()``.

    Returns:
        Full output path ending in ``.pdf``.
    """
    result = classify_input(input_ref)
    if result["type"] in ("doi", "pii"):
        slug = slug_from_doi(result["normalized"])
    else:
        # URL or unknown — use a time-based fallback
        from datetime import datetime

        slug = f"paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    out_dir = Path(output_dir) if output_dir else default_pdf_dir()
    return out_dir / f"{slug}.pdf"


# ---------------------------------------------------------------------------
# Base64 decoding
# ---------------------------------------------------------------------------


def _clean_base64(raw_text: str) -> str:
    """Extract and clean a base64 string from raw tool output.

    Handles:
    - ``### Result\\n`` header prefix from MCP tool output
    - JSON-wrapped base64 (``{"base64": "data:application/pdf;base64,..."}``)
    - Data URL prefix (``data:application/pdf;base64,...``)
    - Line-wrapped base64 (newlines inside the base64 string)
    - Non-ASCII artifacts in the base64 stream
    """
    text = raw_text

    # Strip MCP tool output wrapper
    if "### Result" in text:
        _, _, text = text.partition("\n")

    # Try JSON extraction first
    text_stripped = text.strip()
    if text_stripped.startswith("{"):
        try:
            data = json.loads(text_stripped)
            if isinstance(data, dict) and "base64" in data:
                text = data["base64"]
        except json.JSONDecodeError:
            pass

    # Strip data URL prefix
    if "," in text[:200]:
        # Only strip data URI prefix (data:...;base64,)
        prefix_end = text.index(",") + 1
        text = text[prefix_end:]

    # Remove whitespace and non-base64 chars
    text = re.sub(r"[^A-Za-z0-9+/=]", "", text)

    return text


def decode_base64_file(input_path: str | Path, output_path: str | Path) -> int:
    """Decode a base64-encoded tool output file to a PDF.

    The input file can be:
    1. A JSON file with ``{"base64": "data:application/pdf;base64,..."}``
    2. A raw text file with base64-encoded PDF data (possibly with
       ``### Result`` header wrapper).

    Returns:
        Number of bytes written.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    raw_bytes = input_path.read_bytes()
    text = raw_bytes.decode("utf-8", errors="ignore")

    b64_clean = _clean_base64(text)

    pdf_bytes = __import__("base64").b64decode(b64_clean)
    output_path.write_bytes(pdf_bytes)
    return len(pdf_bytes)


# ---------------------------------------------------------------------------
# PDF verification and metadata extraction
# ---------------------------------------------------------------------------


def _decode_pdf_string(raw: bytes) -> str:
    """Decode a PDF text string, honouring a UTF-16 byte-order mark.

    Publishers embed UTF-16 titles inside literal strings; decoding those as
    latin-1 yields mojibake such as ``'þÿ E v a l u a t i n g'``.
    """
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    return raw.decode("latin-1", errors="replace")


def verify_pdf(pdf_path: str | Path) -> PdfMetadata:
    """Verify a PDF file and extract its metadata.

    Returns:
        PdfMetadata with extracted fields. Raises ValueError if the file
        is not a valid PDF.
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    file_size = pdf_path.stat().st_size
    if file_size == 0:
        raise ValueError("PDF file is empty")

    content = pdf_path.read_bytes()

    # Check PDF header
    if not content.startswith(b"%PDF-"):
        raise ValueError(f"Not a valid PDF (missing %PDF- header): {pdf_path}")

    metadata = PdfMetadata(file_size_bytes=file_size)

    # PDF version
    ver_match = re.search(rb"%PDF-(\d+\.\d+)", content[:100])
    if ver_match:
        metadata.version = ver_match.group(1).decode("ascii")

    # Page count (approximate from /Type /Page entries, not /Pages for kids)
    metadata.pages = len(re.findall(rb"/Type\s*/Page[^s]", content))

    # Title extraction
    # Try PDF metadata first: /Title (...)
    title_match = re.search(rb"/Title\s*<([0-9A-Fa-f]+)>", content)
    if title_match:
        try:
            metadata.title = bytes.fromhex(title_match.group(1).decode("ascii")).decode(
                "utf-16-be", errors="replace"
            )
        except (ValueError, UnicodeDecodeError):
            pass

    if not metadata.title:
        title_match = re.search(rb"/Title\s*\(([^)]*)\)", content)
        if title_match:
            metadata.title = _decode_pdf_string(title_match.group(1))

    # Author extraction
    author_match = re.search(rb"/Author\s*<([0-9A-Fa-f]+)>", content)
    if author_match:
        try:
            author_str = bytes.fromhex(author_match.group(1).decode("ascii")).decode(
                "utf-16-be", errors="replace"
            )
            metadata.authors = [a.strip() for a in author_str.split(";")]
        except (ValueError, UnicodeDecodeError):
            pass

    if not metadata.authors:
        author_match = re.search(rb"/Author\s*\(([^)]*)\)", content)
        if author_match:
            author_str = _decode_pdf_string(author_match.group(1))
            metadata.authors = [a.strip() for a in author_str.split(";")]

    # DOI extraction (from dc:identifier or prism:doi)
    doi_match = re.search(rb"/doi\s*\(([^)]*)\)", content)
    if doi_match:
        metadata.doi = doi_match.group(1).decode("latin-1", errors="replace")

    return metadata


def format_metadata(metadata: PdfMetadata) -> str:
    """Format PdfMetadata as a human-readable table."""
    lines = [
        f"  Title:   {metadata.title}",
        f"  Author:  {', '.join(metadata.authors) if metadata.authors else 'N/A'}",
        f"  DOI:     {metadata.doi or 'N/A'}",
        f"  Pages:   {metadata.pages}",
        f"  Version: PDF {metadata.version}" if metadata.version else "  Version: N/A",
        f"  Size:    {metadata.file_size_bytes:,} bytes ({metadata.file_size_bytes / 1024:.0f} KB)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Download orchestration (merged from scripts/download_paper.py)
# ---------------------------------------------------------------------------
#
# The curl helpers, metadata lookups, Zotero sync and setup check used to live
# inline in ``scripts/download_paper.py`` (650 lines, no tests). They now live
# here so the behaviour is importable and testable; the script is a thin shell.
# The browser flows live in ``download_browser`` (imported lazily by
# ``download_paper`` to keep this module importable without the automation code).

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
CROSSREF_UA = "mylibrary-download-paper/1.0 (mailto:test@example.com)"
DEFAULT_OUT = Path(".playwright-mcp")


def _title_key(text: str) -> str:
    """Normalise a title for comparison: case, punctuation and spacing."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def search_crossref_by_title(title: str, rows: int = 8) -> list[dict]:
    """Crossref bibliographic search; empty list on any failure."""
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({
        "query.bibliographic": title,
        "rows": rows,
        "select": "DOI,title,container-title,issued,type",
    })
    req = urllib.request.Request(url, headers={"User-Agent": CROSSREF_UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["message"]["items"]
    except Exception:
        return []


def pick_doi_by_title(title: str, items: list[dict],
                      threshold: float = 0.6, margin: float = 0.15
                      ) -> tuple[str | None, list[dict]]:
    """Choose a DOI for ``title``, or refuse when the field is ambiguous.

    Copy-pasted titles are usually abbreviated, so exact match is tried first;
    otherwise a clear token-overlap winner is accepted. Two similar candidates
    mean "ask the human", never "pick one".
    """
    if not items:
        return None, []
    target = _title_key(title)
    target_tokens = set(target.split())

    # The same paper often has both a preprint and a journal DOI with the same
    # title; the published record is the one worth ingesting.
    exact = [it for it in items
             if _title_key((it.get("title") or [""])[0]) == target]
    if exact:
        published = [it for it in exact
                     if str(it.get("type", "")).lower() not in ("posted-content", "preprint")]
        chosen = (published or exact)[0]
        return chosen["DOI"], items

    scored: list[tuple[float, str, dict]] = []
    for it in items:
        cand_title = (it.get("title") or [""])[0]
        key = _title_key(cand_title)
        tokens = set(key.split())
        # Coverage, not Jaccard: real titles are longer than the label a human
        # pastes, and a long correct match must not be penalised for that.
        overlap = len(target_tokens & tokens) / max(1, len(target_tokens))
        scored.append((overlap, it.get("DOI", ""), it))

    scored.sort(key=lambda s: s[0], reverse=True)
    best_score = scored[0][0]
    # Candidates that score the same are usually a paper plus its own preprint:
    # prefer the published one rather than declaring the field ambiguous.
    tied = [s[2] for s in scored if abs(s[0] - best_score) <= 0.05]
    journals = [it for it in tied if str(it.get("type", "")).lower() == "journal-article"]
    published = [it for it in tied
                 if str(it.get("type", "")).lower() not in ("posted-content", "preprint")]
    if len(tied) > 1 and len(journals) == 1:
        # A journal article plus its preprint/thesis/report copy: take the journal.
        winner = journals[0]
    elif len(tied) > 1 and len(published) == 1:
        winner = published[0]
    else:
        winner = scored[0][2]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if not (winner.get("DOI") and best_score >= threshold
                and best_score - runner_up >= margin):
            return None, [s[2] for s in scored[:5]]
    return winner["DOI"], items


def crossref_meta(doi: str) -> dict:
    url = "https://api.crossref.org/works/" + doi
    req = urllib.request.Request(url, headers={"User-Agent": CROSSREF_UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        msg = json.load(r)["message"]
    alt = msg.get("alternative-id") or []
    return {
        "title": (msg.get("title") or [""])[0],
        "container": (msg.get("container-title") or [""])[0],
        "type": msg.get("type"),
        "pii": alt[0] if alt else None,
        "prefix": doi.split("/")[0],
        "suffix": doi.split("/", 1)[1],
    }


def unpaywall_is_oa(doi: str) -> str | None:
    """Return the best OA PDF URL if the paper has one."""
    url = f"https://api.unpaywall.org/v2/{doi}?email=mylibrary@example.com"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": CROSSREF_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception:
        return None
    best = data.get("best_oa_location") or {}
    return best.get("url_for_pdf") or best.get("url")


def is_pdf_file(path: Path) -> bool:
    """Cheap boolean check: does the file start with a ``%PDF-`` header?

    Distinct from :func:`verify_pdf`, which returns rich :class:`PdfMetadata`
    and raises on malformed input. This one never raises — it is the fast
    "did the download actually land a PDF?" guard used by the curl/browser flows.
    """
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        return False


def curl_download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sL", "-A", UA, "-o", str(dest), url],
        check=False,
        timeout=300,
    )
    return is_pdf_file(dest)


def copernicus_pdf_url(suffix: str) -> str:
    """Parse a 10.5194 suffix into a published-article or preprint PDF URL.

    Published:  hess-30-5327-2026 -> .../articles/30/5327/2026/hess-30-5327-2026.pdf
    Preprint:   essd-2026-528    -> .../preprints/essd-2026-528/essd-2026-528.pdf
    """
    m = re.fullmatch(r"([a-z]+)-(\d+)-(\d+)-(\d{4})", suffix)
    if m:
        journal, vol, page, year = m.groups()
        return (
            f"https://{journal}.copernicus.org/articles/{vol}/{page}/{year}/{suffix}.pdf"
        )
    m = re.fullmatch(r"([a-z]+)-(\d{4})-(\d+)", suffix)
    if m:
        journal, year = m.group(1), m.group(2)
        # egusphere requires a year directory segment; essd/hess do not
        if journal == "egusphere":
            return (
                f"https://{journal}.copernicus.org/preprints/{year}/{suffix}/{suffix}.pdf"
            )
        return f"https://{journal}.copernicus.org/preprints/{suffix}/{suffix}.pdf"
    raise ValueError(f"Unrecognized Copernicus suffix: {suffix}")


def curl_with_cookies(article_url: str, pdf_url: str, dest: Path) -> bool:
    """Two-step curl: visit article page to set cookies, then fetch PDF."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cookie_jar = dest.parent / ".curl-cookies.txt"
    # Only the cookies matter here; without -o the body (often a Cloudflare
    # challenge page) would be dumped into the middle of our output.
    subprocess.run(
        ["curl", "-sL", "-A", UA, "-c", str(cookie_jar), "-b", str(cookie_jar),
         "-o", os.devnull, article_url],
        check=False, timeout=60,
    )
    subprocess.run(
        ["curl", "-sL", "-A", UA, "-c", str(cookie_jar), "-b", str(cookie_jar),
         "-o", str(dest), pdf_url],
        check=False, timeout=300,
    )
    try:
        cookie_jar.unlink(missing_ok=True)
    except Exception:
        pass
    return is_pdf_file(dest)


def sync_to_zotero(pdf_path: Path, doi: str) -> int:
    cmd = [
        "uv", "run", "python", "-m",
        "hydrolitagent.literature.zotero_sync", str(pdf_path), doi,
    ]
    # Windows consoles default to GBK; force UTF-8 so the Chinese GDrive path
    # and CJK titles printed by zotero_sync don't crash with a UnicodeEncodeError.
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        # Budget covers the one-time index rebuild; steady state is seconds.
        return subprocess.run(cmd, env=env, timeout=ZOTERO_SYNC_TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        print("FAILED: Zotero sync timed out after 900s; the PDF is already saved.",
              file=sys.stderr)
        return 1


def _load_dotenv() -> None:
    """Load <repo>/.env (best-effort) so env-var checks match CLI runs."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except Exception:
            pass


# Budget covers the one-time DOI-index rebuild; steady state is seconds.
ZOTERO_SYNC_TIMEOUT = 900


def _ensure_utf8_stdio() -> None:
    """Emit UTF-8 so unicode log lines cannot crash a GBK Windows console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def setup_check() -> int:
    """Verify a bare-host Zotero/GDrive setup is ready before the first sync."""
    _ensure_utf8_stdio()
    _load_dotenv()
    ok = True
    required = ("ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID", "GDRIVE_PAPERS_PATH")
    missing = [k for k in required if not os.environ.get(k)]
    print("── Zotero/GDrive setup check ──")
    if missing:
        ok = False
        print(f"  [FAIL] missing in .env: {', '.join(missing)}")
        print("         → cp .env.example .env and fill them (see comments)")
    else:
        print("  [ok]   env keys present")

    gd = os.environ.get("GDRIVE_PAPERS_PATH", "")
    if gd:
        p = Path(gd)
        if p.is_dir():
            probe = p / ".setup-check-write-test"
            try:
                probe.write_text("x", encoding="utf-8")
                probe.unlink()
                print(f"  [ok]   GDrive papers dir writable: {p}")
            except OSError as e:
                ok = False
                print(f"  [FAIL] GDrive papers dir not writable: {e}")
        else:
            ok = False
            print(f"  [FAIL] GDRIVE_PAPERS_PATH not a directory: {p}")

    api_key = os.environ.get("ZOTERO_API_KEY", "")
    lib_id = os.environ.get("ZOTERO_LIBRARY_ID", "")
    if api_key and lib_id:
        try:
            from pyzotero import zotero
            z = zotero.Zotero(lib_id, "user", api_key)
            z.items(limit=1)
            print("  [ok]   Zotero Web API credentials valid")
        except Exception as e:
            ok = False
            print(f"  [FAIL] Zotero Web API error: {e}")

    print()
    print("One-time Zotero Desktop setup (per machine):")
    print("  Settings → Advanced → Files and Folders → Linked Attachment Base Directory")
    print(f"  must point to: {gd}")
    print("  ('Automatically rename/move attached files' — ZotMoov — should be OFF for that folder)")
    print("Then just run:  uv run python scripts/download_paper.py --arxiv <id> --sync")
    return 0 if ok else 1


def download_paper(
    doi: str | None = None,
    arxiv: str | None = None,
    out_dir: Path | None = None,
    *,
    sync: bool = False,
    resolve_only: bool = False,
    title: str | None = None,
) -> int:
    """Download a paper by DOI or arXiv id; return a process exit code.

    Orchestration lifted out of ``scripts/download_paper.py`` so it is
    importable and testable. Exit codes match the historical CLI: ``0`` on
    success, ``1`` on download failure / bad metadata. ``ValueError`` from a
    missing DOI is the caller's responsibility (the CLI's ``argparse`` enforces
    that one of ``--doi`` / ``--arxiv`` is given).
    """
    from hydrolitagent.literature.download_browser import download_with_browser, log

    _ensure_utf8_stdio()
    out = Path(out_dir) if out_dir is not None else DEFAULT_OUT

    if title and not doi and not arxiv:
        candidates = search_crossref_by_title(title)
        resolved, options = pick_doi_by_title(title, candidates)
        if not resolved:
            log(f"Could not resolve a single DOI for: {title}")
            if options:
                log("Candidates (pass one explicitly with --doi):")
                for opt in options:
                    guessed = (opt.get("title") or [""])[0][:90]
                    log(f"  {opt.get('DOI', '?')}  {guessed}")
            else:
                log("Crossref returned no results.")
            return 2
        log(f"Resolved title → {resolved}")
        doi = resolved

    if arxiv:
        dest = out / f"arXiv.{arxiv}.pdf"
        url = f"https://arxiv.org/pdf/{arxiv}"
        log(f"arXiv curl: {url}")
        ok = curl_download(url, dest)
        if not ok:
            log("FAILED: no %PDF- header")
            return 1
        log(f"SAVED: {dest} ({dest.stat().st_size} bytes)")
        return sync_to_zotero(dest, f"10.48550/arXiv.{arxiv}") if sync else 0

    meta = crossref_meta(doi)
    if resolve_only:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0
    log(f"{meta['title'][:80]}")
    log(f"  {meta['container']} | {meta['prefix']}")

    try:
        dest = asyncio.run(download_with_browser(doi, meta, out))
    except Exception as e:  # a crashed flow is a download failure, not a traceback
        log(f"FAILED: browser flow crashed ({type(e).__name__}: {e})")
        return 1
    if not dest:
        log("FAILED: download did not produce a verified PDF")
        return 1
    log(f"SAVED: {dest} ({dest.stat().st_size} bytes)")
    return sync_to_zotero(dest, doi) if sync else 0


# ---------------------------------------------------------------------------
# Console script (Entry point)
# ---------------------------------------------------------------------------


def main():
    """Console script entry point for download_pdf.py.

    Same signature as Click but uses plain argparse to avoid dependency
    issues when running standalone.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="PDF download helper for academic papers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Commands:
  detect <url>            Detect publisher from URL
  doi <doi>               Resolve DOI to article URL and publisher
  decode <input> <output> Decode base64 tool output to PDF
  verify <pdf>            Verify PDF and extract metadata""",
    )
    parser.add_argument(
        "command", choices=["detect", "doi", "decode", "verify", "classify", "output-path"]
    )
    parser.add_argument("args", nargs="*", help="Command arguments")

    args = parser.parse_args()

    if args.command == "detect" and len(args.args) >= 1:
        publisher = detect_publisher(args.args[0])
        print(f"Publisher: {publisher.name}")

    elif args.command == "classify" and len(args.args) >= 1:
        result = classify_input(args.args[0])
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "doi" and len(args.args) >= 1:
        result = classify_input(args.args[0])
        print(f"Type:  {result['type']}")
        print(f"DOI:   {result['normalized']}")
        print(f"URL:   {result['url']}")
        if result["url"]:
            pub = detect_publisher(result["url"])
            print(f"Publisher: {pub.name}")

    elif args.command == "decode" and len(args.args) >= 2:
        input_path = args.args[0]
        output_path = args.args[1]
        size = decode_base64_file(input_path, output_path)
        print(f"Decoded {size:,} bytes → {output_path}")

    elif args.command == "output-path" and len(args.args) >= 1:
        path = output_path_for(args.args[0])
        print(str(path))

    elif args.command == "verify" and len(args.args) >= 1:
        try:
            metadata = verify_pdf(args.args[0])
            print("OK Valid PDF")
            print(format_metadata(metadata))
        except (FileNotFoundError, ValueError) as e:
            print(f"FAIL {e}", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
