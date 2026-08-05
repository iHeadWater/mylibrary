# Hydro AI Papers (mylibrary)

Literature knowledge base for AI-driven hydrology and water resources research.

## 定位 (Role)

mylibrary 是 **文献库处理 + 知识库 + 主题深度探讨** 的仓库,以 **Zotero 库为分界线**:
- **上游(dailyinfo)**:采集/下载/入库 → 文献进入 Zotero 之前的动作
- **本仓库(mylibrary)**:读 Zotero → 精读分析卡 → 主题分类 → 公众号文章/播客 → 知识库积累

**Zotero 是唯一共享事实层。** 本仓库的一切输入来自 Zotero MCP(读库),不维护自己的 Zotero 镜像,不读 dailyinfo 的输出文件。

## Zotero 接入方式 (IMPORTANT)

本仓库的 Zotero MCP server(`hydrolitagent/zotero/server.py`,FastMCP SSE 端口 8002)是唯一的 Zotero 访问入口。**不要改动它的技术架构**——已有其他服务依赖。

工具分两类(见 `server.py` 头部注释):
- **元数据类**(pyzotero Web API,api.zotero.org):`zotero_search`、`zotero_get_item`、`zotero_get_recent`、`zotero_get_collection_items`、`zotero_get_collections`、`zotero_get_tags`、`zotero_search_by_tag`、`zotero_fulltext_search`、`zotero_get_attachments`、`zotero_get_annotations`
- **PDF 原文类**(Zotero Desktop **Local API**,`http://host.docker.internal:23119`):`zotero_get_fulltext`、`zotero_get_file_info`。**需要 Zotero Desktop 运行且勾选 "Allow other applications to communicate with Zotero"**。Zotero PDF 存在 Google Drive,只能本地访问——Local API 就是从 GDrive 同步存储取文件的方式。

> ⚠️ 注意:本仓库工具名与 dailyinfo 的 Zotero 插件 MCP 不同(`zotero_get_fulltext` 而非 `zotero_get_item_fulltext`)。weekly-review skill 已适配本仓库工具名,勿混用。

## Agent Skills

深度文献处理 skill 从 dailyinfo 迁入,已适配本仓库 Zotero 工具名:

| Skill | 功能 | Zotero 工具 |
|-------|------|-------------|
| `weekly-review` | 每周文献综述:精读全文→8段分析卡→主题聚类→公众号文章→NotebookLM 播客 | 读库全套 |
| `zotero-notebooklm` | Zotero 论文 → NotebookLM 中文简报/音频/视频 | 读库 |
| `weekly-report-generator` | NotebookLM 输出 → 公众号周报 MD | 无 |
| `figure-skill-v2` | 从 Zotero PDF 提图/配图/封面 | 读附件 |
| `bilibili-upload` | podcast 音频 → MP4 → B 站上传 | 无 |
| `download-pdf` | 论文 PDF 下载(机构访问) | 无 |
| `zotero-query` | 文献库查询 | 读库 |

> `ai-news-weekly-polish` 留在 dailyinfo(它是 dailyinfo pipeline 产物)。`paper-to-zotero`/`run-paper-to-zotero` 属入库端,保留在本仓库作采集入口。

## 分析卡 Schema (cards/)

精读产物统一为 **8 段分析卡**,存 `outputs/weekly-review/{YYYY-MM-DD}/cards/{slug}.md`。模板:

```markdown
# {论文标题}
- **作者**: {creators}
- **年份**: {year}
- **期刊**: {venue}
- **DOI**: {doi}
- **Zotero Key**: `{key}`

## 研究问题  ## 核心方法  ## 实验设计  ## 关键发现
## 局限性  ## 与领域的关系  ## 精读理由  ## 标签
```

**跨周积累规则**:
- 卡片 → `outputs/weekly-review/{date}/cards/`
- 主题分类 → 与 `papers/` 的 10 个主题目录对照(flood-inundation、streamflow-prediction 等)
- 每次精读的 `dateAdded` 范围记录在 `文献总览.md`
- 卡片必须带 Zotero Key,以便与 Zotero 库和知识图谱(graphify)关联

## Commands

### Knowledge Graph
- Build knowledge graph: `uv run hydrolitagent graph <papers_dir> [--update]`
- Merge topic graphs: `uv run hydrolitagent merge --graphs-dir <dir> [--output <dir>]`
- Query a graph: `uv run hydrolitagent query <graph.json> --search "<keyword>"`

### Zotero
- Start MCP Server: `uv run python -m hydrolitagent.zotero.server` (port 8002, 12 tools)
- Add paper by DOI: `uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "<DOI>"`
- Paper pipeline: `bash scripts/run_paper_pipeline.sh "<DOI|arXiv|title>"`
- Link GDrive PDF: `uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>`

### Literature CLI (hydrolitagent/literature — 从 dailyinfo 迁入)
用 `uv run python -m` 调用(与全仓库一致,不依赖 console_scripts):
- B 站上传:`uv run python -m hydrolitagent.literature.bilibili_upload <audio> --title "..." --tags "..." [--dry-run]`
- NotebookLM 简报/音频:`uv run python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio`
- 公众号发布:`uv run python -m hydrolitagent.literature.wechat.push <md_file> [--thumb <media_id>]`
- 公众号润色:`uv run python -m hydrolitagent.literature.wechat.polish <md_file>`
- 配图/封面:`uv run python -m hydrolitagent.literature.wechat.figure <md_file>` (需 ZHIPUAI_API_KEY)

### Docs
- Serve docs: `uv run mkdocs serve`
- Build docs: `uv run mkdocs build --strict`

### General
- Run tests: `uv run pytest`
- Install CLI: `uv pip install -e .`

## Project Structure

```
hydrolitagent/       # Knowledge graph toolkit (graphify integration)
├── cli.py           # CLI entry point (argparse subcommands)
├── _config.py       # Shared TOML loader
├── graph/           # Knowledge graph construction + merging
│   ├── build.py     # Single-topic graph build pipeline
│   └── merge.py     # Multi-topic merge + D3.js HTML viz
├── query/           # Graph query interface
└── zotero/          # Zotero integration
    ├── server.py     # 12-tool MCP Server (FastMCP, port 8002)
    ├── paper_to_zotero.py # DOI → Zotero (Crossref/arXiv/S2 metadata)
    └── zot_link_gdrive.py # Google Drive → linked_file attachment

configs/             # Prompt and extraction configuration
scripts/             # run_paper_pipeline.sh, chunk_fulltext.py (weekly-review 辅助)
skills/              # Agent skills (zotero-query, paper-to-zotero, 及迁入的 weekly-review 等 6 个)
outputs/             # 精读产物: outputs/weekly-review/{date}/{cards,article,podcast}
papers/              # 按主题组织的文献库(10 主题, 6173 篇);知识库核心资产
docs/                # Documentation site (mkdocs-material)
tests/               # pytest (test_zotero_server.py, test_paper_to_zotero.py)

equation_from_data/  # Paper reproduction: equation discovery from data
google_floodhub/     # Paper reproduction: Google flood forecasting
definitions.py       # Shared definitions/constants
```

## Setup

```bash
# Copy and configure
cp .env.example .env   # Add your DEEPSEEK_API_KEY, set HYDROLITAGENT_OUTPUT

# Install
uv pip install -e .

# Build a knowledge graph from markdown papers
uv run hydrolitagent graph papers/your-topic/
```
