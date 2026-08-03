# 论文入库流水线

从 DOI / arXiv ID / 论文标题到 Zotero 条目的全自动流程。

## 一句话

```bash
bash scripts/run_paper_pipeline.sh "<DOI_OR_TITLE>"
```

## 流程概览

```text
输入 (DOI / arXiv ID / 标题)
  │
  ├─→ Step 1: 下载 PDF (paper-fetch)
  │     ├─ 常规模式: paper-fetch → 下载 PDF + 提取元数据
  │     └─ 直链模式: --pdf-url → Python urllib 直接下载
  │
  ├─→ Step 2: 元数据增强 (paper_to_zotero.py)
  │     ├─ Crossref API → 期刊/会议信息
  │     ├─ arXiv API → 预印本元数据
  │     └─ Semantic Scholar → 补充已发表 DOI
  │
  ├─→ Step 3: 创建 Zotero 条目
  │     ├─ pyzotero → Zotero Web API
  │     └─ linked_file 附件 (attachments: scheme)
  │
  └─→ Step 4: 清理临时文件
```

## 输入模式

### DOI

```bash
bash scripts/run_paper_pipeline.sh "10.1038/s41586-024-07145-1"
```

### arXiv ID

支持两种格式，自动转为 DOI：

```bash
# 标准格式
bash scripts/run_paper_pipeline.sh "arxiv:2501.08086"

# 纯数字格式（自动识别）
bash scripts/run_paper_pipeline.sh "2501.08086"
# → 自动转为 10.48550/arXiv.2501.08086
```

### 论文标题

```bash
bash scripts/run_paper_pipeline.sh "Global prediction of extreme floods in ungauged watersheds"
```

标题模式会触发 paper-fetch 的 `--title` 搜索。

## PDF 直链模式

已知 PDF URL 时跳过 paper-fetch 搜索，直接下载：

```bash
bash scripts/run_paper_pipeline.sh --pdf-url "https://hess.copernicus.org/articles/30/3853/2026/hess-30-3853-2026.pdf" "10.5194/hess-30-3853-2026"
```

## 预览模式

```bash
bash scripts/run_paper_pipeline.sh --dry-run "10.1038/s41586-024-07145-1"
```

输出将创建的内容但不实际写入 Zotero。

## 仅元数据模式

不需要 PDF 时直接创建 Zotero 条目：

```bash
uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "10.1038/s41586-024-07145-1"

# 同时链接已有 PDF
uv run python -m hydrolitagent.zotero.paper_to_zotero \
  --metadata-only --pdf-filename "paper.pdf" "10.1038/s41586-024-07145-1"
```

## 配置

流水线依赖以下配置：

| 配置项 | 位置 | 说明 |
|--------|------|------|
| Zotero API 凭据 | `~/.config/zot/config.toml` 或 `ZOTERO_CONFIG_PATH` | `[zotero]` 下的 `library_id` 和 `api_key` |
| paper-fetch 目录 | `PAPER_FETCH_DIR` 环境变量 | 默认 `~/code/paper-fetch` |
| Zotero 脚本 | `ZOTERO_SCRIPT` 环境变量 | 默认 `python3 -m hydrolitagent.zotero.paper_to_zotero` |

详见 [Zotero 配置参考](config.md)。

## 元数据来源优先级

`paper_to_zotero.py` 按以下优先级获取元数据：

1. **Crossref** — 最完整的期刊/会议元数据（标题、作者、摘要、期刊名、卷期页、ISSN/ISBN）
2. **arXiv 升级** — 对于 arXiv DOI，尝试将预印本元数据升级为已发表版本：
   - 先查 arXiv API（`<arxiv:doi>` 元素）
   - 再查 Semantic Scholar（外部 ID 映射）
   - 用已发表 DOI 重新查 Crossref 获取正式元数据
3. **arXiv** — Crossref 失败时的备选（预印本标题、摘要、作者）
4. **paper-fetch** — 最终备选（基本标题、作者、年份）

## 条目类型映射

| Crossref 类型 | Zotero 类型 | 字段路由 |
|---------------|-------------|----------|
| `journal-article` | `journalArticle` | `publicationTitle`, `volume`, `issue`, `pages`, `ISSN` |
| `proceedings-article` | `conferencePaper` | `proceedingsTitle`, `ISBN`, `ISSN`, `publisher` |
| `book-chapter` | `bookSection` | `bookTitle`, `ISBN`, `publisher` |
| `book` | `book` | `ISBN`, `publisher` |
| 其他 | `preprint` | 所有期刊信息放入 `extra` 字段 |

!!! warning "conferencePaper 字段注意"
    `conferencePaper` 使用 `proceedingsTitle` 而非 `publicationTitle`。
    使用 `publicationTitle` 会导致 Zotero API 返回 400 错误。

## 已知问题与故障排查

| 问题 | 症状 | 解决 |
|------|------|------|
| **Crossref 低置信度匹配** | 标题变成数字（如 `"2501"`）或完全错误的论文 | 检查输出中的 `low_confidence: true`，使用手动回退流程 |
| **arXiv ID 被匹配到错误 DOI** | arXiv `2603.05538` → 一篇 2006 年的放疗论文 | 始终核对输出的标题和 DOI 是否匹配预期 |
| **paper-fetch 返回 `not_found`** | 期刊爬虫阻挡或无法访问 | 使用 `--pdf-url` 提供直链，或退回到 `--metadata-only` |
| **Copernicus 下载极慢** | 下载到 80-90% 后超时断开 | 使用 Python urllib + 120s 超时，或 `wget -c` 续传 |
| **附件显示"附件未找到"** | 使用了 `imported_url` linkMode | 始终用 `linked_file` + `attachments:` scheme（脚本已默认） |
| **conferencePaper 更新失败 (400)** | `'publicationTitle' is not a valid field` | 使用 `proceedingsTitle` 代替 `publicationTitle` |
| **SSL 错误** | `UNEXPECTED_EOF_WHILE_READING` | 部分出版商证书有问题，备选 `ssl._create_unverified_context()` |

### 手动回退流程

当流水线匹配到错误论文时：

1. **获取正确元数据**：从 arXiv API 或 Crossref API 直接获取
2. **下载正确 PDF**：Python urllib 从 arXiv 直接下载
3. **删除错误 Zotero 条目**：通过 Zotero Web API DELETE（需 `If-Unmodified-Since-Version` 头）
4. **创建正确条目**：`paper_to_zotero.py --metadata-only --pdf-filename`
5. **验证**：检查标题和 DOI 匹配

## 链接 Google Drive PDF

已有 Zotero 条目时，单独创建 linked_file 附件：

```bash
uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>

# 预览
uv run python -m hydrolitagent.zotero.zot_link_gdrive --dry-run <ZOTERO_KEY> <filename>
```

使用 `attachments:` scheme，路径由 Zotero 桌面版的 **Linked Attachment Base Directory** 解析。
