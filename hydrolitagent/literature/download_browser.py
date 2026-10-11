"""Browser-download flows for paywalled publishers (internal, no CLI).

Moved out of ``scripts/download_paper.py`` so the download logic lives in an
importable, testable package module. ``download_pdf.py`` orchestrates and
imports this module lazily; this module offers no console entry point.

The flows here are the battle-tested publisher automations:

- curl-first for open-access sources (Copernicus, science.org) — delegated to
  ``download_pdf``; no browser needed.
- Browser automation for Cloudflare/verification-protected publishers.
  Prefers the MCP browser profile (stable, rich cookies) over the stealth temp
  profile. The stealth launch (real Chrome channel, no automation flags, masked
  navigator.webdriver) is the fallback when MCP profile is unavailable.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import time
from pathlib import Path

from hydrolitagent.literature.download_pdf import (
    copernicus_pdf_url,
    curl_download,
    curl_with_cookies,
    is_pdf_file,
    pii_to_sciencedirect_url,
    unpaywall_is_oa,
)

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


def find_mcp_profile() -> Path | None:
    """Find the most recently used MCP browser profile directory."""
    if not MCP_BASE.exists():
        return None
    profiles = sorted(MCP_BASE.glob("mcp-chrome-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return profiles[0] if profiles else None


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


def _is_signed_pdf_url(url: str) -> bool:
    """True only for the real signed PDF viewer URL.

    Must exclude three impostors that all contain the substring 'main.pdf':
    - the security-verification page (query has 'p=...main.pdf', path is /craft/capi/cfts/init)
    - the pdfft redirect URL (query has 'pid=...-main.pdf')
    """
    return (
        url.startswith("https://pdf.sciencedirectassets.com/")
        and "/main.pdf?" in url
    )


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
    art = pii_to_sciencedirect_url(pii)
    pdfft = art + f"/pdfft?pid=1-s2.0-{pii}-main.pdf"
    await page.goto(art, timeout=60000, wait_until="domcontentloaded")
    await wait_challenge_clear(page)
    try:
        await page.goto(pdfft, timeout=60000, wait_until="commit")
    except Exception:
        pass  # navigation may be replaced by the redirect chain
    deadline = time.time() + 120
    while time.time() < deadline:
        if _is_signed_pdf_url(page.url):
            break
        await asyncio.sleep(4)
    if not _is_signed_pdf_url(page.url):
        log(f"  never reached main.pdf (url={page.url[:70]})")
        return False
    for _ in range(6):  # URL stabilization across secondary redirects
        u1 = page.url
        await asyncio.sleep(5)
        if page.url == u1 and _is_signed_pdf_url(page.url):
            break
    for attempt in range(4):
        if not _is_signed_pdf_url(page.url):
            await asyncio.sleep(5)
            continue
        try:
            async with page.expect_download(timeout=60000) as dl_info:
                await page.evaluate(ANCHOR_JS)
            await (await dl_info.value).save_as(str(dest))
            if is_pdf_file(dest):
                return True
            log(f"  anchor attempt {attempt + 1}: security-verification HTML captured, retrying")
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
            return dest if ok and is_pdf_file(dest) else None
        finally:
            await ctx.close()
