# ADR-0002：不统一两套 Zotero 客户端（读取路径按运行环境分工）

## Status

Accepted

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

### 读取路径按运行环境分工，**不是**二选一

两条读取路径都成立，各自服务不同的运行环境，**不要混用**：

| 运行环境 | 读取路径 | 原因 |
|---|---|---|
| **裸 host**（本机、制卡机等直接跑 Python 的场景） | **直连**：元数据走 pyzotero（Zotero Web API，凭据在仓库 `.env`），全文走 Zotero Desktop Local API `127.0.0.1:23119` | 本机进程可直接访问本机 Zotero，无需中间服务 |
| **容器部署**（docker compose 起的服务） | **8002 的 MCP 服务**（`hydrolitagent/zotero/server.py`，12 个工具） | 容器内 `127.0.0.1` 指向容器自身；其 Local API 默认 `host.docker.internal:23119`，正是为访问宿主 Zotero 而设 |

`hydro-platform` 运行在**裸 host** 上，所以走直连——这与 `CLAUDE.md` 那句"8002 是唯一访问入口"**并不冲突**：后者描述的是容器侧的服务契约（同一句也写着"不要改动它的技术架构——已有其他服务依赖"），只是原文缺少"在容器部署中"这个作用域限定。

> 一个必须记住的操作事实：**在裸 host 上使用 Local API 必须设 `ZOTERO_LOCAL_BASE_URL=http://127.0.0.1:23119`**，否则默认的 `host.docker.internal` 在裸 host 上不解析（`getaddrinfo failed`）。**那个默认值是容器契约，不要改它**——要换地址就设环境变量。
>
> 变量名现在已统一：`ZOTERO_LOCAL_BASE_URL` 是**首选名**，被两个消费者共同读取（`hydrolitagent/zotero/server.py` 与 `hydrolitagent/literature/zotero_notebooklm.py`）；`ZOTERO_LOCAL_API_URL` 是**旧名**，仍然兼容（容器 compose 文件已在用它）。两者指向同一设置，不是两个不同的东西。

## Decision

**本次不统一两套客户端。** 它们在各自的运行环境里都是正确的实现，合并不会让它们重叠：

- `hydro-platform` 的 `zotero.py` 定位为**只读的 group 访问客户端**，**不承担下载与入库职责**。平台不下载任何 PDF，只读取共享库中已附好的文件。
- **不把任何一方的下载流程移植到另一方**：`download_paper.py` / `paper_to_zotero.py` 是唯一会下载并创建 Zotero 条目的路径。
- **8002 MCP 服务保持原样**（含其架构），并保留其写入/管理类工具面。
  > **勘误（2026-10-01）**：本句对工具面的描述与当前代码不符。`server.py` 的 12 个工具**全部只读**（10 个走 Zotero Web API + 2 个走 Local API），并无写入/管理类工具，且与 `ADR-0001`「mylibrary 的 Zotero MCP server 只读」相抵触。原决定「8002 服务保持原样、不整体弃用」本身不受影响，此处仅更正对工具面的描述。
- `hydro-platform` 的 Zotero 访问层本次**未做任何改动**，行为与合并前一致。

## 新增读取代码时怎么选

先问一句：**这段代码跑在哪里？**

- 跑在**裸 host**（本机、制卡机、任何直接执行 Python 的场景）→ 直连。不要为了省事去调 8002 服务——它绑定 `0.0.0.0:8002`，可达性取决于服务是否已启动（通常只有容器 compose 场景才起它，裸 host 上默认没有在跑）；且它的 Local API 出站默认 `host.docker.internal:23119`，在裸 host 上不解析。
- 跑在**容器**里 → 用 8002 的 MCP 工具面，不要自己拼 Local API 的地址。

两者**都会**受本机 Zotero Desktop 的行为变化影响，但连通条件不同（见上表），排查问题时不要把一侧的结论套到另一侧。

## Follow-up（文档措辞）

根 `CLAUDE.md` 的 Zotero 接入方式节称 8002 MCP server 为"唯一的 Zotero 访问入口"，但未限定"在容器部署中"。该句本身描述无误（同一段也确实记着"不要改动它的技术架构——已有其他服务依赖"），**只是缺少作用域限定**，容易让裸 host 上的读者以为不能用直连。建议补上限定语；本条 ADR 记录该建议，未擅自改动那一节。

## Alternatives Considered

### 以平台的直连客户端为准，弃用 MCP 读取路径

技术上可行（约定本就如此），但代价是同时动到 agent 工具面与个人库入库流程——与本 ADR 要记录的边界无关。8002 服务的写入/管理类工具没有替代品，不能整体弃用。
>
> **勘误（2026-10-01）**：同上——8002 服务当前并无写入/管理类工具（12 个工具全只读），「没有替代品」的前提不成立；「不能整体弃用」的结论仍由 agent 工具面与个人库入库流程的替代成本支撑。

### 以 `hydrolitagent/zotero/server.py` 为准，让平台改调 MCP

方向错误。平台需要的是**进程内的批量只读扫描**（分页快照 + 中途变更检测），经 MCP 往返既无必要，也与"检测共享 group 增量"的语义不符；且平台在无人值守时要能独立于 MCP 服务运行。

### 本次就抽出一层统一客户端

两套实现的差异来自**目标库与方向**，不是实现草率。在两种使用场景都稳定之前抽象共同层，只会得到一个两个调用者都不满意的接口。

## Consequences

- 仓库中长期存在两套 Zotero 客户端，**新增 Zotero 相关代码前必须先确认属于哪一侧**（个人库入库 / 共享库检测），不要凭直觉选。
- 二者都依赖 Zotero Desktop 的 **Local API**，因此本机 Zotero 的行为变化会同时影响两边；但**默认端点并不相同**——平台侧写死 `127.0.0.1:23119` 且只允许回环地址，MCP 侧默认 `host.docker.internal:23119`（为容器内访问宿主 Zotero 而设，可用 `ZOTERO_LOCAL_BASE_URL` 覆盖，`ZOTERO_LOCAL_API_URL` 为兼容旧名）。**两者的连通条件因此不同**：容器外的直连与容器内的 MCP 各按各的前提生效，排查问题时不要把一侧的结论套到另一侧。
- 统一客户端仍是**独立议题**，不在本次合并范围内。若将来统一，应先明确：读取路径以直连为准、MCP 仅保留工具面。
- `hydro-platform` 的 Zotero 访问层本次**未做任何改动**，其行为与合并前一致。
