"""Download a paper PDF by DOI or arXiv id, with browser automation.

Distilled from the download-pdf skill's battle-tested publisher flows:

- curl-first for open-access sources (Copernicus, science.org, arXiv) — no browser needed.
- Browser automation for Cloudflare/verification-protected publishers.
  Prefers the MCP browser profile (stable, rich cookies) over the stealth temp profile.
  The stealth launch (real Chrome channel, no automation flags, masked navigator.webdriver)
  is the fallback when MCP profile is unavailable.
- Optional Zotero sync via hydrolitagent.literature.zotero_sync (linked_file + GDrive).

Usage:
  uv run python scripts/download_paper.py --doi 10.1029/2026GL125188
  uv run python scripts/download_paper.py --doi 10.1016/j.jhydrol.2026.136272 --sync
  uv run python scripts/download_paper.py --arxiv 2608.18495 --sync
  uv run python scripts/download_paper.py --doi 10.1038/s43017-026-00819-6 --resolve-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
CROSSREF_UA = "mylibrary-download-paper/1.0 (mailto:test@example.com)"
DEFAULT_OUT = Path(".playwright-mcp")
PROFILE_DIR = Path(tempfile.gettempdir()) / "pw-download-paper-profile"
MCP_BASE = Path.home() / "AppData/Local/ms-playwright-mcp"

ANCHOR_JS = """() => {
  const a = document.createElement('a');
  a.href = window.location.href;
  a.download = 'temp_pdf_download.pdf';
  document.body.appendChild(a);
  a.click();
  a.remove();
}"""


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Metadata resolution
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# curl downloads (open-access, no bot protection)
# ---------------------------------------------------------------------------


def curl_download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sL", "-A", UA, "-o", str(dest), url],
        check=False,
        timeout=300,
    )
    return verify_pdf(dest)


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
        journal = m.group(1)
        return f"https://{journal}.copernicus.org/preprints/{suffix}/{suffix}.pdf"
    raise ValueError(f"Unrecognized Copernicus suffix: {suffix}")


def verify_pdf(path: Path) -> bool:
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        return False


def find_mcp_profile() -> Path | None:
    """Find the most recently used MCP browser profile directory."""
    if not MCP_BASE.exists():
        return None
    profiles = sorted(MCP_BASE.glob("mcp-chrome-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return profiles[0] if profiles else None


def curl_with_cookies(article_url: str, pdf_url: str, dest: Path) -> bool:
    """Two-step curl: visit article page to set cookies, then fetch PDF."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cookie_jar = dest.parent / ".curl-cookies.txt"
    subprocess.run(
        ["curl", "-sL", "-A", UA, "-c", str(cookie_jar), "-b", str(cookie_jar), article_url],
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
    return verify_pdf(dest)


# ---------------------------------------------------------------------------
# Stealth browser (real Chrome, automation flags stripped)
# ---------------------------------------------------------------------------

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]


async def launch_stealth(playwright, downloads_dir: Path):
    """Launch a persistent context that Cloudflare/AMS verification auto-passes."""
    kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        ignore_default_args=["--enable-automation"],
        downloads_path=str(downloads_dir),
        viewport={"width": 1280, "height": 900},
        args=STEALTH_ARGS,
    )
    try:
        ctx = await playwright.chromium.launch_persistent_context(
            channel="chrome", **kwargs
        )
    except Exception:
        ctx = await playwright.chromium.launch_persistent_context(**kwargs)
    await ctx.add_init_script(
        'Object.defineProperty(navigator, "webdriver", {get: () => undefined});'
    )
    return ctx


async def launch_mcp(playwright, downloads_dir: Path):
    """Launch using the MCP browser profile (stable, rich cookies, no webdriver mask needed)."""
    mcp_profile = find_mcp_profile()
    if not mcp_profile:
        raise FileNotFoundError("MCP profile not found")
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(mcp_profile),
        headless=False,
        downloads_path=str(downloads_dir),
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


async def new_page(ctx):
    return ctx.pages[0] if ctx.pages else await ctx.new_page()


