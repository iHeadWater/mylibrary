# MCP Server 工具

Zotero MCP Server 通过 FastMCP SSE 传输在端口 8002 上暴露 12 个工具。消费者通过 `http://zotero-mcp:8002/mcp` 连接。

## 工具概览

### Web API 工具（10 个）

通过 pyzotero 访问 `api.zotero.org`，需要 `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID`。

| 工具 | 用途 |
|------|------|
| `zotero_search` | 关键词搜索文献库 |
| `zotero_fulltext_search` | 全字段搜索（含全文内容） |
| `zotero_search_by_tag` | 按标签搜索条目 |
| `zotero_get_item` | 获取单篇文献完整元数据 |
| `zotero_get_attachments` | 获取条目的附件和笔记 |
| `zotero_get_annotations` | 获取 PDF 标注（高亮、笔记） |
| `zotero_get_recent` | 获取最近添加的条目 |
| `zotero_get_collections` | 列出所有合集 |
| `zotero_get_collection_items` | 获取某合集下的条目 |
| `zotero_get_tags` | 列出标签（可选按合集过滤） |

### Local API 工具（2 个）

通过 httpx 访问本地 Zotero Desktop API（`host.docker.internal:23119`），需要 Zotero Desktop 运行。

| 工具 | 用途 |
|------|------|
| `zotero_get_fulltext` | 获取条目的全文索引内容 |
| `zotero_get_file_info` | 获取附件文件元数据 |

---

## Web API 工具

### `zotero_search`

关键词搜索 Zotero 文献库。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | `str` | (必需) | 搜索关键词 |
| `limit` | `int` | `10` | 返回条目上限 |

**返回格式**：

```json
{
  "total": 1,
  "query": "flood forecasting",
  "items": [
    {
      "key": "ABC12345",
      "title": "Deep Learning for Hydrology",
      "itemType": "journalArticle",
      "creators": ["Jane Smith", "John Doe"],
      "date": "2026-06-15",
      "DOI": "10.1234/test.2026",
      "abstractSnippet": "A comprehensive study...",
      "url": "https://doi.org/10.1234/test.2026"
    }
  ]
}
```

---

### `zotero_fulltext_search`

全字段搜索，使用 `qmode=everything` 一次调用搜索标题、作者、摘要和索引的 PDF 全文内容。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | `str` | (必需) | 搜索关键词 |
| `limit` | `int` | `20` | 返回条目上限 |

**返回格式**：与 `zotero_search` 相同。

---

### `zotero_search_by_tag`

按标签搜索条目。Zotero API 语义：逗号分隔 = AND，`&&` = OR。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tag` | `str` | (必需) | 标签名（支持逗号/`&&` 组合） |
| `limit` | `int` | `20` | 返回条目上限 |

**示例**：

```
zotero_search_by_tag(tag="deep learning")              # 单个标签
zotero_search_by_tag(tag="hydrology, LSTM")            # 同时有 hydrology AND LSTM
zotero_search_by_tag(tag="hydrology && LSTM")          # 有 hydrology OR LSTM
```

---

### `zotero_get_item`

获取单篇文献的完整元数据。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `item_key` | `str` | (必需) | Zotero 条目 key（如 `ABC12345`） |

**返回格式**：完整的 Zotero item JSON，包含 `data`（元数据）、`meta`（创建/修改者）、`version` 等。

---

### `zotero_get_attachments`

获取条目的子项（附件和笔记）。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `item_key` | `str` | (必需) | Zotero 条目 key |

**返回格式**：

```json
{
  "total": 2,
  "itemKey": "ABC12345",
  "attachments": [
    {
      "key": "ATTACH99",
      "data": {
        "itemType": "attachment",
        "title": "paper.pdf",
        "filename": "paper.pdf",
        "contentType": "application/pdf",
        "linkMode": "imported_file",
        "md5": "abc123",
        "size": 2048000
      }
    },
    {
      "key": "NOTE01",
      "data": {
        "itemType": "note",
        "note": "Important paper"
      }
    }
  ]
}
```

---

### `zotero_get_annotations`

获取 PDF 标注。遍历 paper → attachment → annotations 两级结构。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `item_key` | `str` | (必需) | Zotero 条目 key |

**返回格式**：

```json
{
  "total": 2,
  "itemKey": "ABC12345",
  "annotations": [
    {
      "key": "ANN0001",
      "type": "highlight",
      "text": "LSTM outperforms traditional models",
      "comment": "Key finding",
      "color": "#ffd400",
      "page": "3"
    },
    {
      "key": "ANN0002",
      "type": "note",
      "text": "",
      "comment": "Check the cited reference",
      "color": "#5fb236",
      "page": "5"
    }
  ]
}
```

---

### `zotero_get_recent`

获取最近添加的条目，按 `dateAdded` 降序排列。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | `int` | `10` | 返回条目上限 |
| `since` | `str \| None` | `None` | 仅返回此日期之后的条目（ISO 格式，如 `2026-07-01`） |

**返回格式**：与 `zotero_search` 相同（`total` + `items`）。

---

### `zotero_get_collections`

列出 Zotero 文献库中的所有合集。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | `int` | `50` | 返回合集数上限 |

**返回格式**：

```json
{
  "total": 2,
  "collections": [
    {"key": "COLA1B2C", "version": 42, "name": "Hydrology", "parentCollection": false},
    {"key": "COLD3E4F", "version": 17, "name": "Deep Learning", "parentCollection": "COLA1B2C"}
  ]
}
```

---

### `zotero_get_collection_items`

获取某合集下的所有条目。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `collection_key` | `str` | (必需) | 合集 key |
| `limit` | `int` | `20` | 返回条目上限 |

**返回格式**：`total` + `collectionKey` + `items`。

---

### `zotero_get_tags`

列出 Zotero 文献库的标签。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `collection_key` | `str \| None` | `None` | 可选，限定到某个合集 |

**返回格式**：

```json
{
  "total": 3,
  "tags": ["deep learning", "hydrology", "LSTM"]
}
```

---

## Local API 工具

以下工具需要 Zotero Desktop 正在运行，且本地 API 可访问。

### `zotero_get_fulltext`

获取条目的索引全文内容。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `item_key` | `str` | (必需) | Zotero 条目 key |

**返回格式**：

```json
{
  "content": "Abstract\n\nThis paper presents...\n\nIntroduction\n\nHydrological modeling...",
  "indexedPages": 12,
  "totalPages": 15,
  "itemKey": "ABC12345"
}
```

**错误**：如果条目未索引全文（404），返回错误 JSON。

---

### `zotero_get_file_info`

获取附件文件元数据。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `item_key` | `str` | (必需) | Zotero 条目 key |

**返回格式**：

```json
{
  "filename": "paper.pdf",
  "contentType": "application/pdf",
  "size": 2048000,
  "itemKey": "ABC12345"
}
```

对于 `linked_file` 附件，额外包含 `path` 字段（本地路径），`size` 为 `0`。

---

## 错误处理

所有工具在出错时返回统一的错误格式：

```json
{
  "error": true,
  "context": "zotero_search",
  "message": "Zotero API connection error"
}
```

未配置 API Key 时，Web API 工具返回 `"Web API client not initialized"` 错误。
