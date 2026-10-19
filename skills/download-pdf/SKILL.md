---
name: download-pdf
description: |
  Download academic paper PDFs through institutional access using Playwright browser automation.
  Supports ScienceDirect (Elsevier) with extension architecture for Springer, Wiley, and other publishers.
  Optional Zotero sync via linked_file attachment (ZotMoov + Google Drive, zero cloud quota).
  Use when the user wants to download a paper by DOI, URL, or PII, or sync a downloaded paper to Zotero.
  Triggers: "下载论文", "download pdf", "download paper", "/download-pdf", "download_pdf",
  "下载并加到Zotero", "同步到Zotero", "加到文献库", "add to Zotero", "save to Zotero".
---

# Download Academic PDFs

Download academic paper PDFs through institutional access (any institution whose subscription covers the journal) using Playwright browser automation. The user's browser cookies (WebVPN + Elsevier SSO) enable automatic institutional access — no manual login needed per session.

## Contract

- **脚本模式（首选）**：`uv run python scripts/download_paper.py --doi <doi> [--sync]` 直接用 Python
  Playwright 驱动本机 Chrome，**不需要** MCP 工具。
- **手动模式（兜底）**：只有脚本覆盖不到、或需要人工登录时才用 MCP 工具
  (`browser_navigate`, `browser_click`, `browser_evaluate`)。
- Delegate PDF decoding to `uv run python -m hydrolitagent.literature.download_pdf decode <input> <output>` — never inline base64 decoding logic.
- Always verify the downloaded PDF: check size > 0, file header `%PDF-`, and extract metadata.
- **输出路径**：
  - 脚本模式：`--out DIR`，默认 `.playwright-mcp/`；文件名 `doi.replace('/', '.') + '.pdf'`。
  - 手动模式：`uv run python -m hydrolitagent.literature.download_pdf output-path <doi|pii>`，
    默认 `outputs/papers/`（可用 `MYLIBRARY_PDF_ROOT` 覆盖），文件名取自 DOI slug
    （``10.1016/j.jhydrol.2024.132471`` → ``j.jhydrol.2024.132471.pdf``）。

- If institutional access fails, report the blocker and suggest manual browser login steps.

## Architecture: Publisher Plugins

Each publisher has a `(detect, access, download)` triple:

| Publisher | Detect Pattern | Access Method | Download Method |
|-----------|---------------|---------------|-----------------|
| `elsevier` | `sciencedirect.com` | Elsevier IdP SSO (auto-detects DUT) | Click "View PDF" → fetch via browser |

New publishers are added below as we test them. The structure is intentionally simple:
switch on URL pattern → follow publisher-specific steps → save PDF.

## Fast Path: Autonomous Script Mode (preferred)

`scripts/download_paper.py` packages every publisher flow below into one command.
It prefers the **MCP browser profile** (stable, rich cookies) and falls back to the
stealth temp profile when MCP is unavailable. Try this first; fall back to the
MCP-browser phases only when it can't run.

```bash
# Fresh machine: verify .env / Zotero API / GDrive dir once
uv run python scripts/download_paper.py --setup-check

# Metadata check only (Crossref title/PII, no download)
uv run python scripts/download_paper.py --doi <doi> --resolve-only

# Download (auto-routes by DOI prefix), then Zotero sync
uv run python scripts/download_paper.py --doi <doi> [--sync] [--out DIR]

# arXiv preprint
uv run python scripts/download_paper.py --arxiv <id> --sync
```

- **arXiv 记录质量**:`--sync` 走 `zotero_sync`,建条目委托给 `paper_to_zotero.build_item()`
  (Crossref → arXiv API → Semantic Scholar)。arXiv DOI 在 Crossref 是 404,因此记录来自 arXiv API:
  `preprint` 类型、真实标题/摘要/日期、`extra` 含 `archiveID: arXiv:<id>`。重跑同 DOI 会**补挂到既有条目**;已挂同内容才幂等跳过。
- **post-sync 核验**:Zotero 条目标题/作者与论文一致、`itemType=preprint`、child 为
  `linked_file → attachments:<file>.pdf`、PDF 已在 `GDRIVE_PAPERS_PATH`(= Zotero Desktop 的 Linked Attachment Base Directory)。

Routing: `10.5194` Copernicus → curl · `10.1126` science.org → curl two-step，失败回退浏览器 ·
`10.1016` → SD flow（**直接有头**） · `10.1029`/`10.1002` → Wiley pdfdirect · `10.1175` → AMS ·
`10.1038` → Nature · `10.2139` → SSRN · `10.3724` → sciengine：**有头**，点页面上的
「预览PDF」，记录 `application/pdf` 响应的 URL 再用上下文回取（等控件渲染 20s、最多等 300s、
回取限 180s、45s 无反应再点一次）·
else → 通用 flow（先试响应捕获，再试 `citation_pdf_url` / PDF 锚点 → 导航下载）。

