# Hydro AI Papers (mylibrary)

[仓库顶层说明](README.md) · [在线文档](https://iheadwater.github.io/mylibrary/)

AI 驱动的水文水资源研究 —— 文献流水线的**深度处理层**:精读、主题分类、公众号文章、播客,以 **Zotero 文献库**为根基。

## 定位

mylibrary 承担**情报汇集之后的深度处理**:

- **Zotero 库是文献库的起点** —— 深度处理典型地以 Zotero 库为文献来源(通过 MCP server 读库)。
- **Zotero 论文入库也是本仓库能力** —— DOI / arXiv / 标题 → PDF → Zotero 条目的流水线(`run_paper_pipeline.sh`)就在本仓库。
- 上游的兄弟仓库(dailyinfo)负责**进入 Zotero 之前的情报采集**(资讯流、原始下载);本仓库不读它的输出文件。

产物沉淀为**文献知识库**:`papers/` 按主题组织(10 个主题,约 4000 篇),以及 `outputs/` 下的精读分析卡、公众号文章、播客。

## 能力

| 能力 | 命令 | 文档 |
|---|---|---|
| **Zotero 文献查询** — 12 个工具的 MCP Server(streamable HTTP,端口 8002,端点 `/mcp`):搜索、浏览、读取全文/附件/批注 | `uv run python -m hydrolitagent.zotero.server` | [MCP 工具](docs/user-guide/mcp-tools.md) |
| **论文入库** — DOI / arXiv ID / 标题 → PDF → Zotero 条目 + `linked_file` 附件 | `bash scripts/run_paper_pipeline.sh "<DOI|arXiv|title>"` | [入库流水线](docs/user-guide/paper-pipeline.md) |
| **论文 PDF 下载** — 机构访问:独立 CLI,用 Playwright 驱动本机 Chrome(不依赖 Claude Code) | `uv run python scripts/download_paper.py --doi <doi> [--sync]` | [PDF 下载](docs/user-guide/download-pdf.md) |
| **Zotero 入库 linked_file** — 已下载 PDF 同步进 Zotero 作为 `linked_file`(零云端配额) | `uv run python -m hydrolitagent.literature.zotero_sync <pdf> <doi>` | [Zotero 入库](docs/user-guide/zotero-sync.md) |
| **Zotero → NotebookLM** — 新增论文整理成中文简报 / 音频 / 视频概览 | `uv run python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio` | [NotebookLM](docs/user-guide/zotero-notebooklm.md) |
| **文献深度处理** — Literature CLI:每周综述、公众号发布/润色/配图、B 站上传 | `uv run python -m hydrolitagent.literature.wechat.push <md>` | [文献深度处理](docs/user-guide/literature.md) |
| **论文复现** — 复现 AI 驱动水文学关键论文 | — | `equation_from_data/`、`google_floodhub/` |
| **文献卡与主题卡平台** — 从自己 Zotero 的一篇论文 → 主体卡草稿 → 代码校验 → 若干文献卡 → 候选主题。确定性校验。**运行时为 Windows-only。** | `uv run hydrolitagent cards ai-config --json` | [平台文档](docs/user-guide/cards/index.md) |

## 快速开始

**单篇制卡用户：** 请先看[仓库首页](README.md)的「开工前先配好这些」和[前提与配置](docs/getting-started/installation.md)；能力清单见[文献卡与主题卡](docs/user-guide/cards/index.md)。支持自己的个人/群组 Zotero 文库、Codex/Claude CLI 和可配置输出目录；不需要作者的本机路径、账号或 `.venv`。以下配置主要服务其他工具链，不是单篇制卡必须照抄的前置条件。

```bash
# 克隆并安装
git clone git@github.com:iHeadWater/mylibrary.git
cd mylibrary
uv sync --all-packages   # 装依赖(原 workspace 成员已并入 hydrolitagent/cards)

# 配置
cp .env.example .env   # 按需填 DEEPSEEK_API_KEY、ZOTERO_API_KEY、ZOTERO_LIBRARY_ID 等
```

> 本仓库只有一个包 **`hydrolitagent`** —— 文献卡与主题卡能力在它的 `hydrolitagent/cards/` 子包(workspace 成员随之取消)。`.venv` 与 `uv.lock` 仍只有一份;`uv sync --all-packages` 照旧可用。

完整参考(Zotero Desktop / Linked Attachment Base Directory 配置、环境变量、TOML 配置)见[前提与配置](docs/getting-started/installation.md)。

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
uv run python scripts/download_paper.py --title "<标题>" --sync     # 只有标题：自动检索解析 DOI

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

### 文献卡与主题卡平台

**入库只有两件事 —— 下载 PDF,和建 Zotero 条目。** 本仓库其余的都属于**消费**:读库、精读、主题、公众号、播客。这个平台是消费侧里的一支独立支线 —— 别人产出当期内容,它把**你自己的 Zotero 文献**沉淀成**长期可追溯的文献卡与主题卡**。命令一律从仓库根执行。

> 注意“两侧”不等于“两个包”：本仓库**只有一个包** `hydrolitagent`；文献卡与主题卡是它内部的 `hydrolitagent/cards/`，纯属消费侧。

```bash
# 单篇输入:从自己的一篇论文得到 READY 记录
uv run python scripts/paper_input.py --user-library --item-key ABCD1234 --output paper-input.json

# 生成主体卡草稿(调用所选模型)
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider codex --json

# 离线校验主体卡(不调模型)
uv run hydrolitagent cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json

# 由若干文献卡生成候选主题;--dry-run 只读预览
uv run hydrolitagent cards themes-run --json
uv run hydrolitagent cards themes-run --dry-run --json

# 只读自查模型与产物根
uv run hydrolitagent cards ai-config --json
```

- **平台不下载 PDF** —— 只读取自己 Zotero 中已经附好的文件。下载与入库属于 `paper-to-zotero` / `download-pdf`。
- **运行时为 Windows-only**:本地 CLI 的安装、登录与 PDF 工具准备只在 Windows 上验证过。
- 生成的产物(文献卡、主题池、运行记录)**不入库** —— 运行时写入,另行共享。仓库里只有代码、模板、提示词与 schema。
- 完整命令清单:`uv run hydrolitagent cards --help`(5 个子命令)。

### 学者论文统计

按人查论文，生成学院「学术论文自查情况统计」表所需的数据。**不是解析学院下发的表**，而是从一个人出发去 OpenAlex 查他的论文。

```bash
# 确认身份（同名时只列候选）
uv run hydrolitagent scholars resolve --name "张三" --name-en "Zhang San" --json

# 单人 / 批量
uv run hydrolitagent scholars stats --name "张三" --name-en "Zhang San" --institute "水利所" --output-dir outputs/scholars/2026-10-26 --json
uv run hydrolitagent scholars batch --roster configs/scholars_roster.example.csv --output-dir outputs/scholars/2026-10-26 --json
```

- 口径：2021 年起；期刊 + 会议；第一作者**或**通讯作者任一计入。
- 同名/中文名无别名时**不猜**，汇总数字留空并进复核清单。
- 自查问题列默认「待本人确认」；程序只自动检测撤稿。
- 中文文献可 `--web-search firecrawl` 出候选，人工确认后用 `--supplement` 计入。

详见[学者论文统计](docs/user-guide/scholars/index.md)。

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
| `literature-cards` | 文献卡与主题卡平台 CLI 的入口(自己的 Zotero 文献 → 文献卡 → 主题卡)。运行时为 Windows-only。 |
| `hydrology-evidence-cards` | Zotero 源论文 → 人读证据卡(科研工作流,含机器审计字段) |
| `hydrology-theme-synthesis` | 文献 → 初步主题 → 人工筛选门 → 正式主题(科研工作流) |

## 项目结构（用户入口节选）

完整目录与模块职责见[模块架构](docs/development/architecture.md)。以下只列用户需要的入口。

```
hydrolitagent/
├── cli.py               # CLI 分发:文献卡、主题卡与产物路径查询
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
└── cards/               # 文献卡与主题卡
    ├── cli.py           # 单篇输入、生成、校验、主题池与配置查询
    └── assets/          # 模板、提示词、schema、示例与默认配置

configs/                 # Prompt / 提取配置
scripts/                 # run_paper_pipeline.sh, download_paper.py(隐身一键 PDF 下载), chunk_fulltext.py
skills/                  # 12 个 Agent skill
docs/                    # 文档站点(mkdocs-material)
outputs/                 # 精读产物(默认落点,可配置):weekly-review/{date}/{cards,article,podcast}
papers/                  # 按主题组织的文献库(10 个主题)

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

平台文档在 [`docs/user-guide/cards/`](docs/user-guide/cards/index.md) —— 从那里入门,完整交接也从这份[平台文档导航](docs/user-guide/cards/index.md)开始。保留两套独立 Zotero 客户端的决定记录在 [ADR-0002](docs/adr/0002-zotero-two-clients-boundary.md)。

## 贡献

欢迎贡献:

1. Fork 并创建新分支
2. 将论文、代码或文档添加到相应位置
3. 确保有分享权限、且知道贡献会以 [AGPL-3.0](LICENSE) 授权
4. 提交 PR 并附上清晰说明

## 许可证

**GNU Affero General Public License v3.0**（AGPL-3.0）。© 2025 mylibrary contributors。完整正文见 [LICENSE](LICENSE)。

> **这个协议管什么**：你可以自由使用、修改、分发 —— **包括商用**；但只要你**分发**本软件、
> 或把**修改过的版本作为网络服务提供**给别人用，就必须**同样以 AGPL-3.0 提供完整源码**
> （含你的修改）。换言之：**不能拿它做闭源产品或闭源 SaaS。**
> 这是 [Zotero](https://www.zotero.org/) 本身采用的协议。
