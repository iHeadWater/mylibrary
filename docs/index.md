# Hydro AI Papers

AI 驱动的水文水资源研究 —— 文献流水线的**深度处理层**:以 Zotero 文献库为根基,承担精读、主题分类、公众号文章、播客、知识图谱与知识库积累。

**定位**:mylibrary 承担**情报汇集之后的深度处理**。Zotero 库是文献库的起点(深度处理典型地从读库开始);**Zotero 论文入库也是本仓库能力**——DOI / arXiv / 标题 → PDF → Zotero 条目的流水线就在本仓库。上游的兄弟仓库(dailyinfo)负责进入 Zotero 之前的情报采集。

本仓库的能力分**入库**与**消费**两侧:

| 侧 | 做什么 | 代码 |
|---|---|---|
| **入库**（采集） | 只有两件事:论文 PDF **下载**,以及**建 Zotero 条目**（含 `linked_file` 附件) | `scripts/download_paper.py`、`hydrolitagent/zotero/`、`hydrolitagent/literature/download_pdf.py` |
| **消费** | 其余全部:从 Zotero 库读出 → 精读/分析卡 → 主题分类/知识图谱 → 公众号/播客/B 站;以及文献卡与主题卡平台 | `hydrolitagent/literature/`、`hydrolitagent/graph/`、`hydrolitagent/cards/`、`skills/`、[文献卡与主题卡](user-guide/cards/index.md) |

两点容易搞混,先讲清楚:

- **`hydrolitagent` 横跨两侧** —— 入库的几个命令和消费的绝大部分都在它里面,所以它不是"入库侧"的代名词。
- **两侧产出的东西不同** —— 消费侧的其余部分产出**当期内容**(文章、播客、图谱、分析卡);文献卡与主题卡平台把**自己 Zotero 的文献**沉淀成**长期可追溯的文献卡与主题卡**,特点是确定性校验、**运行时为 Windows-only**。

两者现在是**同一个包 `hydrolitagent`**(文献卡与主题卡在 `hydrolitagent/cards/`),共用一个 `.venv` 与一份 `uv.lock`。

## 能力一览

| 能力 | 说明 | 入口 |
|------|------|------|
| Zotero 文献查询 | 12 个工具的 MCP Server 搜索、浏览、读取全文/附件/批注 | [MCP Server 工具](user-guide/mcp-tools.md) |
| 论文入库流水线 | DOI / arXiv ID / 标题 → 下载 PDF → Zotero 条目 + linked_file 附件 | [论文入库流水线](user-guide/paper-pipeline.md) |
| 论文 PDF 下载 | 机构访问(大连理工 SSO)通过 Claude Code + Playwright 下载 | [论文 PDF 下载](user-guide/download-pdf.md) |
| Zotero 入库(linked_file) | 已下载 PDF 同步进 Zotero 作为 linked_file,零云端配额 | [Zotero 入库](user-guide/zotero-sync.md) |
| Zotero → NotebookLM 简报 | 新增论文整理成中文简报 / 音频 / 视频概览 | [Zotero → NotebookLM](user-guide/zotero-notebooklm.md) |
| 文献深度处理 | Literature CLI:每周综述、公众号发布/润色/配图、B 站上传 | [文献深度处理](user-guide/literature.md) |
| 知识图谱 | 用 graphify 构建结构化、可查询的知识库(实体提取、社区发现、Obsidian 导出) | [模块架构](development/architecture.md) |
| 论文复现 | 复现 AI 驱动水文学关键论文 | `equation_from_data/`、`google_floodhub/` |
| 文献卡与主题卡平台 | 从自己 Zotero 的一篇论文 → 主体卡草稿 → 代码校验 → 若干文献卡 → 候选主题。确定性校验。**运行时为 Windows-only。** | [平台文档](user-guide/cards/index.md) |

## 快速开始

```bash
# 安装
git clone git@github.com:iHeadWater/mylibrary.git
cd mylibrary
uv sync --all-packages   # 装根包依赖（原 workspace 成员已并入）

# 配置 Zotero
cp .env.example .env
# 编辑 .env,填入 ZOTERO_API_KEY 和 ZOTERO_LIBRARY_ID
```