async def wait_challenge_clear(page, timeout_s: int = 90) -> None:
    """Poll until the page title no longer looks like a challenge page."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        title = await page.title()
        if (
            "请稍候" not in title
            and "moment" not in title.lower()
            and "验证" not in title
            and "Verification" not in title
        ):
            return
        await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Publisher flows (stealth browser)
# ---------------------------------------------------------------------------


async def sd_flow(ctx, pii: str, dest: Path) -> bool:
    """ScienceDirect: article page -> pdfft -> signed main.pdf viewer -> anchor download.

    Gotchas encoded here (each cost a failed attempt to discover):
    - pdfft does NOT fire a download event; it lands on a security-verification
      page that auto-redirects (~30s) to a signed main.pdf viewer URL.
    - The viewer URL is hit by SECONDARY redirects right after it appears —
      injecting the anchor immediately throws "Execution context destroyed".
      Wait until the URL is stable across two polls first.
    - Wrap every anchor injection in expect_download and retry: transient
      context-destroyed errors are normal.
    """
    page = await new_page(ctx)
    art = f"https://www.sciencedirect.com/science/article/pii/{pii}"
    pdfft = art + f"/pdfft?pid=1-s2.0-{pii}-main.pdf"
    await page.goto(art, timeout=60000, wait_until="domcontentloaded")
    await wait_challenge_clear(page)
    try:
        await page.goto(pdfft, timeout=60000, wait_until="commit")
    except Exception:
        pass  # navigation may be replaced by the redirect chain
    deadline = time.time() + 120
    while time.time() < deadline:
        if "main.pdf" in page.url:
            break
        await asyncio.sleep(4)
    if "main.pdf" not in page.url:
        log(f"  never reached main.pdf (url={page.url[:70]})")
        return False
    for _ in range(6):  # URL stabilization across secondary redirects
        u1 = page.url
        await asyncio.sleep(5)
        if page.url == u1 and "main.pdf" in page.url:
            break
    for attempt in range(4):
        if "main.pdf" not in page.url:
            await asyncio.sleep(5)
            continue
        try:
            async with page.expect_download(timeout=60000) as dl_info:
                await page.evaluate(ANCHOR_JS)
            await (await dl_info.value).save_as(str(dest))
            return True
        except Exception:
            log(f"  anchor attempt {attempt + 1} failed, retrying")
            await asyncio.sleep(6)
    return False


async def wiley_flow(ctx, doi: str, dest: Path) -> bool:
    """AGU/Wiley pdfdirect: navigation becomes the download (ERR_ABORTED is expected)."""
    host = "agupubs.onlinelibrary.wiley.com" if doi.startswith("10.1029") else "onlinelibrary.wiley.com"
    page = await new_page(ctx)
    url = f"https://{host}/doi/pdfdirect/{doi}?download=true"
    try:
        async with page.expect_download(timeout=150000) as dl_info:
            try:
                await page.goto(url, timeout=60000, wait_until="commit")
            except Exception:
                pass
        await (await dl_info.value).save_as(str(dest))
        return True
    except Exception as e:
        log(f"  wiley flow: {type(e).__name__} {str(e)[:80]}")
        return False


async def ams_flow(ctx, doi: str, dest: Path) -> bool:
    """AMS journals: visit article page → find downloadpdf link → context.request bytes.

    Handles both aop (advance online) and published articles:
    - aop URL may redirect to published URL (e.g., aies/5/4/AIES-D-25-0069.1.xml)
    - Extract vol/issue from final URL to construct downloadpdf path
    - Use context.request.get (shares cookies, avoids TargetClosedError from save_as)
    """
    suffix = doi.split("/", 1)[1].lower()  # e.g. aies-d-25-0113.1
    journal = suffix.split("-")[0]
    aop_url = f"https://journals.ametsoc.org/view/journals/{journal}/aop/{suffix}/{suffix}.xml"
    page = await new_page(ctx)
    await page.goto(aop_url, timeout=60000, wait_until="domcontentloaded")
    await wait_challenge_clear(page)
    final_url = page.url
    # Extract vol/issue from published URL (e.g., /view/journals/aies/5/4/AIES-D-25-0069.1.xml)
    m = re.search(r"/view/journals/(\w+)/(\d+)/(\d+)/", final_url)
    if m:
        pub_journal, vol, issue = m.group(1), m.group(2), m.group(3)
    else:
        pub_journal, vol, issue = journal, None, None
    title = await page.title()
    if "Verification" in title or "验证" in title:
        try:
            await page.get_by_role("button", name="begin").first.click(timeout=8000)
            await wait_challenge_clear(page, timeout_s=180)
        except Exception:
            pass
    # Try to find downloadpdf link on the page first
    href = await page.evaluate(
        """() => {
            const a = Array.from(document.querySelectorAll('a')).find(
                x => (x.getAttribute('href') || '').indexOf('downloadpdf') !== -1);
            return a ? a.getAttribute('href') : null;
        }"""
    )
    if href:
        pdf_url = href if href.startswith("http") else "https://journals.ametsoc.org" + href
    elif vol and issue:
        # Construct downloadpdf URL from published vol/issue
        pdf_url = f"https://journals.ametsoc.org/downloadpdf/view/journals/{pub_journal}/{vol}/{issue}/{suffix}.pdf"
    else:
        log("  AMS: cannot determine downloadpdf URL")
        return False
    art = final_url
    resp = await page.context.request.get(pdf_url, headers={"Referer": art})
    body = await resp.body()
    if not body.startswith(b"%PDF-"):
        log(f"  AMS fetch got HTTP {resp.status}, not a PDF")
        return False
    dest.write_bytes(body)
    return True


async def nature_flow(ctx, suffix: str, dest: Path) -> bool:
    """Nature: click 'Download PDF' on the article page.

    Aborts early (AccessError) when the institution's entitlement doesn't cover
    the journal — check the message before retrying.
    """
    page = await new_page(ctx)
    art = f"https://www.nature.com/articles/{suffix}"
    await page.goto(art, timeout=90000, wait_until="load")
    await asyncio.sleep(6)
    ent = await page.evaluate(
        """() => {
            const el = document.querySelector('[data-test="entitlement-box-main"]');
            return el ? el.innerText.trim() : '';
        }"""
    )
    if "is not available" in ent:
        raise PermissionError(f"No institutional access: {ent[:120]}")
    await page.evaluate(
        """() => {
            const b = document.querySelector('[data-cc-banner]');
            if (b) {
                const btn = b.querySelector('[data-cc-action="accept"], #onetrust-accept-btn-handler');
                if (btn) btn.click();
            }
        }"""
    )
    await asyncio.sleep(2)
    async with page.expect_download(timeout=90000) as dl_info:
        await page.evaluate(
            """() => {
                const a = document.querySelector('[data-test="download-pdf"]')
                    || Array.from(document.querySelectorAll('a')).find(
                        x => x.textContent.trim() === 'Download PDF');
                if (a) a.click(); else throw new Error('no pdf link');
            }"""
        )
    await (await dl_info.value).save_as(str(dest))
    return True


async def ssrn_flow(ctx, abstract_id: str, dest: Path) -> bool:
    """SSRN: visit abstract page → wait Cloudflare → click download → save_as."""
    page = await new_page(ctx)
    art = f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={abstract_id}"
    await page.goto(art, timeout=60000, wait_until="domcontentloaded")
    await wait_challenge_clear(page, timeout_s=90)
    title = await page.title()
    if "请稍候" in title or "moment" in title.lower():
        log("  SSRN Cloudflare not passed")
        return False
    try:
        async with page.expect_download(timeout=90000) as dl_info:
            await page.evaluate(
                """() => {
                    const a = Array.from(document.querySelectorAll('a, button')).find(
                        x => (x.textContent||'').toLowerCase().includes('download'));
                    if (a) a.click(); else throw new Error('no download');
                }"""
            )
        await (await dl_info.value).save_as(str(dest))
        return True
    except Exception as e:
        log(f"  SSRN dl: {type(e).__name__} {str(e)[:60]}")
    return False


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


async def _import_playwright():
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "playwright is not installed. Run:\n"
            "  uv add playwright  (or: uv pip install playwright)\n"
            "  uv run playwright install chromium"
        ) from e
    from playwright.async_api import async_playwright

    return async_playwright


async def download_with_browser(doi: str, meta: dict, out_dir: Path) -> Path | None:
    prefix, suffix = meta["prefix"], meta["suffix"]
    slug = doi.replace("/", ".")

    # Open access: curl directly, no browser.
    if prefix == "10.5194":
        dest = out_dir / f"{slug}.pdf"
        url = copernicus_pdf_url(suffix)
        log(f"  Copernicus curl: {url}")
        return dest if curl_download(url, dest) else None
    if prefix == "10.1126":
        dest = out_dir / f"{slug}.pdf"
        article_url = f"https://www.science.org/doi/{doi}"
        pdf_url = f"https://www.science.org/doi/pdf/{doi}?download=true"
        log(f"  science.org curl two-step")
        return dest if curl_with_cookies(article_url, pdf_url, dest) else None

    apw = await _import_playwright()
    out_dir.mkdir(parents=True, exist_ok=True)
    async with apw() as pw:
        # Prefer MCP profile (stable, rich cookies) over stealth temp profile
        try:
            ctx = await launch_mcp(pw, out_dir)
            log("  browser: MCP profile")
        except Exception:
            try:
                ctx = await launch_stealth(pw, out_dir)
                log("  browser: stealth profile")
            except Exception as e:
                raise SystemExit(
                    f"Could not launch browser: {e}\n"
                    "Run: uv run playwright install chromium"
                )
        try:
            dest = out_dir / f"{slug}.pdf"
            if prefix == "10.1016":
                pii = meta.get("pii")
                if not pii:
                    raise SystemExit(f"No PII in Crossref record for {doi}")
                log(f"  ScienceDirect flow (PII {pii})")
                ok = await sd_flow(ctx, pii, dest)
            elif prefix in ("10.1029", "10.1002"):
                log(f"  Wiley/AGU pdfdirect flow ({prefix})")
                ok = await wiley_flow(ctx, doi, dest)
            elif prefix == "10.1175":
                log("  AMS flow")
                ok = await ams_flow(ctx, doi, dest)
            elif prefix == "10.1038":
                log("  Nature flow")
                try:
                    ok = await nature_flow(ctx, suffix, dest)
                except PermissionError as e:
                    log(f"  {e}")
                    oa = unpaywall_is_oa(doi)
                    if oa:
                        log(f"  Trying Unpaywall OA copy: {oa}")
                        return dest if curl_download(oa, dest) else None
                    return None
            elif prefix == "10.2139":
                log("  SSRN flow")
                ok = await ssrn_flow(ctx, suffix, dest)
            else:
                raise SystemExit(
                    f"Publisher prefix {prefix} has no scripted flow yet. "
                    "See skills/download-pdf/SKILL.md for the manual MCP-browser flows."
                )
            return dest if ok and verify_pdf(dest) else None
        finally:
            await ctx.close()


def sync_to_zotero(pdf_path: Path, doi: str) -> int:
    cmd = [
        "uv", "run", "python", "-m",
        "hydrolitagent.literature.zotero_sync", str(pdf_path), doi,
    ]
    # Windows consoles default to GBK; force UTF-8 so the Chinese GDrive path
    # and CJK titles printed by zotero_sync don't crash with a UnicodeEncodeError.
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(cmd, env=env).returncode


def _load_dotenv() -> None:
    """Load <repo>/.env (best-effort) so env-var checks match CLI runs."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except Exception:
            pass


