# 自动化操作手册

## 1. 手册用途

本手册记录 `hydro-platform` 当前真正可以执行的命令、预期结果、异常处理和已完成的真实验收。它是持续维护的操作入口：以后每新增或修改一项自动化能力，都必须同步更新这里，不能只保留在聊天记录中。

当前只实现：

1. 检查 Zotero Desktop 和目标共享群组库；
2. 建立 Zotero 条目与 PDF 附件基线；
3. 检测新增父条目、新增 PDF、移除条目和替换 PDF；
4. 重复扫描时不把同一变化再次报告为新增；
5. 对指定父条目执行 PDF 全文门禁，检查唯一附件、本地文件、基础 PDF 结构、哈希和可提取文字。

当前尚未实现供制卡使用的完整全文导出、任务状态机、证据包写入、AI 制卡、Git 自动同步和每日调度。

## 2. 运行前提

- Windows 已安装 Python，并可使用 `python` 命令；
- Zotero Desktop 正在运行；
- 当前 Zotero 私人账号能够访问共享库 `qinjiajun`；
- Zotero 已完成条目和附件同步；
- 仓库位于本机可读取的位置；本手册示例位置为 `E:\phd\hydro-platform`；
- [config.json](../config/config.json) 中的目标群组与路径配置正确。

## 3. 打开项目

打开 Windows PowerShell，进入仓库：

```powershell
Set-Location 'E:\phd\hydro-platform'
```

如果仓库以后移动到了其他位置，只需进入新的仓库目录。总配置中的 `paths.project_root` 当前使用相对路径，正常情况下不需要随盘符修改。

## 4. 执行 Zotero 预检

```powershell
python automation/run.py preflight --json
```

成功结果应满足：

- `ok` 为 `true`；
- `group_id` 为 `6618088`；
- `group_name` 为 `qinjiajun`；
- 四项 `checks` 均为 `pass`。

`item_count` 表示 Zotero 顶层论文条目数量，不包含子级 PDF 附件。因此，一篇论文加一个 PDF 时，`item_count` 可以是 `1`，这不是附件遗漏。

预检只读取状态，不修改 Zotero、快照或 GitHub。

## 5. 执行变化扫描

```powershell
python automation/run.py scan --json
```

### 5.1 结果字段

| 字段 | 含义 |
|---|---|
| `mode` | `baseline` 表示首次建立基线；`incremental` 表示与已有快照比较 |
| `counts.all_items` | 扫描到的全部 Zotero 记录，包括父条目和附件 |
| `counts.parents` | 顶层论文父条目数量 |
| `counts.pdf_attachments` | 被识别为 PDF 的附件数量 |
| `change_count` | 与上一次快照相比的变化数量 |
| `changes` | 具体变化事件 |
| `state_path` | 本次读取和更新的本地快照位置 |

当前变化类型：

| 类型 | 含义 |
|---|---|
| `ITEM_ADDED` | 新增论文父条目 |
| `ITEM_REMOVED` | 父条目从共享库中移除 |
| `PDF_ADDED` | 新增 PDF 附件 |
| `PDF_REMOVED` | PDF 附件被移除 |
| `PDF_ATTACHMENT_CHANGED` | 同一附件的版本或元数据发生变化 |

### 5.2 首次运行

如果本机不存在快照，扫描结果为：

```json
{
  "ok": true,
  "mode": "baseline",
  "change_count": 0,
  "changes": []
}
```

首次运行只建立基线。即使共享库已经有论文，也不会把所有历史论文记录成当天新增。

### 5.3 新增论文后的运行

如果基线建立后新增了一篇带 PDF 的论文，正常结果应同时出现：

- 一条 `ITEM_ADDED`；
- 一条 `PDF_ADDED`；
- `PDF_ADDED.parent_key` 等于对应 `ITEM_ADDED.item_key`。

### 5.4 重复运行验证

首次检测到变化后，立即再次执行：

```powershell
python automation/run.py scan --json
```

如果 Zotero 没有再次变化，应得到：

```json
{
  "ok": true,
  "mode": "incremental",
  "change_count": 0,
  "changes": []
}
```

这表示同一条目没有被重复报告为新增。

## 6. 执行 PDF 全文门禁

门禁按父条目 Key 检查单篇论文：

```powershell
python automation/run.py pdf-gate --item-key CEXH4PQA --json
```

将 `CEXH4PQA` 替换为扫描结果中的 `ITEM_ADDED.item_key`。该命令只读 Zotero 和本地 PDF，不修改 Zotero、不生成证据包，也不更新扫描快照。

### 6.1 门禁状态

| `gate_status` | 含义 | 是否可以进入后续制卡 |
|---|---|---|
| `READY` | 本地 PDF 和足量可提取文字均可用 | 可以 |
| `WAITING` | 缺 PDF、附件文件尚未同步或 Zotero 尚未提供全文索引 | 暂时不可以，后续重试 |
| `BLOCKED` | 多个 PDF、文件损坏、文件过小或文字不可提取 | 不可以，需要人工处理 |

关键 `reason_code`：

| 原因码 | 含义 |
|---|---|
| `PDF_READY` | 门禁通过 |
| `PDF_MISSING` | 父条目没有 PDF |
| `PDF_FILE_NOT_SYNCED` | Zotero 有附件记录，但本机没有对应文件 |
| `FULLTEXT_NOT_INDEXED` | 本地文件存在，但 Zotero 尚未提供全文索引 |
| `MULTIPLE_PDFS` | 同一父条目有多个 PDF，系统拒绝猜测主文 |
| `PDF_FILE_TOO_SMALL` | 文件小于总配置规定的最小体积 |
| `PDF_STRUCTURE_INVALID` | 缺少 PDF 文件头或结束标记 |
| `TEXT_NOT_EXTRACTABLE` | 可提取文字不足，可能是扫描件或索引异常；第一版不 OCR |

