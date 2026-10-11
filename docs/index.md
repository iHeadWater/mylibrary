# Hydro AI Papers

AI 驱动的水文水资源研究 —— 文献流水线的**深度处理层**：以 Zotero 文献库为根基，承担精读、主题分类、公众号文章、播客、知识图谱与知识库积累。

**定位**：mylibrary 承担**情报汇集之后的深度处理**。Zotero 库是文献库的起点；
**Zotero 论文入库也是本仓库能力**（DOI / arXiv / 标题 → PDF → Zotero 条目）。
上游的兄弟仓库（dailyinfo）负责进入 Zotero 之前的情报采集。

## 开工前先配好这些

| 你要做的 | 先得有 |
|---|---|
| **所有**能力 | Git · Python 3.12–3.14 · [uv](https://docs.astral.sh/uv/) · `git clone` + `uv sync --all-packages` |
| 读 / 写 Zotero 库 | Zotero **API key**（放 `.env`） |
| **文献卡与主题卡** | Zotero Desktop **正在运行**且**允许其他应用通信** · 一种**已登录**的模型 CLI · **Poppler** |
| 论文入库 | GDrive 论文目录 + Zotero 的 Linked Attachment Base Directory |

逐条说明与凭据清单见 **[前提与配置](getting-started/installation.md)** —— **配一次就够**。
各功能页只写「本页额外需要什么」，不再重复。

## 能让 agent 做什么

配好之后，多数事**直接说人话**就行：

| 你对 agent 说 | 会发生什么 | 详情 |
|---|---|---|
| 「把这篇论文**下载并入库**」 | DOI / arXiv / 标题 → 下载 PDF → 建 Zotero 条目 + `linked_file` 附件 | [论文入库流水线](user-guide/paper-pipeline.md) |
| 「去我的库里找找 X 相关的文献」 | 搜 / 读 Zotero 库（含全文、附件与批注） | [MCP Server 工具](user-guide/mcp-tools.md) |
| 「把这批论文精读成分析卡 / 出一期公众号+播客」 | 每周综述：精读全文 → 分析卡 → 主题聚类 → 文章 → 播客 | [文献深度处理](user-guide/literature.md) |
| 「把《某某》这篇做成卡」 | 从你的 Zotero 找到它 → 读 PDF → 出主体卡草稿 → 代码校验 | [文献卡与主题卡](user-guide/cards/index.md) |
| 「这几篇都做一下」 | 同一条链路逐篇跑，一篇失败不拖累其余 | [单篇论文输入](user-guide/cards/paper-input.md) |
| 「看看能聚出哪些主题」 | 由已有的文献卡生成候选主题、必要时定向精读并回填 | [统一主题池](user-guide/cards/unified-theme-pool.md) |
| 「主题池现在什么样」 | 报当前候选与历史版本 | [统一主题池](user-guide/cards/unified-theme-pool.md) |
| 「当前用哪个模型 / 产物放哪」 | 报模型选择与产物落点，不调模型 | [运行维护](user-guide/cards/runtime-maintenance.md) |

> 前三行是**入库与当期内容**线；后四行是**文献卡与主题卡**线（底层是 `uv run hydrolitagent cards …`
> 的 5 条子命令）。无论哪条 —— **你不需要读那些详情页**，只在想自己动手或排错时才去。
>
> 付费墙（SD / Wiley / Nature 等）的下载需要浏览器 + 机构会话，见[论文 PDF 下载](user-guide/download-pdf.md)。

## 两侧能力

| 侧 | 做什么 | 代码 |
|---|---|---|
| **入库**（采集） | 只有两件事：论文 PDF **下载**，以及**建 Zotero 条目**（含 `linked_file` 附件） | `scripts/download_paper.py`、`hydrolitagent/zotero/`、`hydrolitagent/literature/download_pdf.py` |
| **消费** | 其余全部：从 Zotero 库读出 → 精读/分析卡 → 主题分类/知识图谱 → 公众号/播客/B 站；以及文献卡与主题卡 | `hydrolitagent/literature/`、`hydrolitagent/graph/`、`hydrolitagent/cards/`、`skills/` |

- **`hydrolitagent` 横跨两侧** —— 入库的几个命令和消费的绝大部分都在它里面，所以它不是「入库侧」的代名词。
- 两侧**产出不同**：消费侧其余部分产出**当期内容**（文章、播客、图谱、分析卡）；
  **文献卡与主题卡**把**你自己 Zotero 的文献**沉淀成**长期可追溯**的资产（确定性校验，**运行时 Windows-only**）。

两者现在是**同一个包 `hydrolitagent`**，共用一个 `.venv` 与一份 `uv.lock`。

## 能力一览

| 能力 | 说明 | 入口 |
|------|------|------|
| Zotero 文献查询 | 12 个工具的 MCP Server：搜索、浏览、读取全文/附件/批注 | [MCP Server 工具](user-guide/mcp-tools.md) |
| 论文入库流水线 | DOI / arXiv ID / 标题 → 下载 PDF → Zotero 条目 + linked_file 附件 | [论文入库流水线](user-guide/paper-pipeline.md) |
| 论文 PDF 下载 | 机构访问通过 Claude Code + Playwright 下载 | [论文 PDF 下载](user-guide/download-pdf.md) |
| Zotero 入库（linked_file） | 已下载 PDF 同步进 Zotero，零云端配额 | [Zotero 入库](user-guide/zotero-sync.md) |
| Zotero → NotebookLM | 新增论文整理成中文简报 / 音频 / 视频概览 | [Zotero → NotebookLM](user-guide/zotero-notebooklm.md) |
| 文献深度处理 | Literature CLI：每周综述、公众号发布/润色/配图、B 站上传 | [文献深度处理](user-guide/literature.md) |
| 知识图谱 | 用 graphify 构建结构化、可查询的知识库 | [模块架构](development/architecture.md) |
| **文献卡与主题卡** | 自己的 Zotero 论文 → 文献卡 → 候选主题（**Windows-only**） | [文献卡与主题卡](user-guide/cards/index.md) |
| 论文复现 | 复现 AI 驱动水文学关键论文 | `equation_from_data/`、`google_floodhub/` |

## 项目结构

```
hydrolitagent/
├── cli.py               # CLI 入口：prepare, extract, graph, merge, query, cards
├── zotero/              # Zotero 集成
│   ├── server.py         # 12 工具 MCP Server（FastMCP，端口 8002）
│   ├── paper_to_zotero.py # DOI/arXiv/标题 → Zotero 条目
│   └── zot_link_gdrive.py # Google Drive → linked_file 附件
├── literature/          # Literature CLI（入库后的深度处理）
├── graph/               # 知识图谱构建 + 合并（graphify）
├── query/               # 确定性图查询（不走 LLM）
└── cards/               # 文献卡与主题卡
    ├── *.py              #   5 条子命令的实现
    └── assets/           #   只读资产：模板 / 提示词 / schema / 示例 / 默认配置

configs/                 # 配置：graph_prompts.toml · paths.toml · paper-input.toml · ai.toml
scripts/                 # download_paper.py、run_paper_pipeline.sh、paper_input.py、…
skills/                  # Agent 可用 Skill（12 个）
docs/                    # 文档站点（mkdocs-material）
outputs/                 # 精读产物（默认落点，可配置）
papers/                  # 按主题组织的文献库（10 个主题）
```

> 文献卡与主题卡的**生成产物**（文献卡、主题池、运行记录）不入库，由运行时落到仓库根自建。

## 文档导航

- **[前提与配置](getting-started/installation.md)** — **先看这个**：公共前提与凭据
- [5 分钟上手](getting-started/quickstart.md) — 查询文献、添加论文、启动服务
- [用户指南总览](user-guide/index.md) — 两条能力线各自看哪些页
- [文献卡与主题卡](user-guide/cards/index.md) — 从自己 Zotero 的论文生成文献卡与主题卡（**Windows-only**）
- [MCP Server 工具](user-guide/mcp-tools.md) — 12 个 MCP 工具完整参考
- [论文入库流水线](user-guide/paper-pipeline.md) — DOI 到 Zotero 的完整流程
- [论文 PDF 下载（机构访问）](user-guide/download-pdf.md) · [Zotero 入库（linked_file）](user-guide/zotero-sync.md) · [Zotero → NotebookLM](user-guide/zotero-notebooklm.md)
- [文献深度处理](user-guide/literature.md) — 精读/主题/公众号/播客 CLI
- [Zotero 配置参考](user-guide/config.md) — 配置文件与环境变量逐字段
- [模块架构](development/architecture.md) — 代码结构与数据流
- [贡献指南](development/contributing.md) — 如何运行测试与添加新工具
- [决策记录](adr/0001-zotero-linked-file-sync.md) — 为什么用 linked_file；[ADR-0002](adr/0002-zotero-two-clients-boundary.md) — 为什么保留两套 Zotero 客户端
