# ADR-0002：不统一两套 Zotero 客户端（读取路径约定待裁决）

## Status

Accepted —— **决策范围仅限「本次不统一两套 Zotero 客户端」。**

本 ADR **未**裁定「读取路径以哪条为准」，该问题见 §Open Question。在它裁决之前，本 ADR **不构成读取路径的指导**：不要把它当作「读写都该走直连」或「都该走 MCP」的依据。

## Date

2026-09-10

## Context

合并 `hydro-platform` 时，仓库里出现了**两套彼此独立的 Zotero 客户端**：

| | `hydrolitagent/zotero/server.py` | `hydro-platform/automation/src/hydro_platform/zotero.py` |
|---|---|---|
| 形态 | FastMCP 服务（端口 8002），12 个工具 | 裸 HTTP 客户端，无服务、无状态 |
| 底层 | pyzotero（Web API）+ httpx（Local API，仅全文与附件信息 2 个工具，默认 `host.docker.internal:23119`） | `urllib` 直连 Zotero Desktop Local API，默认 `127.0.0.1:23119`，且**强制**主机名只能是 `127.0.0.1`／`localhost`／`::1` |
| 目标库 | 个人库 | 共享 group 库 |
| 方向 | **把文献弄进来**：下载 PDF → 建条目 → `linked_file` 附件 | **从已有文献里沉淀认识**：检测新增条目与后补 PDF → 门禁 → 制卡 |
| 节奏 | 一次一个 DOI，人驱动 | 批量、事件驱动、无人值守 |
| 调用者 | agent（经 MCP 工具） | 平台流水线自身（进程内 import） |

两者**目标库不同、方向相反、底层 API 也不同**，没有共用的调用场景。

### 读取路径的约定目前自相矛盾

仓库里对"读取 Zotero 走哪条路"存在**两条互相冲突的表述**，合并时未擅自裁定：

| 出处 | 表述 |
|---|---|
| 根 `CLAUDE.md`（Zotero 接入方式节） | "本仓库的 Zotero MCP server（`hydrolitagent/zotero/server.py`，端口 8002）**是唯一的 Zotero 访问入口**。不要改动它的技术架构——已有其他服务依赖。" |
| 近期口头/工作约定 | **读取走本机直连**（pyzotero + Local API `127.0.0.1:23119`），**不走 8002 MCP**；MCP 保留工具面但不再是读取路径 |

`hydro-platform` 的实现事实上站在后者一侧（裸 HTTP 直连 `127.0.0.1:23119`，不经 MCP）。**本条 ADR 记录该冲突，不裁定它。**

## Decision

**本次不统一两套客户端。** 这一点不依赖上面那条未决约定：

- `hydro-platform` 的 `zotero.py` 定位为**只读的 group 访问客户端**，**不承担下载与入库职责**。平台不下载任何 PDF，只读取共享库中已附好的文件。
- **不把任何一方的下载流程移植到另一方**：`download_paper.py` / `paper_to_zotero.py` 是唯一会下载并创建 Zotero 条目的路径。
- **8002 MCP 服务保持原样**（含其架构），并保留其写入/管理类工具面。
- `hydro-platform` 的 Zotero 访问层本次**未做任何改动**，行为与合并前一致。

## Open Question（待裁决）

**读取路径以哪条为准？** 需要仓库负责人明确，并据此更新根 `CLAUDE.md`：

- 若以**直连**为准：`CLAUDE.md` 的"唯一访问入口"表述需修正，8002 服务缩为工具面。
- 若以 **MCP** 为准：`hydro-platform` 的直连客户端需要改造，且要说明无人值守场景下如何依赖 MCP 服务的可用性。

本 ADR 不预设结论；在裁决前，**新增 Zotero 读取代码应先确认属于哪一侧**，不要凭直觉选。

## Alternatives Considered

### 以平台的直连客户端为准，弃用 MCP 读取路径

技术上可行（约定本就如此），但代价是同时动到 agent 工具面与个人库入库流程——与本 ADR 要记录的边界无关。8002 服务的写入/管理类工具没有替代品，不能整体弃用。

### 以 `hydrolitagent/zotero/server.py` 为准，让平台改调 MCP

方向错误。平台需要的是**进程内的批量只读扫描**（分页快照 + 中途变更检测），经 MCP 往返既无必要，也与"检测共享 group 增量"的语义不符；且平台在无人值守时要能独立于 MCP 服务运行。

### 本次就抽出一层统一客户端

两套实现的差异来自**目标库与方向**，不是实现草率。在两种使用场景都稳定之前抽象共同层，只会得到一个两个调用者都不满意的接口。

## Consequences

- 仓库中长期存在两套 Zotero 客户端，**新增 Zotero 相关代码前必须先确认属于哪一侧**（个人库入库 / 共享库检测），不要凭直觉选。
- 二者都依赖 Zotero Desktop 的 **Local API**，因此本机 Zotero 的行为变化会同时影响两边；但**默认端点并不相同**——平台侧写死 `127.0.0.1:23119` 且只允许回环地址，MCP 侧默认 `host.docker.internal:23119`（为容器内访问宿主 Zotero 而设，可用 `ZOTERO_LOCAL_API_URL` 覆盖）。**两者的连通条件因此不同**：容器外的直连与容器内的 MCP 各按各的前提生效，排查问题时不要把一侧的结论套到另一侧。
- 统一客户端仍是**独立议题**，不在本次合并范围内。若将来统一，应先明确：读取路径以直连为准、MCP 仅保留工具面。
- `hydro-platform` 的 Zotero 访问层本次**未做任何改动**，其行为与合并前一致。