门禁通过时还会输出：

- PDF 附件 Key 和父条目 Key；
- 文件名、文件大小和 SHA-256；
- 去除空白后可提取的文字数量。

当前使用 Zotero 的全文索引判断文字是否可提取。它能够阻止空文本和疑似扫描件进入后续环节，但正式制卡前仍需在 US-06 中实现可追溯的完整全文导出。

## 7. 查看本地快照

快照默认保存在：

```text
E:\phd\hydro-platform\.runtime\zotero-snapshot.json
```

在 PowerShell 中查看内容：

```powershell
Get-Content -LiteralPath '.runtime\zotero-snapshot.json' -Raw
```

或者使用记事本打开：

```powershell
notepad '.runtime\zotero-snapshot.json'
```

不要把文件路径直接输入 PowerShell。直接输入路径会被当作命令执行，也不要手工修改快照内容。

## 8. 常见问题

### `python` 命令不存在

尝试：

```powershell
py automation/run.py preflight --json
```

如果 `python` 和 `py` 都不存在，需要先安装项目指定版本的 Python；自动安装脚本尚未实现。

### `ZOTERO_NOT_RUNNING`

打开 Zotero Desktop，等待界面加载完成后重试。

### `LOCAL_API_UNAVAILABLE`

确认 Zotero 正在运行，并检查 [config.json](../config/config.json) 中的 `zotero.base_url`。当前默认接口为 `http://127.0.0.1:23119`。

### `GROUP_NOT_AVAILABLE`

确认当前 Zotero 账号已经加入并同步 `qinjiajun`，同时检查 `zotero.group_id` 是否为 `6618088`。

### 只出现 `ITEM_ADDED`，没有 `PDF_ADDED`

系统发现了论文父条目，但没有发现其 PDF。检查 PDF 是否作为该父条目的子附件存入共享库，并等待 Zotero 完成附件同步。

### 扫描结果为零变化

依次检查：

1. 论文是否放进 `qinjiajun`，而不是个人“我的文库”；
2. 当前扫描前是否已经执行过一次扫描并更新了快照；
3. Zotero 是否完成同步；
4. `counts` 是否已经包含该论文和 PDF。

### PDF 门禁返回 `FULLTEXT_NOT_INDEXED`

等待 Zotero 完成附件同步和全文索引后，再运行同一条 `pdf-gate` 命令。不要因此删除扫描快照。

### PDF 门禁返回 `TEXT_NOT_EXTRACTABLE`

先在 Zotero 中确认 PDF 是否能搜索和复制正文。如果是扫描件，第一版不会自动 OCR；如果是正常文本 PDF，可能需要重新建立 Zotero 全文索引后再试。

## 9. 安全操作规则

- 不要为了重新看到 `ITEM_ADDED` 而随意删除快照；
- 不要手工编辑 `.runtime` 中的状态文件；
- `.runtime`、PDF、密钥和原始日志不得提交到 Git；
- 当前扫描成功只代表发现了 PDF 附件元数据，不代表已经读取 PDF 全文；
- 切换 Zotero 群组时不能只改 `group_id` 后删除旧快照，必须执行后续定义的群组迁移或重新建基线流程；
- 所有可调整路径和固定运行参数统一在 [config.json](../config/config.json) 修改。

## 10. 已完成的真实验收

共享库：`qinjiajun`（群组 ID `6618088`）

样本文献：`Anthropogenic intensification of short-duration rainfall extremes`

| 检查项 | 实际结果 |
|---|---|
| 父条目 Key | `CEXH4PQA` |
| PDF 附件 Key | `JNCB9BGP` |
| 父条目数量 | 1 |
| PDF 附件数量 | 1 |
| 第一次增量扫描 | 产生 1 条 `ITEM_ADDED` 和 1 条 `PDF_ADDED` |
| 父子关联 | `JNCB9BGP.parent_key = CEXH4PQA` |
| 第二次扫描 | `change_count = 0`，没有重复事件 |
| PDF 门禁 | `READY / PDF_READY` |
| 本地 PDF 大小 | 3,132,690 字节 |
| PDF SHA-256 | `115fe50efabc0130ed20d1b8465aaa861b29497ae56949677bb59863c8dbd6e6` |
| 可提取非空白字符 | 91,497 |

结论：US-02 的“真实新增父条目、真实新增 PDF、父子关联和重复扫描幂等”已用一篇真实文献通过验收；US-03 的正常文本 PDF 正向门禁已通过真实验证。替换 PDF、后补 PDF、移除条目以及门禁负面场景目前只有自动化测试覆盖，尚未进行真实 Zotero 操作验收。

## 11. 手册维护规则

以下变化发生时，必须在同一次修改中更新本手册：

- 新增、删除或重命名命令；
- 配置字段、目录或路径规则变化；
- 新增 PDF 门禁、任务处理、证据包、Git 同步或调度能力；
- 输出字段、状态或错误码变化；
- 恢复方式或安全边界变化；
- 完成新的真实环境验收。

更新时必须同时说明“当前已实现”“尚未实现”“如何操作”“如何判断成功”和“失败后怎么处理”，不得把规划中的能力写成已经可用。
