# 论文 PDF 下载（机构访问）

通过机构访问（大连理工大学 SSO）用 Claude Code + Playwright 浏览器自动化下载学术论文。

> **依赖**：下载步骤需要 Claude Code。它不能作为独立 CLI 运行——浏览器编排通过 Claude Code 的 Playwright MCP 插件完成。

## 流程概览

```text
用户输入: /download-pdf <DOI>
  → Claude Code 打开独立 Chromium
  → 导航到出版商站点
  → 处理机构登录(需要时由人完成 DUT SSO)
  → 通过 Chrome 原生下载管理器触发 PDF 下载
  → 用 download_pdf.py verify 验证 PDF
  → [可选] 用 zotero_sync 同步到 Zotero
```

## 一次性设置

### 1. 启用 Playwright 插件

在 `~/.claude/settings.json`:

```json
"enabledPlugins": {
  "playwright@claude-plugins-official": true
}
```

提供 `mcp__plugin_playwright_playwright__*` MCP 工具（独立 Chromium）。

### 2. 安装 Chromium

```bash
npx playwright install chromium
```

### 3. 安装项目依赖

```bash
uv sync --python python3
uv pip install -e .
```

（pyzotero 已是基础依赖，无需单独安装）

### 4. 配置环境

在 `.env`:

```env
# Zotero 同步必需
ZOTERO_API_KEY=<key>          # https://www.zotero.org/settings/keys
ZOTERO_LIBRARY_ID=<id>        # 数字型用户 ID
GDRIVE_PAPERS_PATH=<path>     # 本地 GDrive 路径(ZotMoov 目标)
```

## 用法

**方式一：自主脚本模式（首选，无需交互）**

```bash
uv run python scripts/download_paper.py --doi 10.1029/2026GL125188 --sync
uv run python scripts/download_paper.py --arxiv 2608.18495 --sync
uv run python scripts/download_paper.py --doi <doi> --resolve-only   # 仅查元数据
```

脚本按 DOI 前缀自动路由到对应出版商流程，内置 **stealth Chrome 启动器**
（真实 Chrome 内核 + 剥离自动化标记），Cloudflare / AMS 人机验证**自动通过**，
全程无需手动干预。首次使用需 `uv run playwright install chromium`。

**方式二：agent + Playwright MCP 浏览器**（脚本无法覆盖的出版商或需人工登录时）

```
/download-pdf 10.1038/s41586-026-10704-3
```

agent 打开 Chromium 窗口。你只需在以下情况交互：
- **Cloudflare 挑战**出现（Wiley/AGU）——在浏览器里点击复选框
- **机构登录**需要——在浏览器里完成 DUT SSO

## 支持的出版商

| 出版商 | 访问方式 | 下载模式 |
|--------|---------|---------|
| **Nature** | OA：直接 | 点击 "Download PDF" → Chrome 原生下载 |
| **Nature** | 机构 | WAYF → DUT SSO → 点击 "Download PDF" |
| **Wiley** | 任意 | `pdfdirect?download=true` URL 触发原生下载 |
| **AGU** | 任意 | 同 Wiley（`agupubs.onlinelibrary.wiley.com`） |
| **AMS** | 机构/IP | aop→published redirect → `context.request` 取 PDF 字节 |
| **Elsevier (ScienceDirect)** | SSO 自动识别 | 导航 → "View PDF" → 新标签页(可能经安全校验)→ 同源 `<a download>` 锚点 → 原生下载 |
| **Copernicus (ESSD 等)** | 开放获取 | 直链 `curl -L` 下载(静态 PDF 锚点无效) |
| **science.org** | 开放获取 | curl 两步法：先文章页设 cookie，再带 cookie 拉 PDF |
| **SSRN** | 免费下载 | 浏览器访问摘要页 → Cloudflare 自动通过 → 点击下载 |

## 工作原理

### Nature / Springer

Nature 文章用简单模式：

```
Article: https://www.nature.com/articles/s41586-026-10704-3
PDF:     https://www.nature.com/articles/s41586-026-10704-3.pdf
```

- **OA 论文**：文章页上的 "Download PDF" 链接触发 Chrome 原生下载
- **机构论文**：浏览器重定向到 `wayf.springernature.com`（WAYF）。agent 选择 "Dalian University of Technology"，用户完成 DUT SSO 登录。WAYF/SSO cookie 在浏览器配置中跨 Claude Code 重启持久化

### Wiley / AGU

Wiley 使用 Cloudflare Turnstile 反爬保护。用户手动通过挑战后，agent 使用 `pdfdirect` 端点：

```
https://onlinelibrary.wiley.com/doi/pdfdirect/<DOI>?download=true
https://agupubs.onlinelibrary.wiley.com/doi/pdfdirect/<DOI>?download=true
```

这直接触发 Chrome 原生下载——无 PDF 查看器、无 base64 编码。Cloudflare cookie 在会话内持久化，后续 Wiley/AGU 论文跳过挑战。

### ScienceDirect

点 "View PDF" 后新标签页**可能**先到 security-verification 页（`pdf.sciencedirectassets.com/craft/capi/cfts/init?...`，几秒自动跳转），也可能直跳签名 `main.pdf` URL。签名 URL 是**一次性**的（`X-Amz-Expires=300`，约 5 分钟过期）——**不要对其重新 `page.goto`**（会消耗并跳回文章页）。在该 PDF 标签页用同源 `<a download>` 锚点触发 Chrome 原生下载。首次访问文章页可能遇 "Are you a robot?" captcha——暂停让用户手动完成。

### Copernicus / 开放获取直链 PDF

预印本/文章页暴露纯 `.pdf` 直链（无 `pdfft`/`pdfdirect`）。这类**静态 PDF 按 inline 提供，锚点下载不触发**（无 "Downloading..." 事件）。直接用 `curl -L` 拉取：

