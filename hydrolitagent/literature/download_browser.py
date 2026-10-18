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

# First attempt runs headless (no window); only a challenge that does not clear
# escalates to a visible window with one instruction for the human.
HEADLESS_FIRST = True
HEADLESS_CHALLENGE_GRACE_S = 15
HEADED_CHALLENGE_TIMEOUT_S = 300
GENERIC_DOWNLOAD_TIMEOUT_MS = 30_000

# Title markers that mean "an anti-bot interstitial is showing". These read as
# interstitial copy, so they are safe to gate on before any flow runs: a real
# paper title is very unlikely to say "请稍候" or "are you a robot".
# Keep them specific — a bare "verification" also matches ordinary titles such
# as "Verification of a streamflow model".
ENTRY_TITLE_MARKERS = (
    "just a moment",
    "请稍候",
    "人机验证",
    "安全验证",
    "验证码",
    "verify you are human",
    "checking your browser",
    "are you a robot",
)

# Weaker signals that would also match plausible paper titles ("Security check
# of levee systems"). Used once a flow is running, where waiting is bounded and
# the flow can press its own verification button — never for the entry gate.
CHALLENGE_TITLE_MARKERS = ENTRY_TITLE_MARKERS + ("security check", "human verification")

# Visible challenge DOM nodes. Deliberately Cloudflare-specific: a generic
# [class*="captcha"] also matches benign site-wide widgets such as Google's
# `grecaptcha-badge`, which would make ordinary pages look challenged.
CHALLENGE_DOM_JS = """() => !!Array.from(document.querySelectorAll(
  '#challenge-form, #challenge-stage, #cf-challenge-running, '
  + '.cf-browser-verification, iframe[src*="challenges.cloudflare.com"], '
  + 'iframe[title*="challenge" i]'
)).find(el => el.offsetParent !== null || el.getClientRects().length)"""

# PDF candidates discovered on an article page, in priority order.
PDF_CANDIDATES_JS = """() => {
  const out = [];
  const push = (u) => { try { if (u) out.push(new URL(u, location.href).href); } catch (e) {} };
  const meta = document.querySelector('meta[name="citation_pdf_url"]');
  if (meta) push(meta.content);
  document.querySelectorAll('link[rel="alternate"][type="application/pdf"]')
    .forEach(l => push(l.href));
  const re = /\\.pdf($|\\?)|pdfdirect|pdfft|downloadpdf|epdf|article-pdf/i;
  document.querySelectorAll('a[href]').forEach(a => {
    const text = (a.textContent || '') + ' ' + (a.getAttribute('aria-label') || '');
    if (re.test(a.href) || /download\\s*pdf|下载/i.test(text)) push(a.href);
  });
  return [...new Set(out)].slice(0, 10);
}"""

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


async def launch_stealth(playwright, downloads_dir: Path, *, headless: bool = True):
    """Launch a persistent context that Cloudflare/AMS verification auto-passes."""
    kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
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


async def launch_mcp(playwright, downloads_dir: Path, *, headless: bool = True):
    """Launch using the MCP browser profile (stable, rich cookies, no webdriver mask needed)."""
    mcp_profile = find_mcp_profile()
    if not mcp_profile:
        raise FileNotFoundError("MCP profile not found")
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(mcp_profile),
        headless=headless,
        downloads_path=str(downloads_dir),
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


async def new_page(ctx):
    return ctx.pages[0] if ctx.pages else await ctx.new_page()


async def challenge_pending(page, markers=CHALLENGE_TITLE_MARKERS) -> bool:
    """True when the page is showing an anti-bot challenge."""
    try:
        title = (await page.title() or "").lower()
    except Exception:
        title = ""
    if any(marker in title for marker in markers):
        return True
    try:
        return bool(await page.evaluate(CHALLENGE_DOM_JS))
    except Exception:
        return False