> 本仓库只有一个包 **`hydrolitagent`**——原 `hydro-platform` 已并入其 `hydrolitagent/cards/` 子包。`.venv` 与 `uv.lock` 仍只有一份。

详见 [安装配置](getting-started/installation.md)。

## 项目结构

```
hydrolitagent/
├── cli.py               # CLI 入口:prepare, extract, graph, merge, query
├── zotero/              # Zotero 集成
│   ├── server.py         # 12 工具 MCP Server(FastMCP,端口 8002)
│   ├── paper_to_zotero.py # DOI/arXiv/标题 → Zotero 条目(Crossref/arXiv 元数据)
│   └── zot_link_gdrive.py # Google Drive → linked_file 附件
├── literature/          # Literature CLI(入库后深度处理)
│   ├── download_pdf.py      # 机构访问下载 PDF
│   ├── zotero_sync.py       # PDF → Zotero linked_file
│   ├── zotero_notebooklm.py # Zotero → NotebookLM 简报/音频/视频
│   ├── bilibili_upload.py   # 播客 → MP4 → B 站
│   └── wechat/              # figure.py, polish.py, push.py
├── graph/               # 知识图谱构建 + 合并(graphify)
│   ├── build.py          # prepare / extract / graph
│   └── merge.py          # 多 topic 合并 + D3.js HTML 可视化
└── query/               # 确定性图查询(不走 LLM)
    └── search.py

configs/                 # Prompt / 提取配置
scripts/                 # run_paper_pipeline.sh, download_paper.py (stealth one-command PDF downloader), chunk_fulltext.py
skills/                  # Agent 可用 Skill(12 个)
docs/                    # 文档站点(mkdocs-material)
outputs/                 # 精读产物(默认落点,可配置):weekly-review/{date}/{cards,article,podcast}
papers/                  # 按主题组织的文献库(10 个主题)

hydrolitagent/cards/     # 文献卡与主题卡(消费侧:自己的 Zotero → 文献卡 → 主题卡)
├── automation/          #   Python:单篇输入 → PDF 门禁 → 制卡 → 校验 → 主题池
├── templates/           #   可复用资产:九类证据卡模板、主题提示词、JSON schema
├── config/              #   非敏感配置与完整示例
└── pyproject.toml       #   入口:`uv run hydrolitagent cards`
                         #   生成产物(文献卡、主题池、运行记录)不入库,
                         #   由运行时自建。

equation_from_data/      # 论文复现:从数据发现方程
google_floodhub/         # 论文复现:Google 洪水预测
definitions.py           # 共享常量
```

## 文档导航

- [安装配置](getting-started/installation.md) — 环境搭建与 Zotero API 配置
- [5 分钟上手](getting-started/quickstart.md) — 查询文献、添加论文、启动服务
- [用户指南总览](user-guide/index.md) — 本节导览:两条能力线各自看哪些页
- [MCP Server 工具](user-guide/mcp-tools.md) — 12 个 MCP 工具完整参考
- [论文入库流水线](user-guide/paper-pipeline.md) — DOI 到 Zotero 的完整流程
- [论文 PDF 下载（机构访问）](user-guide/download-pdf.md) — Playwright 浏览器下载
- [Zotero 入库（linked_file）](user-guide/zotero-sync.md) — PDF → Zotero 条目
- [Zotero → NotebookLM 简报](user-guide/zotero-notebooklm.md) — 新机器配置与完整工作流
- [文献深度处理](user-guide/literature.md) — 精读/主题/公众号/播客 CLI
- [Zotero 配置参考](user-guide/config.md) — 配置文件与环境变量
- [模块架构](development/architecture.md) — 代码结构与数据流
- [贡献指南](development/contributing.md) — 如何运行测试与添加新工具
- [决策记录](adr/0001-zotero-linked-file-sync.md) — 为什么用 linked_file；[ADR-0002](adr/0002-zotero-two-clients-boundary.md) — 为什么保留两套 Zotero 客户端
- [文献卡与主题卡平台](user-guide/cards/index.md) — 从自己 Zotero 的论文生成文献卡与主题卡(**Windows-only**)
