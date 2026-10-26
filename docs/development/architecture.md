# 模块架构

本页讲**代码怎么组织**：包与目录、模块职责、数据流。它覆盖「收进来 → 读进去 → 组织起来 →
产出内容 → 沉淀成资产」整条线 —— 那条线的**使用者视图**见[用户指南总览](../user-guide/index.md)。
本节先给整体结构，随后展开 `hydrolitagent` 的模块。

> **开发边界**：`graph/` 与 `query/` 保留为尚未完成的知识图谱技术负债；
> 与文献卡、主题卡的关系尚未厘清。下文涉及它们的是代码结构记录，
> 不代表当前对用户承诺的可用能力，也不作为用户上手步骤。

## 整体结构（节选）

```text
hydrolitagent/
├── zotero/                  # Zotero 集成（MCP Server + 入库）
│   ├── __init__.py
│   ├── server.py            # MCP Server（12 个工具,端口 8002）
│   ├── paper_to_zotero.py   # DOI → Zotero 条目
│   └── zot_link_gdrive.py   # Google Drive → linked_file 附件
├── literature/              # 文献深度处理（从 dailyinfo 迁入）
│   ├── _paths.py            # 路径助手
│   ├── bilibili_upload.py   # B 站发布
│   ├── zotero_notebooklm.py # Zotero → NotebookLM
│   └── wechat/              # 公众号（figure/polish/push）
├── graph/                   # graphify 知识图谱
├── query/                   # 图查询
└── scholars/                # 按人/机构统计论文产出、位次与研究方向

hydrolitagent/cards/         # 文献卡与主题卡（⑤ 沉淀成资产；运行时 Windows-only）
├── cli.py                   # 五条核心命令的注册与分发
├── paper_input.py           # 单篇 Zotero 论文输入（个人/群组库）
├── card_draft.py            # 单篇主体卡草稿生成
├── card_validation.py       # 主体卡确定性代码校验门禁
├── pdf_gate.py              # PDF 全文门禁（体积 / 可抽取字符 / SHA-256）
├── theme_pool.py            # 主题池：哈希链注册表 + 合并/拆分血缘
├── publication.py           # 原子写入与崩溃可恢复的多文件提交
└── assets/                  # 只读资产：templates / prompts / schemas / examples / config

scripts/
├── run_paper_pipeline.sh    # 论文一键入库 Shell 脚本
└── chunk_fulltext.py        # 大文档切块（weekly-review 辅助）

skills/
├── zotero-query/            # 文献查询 Skill
├── paper-to-zotero/         # 论文入库 Skill（详细版）
├── run-paper-to-zotero/     # 论文入库 Skill（简化版）
├── weekly-review/           # 每周文献综述（从 dailyinfo 迁入）
├── zotero-notebooklm/       # Zotero → NotebookLM（迁入）
├── weekly-report-skill/     # 公众号周报（迁入）
├── figure-skill-v2/         # 配图/封面（迁入）
├── bilibili-upload/         # B 站发布（迁入）
├── download-pdf/            # 机构访问下载 PDF
└── literature-cards/        # 文献卡与主题卡的 skill 入口

outputs/
└── weekly-review/{date}/    # 精读产物（cards/article/podcast）

papers/                      # 按主题组织的文献库（知识库核心资产）
tests/                       # pytest（含迁入的 test_literature_*）
```

## 数据流

