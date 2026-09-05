# 自动化操作手册

## 1. 手册用途

本手册记录 `hydro-platform` 当前真正可以执行的命令、预期结果、异常处理和已完成的真实验收。它是持续维护的操作入口：以后每新增或修改一项自动化能力，都必须同步更新这里，不能只保留在聊天记录中。

当前只实现：

1. 检查 Zotero Desktop 和目标共享群组库；
2. 建立 Zotero 条目与 PDF 附件基线；
3. 检测新增父条目、新增 PDF、移除条目和替换 PDF；
4. 重复扫描时不把同一变化再次报告为新增；
5. 对指定父条目执行 PDF 全文门禁，检查唯一附件、本地文件、基础 PDF 结构、哈希和可提取文字；
6. 将全部父条目同步为本地任务清单，记录等待、阻塞或 PDF 已可交给后续处理器的状态；
7. 为 `READY_FOR_EXTRACTION` 任务创建共享证据包骨架和最小占位卡；
8. 重新核对任务、manifest 与 Zotero 当前原始 PDF，形成只读本地文件交付对象；
9. 预检 Codex CLI 是否可运行并明确使用 ChatGPT 账号登录。

当前尚未实现真实 Codex 模型调用、正式证据卡写入、Git 自动同步和每日调度。US-07A 只检查 CLI 与认证环境，不能证明订阅档位、剩余额度或制卡质量。任务领取、租约和完成保护的底层接口已经实现，但在后续制卡处理器接入前不会自行产生真实 `COMPLETED` 状态。

## 2. 运行前提

- Windows 已安装 Python，并可使用 `python` 命令；
- Zotero Desktop 正在运行；
- 当前 Zotero 私人账号能够访问共享库 `qinjiajun`；
- Zotero 已完成条目和附件同步；
- 仓库位于本机可读取的位置；本手册示例位置为 `E:\phd\hydro-platform`；
- [config.json](../config/config.json) 中的目标群组与路径配置正确。
- 执行 US-07A 时，本机还需要安装 Codex CLI，并使用计划用于制卡的 ChatGPT 账号完成登录。

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

当前使用 Zotero 的全文索引判断文字是否可提取。它能够阻止空文本和疑似扫描件进入后续环节，但该索引不会被当作正式制卡输入。US-06 的 `pdf-delivery` 会重新校验原始 PDF 哈希，并形成指向 Zotero 完整原始文件的交付对象，不额外导出一份必须保存的全文文本。

## 7. 同步任务清单

让系统扫描目标共享库、执行每篇论文的 PDF 门禁，并生成或更新任务清单：

```powershell
python automation/run.py tasks-sync --json
```

第一次对当前样本执行时，预期重点结果为：

```json
{
  "ok": true,
  "task_count": 1,
  "changed_count": 1,
  "state_counts": {
    "READY_FOR_EXTRACTION": 1
  }
}
```

在 `tasks` 数组中，应能找到父条目 `CEXH4PQA`，并看到：

- `state` 为 `READY_FOR_EXTRACTION`；
- `reason_code` 为 `PDF_READY`；
- `input.attachment_key` 为 `JNCB9BGP`；
- `input.pdf_sha256` 与 PDF 门禁结果一致；
- `task_id` 以 `TASK-` 开头；
- `history` 只有第一次状态变化记录。

立即再次运行相同命令：

```powershell
python automation/run.py tasks-sync --json
```

预期 `changed_count` 为 `0`，任务数和历史记录不会增加。这是任务清单的幂等验证。

只查看已有任务、不访问 Zotero：

```powershell
python automation/run.py tasks-list --json
```

任务文件默认位于 `.runtime/tasks.json`，进程锁默认位于 `.runtime/worker.lock`。两者都属于本机可重建状态，不进入 Git。

## 8. 同步证据包骨架

先确认 `tasks-sync` 已产生至少一个 `READY_FOR_EXTRACTION` 任务，然后运行：

```powershell
python automation/run.py packages-sync --json
```

首次成功创建时，重点结果应为：

```json
{
  "ok": true,
  "eligible_task_count": 1,
  "package_count": 1,
  "created_count": 1,
  "unchanged_count": 0
}
```

证据包写入 [evidence-packs](../evidence-packs/README.md) 配置对应的目录。单篇论文目录格式为 `EV-父条目Key-简短标题`，当前只包含：

```text
manifest.json
card.md
```

占位 `card.md` 的完整内容为：

```markdown
# 待生成证据卡

状态：PLACEHOLDER
```

立即再次运行相同命令，预期 `created_count = 0`、`unchanged_count = 1`。如果 card.md 已经被人工或后续程序填写，命令只保留它，不会覆盖。

