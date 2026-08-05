# Zotero 入库（linked_file）

把已下载的 PDF 同步进 Zotero 作为 linked_file 附件——**零 Zotero 云存储占用**。

## 流程概览

```text
PDF 下载并验证
  → zotero_sync <pdf> <doi>
  → 拷贝 PDF 到 GDRIVE_PAPERS_PATH
  → 从 Crossref 拉取元数据
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

从 mylibrary 仓库根执行：

```bash
# 带 JSON 输出的同步
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --json

# 干跑（仅预览，不写 API）
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --dry-run
```

> ⚠️ 必须用 `uv run python`,不要用裸 `python`。conda Python 没有 pyzotero。

## 它做了什么

1. **拷贝 PDF** 到 `$GDRIVE_PAPERS_PATH/{doi-slug}.pdf`
2. **拉取元数据** 从 Crossref API（标题、作者、期刊、卷、期、页、ISSN、出版商、摘要）
3. **创建父条目** 用 pyzotero Web API
4. **创建 linked_file 附件**，路径用可移植的 `attachments:<filename>`

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
| Crossref 元数据失败 | 回退到 PDF 内嵌元数据 |
| Zotero API 写入失败 | PDF 在 GDrive——用户可手动链接 |
| `UnicodeEncodeError: 'gbk'` | 同步成功；仅 Windows 打印错误 |

## 相关

- [论文 PDF 下载（机构访问）](download-pdf.md)
- [ADR-0001：linked_file 设计](../adr/0001-zotero-linked-file-sync.md)
- [论文入库流水线](paper-pipeline.md)
- [配置参考](config.md)