```text
┌─────────────────────────────────────────────────────────┐
│                     Consumer Layer                        │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐ │
│  │ Hermes   │  │ Claude Code  │  │ OpenClaw (虾酱)    │ │
│  │ (cron)   │  │ (MCP tools)  │  │ (Discord bot)     │ │
│  └────┬─────┘  └──────┬───────┘  └─────────┬─────────┘ │
│       │               │                    │           │
│       └───────────────┼────────────────────┘           │
│                       │                                 │
│            Skills / MCP / CLI                           │
└───────────────────────┼─────────────────────────────────┘
                        │
┌───────────────────────┼─────────────────────────────────┐
│          mylibrary — hydrolitagent (Zotero Layer)        │
│                       │                                 │
│  ┌────────────────────┼────────────────────────────┐    │
│  │              MCP Server (port 8002)              │    │
│  │  ┌──────────────┐  ┌────────────────────────┐   │    │
│  │  │ Web API (10) │  │ Local API (2)           │   │    │
│  │  │ pyzotero     │  │ httpx → localhost:23119 │   │    │
│  │  └──────┬───────┘  └───────────┬────────────┘   │    │
│  └─────────┼──────────────────────┼────────────────┘    │
│            │                      │                     │
│  ┌─────────▼──────────────────────▼────────────────┐    │
│  │              Zotero Library                      │    │
│  │  ┌─────────────────┐  ┌──────────────────────┐  │    │
│  │  │ Web API          │  │ Local SQLite         │  │    │
│  │  │ api.zotero.org   │  │ (full-text index)    │  │    │
│  │  └─────────────────┘  └──────────────────────┘  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │           Paper Pipeline (CLI)                    │    │
│  │  run_paper_pipeline.sh                            │    │
│  │    ├─ paper-fetch (PDF download)                  │    │
│  │    ├─ paper_to_zotero.py (metadata + Zotero API)  │    │
│  │    └─ cleanup                                     │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

> **上图只画了 `hydrolitagent`（读库与入库为主）。** `hydrolitagent/cards/` 的数据流方向相反:自己的 Zotero 库 → 单篇输入 → PDF 全文门禁 → 单 Agent 制卡 → 代码校验 → 候选主题池;它产出的是长期可追溯的文献卡与主题卡,产物写在平台目录下且**不入库**,由运行时自建。完整流程见[平台架构](platform/architecture.md)与[平台流程](platform/flows.md)。
>
> 两者都读 Zotero,但**走不同的客户端**:`hydrolitagent` 的 MCP 服务经 8002(容器部署),`hydrolitagent/cards/` 直连 Zotero Desktop Local API(裸 host)。为什么保留两套、各自适用什么环境,见 [ADR-0002](../adr/0002-zotero-two-clients-boundary.md)。

## `server.py` — MCP Server

- **框架**：`MCPServer`（mcp 2.x，`mcp.server`；mcp 2.0.0 起 `mcp.server.fastmcp` 已不存在）
- **传输**：streamable HTTP，端口 8002(端点路径 `/mcp`)
- **Web API 客户端**：pyzotero.Zotero（从环境变量初始化）
- **Local API 客户端**：httpx.AsyncClient
- **帮助器**：`_format_item()` 提取关键字段为统一格式，`_make_error()` 构建错误 JSON

### 工具装饰器模式

```python
@mcp.tool()
async def zotero_search(query: str, limit: int = 10) -> str:
    """Search the Zotero library by keyword."""
    # 实现
```

每个工具：
- 是 async 函数
- 返回 JSON 字符串
- 包含完整的 docstring（参数说明 + 返回值描述）
- 在客户端未初始化时返回错误 JSON（不抛异常）

## `paper_to_zotero.py` — 论文入库

- **输入**：paper-fetch JSON 文件或 DOI（metadata-only 模式）
- **元数据源**：Crossref API → arXiv API → Semantic Scholar → paper-fetch（优先级递减）
- **输出**：stdout JSON（`zotero_key`, `attachment_key`, `title`, `doi`）
- **关键函数**：`build_item(doi, pf_meta)` — 构建 Zotero 条目字典

### 元数据增强流程

```text
DOI → Crossref? ──Yes──→ 构建 item_data
         │
         No (或 arXiv preprint)
         │
         ▼
    arXiv ID? ──Yes──→ arXiv API → published DOI?
         │                │
         │                ├─ Yes → 重新查 Crossref → 升级元数据
         │                └─ No  → 使用 arXiv 预印本元数据
         │
         No
         │
         ▼
    paper-fetch 元数据（最终备选）