async def wait_challenge_clear(page, timeout_s: int = 90, poll_s: float = 2.0,
                               markers=CHALLENGE_TITLE_MARKERS) -> bool:
    """Poll until the challenge clears.

    Returns True when clear and False on timeout — callers must be able to tell
    the two apart to decide whether to escalate to a visible browser.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not await challenge_pending(page, markers):
            return True
        await asyncio.sleep(poll_s)
    return False


async def goto_download(page, url: str, dest: Path, timeout_ms: int = 150_000) -> bool:
    """Navigate and let the navigation become the download.

    Playwright reports a download-instead-of-navigation as an error from
    ``goto`` ("Download is starting"), which is the expected case here.
    """
    try:
        async with page.expect_download(timeout=timeout_ms) as dl_info:
            try:
                await page.goto(url, timeout=60_000, wait_until="commit")
            except Exception:
                pass
        await (await dl_info.value).save_as(str(dest))
        return True
    except Exception as e:
        log(f"  goto_download: {type(e).__name__} {str(e)[:80]}")
        return False


async def anchor_download(page, dest: Path, timeout_ms: int = 60_000) -> bool:
    """Trigger a download from the current page with a synthetic same-origin anchor."""
    try:
        async with page.expect_download(timeout=timeout_ms) as dl_info:
            await page.evaluate(ANCHOR_JS)
        await (await dl_info.value).save_as(str(dest))
        return True
    except Exception as e:
        log(f"  anchor_download: {type(e).__name__} {str(e)[:80]}")
        return False


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
        if await anchor_download(page, dest) and is_pdf_file(dest):
            return True
        log(f"  anchor attempt {attempt + 1} failed or captured HTML, retrying")
        await asyncio.sleep(6)
    return False


async def wiley_flow(ctx, doi: str, dest: Path) -> bool:
    """AGU/Wiley pdfdirect: navigation becomes the download (ERR_ABORTED is expected)."""
    host = "agupubs.onlinelibrary.wiley.com" if doi.startswith("10.1029") else "onlinelibrary.wiley.com"
    page = await new_page(ctx)
    url = f"https://{host}/doi/pdfdirect/{doi}?download=true"
    return await goto_download(page, url, dest)


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


class _NoAccess(Exception):
    """The publisher says there is no entitlement and no open-access copy."""


async def _launch_context(pw, downloads_dir: Path, *, headless: bool):
    """Launch the MCP profile, falling back to the stealth profile, retrying on profile locks."""
    last: Exception | None = None
    for _ in range(3):
        for launcher, label in ((launch_mcp, "MCP profile"), (launch_stealth, "stealth profile")):
            try:
                ctx = await launcher(pw, downloads_dir, headless=headless)
                log(f"  browser: {label}{'' if headless else ' (visible)'}")
                return ctx
            except Exception as e:
                last = e
        await asyncio.sleep(1)
    raise SystemExit(
        f"Could not launch browser: {last}\n"
        "If Chromium is missing: uv run playwright install chromium\n"
        "If the profile is locked, close the Playwright MCP browser and retry."
    )


async def _pdf_url_candidates(page, doi: str) -> list[str]:
    """PDF URLs advertised by the article page, plus the common DOI layouts."""
    try:
        raw = await page.evaluate(PDF_CANDIDATES_JS) or []
    except Exception:
        raw = []
    page_urls = [u for u in raw if isinstance(u, str) and u.startswith("http")][:2]
    page_url = getattr(page, "url", "") or ""
    origin = "/".join(page_url.split("/")[:3]) if page_url.startswith("http") else "https://doi.org"
    # Keep the DOI-layout fallbacks in the budget: a page that advertises many
    # PDF-ish anchors must not crowd out the URLs that actually work.
    urls = page_urls + [
        f"{origin}/doi/pdf/{doi}?download=true",
        f"{origin}/doi/pdfdirect/{doi}?download=true",
    ]

    seen: list[str] = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen[:4]


async def generic_flow(ctx, doi: str, meta: dict, dest: Path, *,
                       challenge_timeout_s: int = HEADED_CHALLENGE_TIMEOUT_S) -> bool:
    """Last-resort flow for publishers without a scripted one.

    Composes the same primitives the scripted flows use: navigate to the
    article, harvest a PDF URL, let the navigation download it, and fall back
    to a synthetic anchor on the current page.
    """
    dest.unlink(missing_ok=True)
    page = await new_page(ctx)
    try:
        await page.goto(f"https://doi.org/{doi}", timeout=60_000, wait_until="domcontentloaded")
    except Exception as e:
        log(f"  generic: article page unavailable ({type(e).__name__})")

    if not await wait_challenge_clear(page, timeout_s=challenge_timeout_s):
        log("  generic: challenge not cleared")
        return False

    for url in await _pdf_url_candidates(page, doi):
        if await goto_download(page, url, dest, GENERIC_DOWNLOAD_TIMEOUT_MS):
            if is_pdf_file(dest):
                return True
            dest.unlink(missing_ok=True)
        if await challenge_pending(page):
            # A second challenge can appear on the PDF hop. The human may click
            # as many times as the site asks, so wait again rather than giving up.
            log("  generic: verification appeared again, waiting for it to clear")
            if not await wait_challenge_clear(page, timeout_s=challenge_timeout_s):
                log("  generic: challenge not cleared")
                dest.unlink(missing_ok=True)
                return False

    if await anchor_download(page, dest) and is_pdf_file(dest):
        return True
    dest.unlink(missing_ok=True)
    return False


async def _any_challenge_pending(ctx) -> bool:
    for page in getattr(ctx, "pages", []):
        if await challenge_pending(page):
            return True
    return False


async def _run_scripted(ctx, prefix: str, doi: str, meta: dict, dest: Path) -> bool:
    """Run the publisher-specific flow, if one exists. Never raises SystemExit."""
    suffix = meta["suffix"]
    if prefix == "10.1016":
        pii = meta.get("pii")
        if not pii:
            log(f"  no PII in the Crossref record for {doi}")
            return False
        log(f"  ScienceDirect flow (PII {pii})")
        return await sd_flow(ctx, pii, dest)
    if prefix in ("10.1029", "10.1002"):
        log(f"  Wiley/AGU pdfdirect flow ({prefix})")
        return await wiley_flow(ctx, doi, dest)
    if prefix == "10.1175":
        log("  AMS flow")
        return await ams_flow(ctx, doi, dest)
    if prefix == "10.1038":
        log("  Nature flow")
        try:
            return await nature_flow(ctx, suffix, dest)
        except PermissionError as e:
            log(f"  {e}")
            oa = unpaywall_is_oa(doi)
            if oa:
                log(f"  Trying Unpaywall OA copy: {oa}")
                return curl_download(oa, dest)
            raise _NoAccess(str(e)) from e
    if prefix == "10.2139":
        log("  SSRN flow")
        return await ssrn_flow(ctx, suffix, dest)
    return False


async def _attempt(*, headless: bool, out_dir: Path, prefix: str, doi: str, meta: dict,
                   dest: Path) -> tuple[bool, bool]:
    """One download attempt. Returns (succeeded, challenge_still_pending)."""
    # Headless has nobody to solve a challenge, so do not stall on it: the
    # pre-check below is the single place a human-visible wait can happen.
    grace = HEADLESS_CHALLENGE_GRACE_S if headless else HEADED_CHALLENGE_TIMEOUT_S
    apw = await _import_playwright()
    async with apw() as pw:
        ctx = await _launch_context(pw, out_dir, headless=headless)
        try:
            page = await new_page(ctx)
            try:
                await page.goto(f"https://doi.org/{doi}", timeout=60_000,
                                wait_until="domcontentloaded")
            except Exception:
                pass
            # Entry gate uses interstitial-only markers so a paper titled
            # "Security check of ..." is not mistaken for a challenge.
            if not await wait_challenge_clear(page, timeout_s=grace,
                                              markers=ENTRY_TITLE_MARKERS):
                if headless:
                    # Nobody can solve a challenge without a window; escalate.
                    log("  verification did not clear (headless)")
                    return False, True
                # Headed: the flow knows how to handle its own challenge (AMS
                # needs a button press, others re-wait), so never abort here.
                log("  verification still showing; letting the flow handle it")

            try:
                ok = await _run_scripted(ctx, prefix, doi, meta, dest)
            except _NoAccess:
                raise
            except Exception as e:
                # A crashing flow is a failed attempt, not the end of the road:
                # the generic fallback may still find the PDF.
                log(f"  scripted flow crashed ({type(e).__name__}: {str(e)[:80]})")
                ok = False
            if not (ok and is_pdf_file(dest)):
                ok = await generic_flow(ctx, doi, meta, dest, challenge_timeout_s=grace)
            return bool(ok and is_pdf_file(dest)), await _any_challenge_pending(ctx)
        finally:
            await ctx.close()


async def download_with_browser(doi: str, meta: dict, out_dir: Path) -> Path | None:
    prefix, suffix = meta["prefix"], meta["suffix"]
    slug = doi.replace("/", ".")
    dest = out_dir / f"{slug}.pdf"

    # Open access: curl directly, no browser.
    if prefix == "10.5194":
        url = copernicus_pdf_url(suffix)
        log(f"  Copernicus curl: {url}")
        return dest if curl_download(url, dest) else None
    if prefix == "10.1126":
        article_url = f"https://www.science.org/doi/{doi}"
        pdf_url = f"https://www.science.org/doi/pdf/{doi}?download=true"
        log("  science.org curl two-step")
        if curl_with_cookies(article_url, pdf_url, dest):
            return dest
        # science.org sits behind Cloudflare now; fall through to the browser.
        log("  science.org curl failed; trying browser")

    out_dir.mkdir(parents=True, exist_ok=True)
    kwargs = dict(out_dir=out_dir, prefix=prefix, doi=doi, meta=meta, dest=dest)

    try:
        ok, challenged = await _attempt(headless=HEADLESS_FIRST, **kwargs)
        if ok and is_pdf_file(dest):
            return dest
        if not challenged:
            log("  FAILED: browser flows did not produce a PDF")
            dest.unlink(missing_ok=True)
            return None

        log("⚠ 请在浏览器中完成人机验证(点几次都行)。完成后无需回到终端,程序会自动继续。")
        ok, _ = await _attempt(headless=False, **kwargs)
    except _NoAccess as e:
        log(f"  no access: {e}")
        dest.unlink(missing_ok=True)
        return None

    if ok and is_pdf_file(dest):
        return dest
    dest.unlink(missing_ok=True)
    return None