脚本优先用**无头**浏览器；**无头只要失败就用可见窗口重试一次**（不要求先看到验证，
ScienceDirect 无头下直接 ERR_ABORTED 且不弹验证）。`10.1016` 与 `10.3724` **直接有头**。
只有**没有专用 flow** 的前缀才做入口验证检查（`HEADLESS_CHALLENGE_GRACE_S`，默认 15s）；
有专用 flow 的前缀不做入口预导航——第二次 `goto` 会打断它们的重定向链。
流程中途再次出现的验证会继续等待，最多到该流程自身的超时。
First run needs: `uv run playwright install chromium` (real Chrome via `channel="chrome"` if installed).

**Why stealth matters:** a plain Playwright Chromium carries `navigator.webdriver=true` and the
`--enable-automation` switch; Cloudflare fingerprints it and re-challenges on EVERY navigation
even after the user passes the CAPTCHA by hand (it is NOT an IP ban — it self-heals once the
fingerprint is cleaned). The launcher fixes this with `channel="chrome"`,
`ignore_default_args=["--enable-automation"]`, `--disable-blink-features=AutomationControlled`,
and an init-script masking `webdriver`.

### Stealth inline pattern (when scripting by hand)

If you must drive the flows inline (agent-issued `uv run python -c "..."` scripts), reuse this
launcher verbatim — it is the part that was re-derived painfully across sessions:

```python
browser = await p.chromium.launch_persistent_context(
    user_data_dir=str(PROFILE_DIR),          # persistent dir -> cookies survive runs
    channel="chrome",                        # real Chrome, not bundled Chromium
    headless=True,                           # 脚本默认无头；过不了验证再用 False 重开
    ignore_default_args=["--enable-automation"],
    downloads_path=str(DEST_DIR),
    viewport={"width": 1280, "height": 900},
    args=["--disable-blink-features=AutomationControlled", "--no-first-run",
          "--no-default-browser-check"],
)
await browser.add_init_script(
    'Object.defineProperty(navigator, "webdriver", {get: () => undefined});'
)
```

Per-publisher script flows (all validated end-to-end; `10.1016` 与 `10.3724` 直接有头):

- **ScienceDirect**: `goto article → wait 2s 让工具栏加载 → 点文章自带的 "View PDF"（点不动才回退 goto pdfft） →
  poll until 'main.pdf' in URL → STABILIZE URL (poll until unchanged ×2 — secondary
  redirects kill the anchor) → expect_download + inject `<a download>` anchor, retry ×4 →
  save_as`. Details below in Phase 1 / Failure table.
- **Wiley/AGU**: wrap `goto pdfdirect?download=true` in `expect_download`; the goto itself
  throws ERR_ABORTED (navigation became the download) — catch and ignore it.
- **AMS**: stealth fingerprint passes the verification page; visit the aop URL which
  redirects to the published article (e.g., `aies/5/4/AIES-D-25-0069.1.xml`). Extract
  vol/issue from the final URL, construct the downloadpdf path, then use
  `page.context.request.get(downloadpdf_url, headers={'Referer': article_url})` to fetch
  PDF bytes directly. Do NOT use `expect_download` + `save_as` — the page closes mid-save.
- **SSRN**: Cloudflare auto-passes with MCP profile; visit abstract page, wait for challenge
  to clear, click the download button, save_as.
- **Nature**: check `[data-test="entitlement-box-main"]` text first; if it contains
  "is not available" the institution doesn't subscribe (e.g. Nature Reviews journals under
  "SpringerLink Liaoning & Heilongjiang") — check Unpaywall
  (`api.unpaywall.org/v2/<doi>?email=...`) for an OA copy, else skip.

**Anti-patterns (all failed this session — do not retry):**

- `context.request.get(<signed main.pdf URL>)` → 403: the sciencedirectassets CDN rejects
  the non-browser client even with cookies.
- In-page `fetch()` → base64 on the Chrome PDF-viewer page → fetch fails (viewer context).
- Bare `expect_download` around the pdfft goto → timeout: pdfft goes to verification →
  viewer, and never emits a download event by itself.
- Anchor injection immediately after the main.pdf URL appears → "Execution context was
  destroyed" (secondary redirect). Stabilize the URL first.

## Standard Workflow

### Phase 0: Resolve Input

