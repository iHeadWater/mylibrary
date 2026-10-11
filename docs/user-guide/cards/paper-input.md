# 单篇论文输入

从**你自己的 Zotero 库**里定下一篇论文，产出一份 **READY 记录**交给下一步制卡。
这一步**只读 Zotero 和本机 PDF**，不调用模型。

## 怎么用

跟 agent 说「把《某某》这篇做成卡」时，它先走的就是这一步。自己敲的话：

```bash
uv run hydrolitagent cards paper-input --user-library --query '论文题名或 DOI' --json
uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --json
```

- `--user-library` 读**你自己**的文库；读**共享群组库**把它换成 `--group-id <数字ID>`。
- 要把记录**存成文件**交给下一步：`uv run python scripts/paper_input.py … --output paper-input.json`
  —— 脚本写 UTF-8，比用 `>` 重定向可靠。
- `--item-key` 可以重复给多个：这是批处理，单篇失败不中断其余。

**前提**：Zotero 正在运行且已允许其他应用通信；该论文**已附好可读的 PDF**（这一步**不下载** PDF）。
见[前提与配置](../../getting-started/installation.md)。

## 结果

| 结果 | 含义 |
|---|---|
| `SELECTION_REQUIRED` | 搜索命中多篇 —— 需要你用 `--item-key` 指定哪一篇，它**不替你选**第一篇 |
| `READY` | 身份明确且**只有一个**可读 PDF —— 附文库、父条目、附件、PDF 路径 / 大小 / SHA-256 |
| （返回原因） | 缺 PDF / 有多个 PDF / 文件读不了 |
| `IMPORT_REQUIRED` | 只在 `--demo` 且演示论文尚未导入时 —— 附 Connector 抓取链接 |

记录里是**身份、路径和指纹**，不是论文全文，更不是主体卡。

## 边界

- 搜不到就调关键词或先在 Zotero 里导入 —— 它**不会**自动把共享库的论文抓到你的个人库。
- **Zotero 没建全文索引也能 `READY`** —— 下一步直接读 PDF。
- 群组库用户：确认自己**已加入**该群组，且群组条目与 PDF 在本机 Zotero 可用。
- `--demo` 只查内置的公开演示论文：不下载、不修改你的文库。

## 相关

→ 下一步：[从单篇 PDF 生成主体卡草稿](subject-card-draft.md)