```

## `zot_link_gdrive.py` — Google Drive 链接

- 创建 `linked_file` 附件，指向 Google Drive 中的 PDF
- 使用 `attachments:` scheme（跨平台路径）
- 读取 `ZOTERO_CONFIG_PATH` 获取 API 凭据

## Skill 层

Skills 是面向 Agent 的封装层，每个 Skill 包含：

- `SKILL.md` — Agent 的指令文件（工具列表、使用场景、示例）
- Skill 告诉 Agent **调用哪个命令或 MCP 工具**，不包含实现逻辑

三个 Skill 的分工：

| Skill | 接口方式 | 场景 |
|-------|----------|------|
| `zotero-query` | MCP 工具 | 查询文献库 |
| `run-paper-to-zotero` | Docker 命令 | 一键入库（最简） |
| `paper-to-zotero` | Shell 脚本 | 论文入库 + 手动回退 |

## 代码分三支

| 线 | 做什么 | 代码 / 数据 | 用户入口 |
|---|---|---|---|
| **工具链** | 入库与消费：DOI/arXiv/标题 → PDF → Zotero 条目；读库、精读、知识图谱、公众号/播客/B 站 | `hydrolitagent/`、`scripts/`、`skills/`（12 个技能） | [MCP Server 工具](../user-guide/mcp-tools.md) |
| **文献卡与主题卡** | 从自己 Zotero 的一篇论文 → 主体卡草稿 → 代码校验 → 若干文献卡 → 候选主题（**运行时 Windows-only**） | `hydrolitagent/cards/`、`skills/literature-cards/` | [文献卡与主题卡](../user-guide/cards/index.md) |
| **证据卡与主题综合** | 来源 → 证据卡 → 初步主题 → **人工筛选门** → 既定主题 → Claim 准入 → 万字综合 | `skills/hydrology-evidence-cards/`、`skills/hydrology-theme-synthesis/`、[模板资产](../user-guide/cards/templates.md) | [模板资产](../user-guide/cards/templates.md) |

> **后两支别混用**：**文献卡与主题卡**追求「给定一篇论文，稳定产出可校验的卡片与候选主题」，
> 不做科研裁决、不需人逐条签字；**证据卡与主题综合**追求「每条科学表述都回链可核对的原文，正式主题必须由人签字」。

## Zotero 有四种读法，用途不同

它们读的是**同一台 Zotero Desktop 的本地 HTTP 服务**（`127.0.0.1:23119`），但库、前缀与用途不同：

| 读法 | 位置 | 目标 | 用途 |
|---|---|---|---|
| MCP Server（12 工具，端口 8002） | `hydrolitagent/zotero/server.py` | 元数据走 Web API，全文/附件走本地 API | 容器内或跨机调用 |
| 裸机脚本直连 | `hydrolitagent/literature/` | 本地 API `…/api/users/0/` | 裸 host 上的入库与简报 |
| 共享群组客户端 | `hydrolitagent/cards/zotero.py` | 共享群组（`/api/groups/<id>/`） | 文献卡平台的 Zotero 读取与 PDF 门禁 |
| 只读阅读器 | `skills/hydrology-evidence-cards/scripts/zotero_reader.py` | 个人库 `…/api/users/0/` | 证据卡取材，只读、不改库、不读 SQLite |

**分工而非二选一**：容器里走 8002 的 MCP，裸 host 直连 `23119`。
本地 API 基址的环境变量首选名是 `ZOTERO_LOCAL_BASE_URL`（`ZOTERO_API_URL` 是旧名）。
为什么不统一见 [ADR-0002](../adr/0002-zotero-two-clients-boundary.md)。

## 仓库目录地图

| 位置 | 存什么 |
|---|---|
| `hydrolitagent/` | Python 包：Zotero MCP Server、下载/入库、文献处理、知识图谱 |
| `hydrolitagent/cards/` | 文献卡与主题卡：代码 `*.py` 与只读资产 `assets/`（模板 / 提示词 / schema / 示例 / 默认配置），运行产物落仓库根 |
| `hydrolitagent/scholars/` | 学者与机构论文统计：按人/机构检索 OpenAlex，统计产出、作者位次与研究方向，输出 CSV/JSON/Markdown |
| `skills/` | 12 个技能：9 个工具链技能 + `literature-cards` + 两个水利科研技能 |
| `docs/` | 文档站源码（mkdocs） |
| `scripts/`、`configs/`、`docker/` | 入口脚本、提示词与路径配置、MCP Server 镜像 |
| `tests/` | pytest 测试（原平台测试已并入这一套） |
| `证据卡/`、`主题/`、`运行记录/`、`文献链接/` | 科研产物（**路径可配**，默认在此，不入 Git） |
| `_legacy/` | 专利/项目 Excel 统计（论文部分已迁至 `hydrolitagent/scholars/`） |
| `equation_from_data/`、`google_floodhub/` | 论文复现 |
