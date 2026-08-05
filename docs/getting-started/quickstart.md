# 5 分钟上手

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

## 场景 3：完整流水线

使用自动化脚本完成 下载 PDF → 上传 → Zotero 入库的全流程。

```bash
# DOI 方式
bash scripts/run_paper_pipeline.sh "10.1038/s41586-024-07145-1"

# arXiv ID 方式（自动转为 DOI）
bash scripts/run_paper_pipeline.sh "2501.08086"

# PDF 直链模式（已知 PDF URL 时）
bash scripts/run_paper_pipeline.sh --pdf-url "https://example.com/paper.pdf" "10.xxx"

# 预览模式
bash scripts/run_paper_pipeline.sh --dry-run "10.1038/s41586-024-07145-1"
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