该命令只读取 `.runtime/tasks.json`，不访问或修改 Zotero；它会修改仓库中的 `evidence-packs/` 工作区，但不会自行提交或推送 GitHub。创建骨架也不会改变任务状态，不能把它解释为全文提取或正式制卡完成。

## 9. 验证并交付 Zotero 原始 PDF

先确认 `tasks-sync` 已产生 `READY_FOR_EXTRACTION` 任务，而且 `packages-sync` 已创建对应证据包骨架。然后针对父条目运行：

```powershell
python automation/run.py pdf-delivery --item-key CEXH4PQA --json
```

将 `CEXH4PQA` 替换为需要检查的 Zotero 父条目 Key。成功结果应至少包含：

```json
{
  "ok": true,
  "delivery_status": "READY",
  "delivery_mode": "LOCAL_FILE_PATH",
  "group_id": 6618088,
  "parent_key": "CEXH4PQA",
  "attachment_key": "JNCB9BGP",
  "pdf_sha256": "115fe50efabc0130ed20d1b8465aaa861b29497ae56949677bb59863c8dbd6e6",
  "pdf_path": "Zotero 原始 PDF 的本机绝对路径"
}
```

判断成功时重点检查：

- `pdf_path` 指向 Zotero 管理的原始 PDF，而不是仓库中的复制文件；
- `attachment_key`、`task_id` 和 `pdf_sha256` 与 `.runtime/tasks.json` 及证据包 `manifest.json` 一致；
- `evidence_package_path` 指向唯一证据包；
- 命令不会修改 card.md、manifest.json 或任务状态，也不会调用 AI。

可检查仓库和运行区是否错误产生 PDF 副本：

```powershell
Get-ChildItem -Path 'evidence-packs','.runtime' -Recurse -Filter '*.pdf'
```

正常情况下不应显示任何文件。`verified_at` 每次运行会变化，但相同输入的路径、附件 Key 和 SHA-256 应保持一致。

## 10. 执行 Codex CLI 运行环境预检

这一检查与 Zotero、PDF 和证据卡模板无关，可以单独运行：

```powershell
python automation/run.py generator-preflight --json
```

成功结果应至少满足：

```json
{
  "ok": true,
  "component": "card_generator",
  "adapter": "codex_cli",
  "configured_auth_mode": "chatgpt_account",
  "detected_auth_mode": "chatgpt_account",
  "cli_version": "codex-cli 版本号",
  "resolved_executable": "实际找到的 Codex CLI 路径"
}
```

三项 `checks` 应分别确认可执行程序、版本和认证状态。该命令只在本机运行：

```text
codex --version
codex login status
```

它不会运行 `codex exec`，不会调用模型，不会读取 Zotero、PDF、任务、模板或证据包，也不会写入任何文件。输出只给出归一化结论，不回显 `codex login status` 的原始输出。

这个预检只能确认 CLI 明确报告为 ChatGPT 账号登录。它不能确认账号具体订阅档位、剩余额度或下一次模型调用一定成功；这些属于 US-07B 的受控真实调用验收。

命令返回码：

- `0`：CLI 可运行，并明确识别为 ChatGPT 账号登录；
- `2`：`config.json` 缺字段、字段类型错误，或选择了未实现的适配器/认证方式；
- `3`：CLI 缺失、无法启动、检查超时、未登录、使用 API Key，或无法确认登录方式。

US-07A 的真实验收由用户运行本节命令并保存输出；不要用一次真实模型调用替代本预检。

## 11. 查看本地快照

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

## 12. 常见问题

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

### `TASK_STORE_BUSY`

另一个任务同步或处理进程正在更新任务清单。等待其结束后重试。如果原进程已经崩溃，超过总配置中的锁过期时间后系统才会清理死锁。

### `TASK_STORE_INVALID`

本地任务文件损坏。系统会拒绝静默覆盖。先保留损坏文件并查明原因；正式恢复命令将在 US-12 实现，不要手工伪造任务状态。

### `EVIDENCE_PACKAGE_INCOMPLETE` 或 `EVIDENCE_MANIFEST_INVALID`

已有证据包缺少必要文件，或者 manifest 无法读取。系统不会把半成品当作成功，也不会自动覆盖；先保留现场并检查该目录。

### `EVIDENCE_INPUT_MISMATCH`

当前任务的附件 Key、PDF 哈希或任务 ID 与已有证据包不同。系统会停止，避免把新 PDF 静默关联到旧卡片；PDF 更换后的证据包更新策略需要在后续用户故事中处理。

### `PDF_DELIVERY_TASK_NOT_FOUND` 或 `PDF_DELIVERY_TASK_NOT_READY`

任务尚未建立，或者尚未通过 PDF 门禁。先运行 `tasks-sync --json`，根据任务中的状态和原因处理，不要手工修改 `.runtime/tasks.json`。

