# 模块架构

本仓库的能力分**入库**（只有下载 + 入 Zotero）与**消费**（读库 → 精读/主题/内容产出，以及 `hydro-platform` 的证据包与主题池）两侧。**`hydrolitagent` 横跨两侧**，[`hydro-platform/`](../hydro-platform/index.md) 纯属消费。分侧导览见[用户指南总览](../user-guide/index.md)。本节先给整体结构，随后展开 `hydrolitagent` 的模块。

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
└── query/                   # 图查询

hydro-platform/              # 消费侧（uv workspace 成员；运行时 Windows-only）
├── automation/src/hydro_platform/    # 平台代码
│   ├── pipeline.py          # run-once 串行编排（检测→制卡→主题→账本→日报）
│   ├── tasks.py             # 任务状态机 + 跨平台锁 + 租约
│   ├── pdf_gate.py          # PDF 全文门禁（体积 / 可抽取字符 / SHA-256）
│   ├── card_generation.py   # 单 Agent 制卡编排
│   ├── theme_pool.py        # 主题池：哈希链注册表 + 合并/拆分血缘
│   └── publication.py       # 原子写入与崩溃可恢复的多文件提交
├── templates/               # 九类证据卡模板、主题提示词、JSON schema
├── config/                  # 非敏感配置 + 完整示例
└── pyproject.toml           # 入口：uv run hydro-platform

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
└── hydro-platform/          # 消费侧平台 CLI 入口

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

> **上图只画了 `hydrolitagent`（读库与入库为主）。** `hydro-platform` 的数据流方向相反:Zotero 共享库 → 检测增量 → PDF 全文门禁 → 单 Agent 制卡 → 证据包 → 主题池 → 日报;它产出的是长期可追溯的知识资产,产物写在平台目录下且**不入库**,由运行时自建。完整流程见[平台架构](../hydro-platform/architecture.md)与[平台流程](../hydro-platform/flows.md)。
>
> 两者都读 Zotero,但**走不同的客户端**:`hydrolitagent` 的 MCP 服务经 8002(容器部署),`hydro-platform` 直连 Zotero Desktop Local API(裸 host)。为什么保留两套、各自适用什么环境,见 [ADR-0002](../adr/0002-zotero-two-clients-boundary.md)。

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
