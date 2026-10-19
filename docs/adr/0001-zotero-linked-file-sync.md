# ADR-0001：Zotero 入库使用 linked_file 附件

## Status

Accepted

## Date

2026-06-24（迁移至 mylibrary 时保留原决策）

## Context

`download-pdf` 能力通过机构访问（任何有订阅的机构 SSO）用 Playwright 浏览器自动化下载学术论文（每篇 5–90 MB）。下载后用户希望把 PDF 同步进 Zotero 文献库。用户使用 ZotMoov 在 Google Drive 目录中管理链接 PDF，完全绕过 Zotero 云存储。

同步路径考虑过的选项：

- **zotero-mcp `zotero_add_from_file`**：一次 MCP 调用、零新代码。但创建的是 `imported_file` 附件，存储在 Zotero 云端——300 MB 配额在 3–6 篇论文后即满。
- **zotero-mcp `zotero_add_by_doi` + 手动链接**：MCP 创建元数据，再在 Zotero 桌面端手动拖拽附件。部分自动化，但不够 agentic。
- **pyzotero + `linked_file`**：自定义 Python 脚本，拷贝 PDF 到 GDrive、拉取 CrossRef 元数据、创建 Zotero 父条目、用 Zotero 可移植的 `attachments:` 方案附加 linked_file 指针。需要 Zotero Web API 凭据。

## Decision

使用 **pyzotero 配合 `linked_file` 附件**（`hydrolitagent/literature/zotero_sync.py`）。

脚本流程：
1. 拷贝 PDF 到 `$GDRIVE_PAPERS_PATH/{doi-slug}.pdf`
2. 从 Crossref API 拉取完整元数据（标题、作者、摘要、期刊、卷、页、ISSN、出版商）
3. 通过 pyzotero Web API 创建 Zotero 父条目
4. 创建 linked_file 子附件，路径为 `attachments:{filename}`

Zotero 将 `attachments:` 前缀解析到用户的 "Linked Attachment Base Directory" 偏好（Zotero 偏好设置 → 高级 → 文件和文件夹）。PDF 存放在 Google Drive 中，由 ZotMoov 管理。

## Alternatives Considered

### zotero_add_from_file（MCP）

- 优点：一次 MCP 调用、无需新 Python 代码、无需 API key 配置
- 缺点：创建 `imported_file` 附件存储在 Zotero 云端（300 MB 配额）。一篇 47 MB 的论文即占 15% 配额。不支持 `linked_file`
- 否决原因：机构 PDF 体积下配额消耗过快

### GDrive + rclone 上传 + pyzotero linked_file（myopenclaw 模式）

- 优点：在姊妹项目生产环境中验证过；rclone 稳健处理 GDrive 上传
- 缺点：需要 rclone OAuth 配置；依赖 Docker 容器执行；对本地 PC 工作流是过度设计
- 否决原因：用户 PC 已本地挂载 Google Drive，rclone 徒增复杂度

### zotero-mcp 元数据 + Zotero 桌面手动链接

- 优点：代码最少；使用现有 MCP 工具
- 缺点：未完全自动化；需要人把 PDF 拖进 Zotero 桌面端
- 否决原因：agent 操作的 download-pdf 目的就是消除手动步骤

## Consequences

- mylibrary 的 Zotero MCP server **只读**：collection 发现用 `zotero_get_collections`，collection 归档用 pyzotero 直接调用（`addto_collection`）——脚本只处理 MCP 做不了的（linked_file 附件创建）
- 三个新环境变量：`ZOTERO_API_KEY`、`ZOTERO_LIBRARY_ID`、`GDRIVE_PAPERS_PATH`
- `pyzotero` 已是 mylibrary 的基础依赖（非 optional group）
- 所有期刊元数据字段（`publicationTitle`、`volume`、`issue`、`pages`、`ISSN`、`publisher`）放入 Zotero 专用字段，而非 `extra` 文本块
- `attachments:` 方案跨操作系统和用户账户可移植，只要每台机器的 Linked Attachment Base Directory 配置正确
