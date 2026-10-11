# mylibrary — 水文水资源研究知识平台

**围绕文献的一条线** —— 从收到用，一路都在这个仓库里：

| ① 收进来 | ② 读进去 | ③ 组织起来 | ④ 产出内容 | ⑤ 沉淀成资产 |
|---|---|---|---|---|
| 下载 PDF · 建 Zotero 条目 | 检索 · 精读 · 分析卡 | 主题分类 · 知识图谱 | 公众号 · 播客 · B 站 | 证据卡 · 主题池 |

入口是 **Zotero 文献库**；进入 Zotero **之前**的情报采集由上游兄弟仓库 **dailyinfo** 负责。
现在是**单个包 `hydrolitagent`**，共用一份 `.venv` 与 `uv.lock`。

> 详细能力表见 [`README-zh.md`](README-zh.md)；完整文档站在 [`docs/`](docs/index.md)。

## 开工前先配好这些

| 你要做的 | 先得有 |
|---|---|
| **所有**能力 | Git · Python 3.12–3.14 · [uv](https://docs.astral.sh/uv/) · `uv sync --all-packages` |
| 读 / 写 Zotero 库 | Zotero **API key**（放 `.env`） |
| **文献卡与主题卡** | Zotero Desktop **正在运行**且**允许其他应用通信** · 一种**已登录**的模型 CLI · **Poppler** |
| 论文入库 | GDrive 论文目录 + Zotero 的 Linked Attachment Base Directory |

逐条说明与凭据清单见 **[前提与配置](docs/getting-started/installation.md)** —— **配一次就够**。

## 能让 agent 做什么

配好之后，多数事**直接说人话**就行：

| 你对 agent 说 | 会发生什么 | 详情 |
|---|---|---|
| 「把这篇论文**下载并入库**」 | DOI / arXiv / 标题 → 下载 PDF → 建 Zotero 条目 + `linked_file` 附件 | [论文入库流水线](docs/user-guide/paper-pipeline.md) |
| 「去我的库里找找 X 相关的文献」 | 搜 / 读 Zotero 库（含全文、附件与批注） | [MCP Server 工具](docs/user-guide/mcp-tools.md) |
| 「把这批论文精读成分析卡 / 出一期公众号+播客」 | 每周综述：精读全文 → 分析卡 → 主题聚类 → 文章 → 播客 | [文献深度处理](docs/user-guide/literature.md) |
| 「把《某某》这篇做成卡」 | 从你的 Zotero 找到它 → 读 PDF → 出主体卡草稿 → 代码校验 | [文献卡与主题卡](docs/user-guide/cards/index.md) |
| 「这几篇都做一下」 | 同一条链路逐篇跑，一篇失败不拖累其余 | [单篇论文输入](docs/user-guide/cards/paper-input.md) |
| 「看看能聚出哪些主题」 | 由已有的文献卡生成候选主题、必要时定向精读并回填 | [统一主题池](docs/user-guide/cards/unified-theme-pool.md) |
| 「主题池现在什么样」 | 报当前候选与历史版本 | [统一主题池](docs/user-guide/cards/unified-theme-pool.md) |
| 「当前用哪个模型 / 产物放哪」 | 报模型选择与产物落点，不调模型 | [运行维护](docs/user-guide/cards/runtime-maintenance.md) |

> 前三行是**入库与当期内容**线；后四行是**文献卡与主题卡**线（底层是 `uv run hydrolitagent cards …`
> 的 5 条子命令）。无论哪条 —— **你不需要读那些详情页**，只在想自己动手或排错时才去。
>
> 付费墙（SD / Wiley / Nature 等）的下载需要浏览器 + 机构会话，见[论文 PDF 下载](docs/user-guide/download-pdf.md)。

## 三条线

| 线 | 做什么 | 代码 / 数据 | 入口 |
|---|---|---|---|
| **工具链** | 入库与消费：DOI/arXiv/标题 → PDF → Zotero 条目；读库、精读、知识图谱、公众号/播客/B 站 | `hydrolitagent/`、`scripts/`、`skills/`（12 个技能） | [文档](docs/user-guide/mcp-tools.md) |
| **文献卡与主题卡平台** | 从自己 Zotero 的一篇论文 → 主体卡草稿 → 代码校验 → 若干文献卡 → 候选主题。确定性校验，**运行时 Windows-only** | `hydrolitagent/cards/`、`skills/literature-cards/` | [平台文档](docs/user-guide/cards/index.md) |
| **科研工作流** | 人读证据卡与主题综合：来源 → 证据卡 → 初步主题 → **人工筛选门** → 既定主题 → Claim 准入 → 万字综合。纯标准库脚本，人工决策不可绕过 | `skills/hydrology-evidence-cards/`、`skills/hydrology-theme-synthesis/`、`docs/research-workflow/`（中文规范） | [平台总览](docs/research-workflow/index.md) |

**两条线解决的问题不同**，不要混用：文献卡与主题卡平台追求「给定一篇论文稳定产出可校验的主体卡与候选主题」，科研工作流追求「每一条科学表述都回链可核对的原文，且正式主题必须由人签字」。前者自动化强、不做科研裁决；后者有完整人工决策门，但没有调度器。

## Zotero 有四种读法，用途不同

这是最容易搞混的地方。它们读的是**同一台 Zotero Desktop 的本地 HTTP 服务**（`127.0.0.1:23119`），但库、前缀与用途不同：

| 读法 | 位置 | 目标 | 用途 |
|---|---|---|---|
| MCP Server（12 工具，端口 8002） | `hydrolitagent/zotero/server.py` | 元数据走 Web API，全文/附件走本地 API | 容器内或跨机调用 |
| 裸机脚本直连 | `hydrolitagent/literature/` | 本地 API `…/api/users/0/` | 裸 host 上的入库与简报 |
| 共享群组客户端 | `hydrolitagent/cards/zotero.py` | 共享群组（`/api/groups/<id>/`） | 文献卡平台的 Zotero 读取与 PDF 门禁 |
| 只读阅读器 | `skills/hydrology-evidence-cards/scripts/zotero_reader.py` | 个人库 `…/api/users/0/` | 证据卡取材，只读、不改库、不读 SQLite |

**分工而非二选一**：容器里走 8002 的 MCP，裸 host 直连 `23119`。本地 API 基址的环境变量首选名是 `ZOTERO_LOCAL_BASE_URL`（`ZOTERO_API_URL` 是旧名）。

## 科研产物路径与当前边界

合并后的配置同时保留了两组产物路径：

- 单篇流程写入 `--output-root`（默认仓库 `outputs/`），主题池写入 `paths.themes_dir`。
- `paths.artifact_root` 及其下的 `证据卡/`、`主题/`、`运行记录/`、`文献链接/` 已能解析和校验，可指向仓库根或显式允许的外部共享位置，但自动化发布尚未接入这四个目录。

所有实际科研产物、原始 PDF、Zotero 数据库、`.runtime` 和本机路径均不进入 Git。目标是在两组目录之间建立明确的准入与发布边界，再将 `artifact_root` 作为 Obsidian 阅读层；不应把当前的配置字段理解为两套工作流已经打通。

字段、现状和目标设计见[总配置字段说明](docs/development/platform/config.md)、[自动化边界](docs/development/platform/automation.md)和[项目级设计](docs/development/platform/project-design.md)。

## 快速开始

```bash
git clone --branch literature-platform https://github.com/iHeadWater/mylibrary.git mylibrary
cd mylibrary
uv sync --all-packages --locked
cp .env.example .env      # 按需填 ZOTERO_API_KEY / ZOTERO_LIBRARY_ID / GDRIVE_PAPERS_PATH
```

上面只装了**通用部分**；每条能力额外要什么、凭据放哪，见[前提与配置](docs/getting-started/installation.md)。

不用自己的论文也能先跑通入口（合成示例，**不调用模型**）：

```bash
uv run python scripts/paper_validate.py --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
```

返回 `status: PASS`、退出码 `0` 即入口可用。**不要把文档里的预期结果当成实际输出。**

### 文献卡与主题卡（Windows）

配好之后跟 agent 说「把《某某》这篇做成卡」即可。自己敲是这 5 条：

```bash
uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --json
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider codex --json
uv run hydrolitagent cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json
uv run hydrolitagent cards themes-run --json
uv run hydrolitagent cards ai-config --json          # 看模型选择与产物落点
```

用 **CC Switch 接入 DeepSeek** 时**仍选 `--ai-provider claude`** —— 选的是**命令行适配器**，不是模型厂家。
详见[文献卡与主题卡](docs/user-guide/cards/index.md)（**你通常不需要读它**）。

单篇本地流程**不需要**先填工具链的 Zotero Web API 密钥，也**不需要**启动 MCP Server。

### 其他工具链与批量自动化

```bash
git clone git@github.com:iHeadWater/mylibrary.git
cd mylibrary
uv sync --all-packages   # 装依赖（workspace 成员已并入 hydrolitagent/cards）
cp .env.example .env     # 填入 DEEPSEEK_API_KEY、ZOTERO_API_KEY、ZOTERO_LIBRARY_ID 等
```

> 本仓库只有**一个包** —— `uv sync` 与 `uv sync --all-packages` 等价。

```bash
# 工具链：启动 12 个工具的 MCP Server（端口 8002）
uv run python -m hydrolitagent.zotero.server

# 工具链：下载论文并入库 —— DOI / arXiv ID / 标题 → 下载 PDF → Zotero 条目 + linked_file 附件
uv run python scripts/download_paper.py --setup-check                                  # 新机器先自检一次
uv run python scripts/download_paper.py --doi "10.1016/j.jhydrol.2023.130249" --sync
uv run python scripts/download_paper.py --arxiv 2501.08086 --sync

# 容器（myopenclaw hermes）里用打包好的流水线；逐条细节见 docs/user-guide/paper-pipeline.md
bash scripts/run_paper_pipeline.sh "10.1016/j.jhydrol.2023.130249"

# 文献卡平台：只读自查模型与产物根（Windows）
uv run hydrolitagent cards ai-config --json

# 科研工作流：先自测，再制卡
python skills/hydrology-evidence-cards/tests/self_test.py
python skills/hydrology-theme-synthesis/tests/self_test.py
```

## 目录地图

| 位置 | 存什么 |
|---|---|
| `hydrolitagent/` | Python 包：Zotero MCP Server、下载/入库、文献处理、知识图谱 |
| `hydrolitagent/cards/` | 自动化平台：代码 `*.py` 与只读资产 `assets/`（模板 / 提示词 / schema / 示例 / 默认配置），运行产物落仓库根 |
| `skills/` | 12 个技能：9 个工具链技能 + `literature-cards` + 两个水利科研技能 |
| `docs/` | 文档站源码（mkdocs）：英文技术文档 + 平台文档（`user-guide/cards/`、`development/platform/`）与科研规范（`research-workflow/`） |
| `scripts/`、`configs/`、`docker/` | 入库脚本、图谱提示词、MCP Server 镜像 |
| `tests/` | pytest 测试（原平台测试已并入这一套） |
| `证据卡/`、`主题/`、`运行记录/`、`文献链接/` | 科研产物（**路径可配**，默认在此，不入 Git） |
| `_legacy/`、`equation_from_data/`、`google_floodhub/` | 历史代码与论文复现 |
| `docs/research-workflow/index.md` | 科研工作流层的完整说明（原王新宇线 README） |

## 文档与测试

```bash
uv run mkdocs serve     # 本地预览文档站
uv run pytest           # 一套测试：tests/（原平台测试已并入）
```

`tests/test_zotero_local_api_integration.py` 是依赖本机 Zotero 在线及特定文献样本的集成测试，不是所有新用户都能复现同一结果。本次环境有一项因指定样本只有一篇 PDF、测试要求至少两篇而失败。只验证平台代码可运行 `uv run pytest`；完整测试出现失败时应看具体原因，不把排除测试后的结果称为完整全绿。
