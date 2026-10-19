# ADR-0006：下载路由增加通用浏览器兜底与无头优先

## 状态

已采纳（2026-10-18）。

## 背景

`download_browser.download_with_browser()` 按 DOI 前缀把下载分派给各出版商的专用流程。
这些流程运行良好——`.playwright-mcp/` 里一周内就有 14 份 ScienceDirect、3 份 WRR、
多份 Nature/Copernicus 的下载记录。

但路由本身有两个死角：

1. **`10.1126`（science.org）只有 curl 两步法，没有浏览器分支。** 该站后来上了 Cloudflare，
   curl 拿到的是 "Just a moment..." 挑战页，于是 `return None`——没有任何回退。
2. **前缀不在名单里直接 `raise SystemExit("no scripted flow yet")`**，连试都不试。

另外 `wait_challenge_clear()` 在"已通过"和"超时"两种情况下都返回 `None`，
调用方无法区分，也就无法实现"人点完验证、程序自动继续"。

## 决策

1. **抽取而非复制。** `goto_download()`（导航即下载）从 `wiley_flow` 抽出，
   `anchor_download()`（注入同源 `<a download>`）从 `sd_flow` 抽出，两处改为调用共享原语。
   通用流程 `generic_flow()` 完全由这两个原语 + 现有 `is_pdf_file` 组合而成，
   不重写任何下载逻辑。
2. **未知前缀改走 `generic_flow`**：读 `citation_pdf_url` / PDF 锚点逐一尝试，
   最后兜底注入 anchor。不再 `SystemExit`。
3. **`10.1126` 保留 curl 优先**（能过就不开浏览器），失败后落入浏览器路径。
4. **无头优先**：第一次尝试不弹窗。入口先做一次验证检查，无头模式下 15 秒内过不去
   （`HEADLESS_CHALLENGE_GRACE_S`）就关闭上下文、以有头模式重开——因为无头环境里没有人能点。
   有头模式下**不在入口中止**：AMS 需要按 `begin` 按钮，各 flow 自己会处理验证，入口只负责提示。
5. **挑战检测**返回布尔；DOM 选择器只认 Cloudflare 专有节点，不使用通用的
   `[class*="captcha"]`——后者会匹配 Google 的 `grecaptcha-badge` 等无害组件，
   把普通页面误判成挑战页。

## 实测依据

`10.1126/sciadv.aeb1692`（2026-10-18）：

- 真实 Chrome + MCP profile 打开文章页，Cloudflare 约 2 秒自动放行；
- 页内 `fetch()` 与 `context.request` 取 PDF **仍然 403**，不能用；
- 让**页面导航**到 `/doi/pdf/<DOI>?download=true` 会触发下载，
  Playwright 以 `goto()` 抛 `Error: Download is starting` 的形式报告，
  用 `expect_download()` 包住即可 `save_as()` 保存。

## 补充（2026-10-19）：点按钮才出 PDF 的站点

sciengine（`10.3724`，水利学报等）暴露了第三类站点：PDF **没有可猜的 URL**。
实测其流程是点页面上的「预览PDF」→ 两级 302 → `files.sciengine.com/...pdf`（`application/pdf`）
→ 新标签页内联预览，整个过程约 30 秒。

对这类站点，"找 PDF URL 再下载"从原理上就不成立，于是增加 `capture_pdf_response()`：
在 **context** 层监听 `application/pdf` 响应（这样新标签页里的响应也能收到），
点击页面自己的控件，把第一个真正的 PDF 存盘。宽限 120 秒、可提前返回、45 秒无响应再点一次。

**为什么不写死 sciengine 的 API 路径**：那依赖对方的内部路由，改版即失效；
响应捕获只依赖"最终会有一个 PDF 响应"这个稳定事实，对同类 JS 站点同样适用。

## 后果

- 新出版商不需要再写专用 flow 才能下载；现有五个 flow 的业务逻辑一行未改。
- 人机验证：出现几次就点几次，点完无需回到终端。
- `HEADLESS_FIRST = False` 可在不改结构的前提下回到"总是弹窗"。
- 已知限制：脚本专用 flow 内部仍有各自的 90–180 秒等待，无头模式下遇到不会自动消失的
  验证时，最多要等这么久才会升级到有头。