### `PDF_DELIVERY_PACKAGE_MISSING` 或 `PDF_DELIVERY_PACKAGE_INCOMPLETE`

任务已有可读取 PDF，但证据包骨架不存在或不完整。先运行 `packages-sync --json`；如果仍然报不完整，保留现场并检查对应证据包，不能手工伪造 manifest。

### `PDF_ATTACHMENT_CHANGED` 或 `PDF_INPUT_CHANGED`

Zotero 当前附件或 PDF 内容已经与任务和 manifest 中记录的输入不一致。系统拒绝交付，也不会覆盖已有卡片。先重新运行 `tasks-sync --json` 进行对账；已有证据包如何处理需要人工判断。

### `CODEX_CLI_NOT_FOUND` 或 `CODEX_CLI_UNAVAILABLE`

先在同一个 PowerShell 中运行 `codex --version`。如果命令不存在，安装或修复 Codex CLI；如果 Codex 位于非标准位置，把 [config.json](../config/config.json) 中的 `card_generator.executable` 改为实际命令或路径，然后重试预检。

### `CODEX_NOT_LOGGED_IN`

在制卡机上用计划用于制卡的 ChatGPT 账号完成 Codex CLI 登录，然后重新运行 `generator-preflight --json`。登录凭据由 Codex 保存在本机，不得抄入 `config.json`。

### `CODEX_AUTH_MODE_MISMATCH`

CLI 当前报告为 API Key 登录，而本阶段只允许 ChatGPT 账号认证。先在 Codex CLI 中切换到 ChatGPT 登录；不要通过把 API Key 写入仓库来绕过门禁。

### `CODEX_AUTH_MODE_UNKNOWN`

CLI 命令成功，但输出没有让程序明确识别出 ChatGPT 登录方式。先人工运行 `codex login status` 查看本机结果，并检查是否使用了不兼容的 CLI 版本；不能把“命令返回 0”直接解释为订阅登录成功。

## 13. 安全操作规则

- 不要为了重新看到 `ITEM_ADDED` 而随意删除快照；
- 不要手工编辑 `.runtime` 中的状态文件；
- `.runtime`、PDF、密钥和原始日志不得提交到 Git；
- 当前扫描成功只代表发现了 PDF 附件元数据，不代表已经读取 PDF 全文；
- `pdf-delivery` 成功只代表完整原始 PDF 已通过交付校验，不代表 Codex 已阅读或证据卡已生成；
- `generator-preflight` 成功只代表 Codex CLI 可运行且报告为 ChatGPT 账号登录，不代表已经调用模型、拥有剩余额度或完成制卡；
- 不要手工修改 manifest.json；card.md 可以在后续流程填写，但 `packages-sync` 不会覆盖非占位内容；
- 切换 Zotero 群组时不能只改 `group_id` 后删除旧快照，必须执行后续定义的群组迁移或重新建基线流程；
- 所有可调整路径和固定运行参数统一在 [config.json](../config/config.json) 修改。

## 14. 真实验收记录

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

### US-04 真实任务清单验收

在同一篇样本文献上连续执行两次 `python automation/run.py tasks-sync --json`：

| 检查项 | 实际结果 |
|---|---|
| 首次同步 | `task_count = 1`，`changed_count = 1` |
| 初始状态 | `READY_FOR_EXTRACTION / PDF_READY` |
| 记录 ID | `6618088:CEXH4PQA` |
| 任务 ID | `TASK-319b93c67deebdf073242fb902806053e90af7322f7ad98293383eaf9025be6c` |
| 输入附件 Key | `JNCB9BGP` |
| 输入 PDF SHA-256 | `115fe50efabc0130ed20d1b8465aaa861b29497ae56949677bb59863c8dbd6e6` |
| 初始领取状态 | `attempt_count = 0`，`lease = null` |
| 初始状态历史 | 只有 1 条 `null → READY_FOR_EXTRACTION` 记录 |
| 第二次同步 | `task_count = 1`，`changed_count = 0` |
| 幂等性 | 任务 ID、输入指纹、创建/更新时间和状态历史均未改变 |
| 本地状态文件 | `E:\phd\hydro-platform\.runtime\tasks.json` |

结论：US-04 的真实任务创建与重复同步幂等已经通过验收。并发领取、租约过期恢复、损坏任务清单和 PDF 更换等异常路径目前由自动化测试覆盖，尚未在真实环境中主动制造故障验收。

### US-05 真实证据包骨架验收

对 US-04 已产生的真实 `READY_FOR_EXTRACTION` 任务连续执行两次 `python automation/run.py packages-sync --json`：

