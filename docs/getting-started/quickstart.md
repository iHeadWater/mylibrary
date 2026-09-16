# 5 分钟上手

> 本页覆盖**入库**（下载 + 入 Zotero）与**消费侧的当期内容支线**（读库、深度处理）。注意入库只有三件事:论文 PDF 下载 → 建 Zotero 条目 → `linked_file` 附件。
>
> 消费侧还有另一支 —— `hydro-platform`:把共享 Zotero 库里**已经附好 PDF** 的论文沉淀成**证据包与持续演化的主题池**。它产出的是长期可追溯的知识资产,而不是文章/播客这类当期内容;无人值守、**Windows-only** 运行时。如果你的目标是这一支,见[科研知识平台](../hydro-platform/index.md) 或[用户指南总览](../user-guide/index.md)。

## 场景 1：查文献

通过 MCP Server 搜索你的 Zotero 文献库。

### 启动 MCP Server

```bash
uv run python -m hydrolitagent.zotero.server
# 启动在 http://0.0.0.0:8002/mcp
```

### 调用工具搜索

```python
# 关键词搜索
zotero_search(query="flood forecasting", limit=10)
# → 返回标题、作者、日期、DOI、摘要片段

# 全文搜索（需要 Zotero 桌面版运行）
zotero_fulltext_search(query="LSTM streamflow", limit=20)

# 按标签搜索
zotero_search_by_tag(tag="deep learning")

# 查看最近添加
zotero_get_recent(limit=10)
```

MCP Server 提供 12 个工具，详见 [MCP Server 工具参考](../user-guide/mcp-tools.md)。

## 场景 2：加论文

从 DOI 或 arXiv ID 一键将论文加入 Zotero。

```bash
# 通过 DOI 添加（仅元数据，无 PDF）
uv run python -m hydrolitagent.zotero.paper_to_zotero \
  --metadata-only "10.1038/s41586-024-07145-1"

# 通过 arXiv ID 添加
uv run python -m hydrolitagent.zotero.paper_to_zotero \
  --metadata-only "10.48550/arXiv.2501.08086"

# 预览模式（不实际写入）
uv run python -m hydrolitagent.zotero.paper_to_zotero \
  --dry-run --metadata-only "10.1038/s41586-024-07145-1"
```

## 场景 3：完整流水线（下载 PDF → GDrive → Zotero 入库）

**裸 host / 本仓库直跑（推荐）**——新机器先自检一次，之后一条命令：

```bash
uv run python scripts/download_paper.py --setup-check
uv run python scripts/download_paper.py --doi "10.1038/s41586-024-07145-1" --sync
uv run python scripts/download_paper.py --arxiv 2501.08086 --sync
```

arXiv 与 OA DOI（science.org / Copernicus 等）走 curl，秒级；付费墙（SD/Wiley/Nature）需浏览器 + 机构会话。
同 DOI 重跑会把 PDF **补挂到既有条目**（条目在、缺 PDF 的常见情形）；已挂同内容则幂等跳过。

**myopenclaw / hermes 容器（爱码士）**——用打包进容器的 pipeline（需要 paper-fetch）：

```bash
docker compose exec hermes-coder /opt/hermes/scripts/run-paper-pipeline.sh "10.1038/s41586-024-07145-1"
docker compose exec hermes-coder /opt/hermes/scripts/run-paper-pipeline.sh --dry-run "10.xxx"
```

## 场景 4：链接 Google Drive PDF

已有 Zotero 条目，只缺 PDF 附件。

```bash
# 需要先配置 rclone 和 Google Drive
uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>
```

## 场景 5：文献深度处理

对已入库的 Zotero 文献做精读、主题分析、公众号/播客产出(该能力从 dailyinfo 迁入)。

```bash
# 每周文献综述:精读 → 8 段分析卡 → 主题聚类 → 文章 → 播客
# (由 skills/weekly-review/ 驱动,产物在 outputs/weekly-review/{date}/)

# B 站发布 podcast
uv run python -m hydrolitagent.literature.bilibili_upload audio.mp3 --title "标题" --dry-run

# Zotero → NotebookLM 音频
uv run python -m hydrolitagent.literature.zotero_notebooklm --collection water --artifact audio
```

## 下一步

- [MCP Server 工具详解](../user-guide/mcp-tools.md) — 每个工具的用途、参数和返回格式
- [论文入库流水线详解](../user-guide/paper-pipeline.md) — 完整流程和故障排查
- [文献深度处理详解](../user-guide/literature.md) — literature CLI 和知识库
- [Zotero 配置参考](../user-guide/config.md) — 环境变量和配置文件
- [科研知识平台](../hydro-platform/index.md) — **消费侧的另一支**：Zotero → 证据包 → 主题池（Windows-only，无人值守）
