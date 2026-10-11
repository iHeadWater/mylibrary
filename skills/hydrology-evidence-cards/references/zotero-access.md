# Zotero 本地读取

## 前提

- Zotero Desktop 在当前计算机运行。
- 本地 API 已启用，默认地址为 `http://127.0.0.1:23119`。
- 此 Skill 只读取条目、子附件和 Zotero 已索引全文，不修改 Zotero 条目，也不直接打开或写入 `zotero.sqlite`。

## 推荐命令

在 Skill 目录执行：

```text
python scripts/zotero_reader.py status
python scripts/zotero_reader.py search "题名、作者、DOI或关键词" --out search.json
python scripts/zotero_reader.py item ITEMKEY --out item.json
python scripts/zotero_reader.py children ITEMKEY --out children.json
python scripts/zotero_reader.py fulltext ATTACHMENTKEY --out fulltext.txt
python scripts/zotero_reader.py packet ITEMKEY --out-dir 临时目录
```

`packet` 会写题录、附件清单和可取得的 PDF 索引文本，用于一次阅读任务。临时包可能包含受版权保护全文，必须放在系统临时目录或授权工作目录，完成后删除，禁止提交 Git。

如果环境已安装官方 Zotero Skill，也可使用其 `status --json`、`search QUERY --json`、`children ITEMKEY --json`、`fulltext ATTACHMENTKEY --out FILE`；两套接口的证据边界相同。

## 消歧

搜索返回多个条目时，依次核对原题名、作者顺序、年份、DOI/ISBN/报告号、附件首页和版本。不能自动取第一条。重复条目不在本 Skill 中删除或合并。

## 全文不足

- 无 PDF：检查是否有 HTML 快照、报告附件或用户指定的授权文件。
- PDF 无索引文本：可记录 `未取得可检索全文`，并按需要读取原 PDF；不要把摘要当全文。
- `indexedPages < totalPages`：记录索引覆盖不足，关键页回看原件。
- 扫描 OCR：公式、表格、负号、小数点、上下标和页眉串入必须人工核对。
- 附件版本与题录不符：暂停结果提取，先解决版本身份。

## 非本机与可移植性

其他人安装 Skill 后仍需在自己的 Zotero Desktop 中准备条目和附件。Skill 不传输私人 Zotero 库，也不要求共享同一个数据库。团队共享的是证据卡、稳定标识和允许公开的来源链接；PDF 权限由各成员自行合法取得。