| 检查项 | 实际结果 |
|---|---|
| 可处理任务 | `eligible_task_count = 1` |
| 首次同步 | `package_count = 1`，`created_count = 1`，`unchanged_count = 0` |
| 证据 ID | `EV-CEXH4PQA` |
| 首次动作 | `CREATED` |
| 占位卡状态 | `PLACEHOLDER` |
| 证据包目录 | `EV-CEXH4PQA-anthropogenic-intensification-of-short-duration-rainfall-ext` |
| manifest 来源 | 群组 `6618088`、父条目 `CEXH4PQA`、附件 `JNCB9BGP` |
| manifest PDF SHA-256 | `115fe50efabc0130ed20d1b8465aaa861b29497ae56949677bb59863c8dbd6e6` |
| manifest 来源任务 | `TASK-319b93c67deebdf073242fb902806053e90af7322f7ad98293383eaf9025be6c` |
| card.md 内容 | 只有“待生成证据卡”和 `PLACEHOLDER` 状态 |
| 第二次同步 | `created_count = 0`，`unchanged_count = 1`，动作为 `UNCHANGED` |

结论：US-05 的真实证据包首次创建、来源追溯、最小占位卡和重复同步幂等已经通过验收。半成品目录、重复目录、损坏 manifest、PDF 输入变化和非占位卡保护等异常路径目前由自动化测试覆盖，尚未在真实证据包中主动制造故障验收。

### US-06 真实原始 PDF 交付验收

用户对真实父条目 `CEXH4PQA` 执行了 `python automation/run.py pdf-delivery --item-key CEXH4PQA --json`，结果如下：

| 检查项 | 实际结果 |
|---|---|
| 交付状态 | `READY / LOCAL_FILE_PATH` |
| 群组 ID | `6618088` |
| 父条目 Key | `CEXH4PQA` |
| PDF 附件 Key | `JNCB9BGP` |
| 任务 ID | `TASK-319b93c67deebdf073242fb902806053e90af7322f7ad98293383eaf9025be6c` |
| PDF SHA-256 | `115fe50efabc0130ed20d1b8465aaa861b29497ae56949677bb59863c8dbd6e6` |
| PDF 大小 | `3,132,690` 字节 |
| 原始文件位置 | `C:\Users\Dell\Zotero\storage\JNCB9BGP\Fowler 等 - 2021 - Anthropogenic intensification of short-duration rainfall extremes.pdf` |
| 证据包 | `EV-CEXH4PQA-anthropogenic-intensification-of-short-duration-rainfall-ext` |
| 验证时间 | `2026-09-05T06:16:59.091997Z` |
| PDF 副本检查 | `evidence-packs` 与 `.runtime` 中均为 0 |
| 写入保护检查 | card.md 仍为 `PLACEHOLDER`，任务仍为 `READY_FOR_EXTRACTION` |
| 三方一致性 | 本次交付、任务清单和 manifest 的附件 Key、任务 ID、SHA-256 完全一致 |

结论：US-06 的真实原始 PDF 定位、输入指纹复核、只读交付和不复制约束已经通过验收。该结果不代表 Codex 已读取论文或证据卡已经生成。

### US-07A 真实运行环境预检

用户在真实制卡机上执行了 `python automation/run.py generator-preflight --json`，结果如下：

| 检查项 | 实际结果 |
|---|---|
| 总体结果 | `ok = true` |
| 组件 | `card_generator` |
| 适配器 | `codex_cli` |
| 配置的可执行程序 | `codex` |
| 解析后的可执行程序 | `C:\Users\Dell\AppData\Local\Programs\OpenAI\Codex\bin\codex.EXE` |
| CLI 版本 | `codex-cli 0.149.1` |
| 配置认证方式 | `chatgpt_account` |
| 检测认证方式 | `chatgpt_account` |
| 可执行程序检查 | `pass` |
| 版本检查 | `pass` |
| 认证检查 | `pass` |
| 验收时间 | `2026-09-05T06:39:38.648951Z` |

结论：US-07A 的真实运行环境正向验收已经通过。该结果证明当前制卡机能找到并运行 Codex CLI，且 CLI 明确报告为 ChatGPT 账号登录；它不证明订阅档位、剩余额度、模型调用成功或证据卡质量，后四项仍属于 US-07B。

## 15. 手册维护规则

以下变化发生时，必须在同一次修改中更新本手册：

- 新增、删除或重命名命令；
- 配置字段、目录或路径规则变化；
- 新增 PDF 门禁、任务处理、证据包、Git 同步或调度能力；
- 输出字段、状态或错误码变化；
- 恢复方式或安全边界变化；
- 完成新的真实环境验收。

更新时必须同时说明“当前已实现”“尚未实现”“如何操作”“如何判断成功”和“失败后怎么处理”，不得把规划中的能力写成已经可用。