```bash
curl -sL -A "Mozilla/5.0" -o paper.pdf "https://essd.copernicus.org/preprints/<msid>/<msid>.pdf"
```

Copernicus 偶有慢速/超时——curl 中断用 `wget -c` 续传，或 Python urllib 配 120s 超时。

### Stealth Chrome 脚本模式（scripts/download_paper.py）

裸 Playwright Chromium 带 `navigator.webdriver=true` 和 `--enable-automation` 开关，Cloudflare 靠指纹识别后**每次导航都重新弹验证**（即使人工通过也没用——这不是 IP 封禁）。脚本模式改用：

- `channel="chrome"`（本机真实 Chrome）+ `ignore_default_args=["--enable-automation"]`
- `--disable-blink-features=AutomationControlled` + init-script 掩蔽 `webdriver`
- persistent profile（临时目录下），验证 cookie 跨次运行复用

效果：AMS "Human Verification" 与 ScienceDirect Cloudflare 全部自动通过。

### AMS

stealth 指纹过掉验证页后，用 `page.context.request.get(downloadpdf_url)`（带文章页 Referer，cookie 自动共享）直接取 PDF 字节。**不要**用 `expect_download` + `save_as`——下载触发后页面立即关闭，save 会竞速失败（TargetClosedError）。

### science.org

开放获取，但对自动化浏览器有 bot 检测（无限重定向）。用 **curl 两步法**绕过：

```bash
# 第一步：访文章页设 cookie
curl -sL -A "Mozilla/5.0" -c cookies.txt -b cookies.txt "https://www.science.org/doi/<DOI>"
# 第二步：带 cookie 拉 PDF
curl -sL -A "Mozilla/5.0" -c cookies.txt -b cookies.txt -o paper.pdf "https://www.science.org/doi/pdf/<DOI>?download=true"
rm cookies.txt
```

### SSRN

SSRN 预印本免费下载。Cloudflare 挑战在 MCP 浏览器 profile 下自动通过。访问摘要页
`https://papers.ssrn.com/sol3/papers.cfm?abstract_id=<id>`，等待验证通过后点击
下载按钮即可。

### 反模式（DO NOT USE）

| 模式 | 为什么坏 |
|------|---------|
| `browser_evaluate` + `fetch()` + `readAsDataURL()` | Base64 超 MCP 传输限制 → 崩溃 |
| `browser_run_code` + `require('fs')` | MCP 运行时未定义 `require` |
| `mcp__plugin_ecc_playwright__*` | 需要 Chrome 扩展桥，非独立 |
| `python scripts/zotero_sync.py` | 用 `uv run python`——conda Python 缺依赖 |
| 裸 Playwright Chromium 反复被 Cloudflare 拦 | `navigator.webdriver` 指纹暴露；用 stealth 启动器（`channel="chrome"` + 去 automation 标记） |
| `context.request` 拉 ScienceDirect 签名 PDF | assets CDN 对非浏览器 TLS 指纹返回 403（AMS 可用，SD 不可用） |
| main.pdf URL 一出现就注入锚点 | 二次重定向会摧毁执行上下文——先等 URL 稳定 |
| 浏览器上下文长时间运行后崩溃 | 约 8 次导航后 stealth temp profile 不稳定；用 MCP profile（脚本已自动优先） |
| science.org 浏览器无限重定向 | bot 检测；改用 curl 两步法（先文章页设 cookie） |

## 命令参考

```bash
# 一条命令：解析 → 按出版商路由 → 下载 → 验证（--sync 加入库）
uv run python scripts/download_paper.py --doi <doi> [--sync] [--out DIR]
uv run python scripts/download_paper.py --arxiv <id> [--sync]
uv run python scripts/download_paper.py --doi <doi> --resolve-only   # 仅查元数据

# 解析和分类输入
uv run python -m hydrolitagent.literature.download_pdf doi <doi>
uv run python -m hydrolitagent.literature.download_pdf classify <input>
uv run python -m hydrolitagent.literature.download_pdf detect <url>

# 计算输出路径
uv run python -m hydrolitagent.literature.download_pdf output-path <doi>

# 解码 base64（遗留，仅小 PDF）
uv run python -m hydrolitagent.literature.download_pdf decode <input> <output>

# 验证 PDF
uv run python -m hydrolitagent.literature.download_pdf verify <pdf>
```

## 失败模式

| 症状 | 原因 | 修复 |
|------|------|------|
| 页面标题 "请稍候…" / 403 | Cloudflare Turnstile 拦截 | 用户在浏览器中通过挑战 |
| "Access through your institution" | 未登录 / 会话过期 | 走 WAYF → DUT SSO 流程 |
| "Buy or subscribe" / 无 PDF 链接 | 期刊不在 DUT 订阅中 | 跳过——从其他来源下载 |
| 大 PDF 时 MCP 崩溃 | base64 编码溢出 | 用 Chrome 原生下载，不用 evaluate |
| `ModuleNotFoundError: pyzotero` | 用错 Python（`python` vs `uv run python`） | 始终用 `uv run python` |
| Copernicus 锚点下载无文件 | 静态 PDF inline 提供，锚点不触发下载 | `curl -L` 直连 |
| ScienceDirect 签名 URL 重导航后跳回文章页 | 签名 URL 一次性 | 回文章页重点 "View PDF" 获取新 URL |

## 相关

- [Zotero 入库（linked_file）](zotero-sync.md)
- [论文入库流水线](paper-pipeline.md)
- [ADR-0001：linked_file 设计](../adr/0001-zotero-linked-file-sync.md)
- [配置参考](config.md)
