---
name: zotero-query
description: Zotero 文献库查询。当用户提到"查文献"、"搜论文"、"Zotero"、"文献库"、"最近添加"、"找一下有没有"、"库里有没有"、"文献检索"时自动触发。使用 MCP zotero 工具完成查询。
---

# Zotero 文献查询

YOU MUST use the Zotero MCP tools. Do NOT use `zot` CLI, direct SQLite access, or REST API calls. Do NOT search for local scripts.

## Available MCP tools

| 工具 | 用途 |
|------|------|
| `zotero_search` | 关键词搜索文献库 |
| `zotero_get_item` | 获取单篇文献详情 |
| `zotero_get_recent` | 获取最近添加的文献 |
| `zotero_get_collection_items` | 获取某个合集下的文献 |
| `zotero_get_fulltext` | 获取文献全文内容（需本地 Zotero） |
| `zotero_get_file_info` | 获取文献附件信息（需本地 Zotero） |

## 示例

- 查最近文献：直接调用 `zotero_get_recent`
- 搜索关键词：直接调用 `zotero_search`，传入 query 参数
- 查特定论文：先用 `zotero_search` 找到 key，再用 `zotero_get_item` 获取详情
