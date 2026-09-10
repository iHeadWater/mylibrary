# Hydro AI Papers (mylibrary)

[English](README.md)

AI 驱动的水文水资源研究 —— 文献流水线的**深度处理层**:精读、主题分类、公众号文章、播客、知识图谱,以 **Zotero 文献库**为根基。

## 定位

mylibrary 承担**情报汇集之后的深度处理**:

- **Zotero 库是文献库的起点** —— 深度处理典型地以 Zotero 库为文献来源(通过 MCP server 读库)。
- **Zotero 论文入库也是本仓库能力** —— DOI / arXiv / 标题 → PDF → Zotero 条目的流水线(`run_paper_pipeline.sh`)就在本仓库。
- 上游的兄弟仓库(dailyinfo)负责**进入 Zotero 之前的情报采集**(资讯流、原始下载);本仓库不读它的输出文件。

产物沉淀为**文献知识库**:`papers/` 按主题组织(10 个主题,6000+ 篇),以及 `outputs/` 下的精读分析卡、公众号文章、播客。

## 能力

| 能力 | 命令 | 文档 |
|---|---|---|
| **Zotero 文献查询** — 12 个工具的 MCP Server(streamable HTTP,端口 8002,端点 `/mcp`):搜索、浏览、读取全文/附件/批注 | `uv run python -m hydrolitagent.zotero.server` | [MCP 工具](docs/user-guide/mcp-tools.md) |
| **论文入库** — DOI / arXiv ID / 标题 → PDF → Zotero 条目 + `linked_file` 附件 | `bash scripts/run_paper_pipeline.sh "<DOI|arXiv|title>"` | [入库流水线](docs/user-guide/paper-pipeline.md) |
| **论文 PDF 下载** — 机构访问(大连理工 SSO)通过 Claude Code + Playwright 下载 | `uv run python -m hydrolitagent.literature.download_pdf doi <doi>` | [PDF 下载](docs/user-guide/download-pdf.md) |
| **Zotero 入库 linked_file** — 已下载 PDF 同步进 Zotero 作为 `linked_file`(零云端配额) | `uv run python -m hydrolitagent.literature.zotero_sync <pdf> <doi>` | [Zotero 入库](docs/user-guide/zotero-sync.md) |
| **Zotero → NotebookLM** — 新增论文整理成中文简报 / 音频 / 视频概览 | `uv run python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio` | [NotebookLM](docs/user-guide/zotero-notebooklm.md) |
| **文献深度处理** — Literature CLI:每周综述、公众号发布/润色/配图、B 站上传 | `uv run python -m hydrolitagent.literature.wechat.push <md>` | [文献深度处理](docs/user-guide/literature.md) |
| **知识图谱** — 用 [graphify](https://github.com/graphify) 构建结构化、可查询的知识库(实体提取、社区发现、Obsidian 导出) | `uv run hydrolitagent graph papers/your-topic/` | [模块架构](docs/development/architecture.md) |
| **论文复现** — 复现 AI 驱动水文学关键论文 | — | `equation_from_data/`、`google_floodhub/` |
| **科研知识平台** — **消费侧的长期资产支线**:检测共享 Zotero 库新增论文 → 全文门禁 → 逐篇证据包 → 持续演化的主题池 → 日报。无人值守、确定性、不需手工编辑。**运行时为 Windows-only。** | `uv run hydro-platform run-once --json` | [平台文档](docs/hydro-platform/index.md) |

## 快速开始

```bash
# 克隆并安装
git clone git@github.com:OuyangWenyu/mylibrary.git
cd mylibrary
uv sync --all-packages   # 把 uv workspace 的**两个**包都装进共享的根 .venv

# 配置
cp .env.example .env   # 填入 DEEPSEEK_API_KEY;设置 HYDROLITAGENT_OUTPUT、ZOTERO_API_KEY、ZOTERO_LIBRARY_ID
```

> 本仓库是**uv workspace**,含两个成员:`hydrolitagent`(根)与 `hydro-platform`。二者共享同一个 `.venv` 和同一个 `uv.lock`。请用 `uv sync --all-packages` —— 裸 `uv sync` 只装根包的依赖,`uv run hydro-platform …` 会不可用。

完整参考(Zotero Desktop / Linked Attachment Base Directory 配置、环境变量、TOML 配置)见[安装配置](docs/getting-started/installation.md)。

## 常用命令

### Zotero 工具

```bash
# 启动 12 个工具的 MCP Server(端口 8002)
uv run python -m hydrolitagent.zotero.server

# 通过 DOI 添加论文到 Zotero(仅元数据)
uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "10.1038/s41586-024-07145-1"

# 一键流水线:下载 PDF + 建 Zotero 条目 + linked_file 附件
bash scripts/run_paper_pipeline.sh "10.1038/s41586-024-07145-1"

# 把已有的 GDrive PDF 链接为 Zotero linked_file
uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>
```

### Literature CLI(入库后深度处理)

```bash
# 一条命令完成下载 + Zotero 同步(隐身 Chrome;自动按出版商路由)
uv run python scripts/download_paper.py --doi <doi> --sync
uv run python scripts/download_paper.py --arxiv <id> --sync

# 机构访问下载 PDF
uv run python -m hydrolitagent.literature.download_pdf doi <doi>

# 把已下载 PDF 同步进 Zotero 作为 linked_file
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --json

# Zotero → NotebookLM 简报 / 音频 / 视频(需 [notebooklm] extra)
uv run --extra notebooklm python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio

# 公众号工作流
uv run python -m hydrolitagent.literature.wechat.polish <draft.md>
uv run python -m hydrolitagent.literature.wechat.figure <article.md>
uv run python -m hydrolitagent.literature.wechat.push <polished.md> [--thumb <media_id>]

# 上传播客音频到 B 站
uv run python -m hydrolitagent.literature.bilibili_upload <audio.mp3> --title "标题" --tags "AI,水文,科研" [--dry-run]
```

### 知识图谱

```bash
# 对目录下的 Markdown 论文执行三步 pipeline
uv run hydrolitagent prepare papers/your-topic/    # 第一步:检测 + 分批
uv run hydrolitagent extract papers/your-topic/     # 第二步:LLM 提取
uv run hydrolitagent graph papers/your-topic/       # 第三步:建图 + 聚类 + 导出

# 合并多个 topic 图谱为统一图谱
uv run hydrolitagent merge --graphs-dir outputs/graph/ --output outputs/graph/unified/

# 查询图谱(确定性查询,不走 LLM)
uv run hydrolitagent query outputs/graph/graph.json --search "LSTM"
```

每次建图会把 `graph.json`、`graph.html`(D3.js)、`GRAPH_REPORT.md`、`obsidian/`(带 `[[wikilinks]]` 的 Obsidian 知识库)写入 `HYDROLITAGENT_OUTPUT` 或 `--output`。

### 科研知识平台(`hydro-platform`)

**入库只有两件事 —— 下载 PDF,和建 Zotero 条目。** 本仓库其余的都属于**消费**:读库、精读、主题、知识图谱、公众号、播客。这个平台是消费侧里的一支独立支线 —— 别人产出当期内容,它产出**长期可追溯的知识资产**:把**共享 Zotero 库**里已有的论文沉淀成**证据包**与持续演化的**主题池**。命令一律从仓库根执行。

> 注意"两侧"不等于"两个包":`hydrolitagent` **横跨两侧**(它既有入库的命令,也含消费侧的大部分),而 `hydro-platform` 纯属消费。

```bash
# 跑完一整轮:检测 → 门禁 → 制卡 → 主题 → 账本 → 日报
uv run hydro-platform run-once --json

# 只预览已有本地任务 —— 不扫 Zotero、不调模型
uv run hydro-platform run-once --dry-run --json

# 只跑主题部分;--dry-run 只读预览,不调模型
uv run hydro-platform themes-run --json
uv run hydro-platform themes-run --dry-run --json

# 集中检查(配置、依赖、登录、Zotero)—— 不调模型
uv run hydro-platform doctor --json
```

- **平台不下载 PDF** —— 只读取共享库中已经附好的文件。下载与入库属于 `paper-to-zotero` / `download-pdf`。
- **运行时为 Windows-only**:定时调度、Poppler 原生工具安装、PDF 沙箱探针都依赖 Windows。编排逻辑本身与操作系统无关,但只在 Windows 上验证过。
- 生成的产物(证据包、主题池、日报、贡献账本)**不入库** —— 运行时写入,另行共享。仓库里只有代码、模板、提示词与 schema。
- 完整命令清单:`uv run hydro-platform --help`(29 个子命令)。

## Agent Skills

| Skill | 功能 |
|---|---|
| `zotero-query` | 通过 MCP 工具查询 Zotero 文献库 |
| `paper-to-zotero` | 下载论文并入库 Zotero(DOI / arXiv / 标题) |
| `run-paper-to-zotero` | 一键 paper-fetch → GDrive → Zotero linked_file 流水线 |
| `download-pdf` | Playwright 机构访问下载 PDF(另含 `scripts/download_paper.py` 隐身一键模式) |
| `zotero-notebooklm` | Zotero 论文 → NotebookLM 中文简报 / 音频 / 视频 |
| `weekly-review` | 每周文献综述:精读 → 分析卡 → 公众号文章 → NotebookLM 播客 |
| `weekly-report-skill` | NotebookLM 输出 → 公众号周报 MD |
| `figure-skill-v2` | 每篇论文配图 + 整期封面(优先 PDF 提取,否则智谱 CogView 生成) |
| `bilibili-upload` | 播客音频 → MP4 → B 站上传 |
| `hydro-platform` | 科研知识平台 CLI 的入口(共享 Zotero 库 → 证据包 → 主题池)。运行时为 Windows-only。 |

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
scripts/                 # run_paper_pipeline.sh, download_paper.py(隐身一键 PDF 下载), chunk_fulltext.py
skills/                  # 10 个 Agent skill
docs/                    # 文档站点(mkdocs-material)
outputs/                 # 精读产物:outputs/weekly-review/{date}/{cards,article,podcast}
papers/                  # 按主题组织的文献库(10 个主题)

hydro-platform/          # 科研知识平台(uv workspace 成员)
├── automation/          #   Python:检测 → PDF 门禁 → 任务状态机 → 制卡 → 主题池
├── templates/           #   可复用资产:八类证据卡模板、主题提示词、JSON schema
├── config/              #   非敏感配置与完整示例
└── pyproject.toml       #   入口:`uv run hydro-platform`
                         #   生成产物(evidence-packs/、themes/、reports/、
                         #   activity/、members/)不入库,由运行时自建。

equation_from_data/      # 论文复现:从数据发现方程
google_floodhub/         # 论文复现:Google 洪水预测
definitions.py           # 共享常量
```

## 文档

文档站点基于 [mkdocs-material](https://squidfunk.github.io/mkdocs-material/),源码在 [`docs/`](docs/):

```bash
uv run mkdocs serve    # http://127.0.0.1:8000
uv run mkdocs build --strict
```

平台文档在 [`docs/hydro-platform/`](docs/hydro-platform/index.md) —— 从那里入门,完整交接看[平台操作说明](docs/hydro-platform/platform-operations-guide.md)。保留两套独立 Zotero 客户端的决定记录在 [ADR-0002](docs/adr/0002-zotero-two-clients-boundary.md)。

## 贡献

欢迎贡献:

1. Fork 并创建新分支
2. 将论文、代码或文档添加到相应位置
3. 确保有分享权限且兼容 [MIT License](LICENSE)
4. 提交 PR 并附上清晰说明

## 许可证

MIT License。详见 [LICENSE](LICENSE)。
