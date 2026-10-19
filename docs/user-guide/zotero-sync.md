# Zotero 入库（linked_file）

把已下载的 PDF 同步进 Zotero 作为 linked_file 附件——**零 Zotero 云存储占用**。

## 流程概览

```text
PDF 下载并验证
  → zotero_sync <pdf> <doi>
  → 拷贝 PDF 到 GDRIVE_PAPERS_PATH
  → 查重：同 DOI 是否已有条目？（本地索引 + 增量，命中零请求）
      ├─ 已有 → 把 PDF 挂到既有条目上（不拉元数据）
      └─ 没有 → build_item 拉元数据（Crossref → arXiv API → Semantic Scholar）
                → 用 pyzotero Web API 创建父条目
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
uv run python scripts/download_paper.py --title "<标题>" --sync   # 只有标题：先检索成 DOI
```

直接调用 `zotero_sync`（本文档，处理已有 PDF）——从 mylibrary 仓库根执行：

```bash
# 带 JSON 输出的同步
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --json

# 干跑（仅预览，不写 API）
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --dry-run

# 同槽位已有附件但内容不同时，强制覆盖那个文件
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --replace

# 同 DOI 已存在时强制新建父条目（会产生第二条重复条目，慎用）
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --allow-duplicate

# 恢复旧行为：同 DOI 已存在就直接退出，不挂附件
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --skip-existing
```

> ⚠️ 必须用 `uv run python`,不要用裸 `python`。conda Python 没有 pyzotero。

## 它做了什么

1. **查重** 先看本地索引（带水位线的增量）。命中就直接走补挂，
   **不再付 Crossref 延迟**，Crossref 故障也不会挡住补挂。
2. **拷贝 PDF** 到 `$GDRIVE_PAPERS_PATH/{doi-slug}.pdf`
3. **未命中才拉取元数据** 用 `paper_to_zotero.build_item()`（Crossref → arXiv API → Semantic Scholar）。
   arXiv DOI（`10.48550/arXiv.*`）在 Crossref 是 404，由 arXiv API 给出正确的 `preprint` 记录
   （真实标题/作者/摘要/日期 + `archiveID: arXiv:…`），不再退回 PDF 内嵌元数据。
3. **查重并决定动作** 同 DOI 已存在时**把 PDF 补挂到既有条目**，而不是跳过：
   - 该条目还没有本 DOI 槽位的附件 → 拷贝 PDF 并新建 `linked_file` 附件
   - 已有同槽位附件、内容一致（sha256 相同）→ 幂等跳过，不重复挂
   - 已有同槽位附件、内容不同 → 报冲突并**保持原文件不动**（`--replace` 才覆盖）
   - 已有附件但文件名不同 → 视为不同内容，允许再挂一个
   - `--skip-existing` → 回到旧行为（打印 SKIP 后退出）
4. **创建父条目** 用 pyzotero Web API（仅在查重未命中时）
5. **创建 linked_file 附件**，路径用可移植的 `attachments:<filename>`

## 查重索引（增量）

`.zotero-sync-index.json` 保存在 `$GDRIVE_PAPERS_PATH` 里，字段为
`{version, updated, last_version, library_id, items}`：`items` 是 `{DOI → Zotero key}`，
`last_version` 是**库水位线**，`library_id` 记录这份账本属于哪个库。

Zotero Web API 的快速搜索 `q` **不索引 DOI 字段**，所以"这个 DOI 存在吗"没法直接问服务端。
索引的作用就是把这个问题变成一次本地查表：

| 情况 | 请求数 | 耗时 |
|------|--------|------|
| DOI 在索引里（命中） | 0 | 立即 |
| 未命中，且库水位没动 | 1（只读水位） | ~1 秒 |
| 未命中，库有改动 | 3（水位 + `since` 增量 + 删除列表） | 1–3 秒 |
| 首次升级到 v2（同库、索引完好） | ~60 | 约 5 分钟，**仅一次** |
| 每次 `--refresh-index` | ~60 | 约 5 分钟 |
| 索引损坏 / 换库 / 水位倒退 | ~60 | 约 5 分钟（各自触发一次重建） |

**为什么"库水位没动"就能断定不存在：** 全量扫描记录了扫描时刻的水位 V；此后每次增量把
V→W 之间的新增、修改、删除全部并入；若当前水位仍是 W，说明窗口内没有任何变化，
因此索引里没有的 DOI 就是真的没有。

> ⚠️ **升级后第一次运行仍会做一次全量扫描**（约 5 分钟）。这是为了建立水位线，
> 让之后每一次都能秒级判定。同一库、索引完好的前提下只发生一次；
> 但**换库、索引损坏、库版本倒退**都会各自再触发一次全量重建。

增量读取用 `top(since=…, includeTrashed=1)`：移到回收站是一次条目更新（`data.deleted=1`），
不带这个参数就永远看不到，账本里的陈旧命中也就不自愈。回收站条目会从索引中移除。
`since` 增量按 100 条分页，所以"3 次请求"是最小值，改动多时会更多。

索引写入是**原子**的（`.tmp` + `os.replace`），Google Drive 同步中断不会留下半个文件。
重建索引：`--refresh-index`，或直接删掉 `.zotero-sync-index.json`。

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
| 同 DOI 条目已存在、缺 PDF | **补挂** linked_file 到既有条目（旧版本会 SKIP） |
| 同槽位附件内容不一致 | 报 CONFLICT（退出码 0），原文件保持不动；`--replace` 强制覆盖 |
| 同 DOI 且已有同槽位相同内容的附件 | 幂等跳过；`--skip-existing` 回到旧的直接退出 |
| Zotero API 写入失败 | PDF 在 GDrive——用户可手动链接 |
| Windows 打印中文乱码 / GBK 崩溃 | 已修复：子进程注入 `PYTHONIOENCODING=utf-8` |

## 相关

- [论文 PDF 下载（机构访问）](download-pdf.md)
- [ADR-0001：linked_file 设计](../adr/0001-zotero-linked-file-sync.md)
- [论文入库流水线](paper-pipeline.md)
- [配置参考](config.md)