1. Accept input in any of these forms:
   - **DOI**: `10.1016/j.jhydrol.2024.132471` or `https://doi.org/10.1016/j.jhydrol.2024.132471`
   - **PII**: `S0022169424018675`
   - **ScienceDirect URL**: `https://www.sciencedirect.com/science/article/pii/S0022169424018675`
   - **Direct PDF URL**: `https://pdf.sciencedirectassets.com/.../main.pdf?...`
   - **Copernicus preprint URL**: `https://essd.copernicus.org/preprints/<msid>/` (goes through "URL: use directly", then handled per Phase 4)

2. Resolve to article URL:
   - If DOI: navigate to `https://doi.org/<doi>` which redirects to the article page
   - If PII: construct `https://www.sciencedirect.com/science/article/pii/<pii>`
   - If URL: use directly

3. Detect publisher from the resolved URL with `uv run python -m hydrolitagent.literature.download_pdf detect <url>`.

### Phase 1: ScienceDirect / Elsevier

This is the earliest end-to-end verified flow, with the most gotchas encoded. The flow:

4. Navigate to the article page:
   ```
   browser_navigate → https://www.sciencedirect.com/science/article/pii/<PII>
   ```

5. Check for institutional access. Evaluate in browser:
   ```javascript
   () => {
     const banners = document.querySelectorAll('[class*="access"], [class*="institution"], [class*="entitled"]');
     const texts = Array.from(banners).map(b => b.textContent.trim()).filter(Boolean);
     const pdfLink = document.querySelector('a[href*="pdfft"]');
     return { accessBanners: texts.slice(0, 5), hasPdfLink: !!pdfLink, url: window.location.href };
   }
   ```
   - Expected: your institution's name or "Full text access" in the banners.
   - If access banner is MISSING: user's SSO session may have expired. Tell the user to:
     1. Open `https://www.sciencedirect.com/` in the shared browser
     2. Click "Access through your organization" → select your institution
     3. Complete SSO login (CAPTCHA/verification code if needed)
     4. Then retry.