def setup_check() -> int:
    """Verify a bare-host Zotero/GDrive setup is ready before the first sync."""
    try:  # Windows consoles default to GBK; emit UTF-8 so captured output is clean
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--doi", help="Paper DOI, e.g. 10.1029/2026GL125188")
    g.add_argument("--arxiv", help="arXiv id, e.g. 2608.18495")
    ap.add_argument("--setup-check", action="store_true",
                    help="Verify .env / Zotero API / GDrive dir, print next steps")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    ap.add_argument("--resolve-only", action="store_true", help="Show metadata and exit")
    ap.add_argument("--sync", action="store_true", help="Sync to Zotero after download")
    args = ap.parse_args()

    if args.setup_check:
        return setup_check()
    if not (args.doi or args.arxiv):
        ap.error("one of --doi / --arxiv / --setup-check is required")

    if args.arxiv:
        dest = args.out / f"arXiv.{args.arxiv}.pdf"
        url = f"https://arxiv.org/pdf/{args.arxiv}"
        log(f"arXiv curl: {url}")
        ok = curl_download(url, dest)
        if not ok:
            log("FAILED: no %PDF- header")
            return 1
        log(f"SAVED: {dest} ({dest.stat().st_size} bytes)")
        return sync_to_zotero(dest, f"10.48550/arXiv.{args.arxiv}") if args.sync else 0

    meta = crossref_meta(args.doi)
    if args.resolve_only:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0
    log(f"{meta['title'][:80]}")
    log(f"  {meta['container']} | {meta['prefix']}")

    dest = asyncio.run(download_with_browser(args.doi, meta, args.out))
    if not dest:
        log("FAILED: download did not produce a verified PDF")
        return 1
    log(f"SAVED: {dest} ({dest.stat().st_size} bytes)")
    return sync_to_zotero(dest, args.doi) if args.sync else 0


if __name__ == "__main__":
    sys.exit(main())
