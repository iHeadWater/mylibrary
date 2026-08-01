# Zotero MCP

Zotero MCP 提供对 Zotero 文献库的编程访问，通过 Zotero Web API 进行读写操作，通过本地 SQLite 数据库进行快速全文检索。

## 前置条件

1. **Zotero 桌面版**：需安装并至少运行过一次，确保 `~/Zotero/zotero.sqlite` 数据库文件存在。Zotero 不需要一直运行——读操作直接读 SQLite 文件。
2. **Zotero Web API key**（写操作和远程读操作需要）：在 [zotero.org/settings/keys](https://www.zotero.org/settings/keys) 创建 key：
   - 点击 "Create New Private Key"
   - 勾选 **Allow library access** 和 **Allow notes access**
   - 记录生成的 Key 和页面顶部显示的 **User ID**（数字）

## 配置

在 `.env` 中设置（参考 `.env.example`）：

```bash
# Zotero Web API (read/write access to your library)
ZOTERO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
ZOTERO_LIBRARY_ID=1234567
ZOTERO_LIBRARY_TYPE=user
# Zotero Local API (full-text access, requires Zotero Desktop running)
ZOTERO_LOCAL_API_URL=http://host.docker.internal:23119
```

- `ZOTERO_LIBRARY_ID` 为你的 Zotero User ID（数字），在 [zotero.org/settings/keys](https://www.zotero.org/settings/keys) 页面可查
- `ZOTERO_LIBRARY_TYPE` 默认 `user`；若使用群组库则填 `group`，`ZOTERO_LIBRARY_ID` 填群组 ID
- `ZOTERO_LOCAL_API_URL` 为 Zotero Desktop 本地 API 地址（需要安装 [Zotero Bridge](https://github.com/retorquere/zotero-bridge) 插件）

## Python 依赖

项目使用 `pyzotero` 访问 Zotero Web API：

```bash
uv pip install pyzotero>=1.13.0
```

已在 `pyproject.toml` 中声明为项目依赖。

## 常用操作

### 搜索文献

```python
from pyzotero import zotero as zt
import os

z = zt.Zotero(
    os.environ["ZOTERO_LIBRARY_ID"],
    os.environ["ZOTERO_LIBRARY_TYPE"],
    os.environ["ZOTERO_API_KEY"],
)

# 搜索
items = z.top(q="transformer attention", limit=10)
for item in items:
    data = item["data"]
    print(f"{data.get('title', '?')} ({data.get('date', '?')})")
```

### 查看条目详情

```python
item = z.item("ABC123")
data = item["data"]
print(f"Type: {data['itemType']}")
print(f"Title: {data['title']}")
print(f"DOI: {data.get('DOI', 'N/A')}")
print(f"Abstract: {data.get('abstractNote', 'N/A')[:200]}...")

# 查看作者
for creator in data.get("creators", []):
    print(f"  {creator.get('firstName', '')} {creator.get('lastName', '')}")
```

### 通过 DOI 添加条目

```python
from pyzotero import zotero as zt

z = zt.Zotero(lib_id, lib_type, api_key)
# 通过 DOI 创建条目
template = z.item_template("journalArticle")
template["DOI"] = "10.1038/s41586-023-06139-9"
resp = z.create_items([template])
print(f"Created: {resp['successful']}")
```

### 查看最近添加

```python
items = z.top(limit=20, sort="dateAdded", direction="desc")
for item in items:
    data = item["data"]
    print(f"[{data.get('dateAdded', '?')[:10]}] {data.get('title', '?')[:80]}")
```

### 列出合集

```python
collections = z.collections()
for col in collections:
    data = col["data"]
    print(f"{col['key']}: {data['name']} ({data.get('meta', {}).get('numItems', 0)} items)")
```

### 更新条目

```python
item = z.item("ABC123")
item["data"]["abstractNote"] = "Updated abstract..."
item["data"]["tags"] = [{"tag": "important"}, {"tag": "hydrology"}]
z.update_item(item)
```

### 添加附件（linked_file）

```python
# 添加 linked_file 附件（文件存储在本地，Zotero 只记录路径）
import os

item_key = "ABC123"
pdf_path = os.path.expanduser("~/Documents/Papers/paper.pdf")

# 创建 linked_file attachment
attachment = z.item_template("attachment", link_mode="linked_file")
attachment["title"] = os.path.basename(pdf_path)
attachment["path"] = pdf_path
attachment["contentType"] = "application/pdf"
attachment["parentItem"] = item_key

z.create_items([attachment])
```

## 与 hydrolitagent 集成

hydrolitagent 可以通过 Zotero MCP 实现文献管理闭环：

1. **文献发现**：通过 graphifyy 的知识图谱发现相关文献
2. **文献入库**：通过 pyzotero Web API 将文献元数据写入 Zotero
3. **PDF 管理**：通过 linked_file 附件关联本地 PDF 文件
4. **全文检索**：通过 Zotero Local API 进行 PDF 全文检索

### 配置检查清单

- [ ] `.env` 中已配置 `ZOTERO_API_KEY`
- [ ] `.env` 中已配置 `ZOTERO_LIBRARY_ID`
- [ ] Zotero 桌面版已安装并运行过（生成 `zotero.sqlite`）
- [ ] （可选）Zotero Bridge 插件已安装（用于本地全文检索）

## 参考

- [pyzotero 文档](https://pyzotero.readthedocs.io/)
- [Zotero Web API 文档](https://www.zotero.org/support/dev/web_api/v3/start)
- [Zotero Bridge 插件](https://github.com/retorquere/zotero-bridge)
