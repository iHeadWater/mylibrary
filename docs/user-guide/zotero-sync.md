# Zotero 入库（linked_file）

把已下载的 PDF 同步进 Zotero 作为 linked_file 附件——**零 Zotero 云存储占用**。

## 流程概览

```text
PDF 下载并验证
  → zotero_sync <pdf> <doi>
  → 拷贝 PDF 到 GDRIVE_PAPERS_PATH
  → build_item 拉元数据（Crossref → arXiv API → Semantic Scholar）
  → 用 pyzotero Web API 创建 Zotero 父条目
  → 创建 linked_file 附件（attachments:<filename> 方案）
```

## 前置条件

### 环境变量

```env
ZOTERO_API_KEY=<key>            # https://www.zotero.org/settings/keys
ZOTERO_LIBRARY_ID=6716904       # 数字型用户 ID
GDRIVE_PAPERS_PATH=G:\...\Zotero_Papers   # 本地 GDrive 路径
```

### Zotero 桌面端配置

Zotero → 偏好设置 → 高级 → 文件和文件夹：
- **Linked Attachment Base Directory**：与 `GDRIVE_PAPERS_PATH` 相同路径

## 用法

**推荐（一键 下载+同步）**——用 `scripts/download_paper.py`，arXiv 与期刊 DOI 都自动建正确条目：

```bash
uv run python scripts/download_paper.py --setup-check            # 新机器先自检一次
uv run python scripts/download_paper.py --arxiv <id> --sync      # arXiv → preprint 记录
uv run python scripts/download_paper.py --doi <doi> --sync       # 期刊 / 会议 DOI
```

直接调用 `zotero_sync`（本文档，处理已有 PDF）——从 mylibrary 仓库根执行：

```bash
# 带 JSON 输出的同步
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --json

# 干跑（仅预览，不写 API）
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --dry-run

# 同 DOI 已存在时强制重建
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --allow-duplicate
```

> ⚠️ 必须用 `uv run python`,不要用裸 `python`。conda Python 没有 pyzotero。

## 它做了什么

1. **拷贝 PDF** 到 `$GDRIVE_PAPERS_PATH/{doi-slug}.pdf`
2. **拉取元数据** 用 `paper_to_zotero.build_item()`（Crossref → arXiv API → Semantic Scholar）。
   arXiv DOI（`10.48550/arXiv.*`）在 Crossref 是 404，由 arXiv API 给出正确的 `preprint` 记录
   （真实标题/作者/摘要/日期 + `archiveID: arXiv:…`），不再退回 PDF 内嵌元数据。
3. **幂等检查** 同 DOI 已存在则 SKIP 并打印既有 key（`--allow-duplicate` 强制重建）
4. **创建父条目** 用 pyzotero Web API
5. **创建 linked_file 附件**，路径用可移植的 `attachments:<filename>`

## 为什么用 linked_file

| 附件类型 | 存储 | 配额 |
|---------|------|------|
| `imported_file` | Zotero 云端 | 300 MB |
| `linked_file` | Google Drive | 无限 |

机构 PDF 每篇 10–90 MB——Zotero 的 300 MB 大约 5 篇论文即满。参见 [ADR-0001](../adr/0001-zotero-linked-file-sync.md)。

## 附件方案

```
path: "attachments:s41586-026-10704-3.pdf"
```

Zotero 将 `attachments:` 解析到 "Linked Attachment Base Directory"。跨机器可移植。

## 失败处理

| 场景 | 行为 |
|------|------|
| `ZOTERO_API_KEY` / `ZOTERO_LIBRARY_ID` 未设置 | 报错——PDF 已保存在本地 |
| `GDRIVE_PAPERS_PATH` 未设置 | 报错——PDF 已保存在本地 |
| Crossref 对 arXiv DOI 返回 404 | `build_item` 走 arXiv API → 正确 preprint 记录（不再回退 PDF 内嵌元数据） |
| Crossref / arXiv API 全失败 | 回退到 PDF 内嵌元数据 |
| 同 DOI 条目已存在 | SKIP（幂等），打印既有 key；`--allow-duplicate` 强制重建 |
| Zotero API 写入失败 | PDF 在 GDrive——用户可手动链接 |
| Windows 打印中文乱码 / GBK 崩溃 | 已修复：子进程注入 `PYTHONIOENCODING=utf-8` |

## 相关

- [论文 PDF 下载（机构访问）](download-pdf.md)
- [ADR-0001：linked_file 设计](../adr/0001-zotero-linked-file-sync.md)
- [论文入库流水线](paper-pipeline.md)
- [配置参考](config.md)
