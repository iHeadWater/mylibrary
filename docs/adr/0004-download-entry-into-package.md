# ADR-0004：下载逻辑收进包，`scripts/download_paper.py` 变薄壳

- 状态：已接受
- 日期：2026-10-11
- 相关：[ADR-0001](0001-zotero-linked-file-sync.md)、[ADR-0002](0002-zotero-two-clients-boundary.md)

## Context

仓库里「把一篇论文的 PDF 搞到手」有两个入口：

| | `scripts/download_paper.py` | `hydrolitagent/literature/download_pdf.py` |
|---|---|---|
| 行数 | **650** | 484 |
| 形态 | **脚本**，逻辑全在文件里，**零测试** | **包内模块**，有 `tests/test_literature_download_pdf.py` |
| 路由方式 | 按 **DOI 前缀** | 按 **URL 主机** |
| 覆盖 | Copernicus · science.org · SD · Wiley+AGU · AMS · Nature · SSRN | Elsevier · Springer · Wiley · T&F · AGU |
| 谁在用 | **全部 3 个 skill**（`download-pdf` / `paper-to-zotero` / `run-paper-to-zotero`） | 只有文档 |

**先澄清一个误判**：这两个**不是两份重复实现** —— 路由维度与覆盖面都不同，是**互补**的。
真正的问题是**形态**：`scripts/` 下另外两个脚本（`paper_input.py` / `paper_validate.py`）
都已是「薄壳转发到包内」的形态，**就它把 650 行逻辑内联在脚本里，且没有测试**。

另有两处小病：`verify_pdf` 在两个文件里**同名不同物**
（脚本里返 `bool` 只查 `%PDF-`；模块里返 `PdfMetadata` 且会抛异常）；
`sd_flow` 里手写了 `https://www.sciencedirect.com/science/article/pii/{pii}`，
而模块里已有 `pii_to_sciencedirect_url`。

## Decision

**把下载逻辑收进包，`scripts/download_paper.py` 变薄壳。**

- 新增 `hydrolitagent/literature/download_browser.py`（内部模块，无 CLI）：浏览器流程
  （stealth / MCP 档案、5 个出版商 flow、playwright 惰性导入）。
  单独成文件是为了不让 `download_pdf.py` 过千行。
- `hydrolitagent/literature/download_pdf.py` 成为**公开模块**：原有工具函数 + 并入
  curl 优先、Crossref/Unpaywall、`setup_check`、`sync_to_zotero`，以及公开入口
  `download_paper(...) -> int`。原有 6 个子命令 CLI **不动**。
- `scripts/download_paper.py` 只解析 CLI → 调包内入口。
  **参数、help 文本、退出码逐项不变**（3 个 skill 与多篇文档依赖它）。
- `verify_pdf`（bool 那个）改名 **`is_pdf_file`**；`sd_flow` 改用 `pii_to_sciencedirect_url`。

**明确不做**：不合并 `literature/` 与 `cards/` 的取文献层（无重复代码，且 **ADR-0002 仍然有效**
——那两套 Zotero 客户端读的是**不同库**：群组库 vs 个人库）。

## Consequences

- 下载逻辑**可测**了：`tests/test_literature_download_pdf.py` 41 → 59 个用例。
- `scripts/` 三个脚本形态一致：都是薄壳。脚本 650 → 68 行。
- 同一件事不再有两个名字（`verify_pdf` 撞名消除；`pii_to_sciencedirect_url` 不再有第二份）。
- **代价**：付费墙浏览器流程（SD / Wiley / AMS / Nature / SSRN）本地**跑不了** ——
  本次只做到「原样搬运 + 可编译 + 静态核对」，其实跑行为**未验证**。将来改动这些流程时，
  仍需真实 Chrome + 机构会话才能验证。
- 想统一的读者注意：`download_pdf.py` 的 6 个子命令（`detect` / `doi` / `decode` /
  `verify` / `classify` / `output-path`）仍在原处 —— 那是它的公开 CLI，未迁移。
