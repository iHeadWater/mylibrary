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

Download academic paper PDFs through institutional access (Dalian University of Technology) using Playwright browser automation. The user's browser cookies (WebVPN + Elsevier SSO) enable automatic institutional access — no manual login needed per session.

## Contract

- Use Playwright MCP tools (`browser_navigate`, `browser_click`, `browser_evaluate`) for all browser interaction.
- Delegate PDF decoding to `uv run python -m hydrolitagent.literature.download_pdf decode <input> <output>` — never inline base64 decoding logic.
- Always verify the downloaded PDF: check size > 0, file header `%PDF-`, and extract metadata.
- **Default output path**: computed by `uv run python -m hydrolitagent.literature.download_pdf output-path <doi|pii>`.

  - Defaults to `mylibrary/outputs/papers/` (overridable via `MYLIBRARY_PDF_ROOT`).
  - Filename is auto-generated from the DOI slug (e.g. ``10.1016/j.jhydrol.2024.132471`` → ``j.jhydrol.2024.132471.pdf``).
  - Use the `-o` flag to override: ``/download-pdf <doi> -o /custom/path/paper.pdf``.

- If institutional access fails, report the blocker and suggest manual browser login steps.

## Architecture: Publisher Plugins

Each publisher has a `(detect, access, download)` triple:

| Publisher | Detect Pattern | Access Method | Download Method |
|-----------|---------------|---------------|-----------------|
| `elsevier` | `sciencedirect.com` | Elsevier IdP SSO (auto-detects DUT) | Click "View PDF" → fetch via browser |

New publishers are added below as we test them. The structure is intentionally simple:
switch on URL pattern → follow publisher-specific steps → save PDF.

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

This is the only publisher tested end-to-end. The flow:

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
   - Expected: "Dalian University of Technology" or "Full text access" in the banners.
   - If access banner is MISSING: user's SSO session may have expired. Tell the user to:
     1. Open `https://www.sciencedirect.com/` in the shared browser
     2. Click "Access through your organization" → select "Dalian University of Technology"
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
| **Institutional** | Redirects to `wayf.springernature.com` or shows "Access through your institution" | User completes WAYF → DUT SSO login, then click "Download PDF" |
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
    - Click "Dalian University of Technology" from the dropdown
    - **Pause**: tell user to complete DUT SSO login in the browser window, wait for "done"
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
| Crossref metadata fetch fails | Script falls back to PDF-embedded metadata (title, author, DOI) |
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
| `zotero_sync.py` prints `UnicodeEncodeError: 'gbk'` | Windows terminal encoding issue. Sync itself succeeds — the error is only in the print output. |
| Playwright MCP "No such tool available" | Use `mcp__plugin_playwright_playwright__*` (standalone Chromium from official plugin). NOT `plugin_ecc_playwright` (needs Chrome extension). |
| mylibrary Zotero MCP server is read-only | For writes (create item, attach PDF, file to collection) use `uv run python -m hydrolitagent.literature.zotero_sync` (pyzotero Web API). The MCP server covers reads only. |
| Institution login needs manual intervention | **Pause and wait for user**. Tell user what to do in the browser, wait for "done" signal, then continue. |
| Copernicus / static direct-PDF: anchor download shows no "Downloading..." event, no file lands | Static PDFs are served `Content-Disposition: inline` (not attachment). Use `curl -L` directly (open access); if curl stalls, `wget -c` resume or Python urllib with a 120s timeout. |
| `page.goto` to a `.pdf` direct link times out / `networkidle` never fires | Same PDF-viewer connection issue as ScienceDirect. Don't navigate — use `curl -L` on the PDF URL. |

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
2. If WAYF redirect: type "Dalian" → Enter → click "Dalian University of Technology"
3. ⚠️ PAUSE: tell user to complete DUT SSO login, wait for "done"
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