6. Click the "View PDF" link:
   - The URL pattern is `.../pii/<PII>/pdfft?md5=...&pid=1-s2.0-<PII>-main.pdf`
   - Use selector: `a[href*="<PII>/pdfft"]` or the first `a[href*="/pdfft?"]`
   - This opens the PDF in a new tab (Chrome's built-in PDF viewer).

7. Switch to the PDF tab:
   ```
   browser_tabs(action='select', index=<pdf_tab_index>)
   ```

8. Download the PDF via **Chrome native download** — a same-origin `<a download>` anchor click.

   **Why not `browser_run_code` / `require('fs')`?** The Playwright MCP runtime has no Node.js `require` (`ReferenceError: require is not defined`), and `page.goto(..., {waitUntil: 'networkidle'})` never completes on the PDF viewer (it keeps connections open → 30s timeout). `browser_evaluate` + `fetch() + readAsDataURL()` base64 crashes the MCP transport on PDFs >1MB, and ScienceDirect papers are usually 10–30MB. The reliable path is the same Chrome native download used for Nature/Wiley, triggered here by a JS-injected `<a download>` anchor.

   **Signed-URL / security-verification flow (read first).** Clicking "View PDF" opens a new tab that may first land on a **security-verification page** (`pdf.sciencedirectassets.com/craft/capi/cfts/init?...`, title "Security verification" / "Request Verification: In Progress"). After a few seconds it auto-redirects to a **one-time signed** `main.pdf` URL (`X-Amz-Expires=300`, ~5 min). Once trust is established, later "View PDF" clicks go straight to the PDF. Notes:
   - The signed URL is **single-use** — do NOT `page.goto` it again (it expires and redirects back to the article page). To re-download, go back to the article tab and click "View PDF" again for a fresh URL.
   - A `pdf_country_code_mismatch` flag in the URL is usually harmless — let the verification finish.
   - The first article-page visit may show an Elsevier "Are you a robot?" captcha — pause and have the user complete it.

   **Steps:**
   a. Confirm the current tab is the PDF tab (URL contains `main.pdf`), not the article page: `browser_tabs(action='select', index=<pdf_tab_index>)`.
   b. Run `mcp__plugin_playwright_playwright__browser_evaluate` on the PDF tab:
   ```javascript
   () => {
     const a = document.createElement('a');
     a.href = window.location.href;
     a.download = 'temp_pdf_download.pdf';
     document.body.appendChild(a);
     a.click();
     a.remove();
     return { isPdf: window.location.href.includes('main.pdf') };
   }
   ```
   c. Confirm the tool result shows "Downloading file ..." / "Downloaded file ... to ...".
   d. Find the file: `ls -t .playwright-mcp/*.pdf | head -1` — the filename comes from the server's `Content-Disposition` (e.g. `1-s2.0-<PII>-main.pdf`), not the `download` attribute.
   e. Verify it's a real PDF: `head -c 8 <file>` should print `%PDF-`. If it's HTML, the signed URL was consumed → go back to the article tab, click "View PDF" again, and retry on the fresh PDF tab.

   **Fallback (small PDFs < 1MB only):** `fetch() + readAsDataURL()` base64, saved to a temp file and decoded with `uv run python -m hydrolitagent.literature.download_pdf decode <input> <output>`. **Do NOT use for PDFs over 1MB** — crashes the MCP transport.

9. Compute the output path (if the user didn't specify one):
   ```bash
   uv run python -m hydrolitagent.literature.download_pdf output-path 10.1016/j.jhydrol.2024.132471
   ```
   This prints the default path (e.g. `mylibrary/outputs/papers/j.jhydrol.2024.132471.pdf`).

10. Copy the downloaded PDF to the final path:
    ```bash
    cp D:/Code/mylibrary/.tmp/temp_pdf_download.pdf <output_path>
    ```

11. Clean up the temp file:
    ```bash
    rm D:/Code/mylibrary/.tmp/temp_pdf_download.pdf
    ```

12. Verify the downloaded PDF:
    ```bash
    uv run python -m hydrolitagent.literature.download_pdf verify <output_path>
    ```

### Phase 2: Nature / Springer

Nature articles use a simple download pattern: click "Download PDF" on the article page, and Chrome's native download manager saves the PDF. No base64 encoding needed.

The Playwright browser profile persists WAYF/SSO cookies, so once you've logged in once, subsequent Nature papers download without re-authentication.

**Access types:**

| Type | Indicator | Action |
|------|-----------|--------|
| **Open Access** | Gold OA badge on article page | Click "Download PDF" directly |
| **Institutional** | Redirects to `wayf.springernature.com` or shows "Access through your institution" | User completes WAYF → institutional SSO login, then click "Download PDF" |
| **Subscription only** | "Buy or subscribe" button, no institutional option, `.pdf` URL redirects to article | Skip |

**Deterministic flow:**

12. Navigate to the article page:
    ```
    mcp__plugin_playwright_playwright__browser_navigate → https://www.nature.com/articles/<article-id>
    ```

13. **If redirected to `wayf.springernature.com`** (institutional login):
    - Take a snapshot to find the institution search box
    - Type "Dalian" in the search box (`browser_type`)
    - Press Enter to show results (`browser_press_key key=Enter`)
    - Click your institution from the dropdown
    - **Pause**: tell user to complete the institutional SSO login in the browser window, wait for "done"
    - After user confirms, the page returns to the article

14. **Click "Download PDF"**:
    - Grep the snapshot YAML for `Download PDF` to find the ref
    - `browser_click(ref="<ref>")`
    - Chrome's native download manager saves the PDF to `.playwright-mcp/<filename>.pdf`
    - The tool result includes "Downloaded file ... to ..." confirming success

15. **Do NOT use** `browser_evaluate` + `fetch() + readAsDataURL()` — crashes on PDFs >1MB.
    **Do NOT use** `browser_run_code` + `require('fs')` — `require` is not defined in the Playwright MCP runtime.
    **DO use** Chrome native download triggered by clicking the download link.

### Phase 3: Wiley / AGU

Wiley Online Library (including AGU journals on `agupubs.onlinelibrary.wiley.com`) uses Cloudflare Turnstile anti-bot protection. The user must pass the challenge manually once per session.

**Key insight**: Wiley supports a `pdfdirect` endpoint with `?download=true` that triggers Chrome native download without opening the PDF viewer.

**Pattern:**
```
https://onlinelibrary.wiley.com/doi/pdfdirect/<DOI>?download=true
https://agupubs.onlinelibrary.wiley.com/doi/pdfdirect/<DOI>?download=true
```

**Deterministic flow:**

16. **First download of the session**: Navigate to an article page. If Cloudflare Turnstile blocks (page title "请稍候…" or 403 errors), tell the user:
    > Cloudflare 验证拦截了。请在浏览器窗口中手动完成人机验证，完成后回复 "done"。

17. After Cloudflare passed: navigate directly to the `pdfdirect` URL:
    ```
    mcp__plugin_playwright_playwright__browser_navigate → https://agupubs.onlinelibrary.wiley.com/doi/pdfdirect/10.1029/2024EA004157?download=true
    ```
    This triggers Chrome's native download immediately. The PDF lands in `.playwright-mcp/<filename>.pdf`.

18. Check for the downloaded file:
    ```bash
    ls -t .playwright-mcp/*.pdf | head -1
    ```

19. Cloudflare cookies persist in the browser profile, so subsequent Wiley/AGU papers in the same session can skip step 16 and go directly to the `pdfdirect` URL.

### Phase 4: Copernicus / Open-Access Direct PDF (curl)

Detect: URL contains `copernicus.org` (e.g. `essd.copernicus.org/preprints/<msid>/`), or the preprint/article page exposes a plain `.pdf` link (URL ends in `.pdf`, no `pdfft` / `pdfdirect` pattern). Copernicus papers are open access.

**Flow:**

a. `browser_navigate` → preprint/article page (e.g. `https://essd.copernicus.org/preprints/<msid>/`).

b. `browser_find "PDF"` → copy the "Preprint (... KB)" link's absolute URL (a plain `.pdf`, e.g. `https://essd.copernicus.org/preprints/<msid>/<msid>.pdf`).

c. Download with `curl` directly — open access, no bot protection:
   ```bash
   curl -sL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36" -o <file>.pdf "<pdf_url>"
   ```

d. Verify: `head -c 8 <file>` → should print `%PDF-`.

**Why NOT the `<a download>` anchor:** these static PDFs are served `Content-Disposition: inline` (not `attachment`), so the same-origin anchor does NOT emit the MCP "Downloading file..." event / land a file (tested this session). Go straight to curl — don't waste a round trip.

**Slow/stalling note:** Copernicus can be slow (see `skills/paper-to-zotero`). If curl stalls, resume with `wget -c`, or use Python urllib with a long 120s timeout.

### Phase 4b: science.org (curl first, browser fallback)

Detect: DOI prefix `10.1126`. science.org papers are open access, but the site now sits
behind Cloudflare: the two-step curl often returns the "Just a moment..." challenge page
instead of a PDF.

**Preferred (still fastest when it works)** — two-step curl with a shared cookie jar:
```bash
# Step 1: visit article page (sets cookies)
curl -sL -A "<UA>" -c cookies.txt -b cookies.txt -o /dev/null "https://www.science.org/doi/<DOI>"
# Step 2: fetch PDF with the same cookies
curl -sL -A "<UA>" -c cookies.txt -b cookies.txt -o paper.pdf "https://www.science.org/doi/pdf/<DOI>?download=true"
rm cookies.txt
```

**Fallback — browser (verified on `10.1126/sciadv.aeb1692`, 2026-10-18).**
An earlier version of this skill said "do NOT use browser automation for science.org";
that is no longer true. What actually works:

- The article page renders fine in real Chrome — Cloudflare clears in ~2s with the MCP profile.
- Fetching the PDF from **inside** the page (`fetch()` / `context.request`) still returns 403.
- Letting the **page navigate** to `/doi/pdf/<DOI>?download=true` starts a download;
  Playwright surfaces it as `goto()` raising `Error: Download is starting`, so wrap the
  navigation in `page.expect_download()` and `save_as()`.

The script does this automatically via `generic_flow` after the curl attempt fails.

In **script mode** no reply is needed after the human passes verification — the program
waits and continues. In **manual MCP mode** (you driving `browser_*` tools), still ask the
user to confirm they finished before you continue.

### Phase 5: Sync to Zotero (linked_file)

After a PDF is downloaded and verified, optionally sync it to Zotero with a linked_file attachment. The PDF is copied to the user's Google Drive papers folder (managed by ZotMoov), and Zotero stores only a pointer — **zero Zotero cloud storage used**.

**Prerequisites (one-time):**
- `ZOTERO_API_KEY` — create at https://www.zotero.org/settings/keys (enable "Allow library access")
- `ZOTERO_LIBRARY_ID` — your numeric user ID (visible on the same page)
- `GDRIVE_PAPERS_PATH` — local path to the Google Drive folder where ZotMoov stores linked PDFs
- Zotero desktop → Preferences → Advanced → Files and Folders → "Linked Attachment Base Directory" set to the same Google Drive folder
- Dependencies: `uv pip install -e ".[zotero]"` (installs pyzotero)

**Flow:**

20. **Ask the user** if they want to sync to Zotero. If the user invokes the skill with trigger phrases like "下载并加到Zotero", "加到文献库", or "add to Zotero", proceed automatically.

21. **[Optional] Resolve the target collection.** If the user specified a collection name, resolve its key via the mylibrary Zotero MCP server:
    ```
    zotero_get_collections(limit=50)   # then match by name
    ```
    Extract the 8-character key from the result.

22. **Run the sync script.** ⚠️ **MUST use `uv run python`**, NOT bare `python` (conda Python lacks pyzotero). From the mylibrary repo root:
    ```bash
    uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --json
    ```
    This single command:
    - Copies the PDF to `$GDRIVE_PAPERS_PATH/{doi-slug}.pdf`
    - Fetches rich metadata from Crossref (title, authors, journal, year, abstract)
    - Creates a Zotero parent item via pyzotero
    - Creates a linked_file attachment using the portable `attachments:` scheme
    - Outputs JSON: `{"ok": true, "zotero_key": "...", "title": "...", ...}`

23. **[Optional] File the item into a collection.** ⚠️ The mylibrary MCP server currently exposes **read-only** tools (no `zotero_manage_collections`). To file into a collection, use pyzotero directly:
    ```bash
    uv run python -c "from pyzotero import zotero as z; import os; c=z.Zotero(os.environ['ZOTERO_LIBRARY_ID'],'user',os.environ['ZOTERO_API_KEY']); c.addto_collection('<COLLECTION_KEY>',['<ZOTERO_KEY>']); print('filed')"
    ```

24. **[Optional] Verify the item was created correctly:**
    ```
    zotero_get_item(item_key="<zotero_key>")
    ```
    Confirm the title, DOI, and linked_file attachment are present.

21. **Report** the Zotero item key, title, collection, and local file path.

**How linked_file works:**

The script uses Zotero's portable `attachments:<filename>` scheme. Zotero resolves this against the "Linked Attachment Base Directory" set in Zotero preferences. The PDF lives in Google Drive (managed by ZotMoov), so:
- Zotero cloud storage quota is never touched
- The PDF is available on all machines with the same Google Drive + Zotero setup
- ZotMoov handles file organization within the linked folder

**Zotero Sync Failure Handling:**

| Scenario | Action |
|----------|--------|
| `ZOTERO_API_KEY` / `ZOTERO_LIBRARY_ID` not set | Report missing env vars; PDF is already saved locally |
| `GDRIVE_PAPERS_PATH` not set | Report missing env var; PDF is already saved locally |
| Crossref metadata fetch fails | 回退顺序：arXiv API（arXiv DOI）→ PDF 内嵌元数据（title/author/DOI）。Crossref 本身会先重试一次。 |
| Zotero API write fails | Report error; PDF is already in GDrive folder — user can manually link |
| Collection not found | Skip collection filing; item goes to "My Library" root |
| `attachments:` path not resolving | User needs to configure "Linked Attachment Base Directory" in Zotero preferences |

## Failure Handling

| Scenario | Action |
|----------|--------|
| DOI resolves to wrong page | Navigate directly to the publisher's article URL instead |
| "Access through your organization" modal blocking | Click the modal button first, wait for SSO redirect, then retry |
| Stale element reference | Re-snapshot the page before clicking |
| **MCP crash on `browser_evaluate` + base64** | **NEVER use this pattern for PDFs.** Use Chrome native download: click the download link or navigate to `pdfdirect?download=true`. |
| `require('fs')` not defined in `browser_run_code` (all phases — incl. ScienceDirect Phase 1) | Playwright MCP runtime has no Node.js `require`. Use Chrome native download instead (ScienceDirect: same-origin `<a download>` anchor on the PDF tab). |
| ScienceDirect `page.goto` on the PDF tab times out / `networkidle` never fires | Chrome's PDF viewer keeps connections open. Don't `page.goto` to grab the PDF — use the same-origin `<a download>` anchor on the PDF tab. |
| ScienceDirect signed URL jumps back to the article page on re-request | The signed `main.pdf` URL is one-time. Click "View PDF" on the article tab again to get a fresh URL. |
| ScienceDirect anchor download produced an HTML file (not `%PDF-`) | The download ran while on the article page, not the PDF tab. Retry from the tab whose URL contains `main.pdf`. |
| ScienceDirect article page shows "Are you a robot?" captcha | Pause and let the user complete the captcha manually in the browser; wait for "done". |
| `python` lacks `pyzotero` (ModuleNotFoundError) | **Always use `uv run python`** for zotero_sync.py. Conda Python doesn't have project dependencies. |
| **Wiley/AGU: "请稍候…" page or 403 errors** | Cloudflare Turnstile blocking. Tell user to pass the challenge manually in the browser window, then retry. |
| **Nature `.pdf` URL redirects to article page** | Paper requires institutional access. Follow Phase 2 WAYF login flow, then click "Download PDF" on the article page. |
| **Nature Reviews journals: no "Download PDF" link** | DUT may not subscribe to that Nature-branded journal. Check for "Buy or subscribe" vs "Access via your institution". |
| `UnicodeEncodeError: 'gbk'` | 已修：canonical 路径 `download_paper.py --sync` 会强制 UTF-8（`_ensure_utf8_stdio` + `PYTHONIOENCODING`）。只有直接跑 `python -m ...zotero_sync` 时才可能复现。 |
| Playwright MCP "No such tool available" | Use `mcp__plugin_playwright_playwright__*` (standalone Chromium from official plugin). NOT `plugin_ecc_playwright` (needs Chrome extension). |
| mylibrary Zotero MCP server is read-only | For writes (create item, attach PDF, file to collection) use `uv run python -m hydrolitagent.literature.zotero_sync` (pyzotero Web API). The MCP server covers reads only. |
| Institution login needs manual intervention | **Pause and wait for user**. Tell user what to do in the browser, wait for "done" signal, then continue. |
| Copernicus / static direct-PDF: anchor download shows no "Downloading..." event, no file lands | Static PDFs are served `Content-Disposition: inline` (not attachment). Use `curl -L` directly (open access); if curl stalls, `wget -c` resume or Python urllib with a 120s timeout. |
| `page.goto` to a `.pdf` direct link times out / `networkidle` never fires | Same PDF-viewer connection issue as ScienceDirect. Don't navigate — use `curl -L` on the PDF URL. |
| **脚本浏览器反复弹人机验证（手动通过后下次导航又被拦）** | 自动化指纹被识别，不是 IP 封禁。用 stealth launcher（`channel="chrome"` + 去 `--enable-automation` + mask `webdriver`），见 Fast Path 节。 |
| **ScienceDirect 锚点注入报 "Execution context was destroyed"** | main.pdf URL 出现后仍有二次重定向。先等 URL 连续两次轮询不变再注入锚点，并用 expect_download + 重试循环（×4, 间隔 6s）包裹。 |
| **AMS `expect_download` + `save_as` 报 TargetClosedError** | 下载触发后页面即关闭，save 竞速失败。改用 `page.context.request.get(pdf_url, Referer=article)` 直接取字节（cookie 已共享，AMS 对此不设防）。 |
| **`context.request.get` 签名 main.pdf 返回 403（832KB 错误页）** | sciencedirectassets CDN 对非浏览器 TLS 指纹拦截。SD 必须走页面内锚点下载；context.request 只对 AMS 可用。 |
| **pdfft goto 后 `expect_download` 超时** | pdfft 不触发下载事件——它进 security-verification → 签名 main.pdf 查看器。等 URL 变 main.pdf 后再注入锚点。 |
| **脚本启动报 Playwright 浏览器缺失** | `uv run playwright install chromium`。之后仍优先 `channel="chrome"`（本机真 Chrome），失败再回退 bundled Chromium。 |
| **机构访问在脚本浏览器中失效（显示 preview）** | 机构会话存在 MCP profile（`%LOCALAPPDATA%/ms-playwright-mcp/mcp-chrome-*`）或走 IP。先看 entitlement 文案；"is not available" = 机构不订阅该刊（如 Nature Reviews 系列），查 Unpaywall 后放弃或换 OA 副本，勿反复重试触发风控。 |
| **arXiv 多作者条目作者被拆错** | 只有 `verify_pdf` 解析 PDF `/Author` 时才按 `;` 拆分（`build_item` 从 Crossref/arXiv 直接构造 creators，不受影响）。用 `paper_to_zotero.fetch_arxiv`（注意其 `authors` 是 `"First Last"` 字符串列表，非 dict）拼 creators 后走 `_create_zotero_item`。 |
| **stealth profile 长时间运行后浏览器上下文崩溃** | 约 8 次以上导航后 stealth temp profile 不稳定（TargetClosedError 级联）。改用 MCP profile（`%LOCALAPPDATA%/ms-playwright-mcp/mcp-chrome-*`）；脚本已自动优先选 MCP。 |
| **AMS aop URL 返回 403** | 文章已发表，aop 不再可用。重定向到 published URL（如 `aies/5/4/...`），从中提取 vol/issue 构造 downloadpdf 路径。脚本 `ams_flow()` 已处理。 |
| **science.org 浏览器无限重定向** | 旧的裸 Chromium 会被 bot 检测拦成 ERR_TOO_MANY_REDIRECTS。curl 两步法仍是首选；失败时脚本回退到真实 Chrome + `expect_download`（2026-10-18 实测于 `10.1126/sciadv.aeb1692`）。 |

## Deterministic Patterns (for agents)

These are the ONLY patterns to use. Do not deviate.

### Download: Nature OA paper
```
1. browser_navigate → https://www.nature.com/articles/<id>
2. Grep snapshot for "Download PDF" ref
3. browser_click(ref="<ref>")  → triggers Chrome native download
4. File lands in .playwright-mcp/<name>.pdf
```

### Download: Nature institutional-access paper
```
1. browser_navigate → https://www.nature.com/articles/<id>
2. If WAYF redirect: type your institution's name → Enter → click it in the list
3. ⚠️ PAUSE: tell user to complete the institutional SSO login, wait for "done"
4. After login: Grep for "Download PDF" ref, click it
```

### Download: Wiley/AGU paper (any access type)
```
1. browser_navigate → https://onlinelibrary.wiley.com/doi/pdfdirect/<DOI>?download=true
   OR: https://agupubs.onlinelibrary.wiley.com/doi/pdfdirect/<DOI>?download=true
2. If Cloudflare blocks: ⚠️ PAUSE: tell user to pass challenge, wait for "done"
3. Chrome native download triggers automatically
4. File lands in .playwright-mcp/<name>.pdf
```

### Download: ScienceDirect / Elsevier (any access type)
```
1. browser_navigate → article page (resolve DOI via https://doi.org/<DOI>, or use the PII URL directly)
2. If "Are you a robot?" captcha: ⚠️ PAUSE: tell user to complete it, wait for "done"
3. browser_click on "View PDF" → new tab opens (may pass a "Security verification" page, then auto-redirect to `main.pdf`)
4. browser_tabs(action='select', index=<pdf_tab_index>) → confirm URL contains `main.pdf`
5. browser_evaluate → inject `<a download>` anchor at current URL, click it → Chrome native download
6. File lands in .playwright-mcp/<server-filename>.pdf; verify header is `%PDF-` (re-click "View PDF" if it's HTML)
```

### Download: Copernicus / open-access direct PDF
```
1. browser_navigate → preprint/article page (e.g. https://essd.copernicus.org/preprints/<msid>/)
2. browser_find "PDF" → copy the "Preprint" link (plain .pdf, no pdfft/pdfdirect)
3. curl -sL -A "<browser UA>" -o <file>.pdf "<pdf_url>"   # anchor won't fire on static inline PDFs
4. verify %PDF- header; if curl stalls → wget -c (resume) or urllib with 120s timeout
```

### Download: any publisher — script mode (stealth Chrome)
```
1. uv run python scripts/download_paper.py --doi <doi> [--sync]     # auto-routes by prefix
2. 10.5194 → curl; 10.1126 → curl 失败回退浏览器; 10.1016 → SD flow（直接有头）;
   10.1029/10.1002 → pdfdirect; 10.1175 → AMS context.request;
   10.1038 → Nature download-pdf click; 10.2139 → SSRN;
   10.3724 → sciengine（直接有头，点「预览PDF」并捕获 application/pdf 响应）;
   else → 通用 flow（响应捕获 → 候选 URL → anchor）
3. verify %PDF- header (script does it); --sync runs zotero_sync in the same step
```

### Download: science.org (curl two-step, browser fallback)
```
1. curl -sL -A "<UA>" -c cookies.txt -b cookies.txt -o /dev/null "https://www.science.org/doi/<DOI>"   # set cookies
2. curl -sL -A "<UA>" -c cookies.txt -b cookies.txt -o paper.pdf "https://www.science.org/doi/pdf/<DOI>?download=true"
3. rm cookies.txt; verify %PDF- header
```

### Download: SSRN preprint
```
1. uv run python scripts/download_paper.py --doi 10.2139/ssrn.<id> --sync
   (auto-routes to ssrn_flow: visit abstract page → wait Cloudflare → click download)
```

### Batch papers (titles list)
```
1. Resolve all titles first: Crossref query.bibliographic (journal version wins over
   preprint) + arXiv all:"<exact title>" when Crossref misses — one uv run python script
2. Dedup-check 用本地 `.zotero-sync-index.json`（带水位线的增量）；**不要**用 `q=doi`，
   Zotero 快速搜索不索引 DOI 字段。直接跑 `download_paper.py --doi ... --sync` 即可，查重是其中的一步。
3. Route each DOI through scripts/download_paper.py; group same-publisher papers to
   reuse the warm browser profile (challenge cookies persist)
```

### Sync to Zotero (all publishers)
```
1. uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --json
2. Output: {"ok": true, "zotero_key": "...", ...}
```

## Reporting

After each download, report:
- Paper title and first author
- File size and page count
- Output path
- Publisher used
- Whether institutional access was automatic or required manual intervention
- If synced to Zotero: item key, collection, and `attachments:` path
