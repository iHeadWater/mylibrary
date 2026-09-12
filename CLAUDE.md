# Hydro AI Papers (mylibrary)

Literature knowledge base for AI-driven hydrology and water resources research.

## 定位 (Role)

mylibrary 承担**情报汇集之后的深度处理**:读 Zotero → 论文入库 → 精读分析卡 → 主题分类 → 公众号文章/播客 → 知识库积累。**Zotero 库是文献库的起点**,深度处理典型地以 Zotero 库为文献来源(通过 Zotero MCP 读库);**Zotero 论文入库也是本仓库能力**(`run_paper_pipeline.sh`/`paper_to_zotero.py`)。上游 dailyinfo 负责进入 Zotero 之前的情报采集(资讯流、原始下载)。

**Zotero 是文献库的事实层。** 深度处理的输入来自 Zotero MCP(读库);本仓库不维护自己的 Zotero 镜像,不读 dailyinfo 的输出文件。

## Zotero 接入方式 (IMPORTANT)

本仓库的 Zotero MCP server(`hydrolitagent/zotero/server.py`,streamable HTTP 端口 8002,端点路径 `/mcp`)是唯一的 Zotero 访问入口。**不要改动它的技术架构**——已有其他服务依赖。

> ⚠️ **上句的作用域是容器部署,不是全部场景。** 读取 Zotero 按运行环境分工:**裸 host**(本机、制卡机)走直连——元数据用 pyzotero、全文用 Zotero Desktop Local API `127.0.0.1:23119`;**容器**里才走这个 8002 MCP 服务(它的 Local API 默认 `host.docker.internal:23119`,正是为访问宿主 Zotero 而设)。`hydro-platform` 跑在裸 host,所以走直连,与此处并不冲突。详见 [ADR-0002](docs/adr/0002-zotero-two-clients-boundary.md)。

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
| `hydro-platform` | 科研知识平台 CLI 入口:共享 Zotero 库 → 证据包 → 主题池。**运行时 Windows-only**,详见该 skill | 直连 Local API |

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
- **下载+入库 canonical（裸 host / 本仓库直跑）**:`uv run python scripts/download_paper.py --arxiv <id> --sync` / `--doi <doi> --sync`;新机器先 `uv run python scripts/download_paper.py --setup-check`
  - 建条目统一由 `paper_to_zotero.build_item()` 生成（arXiv → preprint + 摘要 + `archiveID`）;同 DOI 重跑幂等跳过
  - arXiv 与 OA DOI 走 curl 无需 playwright;付费墙（SD/Wiley/Nature）需浏览器 + 机构会话
- **下载+入库 canonical（myopenclaw hermes 容器 / 爱码士）**:`docker compose exec hermes-coder /opt/hermes/scripts/run-paper-pipeline.sh "<DOI|arXiv|title>"`（该脚本在 build 时从本仓库 `scripts/` 拷入镜像;详见 `skills/paper-to-zotero` 双模式说明）
- Add paper by DOI (仅元数据):`uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "<DOI>"`
- Paper pipeline (旧,需 paper-fetch):`bash scripts/run_paper_pipeline.sh "<DOI|arXiv|title>"`
- Link GDrive PDF: `uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>`

> 凭据:裸 host 用 `.env` 的 `ZOTERO_API_KEY/ZOTERO_LIBRARY_ID/GDRIVE_PAPERS_PATH`(`paper_to_zotero` 在无 TOML 时回退读它);容器/旧环境用 `~/.config/zot/config.toml`(或 `ZOTERO_CONFIG_PATH`)。`skills/paper-to-zotero` 的「双模式」节与 `scripts/download_paper.py --setup-check` 会解释所需一次性设置。

### Literature CLI (hydrolitagent/literature — 从 dailyinfo 迁入)
用 `uv run python -m` 调用(与全仓库一致,不依赖 console_scripts):
- B 站上传:`uv run python -m hydrolitagent.literature.bilibili_upload <audio> --title "..." --tags "..." [--dry-run]`
- NotebookLM 简报/音频:`uv run python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio`
- 公众号发布:`uv run python -m hydrolitagent.literature.wechat.push <md_file> [--thumb <media_id>]`
- 公众号润色:`uv run python -m hydrolitagent.literature.wechat.polish <md_file>`
- 配图/封面:`uv run python -m hydrolitagent.literature.wechat.figure <md_file>` (需 ZHIPUAI_API_KEY)

### 科研知识平台 (hydro-platform)

**消费侧的长期资产支线**(入库只有两件事:下载 PDF + 建 Zotero 条目;其余都算消费):把共享 Zotero 库里已有的论文沉淀成证据包与主题池,产出的是长期可追溯的知识资产而非当期内容。不是交互式问答。运行时 **Windows-only**。命令一律从**仓库根**执行:

- 跑完一整轮(检测 → 门禁 → 制卡 → 主题 → 账本 → 日报):`uv run hydro-platform run-once --json`
- 只预览本地任务,不扫 Zotero、不调模型:`uv run hydro-platform run-once --dry-run --json`
- 只跑主题:`uv run hydro-platform themes-run --json`(`--dry-run` 只读预览)
- 健康检查:`uv run hydro-platform doctor --json`
- 全部 29 个子命令:`uv run hydro-platform --help`

不要直接读写平台的状态文件(`.runtime/tasks.json`、`themes/_registry.json`),也不要手工编辑证据包/主题文件——平台原子写入并校验哈希,手改会被判为漂移。完整说明在 `docs/hydro-platform/`。

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
├── _config.py       # Shared TOML loader + 精读产物根解析(resolve_literature_root)
├── graph/           # Knowledge graph construction + merging
│   ├── build.py     # Single-topic graph build pipeline
│   └── merge.py     # Multi-topic merge + D3.js HTML viz
├── query/           # Graph query interface
└── zotero/          # Zotero integration
    ├── server.py     # 12-tool MCP Server (FastMCP, port 8002)
    ├── paper_to_zotero.py # DOI → Zotero (Crossref/arXiv/S2 metadata)
    └── zot_link_gdrive.py # Google Drive → linked_file attachment

configs/             # 配置:graph_prompts.toml · paths.toml(精读产物根的默认值)
scripts/             # run_paper_pipeline.sh, chunk_fulltext.py (weekly-review 辅助)
skills/              # Agent skills (zotero-query, paper-to-zotero, 及迁入的 weekly-review 等 6 个)
outputs/             # 精读产物(默认落点,可配置):weekly-review/{date}/{cards,article,podcast}
papers/              # 按主题组织的文献库(10 主题, 6173 篇);知识库核心资产
docs/                # Documentation site (mkdocs-material)
hydro-platform/      # 科研知识平台(uv workspace 成员;消费侧:Zotero → 证据包 → 主题池)
                     #   automation/ 代码 · templates/ 规范资产 · config/ 配置
                     #   生成产物(evidence-packs/ themes/ reports/ activity/ members/)
                     #   不入库,由运行时自建
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
