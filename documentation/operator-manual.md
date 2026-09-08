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
9. 预检 Codex CLI 是否可运行并明确使用 ChatGPT 账号登录；
10. 执行一次不带论文和模板、不会写文件的最小模型调用；
11. 由单 Agent 读取完整 PDF、自动选型、按模板生成详细粗卡并区分原文与 AI 推理；
12. 通过 Python 质量门后原子写入粗卡、manifest 和质量审计；
13. 对已有卡执行不覆盖正式文件的多 Agent 试运行。

US-07B1 和模板接入已有真实验收。历史单调用卡质量未达目标，六角色试运行又出现耗时和末阶段失败；2026-09-08 经用户确认改为单 Agent 详细粗卡。当前新实现已做离线测试，尚未代跑真实制卡。每日调度与 Git 自动同步尚未实现。

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

这一检查不读取 Zotero 或 PDF，但会同时核对 Codex 和当前配置的本机 PDF 读取依赖，可以单独运行：

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
  "resolved_executable": "实际找到的 Codex CLI 路径",
  "pdf_reader": {
    "adapter": "local_path",
    "resolved_tools": { "pdfinfo": "工具路径", "pdftoppm": "工具路径", "shell": "PowerShell 路径", "python": "Python 路径" }
  }
}
```

`checks` 确认 Codex 可执行程序、版本和认证状态；`pdf_reader` 给出本机工具位置，`workflow_mode=single_agent` 标明当前模式，不再检查六角色资产。当前 `local_path` 不检查或启动 MCP 脚本；采用 pypdf 时不依赖 pdftotext。该命令只把下面两条 Codex 命令作为子进程运行：

```text
codex --version
codex login status
```

它不会运行 `codex exec`，不会调用模型，不会读取 Zotero、PDF、任务、模板或证据包，也不会写入任何文件。它会读取共用读取提示词和角色提示词/schema，PDF 依赖只做路径定位，不打开论文。输出不回显 `codex login status` 的原始输出。

这个预检只能确认 CLI 明确报告为 ChatGPT 账号登录。它不能确认账号具体订阅档位、剩余额度或下一次模型调用一定成功；这些属于 US-07B1 的受控真实调用验收。

命令返回码：

- `0`：CLI 可运行、明确识别为 ChatGPT 账号登录，且当前读取依赖可定位；
- `2`：`config.json` 缺字段、字段类型错误，或选择了未实现的适配器/认证方式；
- `3`：CLI 或 PDF 读取依赖缺失、无法启动、检查超时、未登录、使用 API Key，或无法确认登录方式。

US-07A 的真实验收由用户运行本节命令并保存输出；不要用一次真实模型调用替代本预检。

## 11. 执行无论文的最小模型调用

该命令会真实调用一次 Codex 模型并消耗少量账号用量，但不会提供论文、模板或任务数据：

```powershell
python automation/run.py generator-smoke-test --json
```

成功结果应至少满足：

```json
{
  "ok": true,
  "component": "card_generator",
  "operation": "smoke_test",
  "configured_model": null,
  "model_source": "codex_default",
  "configured_reasoning_effort": null,
  "reasoning_effort_source": "model_default",
  "probe_version": "codex-cli-smoke-v1",
  "isolated_workspace": true,
  "sandbox": "read-only",
  "ephemeral": true,
  "model_invoked": true,
  "unexpected_item_types": [],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0
  }
}
```

上例中的 token 数只是字段示意，以实际结果为准。成功时，`checks` 还应满足：

- 可执行程序、版本和认证检查均为 `pass`；
- `model_invocation` 为 `pass`；
- `expected_response` 为 `pass`。

程序实际调用固定版本探针，要求模型只返回 `HYDRO_GENERATOR_OK`。命令强制启用：

- `--json`：以 JSONL 事件读取结果；
- `--ephemeral`：不保存会话 rollout 文件；
- `--sandbox read-only`：模型生成的命令没有写权限；
- `--ignore-user-config`：不加载用户配置或 MCP；
- `--ignore-rules`：不加载用户和项目执行策略规则；
- `--skip-git-repo-check`：允许探针在隔离的空临时目录中运行；
- `--color never`：避免终端颜色码污染机器解析。

程序会在系统临时位置创建一个空目录作为探针工作区，并在调用结束后删除；项目仓库不是模型工作目录。同时，程序会拒绝包含命令执行、文件修改、MCP 调用或联网搜索事件的结果。它不会把模型最终文本、stderr 原文或线程 ID 写入仓库、任务或证据包。

`config.json` 中：

- `card_generator.model = null` 表示使用 Codex 内置默认模型；
- 填写非空模型名时，程序通过 `--model` 显式使用该模型；
- `card_generator.reasoning_effort = null` 表示使用模型默认推理强度；
- 可显式填写 `none`、`minimal`、`low`、`medium`、`high`、`xhigh` 或 `max`，程序通过 `--config model_reasoning_effort="..."` 传给 Codex CLI；具体模型可能只支持其中一部分；
- `smoke_test_timeout_seconds` 控制这次调用的最长等待时间，当前为 120 秒。

例如要测试 GPT-5.6 Sol 的高推理强度，把两项改为：

```json
"model": "gpt-5.6-sol",
"reasoning_effort": "high"
```

要测试 GPT-5.5 的模型默认推理强度，则使用：

```json
"model": "gpt-5.5",
"reasoning_effort": null
```

返回码仍为 `0` 成功、`2` 配置错误、`3` 调用或协议失败。不要连续重复运行探针；真实验收仅返回固定标记仍消耗了 16,324 个输入 token，一次成功已经足以验证当前调用链。本命令不得加入每日调度，只在安装、重新登录、CLI 升级、模型或推理强度改变后受控执行。

## 12. 校验证据卡模板

模板接入或修改后运行：

```powershell
python automation/run.py evidence-templates-validate --json
```

成功时至少应看到：

```json
{
  "ok": true,
  "component": "evidence_templates",
  "catalog_version": "1.0.0",
  "template_count": 8,
  "enabled_count": 8
}
```

这表示八个模板的来源、版本、路径、front matter 和内容哈希一致。它不表示 Codex 已完成论文分类，也不表示模板的科研内容质量已经通过真实论文验收。

该命令只读取 `config.json` 指定的模板目录和 `_catalog.json`，不访问 Zotero、不调用 Codex、不读取 PDF，也不修改现有证据包。常见错误：

- `EVIDENCE_TEMPLATE_CATALOG_NOT_FOUND`：总配置指向的 `_catalog.json` 不存在；
- `EVIDENCE_TEMPLATE_CATALOG_INVALID`：清单 JSON、版本、来源或启用状态不合法；
- `EVIDENCE_TEMPLATE_NOT_FOUND`：清单声明的 Markdown 文件缺失；
- `EVIDENCE_TEMPLATE_PATH_INVALID`：模板或清单离开了配置允许的目录；
- `EVIDENCE_TEMPLATE_DUPLICATE`：模板 ID 或模板文件重复；
- `EVIDENCE_TEMPLATE_HASH_MISMATCH`：模板正文被修改，但本地版本和内容哈希没有同步维护；
- `EVIDENCE_TEMPLATE_INVALID`：模板 front matter 缺少平台必填字段，或字段与清单不一致。

不要通过删除清单字段或放宽校验来绕过失败。修改模板时，应同时提升模板版本并更新清单中的内容哈希。

## 13. 为一篇论文生成粗证据卡

2026-09-08 起，默认改为“单 Agent、模板驱动、详细粗卡”，不再运行六个角色。详细规则、字段说明及故障处理见 [单 Agent 制卡说明](single-agent-rough-card.md)。

### 当前样本的操作

CEXH4PQA 已有正式卡，因此只试运行，不覆盖：

```powershell
Set-Location 'E:\phd\hydro-platform'
python automation/run.py evidence-generate-trial --item-key CEXH4PQA --json
```

成功返回 action=VALIDATED_TRIAL_SAVED、quality_status=STRUCTURE_VALIDATED；quality_report 中 protocol_version=rough-card-single-agent-v1、completed_role_count=1。trial_path/card_path 指向新结果，正式卡、manifest 和任务均不改变。

只有未生成的占位卡使用 evidence-generate 命令和实际父条目 Key。成功后任务进入 COMPLETED，已有非占位卡直接跳过，不调用模型。

### 内容和进度

一个会话自行读取全部 PDF 文字和页面图像、自动选型、详细填模板并自检；Python 检查来源身份、归因格式及模板结构。不摘句、不设置最低事实/批评条数、不安排人工核验。原文陈述/转述、AI 推理及信息边界分开。

stderr 显示 [1/1 全文阅读与详细制卡]、实际事件和等待心跳；stdout 保留最终 JSON。--no-progress 可关闭进度。心跳不是进度百分比或远端模型存活证明。

config/config.json 中 workflow_mode=single_agent；模型仍为 gpt-5.6-sol / high。generation_timeout_seconds 直接控制单会话，当前为 1200 秒，保留此前单会话 20 分钟上限；不是预计用时。reconnect_stop_enabled=false 保持不变，idle_timeout_seconds=1200。路径方式不统计旧 MCP 调用预算，失败不会自动重开一次模型会话。

### 输出保全和结果边界

模型最后回复先保存在 paths.runtime_dir/generation-drafts，状态 UNVALIDATED_MODEL_OUTPUT，不是正式证据、不供主题读取。临时目录清理失败只给 SCRATCH_CLEANUP_FAILED 警告，继续校验及保存，不修复 ACL 或清理历史残留。真正 I/O 错误保留 stage、exception_type、errno/winerror。输出校验失败尽可能给出 diagnostic.draft_path。

保存规则已放宽：保留模板必需的二级章节名称，允许多加小节和图表、调整顺序及普通表格布局。结构差异写在 structure_validation.notes 中，PASS_WITH_NOTES 仍然正常保存，不安排人工审批；缺失主要章节会返回具体 missing_sections，空内容、来源不匹配、归因格式错误仍被拦截。不需要手工修改总配置启用此规则。

若模型已完成却在保存校验处失败，先使用返回的 draft_path 导出已有草稿，不必重跑模型。本次草稿示例：

```powershell
Set-Location 'E:\phd\hydro-platform'
python automation/run.py evidence-draft-export --draft '.runtime\generation-drafts\f8c465a19fed4b6fa696526163567a30.json' --json
```

该命令不调用 Zotero、Codex 或 PDF 工具。成功返回 RECOVERED_DRAFT_EXPORTED；card_path 是原样 Markdown，export_report_path 记录当前结构检查及来源。位置为 paths.card_trials_dir/recovered/ 下的新目录，默认 .runtime/card-trials/recovered/。原草稿、正式卡、manifest 和任务不变。草稿缺少完整执行审计，因此只导出预览，不补造已完成的生产验收，也不会自动发布。网络失败没有产出完整内容时无法用此命令恢复。

SINGLE_CARD_CONTRACT_FAILED 表示归因格式、引用 C 编号或人工核验交办语句不合约。正式任务进入 QUALITY_FAILED，修正原因后才显式 --retry-quality-failed；这属于运维故障处理，不是逐卡科研人工审批。

quality-audit.json 沿用文件名，但实际是单会话生成记录；independent_review、scientific_correctness_verified 固定 false。source_access.full_read_verified 和 visual_understanding_verified 也为 false。结构通过不是独立科学验证。本次未替用户运行新方案；真实耗时与卡片质量尚待确认。

## 14. 查看本地快照

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

## 15. 常见问题

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

### `CODEX_SMOKE_TIMEOUT`

最小模型调用超过 `card_generator.smoke_test_timeout_seconds`。先检查网络和 Codex 服务状态；可以合理增大总配置中的超时，但不要立即循环重试。

### `CODEX_RATE_LIMITED` 或 `CODEX_USAGE_LIMIT`

当前调用受到速率限制或账号没有可用调用额度。保留错误码并稍后人工重试；US-07B1 不会自动重试，也不会因此修改任务或证据包。

### `CODEX_MODEL_UNAVAILABLE`

`card_generator.model` 指定的模型当前不可用。将其改为账号可用的明确模型，或设为 `null` 使用 Codex 内置默认，然后只重试一次。

### `CODEX_REASONING_EFFORT_UNAVAILABLE`

`card_generator.reasoning_effort` 的拼写虽然有效，但当前所选模型不支持这个推理强度。先查询该模型支持的档位，修改模型或推理强度后只重试一次；不要静默降级，因为这会让实际运行参数与配置记录不一致。

### `CODEX_EXEC_PROTOCOL_ERROR` 或 `CODEX_SMOKE_OUTPUT_INVALID`

CLI 没有返回有效 JSONL 完成事件，或者模型没有严格返回固定标记。不要把这种结果算作成功；先核对 Codex CLI 版本和配置，再检查适配器兼容性。

### `CODEX_OUTPUT_SCHEMA_INVALID`

Codex 或模型拒绝了制卡结构化输出 schema。先确认当前项目中的 `automation/schemas/card-generation-output.schema.json` 使用最小兼容结构，再核对 Codex CLI 与模型是否支持 `--output-schema`；不要通过取消 Python 的结果校验来绕过。

### `CODEX_CONTEXT_LIMIT`

提示词、模板和全文读取结果超过当前模型上下文限制。不要直接放宽输出校验；先统计实际输入规模，再决定是否需要受控分段读取。

### `CODEX_SERVICE_UNAVAILABLE`

服务端流或网络连接在生成过程中中断。原占位卡保持不变；确认账号未触发额度限制后再受控重试一次，不得进入自动循环重试。

### `CODEX_EXEC_PERMISSION_DENIED`

Codex 在读取 Zotero PDF 或运行只读解析命令时受到权限或沙箱限制。先检查 `diagnostic.summary` 和 PDF 本机权限，不要直接改成可写沙箱。

### `CODEX_PDF_NOT_ACCESSED`

当前 `local_path` 下表示没有本机读取/处理命令事件，或来源记录不符合协议；只返回“已阅读”不会通过。若使用旧 `project_mcp` 配置，则表示缺少读取回执。正式命令保留占位卡并进入 `RETRY_PENDING`；试运行不改变原任务。不要为排障删除卡片或任务。

### `CODEX_PDF_NOT_FULLY_ACCESSED`、`CODEX_PDF_VISUALS_NOT_ACCESSED` 或 `CODEX_PDF_PAGE_COUNT_MISMATCH`

前两类是旧 MCP 路径的漏页/图像交付错误。当前 `local_path` 下，模型未声明完整读取时返回 `PDF_DIRECT_READING_INCOMPLETE`，页数不符返回 `CODEX_PDF_PAGE_COUNT_MISMATCH`；本机预检失败返回 `PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED`，该角色尚未调用模型。检查总配置的解释器/工具路径和报告，不伪造完成状态，也不自动切回旧读取器。

### `CODEX_PDF_READ_UNVERIFIED` 或 `CODEX_PDF_VISUALS_UNVERIFIED`

Codex 未能确认已经遍历完整 PDF、返回有效页数，或未能检查论文中的图、表和公式。系统不会降级为只看纯文本的卡片。先确认本机 PDF 工具或 MCP 能读取原文件及视觉内容，再受控重试一次。

### `CODEX_SMOKE_UNEXPECTED_ACTIVITY`

探针过程中出现了命令、文件、MCP 或联网搜索活动。系统会拒绝结果，即使模型最终返回固定标记也不通过。保留现场，不要通过放宽沙箱来绕过。

### `CODEX_GENERATION_TIMEOUT`、`CODEX_RATE_LIMITED` 或 `CODEX_USAGE_LIMIT`

真实制卡超时、被限流或订阅额度不足。系统不会写入半张卡，任务进入 `RETRY_PENDING`。不要立即循环重试；先检查账号状态、额度和 `card_generator.generation_timeout_seconds`。

### `CARD_GENERATION_TEMPLATE_INVALID` 或 `CARD_GENERATION_STRUCTURE_INVALID`

模型返回了非法/未启用模板，或者没有完整保留所选模板的标题层级和表格结构。系统拒绝写卡。不要静默套用默认模板，也不要放宽结构校验；先保留输出错误码并检查提示词、模板或模型配置。

### `CARD_GENERATION_PLACEHOLDER_REMAINED`

模型输出仍有模板占位符或“待填写”等未完成内容。系统会保留原占位卡并进入 `RETRY_PENDING`。缺失信息必须改用受控值，而不是让半成品进入共享证据库。

### `CARD_QUALITY_CONTRACT_FAILED`、`CARD_QUALITY_UNVERIFIED` 或 `CARD_QUALITY_FAILED`

当前检查工作流记录、来源身份、模板及归因格式；旧六角色相关错误仅用于历史兼容。SINGLE_CARD_CONTRACT_FAILED 和 CARD_QUALITY_* 进入 QUALITY_FAILED，不自动重跑。先修正失败原因，再显式 --retry-quality-failed；不要求人工逐条科研核卡。

### `EVIDENCE_CARD_ALREADY_EXISTS`

模型调用期间 card.md 已被其他过程或人工修改。系统在最终写入前再次检查并拒绝覆盖。保留现有卡片，先确认其来源和有效性。

## 16. 安全操作规则

- 不要为了重新看到 `ITEM_ADDED` 而随意删除快照；
- 不要手工编辑 `.runtime` 中的状态文件；
- `.runtime`、PDF、密钥和原始日志不得提交到 Git；
- 当前扫描成功只代表发现了 PDF 附件元数据，不代表已经读取 PDF 全文；
- `pdf-delivery` 成功只代表完整原始 PDF 已通过交付校验，不代表 Codex 已阅读或证据卡已生成；
- `generator-preflight` 成功代表 Codex CLI、ChatGPT 登录、当前本机 PDF 工具及角色资产可定位；不代表已经调用模型、拥有剩余额度或完成制卡；
- `generator-smoke-test` 成功只代表当前时刻最小模型调用链可用，不代表模型读过论文、正式制卡可用或科研质量合格；
- `evidence-templates-validate` 成功只代表模板结构和版本完整，不代表论文类型判断或制卡质量合格；
- evidence-generate 成功仅代表当前单 Agent 的来源/归因/模板及写入协议通过；不代表独立科学验证或最终主题已达标；
- 不要为了让探针通过而改成 `workspace-write` 或 `danger-full-access`，也不要连续运行消耗额度；
- 不要手工修改 manifest.json；card.md 可以在后续流程填写，但 `packages-sync` 不会覆盖非占位内容；
- 切换 Zotero 群组时不能只改 `group_id` 后删除旧快照，必须执行后续定义的群组迁移或重新建基线流程；
- 所有可调整路径和固定运行参数统一在 [config.json](../config/config.json) 修改。

## 17. 真实验收记录

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

结论：US-07A 的真实运行环境正向验收已经通过。该结果证明当前制卡机能找到并运行 Codex CLI，且 CLI 明确报告为 ChatGPT 账号登录；它不证明模型调用成功或证据卡质量，分别由 US-07B1 和 US-07B3 验收。

### US-07B1 最小模型调用（已通过）

| 项目 | 真实结果 |
|---|---|
| 适配器 | `codex_cli` |
| CLI 版本 | `codex-cli 0.149.1` |
| 认证方式 | 配置和检测均为 `chatgpt_account` |
| 配置模型 | `gpt-5.6-sol`，来源为 `configured` |
| 配置推理强度 | `low`，来源为 `configured` |
| 探针版本 | `codex-cli-smoke-v1` |
| 隔离与权限 | 空临时工作区、`read-only`、`ephemeral` |
| 模型调用 | 已执行并通过 |
| 非预期工具活动 | 无 |
| 输入 token | 16,324，其中缓存输入 10,880 |
| 输出 token | 10 |
| 推理输出 token | 0 |
| 五项检查 | 全部 `pass` |
| 验收时间 | `2026-09-06T08:07:37.982713Z` |

结论：US-07B1 真实正向验收完成，证明当前制卡机能够通过 Python 使用 ChatGPT 账号非交互调用指定的 `gpt-5.6-sol / low`，并按固定协议返回结果。它不证明模型能正确读取论文或生成合格证据卡；当前内容质量验收属于 US-07B4。

### US-07B2 模板静态验收

运行：

```powershell
python automation/run.py evidence-templates-validate --json
```

真实结果为 `ok = true`、`template_count = 8`、`enabled_count = 8`、`catalog_version = 1.0.0`，来源提交为 `457d5a420959f543773fc0a5c955cc64b1ca0ecb`。结论：八个模板的来源、版本、路径、front matter 和内容哈希已在真实项目配置上通过；这不等于模板科研质量或自动分类已经通过。

### US-07B3 单调用真实验收（历史基线）

样本文献曾成功生成 `ROUGH` 卡并进入 `COMPLETED`，证明订阅账号、PDF MCP 和安全写入链路可运行。但用户评定卡片质量一般，因此该结果不能作为当前产品验收通过，单调用方案已被替代。

### US-07B4 六角色真实论文验收（历史方案，已停止作为默认）

使用同一篇样本文献运行：

```powershell
python automation/run.py evidence-generate-trial --item-key CEXH4PQA --json
```

历史记录：2026-09-08 用户运行至 49:43，在第六阶段 adversarial_reviewer 报 PDF_DIRECT_EXEC_IO_ERROR；未形成成功的新产物。默认方案现已改为单 Agent，后续不再按六角色验收要求执行。新的质量和时间验证以第 13 节为准，不覆盖历史卡。

## 18. 手册维护规则

以下变化发生时，必须在同一次修改中更新本手册：

- 新增、删除或重命名命令；
- 配置字段、目录或路径规则变化；
- 新增 PDF 门禁、任务处理、证据包、Git 同步或调度能力；
- 输出字段、状态或错误码变化；
- 恢复方式或安全边界变化；
- 完成新的真实环境验收。

更新时必须同时说明“当前已实现”“尚未实现”“如何操作”“如何判断成功”和“失败后怎么处理”，不得把规划中的能力写成已经可用。

## 19. PDF 路径直读实验（独立入口）

### 目的与当前状态

验证“告诉 Codex 原始 PDF 的位置，让它自己使用本机工具读全文和看图”是否可行。绕开自建 `hydro_pdf_reader` MCP 和旧整篇读取次数保护，但不绕过 Codex 本身的权限规则。

2026-09-08 用户真实执行 `pdf-direct-read-v2` 返回 `READING_REPORT_ACCEPTED`，报告声明 16 页文字与图像阅读完成，并给出 6 幅图的观察；原始 PDF 不变。报告目录为 `.runtime/card-trials/pdf-direct-read/CEXH4PQA-51d25e8e797e48f9a781c68f2f5b8811/`。此前摘录失败报告保留，不追改。此命令仍只做独立读取实验，不生成卡片；经用户确认，相同读取方式已用于当前单 Agent 制卡入口，新卡效果尚待真实运行验证。没有修改网络、代理或 Codex 自身的重连策略。

### 如何操作

保持 Zotero 开启且目标 PDF 已同步，使用已完成 PDF 交付的样本文献：

```powershell
Set-Location 'E:\phd\hydro-platform'
python automation/run.py pdf-direct-read-trial --item-key CEXH4PQA --json
```

程序复用现有的任务、证据包和 PDF 指纹检查，允许试读已完成或质量失败的任务。不要为了试读删除已有卡片或任务。

流程为：复核 Zotero PDF 路径和指纹 → 检查 CLI 账号和工具 → 在 Windows 沙箱中实际启动 PowerShell/Python、读取 PDF、提取首页文字、渲染首页 → 通过后才启动一个全新 Codex 模型会话 → Codex 自主提取文字、渲染并查看页面 → Python 检查报告结构及模型声明是否完整 → 保存实验报告。

只检查本机、不调用模型：

```powershell
python automation/run.py pdf-direct-read-trial --item-key CEXH4PQA --preflight-only --json
```

此命令通过时是 `validation_status=SANDBOX_PREFLIGHT_PASSED`、`model_invoked=false`。正常直读命令会自动先做相同检查，无需每次手动运行两条命令。

不要求模型摘录固定页原文，不返回摘录字段，也不做摘录长度或逐字匹配检查。这里只取消读取实验的额外摘句任务，不取消正式多 Agent 制卡中的科研事实复核。Python 不把全文提前塞进提示词，但 Codex 自主读取时仍需把文字或页面图像提供给模型，因此仍会消耗订阅额度。这不是把 PDF 路径变成上传附件，也不是承诺无需任何底层 PDF 工具。

### 权限与文件

使用 `workspace-write` 沙箱，工作目录是本次独立临时目录，供模型保存提取文字或页面图片；不把 Zotero 或证据包目录加入可写根。关闭用户配置加载、应用/插件、多 Agent 和工具网络访问，保留本机 shell 与图片查看能力；显式传入总配置的 `windows_sandbox`，保留 private desktop；不使用 `--ignore-rules` 或无限制权限。原生沙箱模式遵循 [OpenAI Windows 沙箱说明](https://learn.chatgpt.com/docs/windows/windows-sandbox)。

本机预检使用当前 Windows CLI 的 `codex sandbox -P :workspace` 和相同原生沙箱模式，包含管理员配置，执行固定受控的检查代码，不启动模型。它验证操作系统沙箱和本机 PDF 工具，不覆盖模型侧工具路由、工具参数或 execpolicy 全链路，因此不能把本机通过当作 AI 阅读成功。遇到实际策略拒绝时记录并停止，不绕过规则。

正常结束、超时或受控失败后会清理本次临时目录；机器断电等强制中断可能留下目录。结果默认保存在：

```text
.runtime/card-trials/pdf-direct-read/<父条目Key>-<本次唯一ID>/
├─ result.json        Python 核对结果、模型用量和安全诊断
└─ model-report.json  模型的图表观察、读取声明和限制（有有效报告时）
```

实际根目录由 `paths.card_trials_dir` 决定，JSON 会返回准确路径。新报告不设原文摘录字段，不保存原始终端命令/工具输出；默认 `.runtime` 已被 Git 忽略。每次新建报告目录，不覆盖前次结果。原始 PDF 在结束时再次核对 SHA-256。

### 配置和进度

在 `config/config.json` 修改：

| 配置项 | 用途 |
|---|---|
| `card_generator.model` | 本实验模型，不使用六角色单独覆盖值 |
| `card_generator.reasoning_effort` | 本实验思考强度 |
| `card_generator.pdf_direct_trial.timeout_seconds` | 整次模型调用时限；默认 1200 秒 |
| `card_generator.pdf_direct_trial.prompt_file` / `schema_file` | 实验提示词和输出协议 |
| `card_generator.pdf_direct_trial.windows_sandbox` | Windows 原生沙箱；当前 elevated，显式传参，不依赖个人配置 |
| `card_generator.pdf_direct_trial.shell_executable` | 本机预检 PowerShell；命令名或完整路径 |
| `card_generator.pdf_direct_trial.preflight_timeout_seconds` | 本机沙箱预检时限，默认 120 秒 |
| `card_generator.pdf_direct_trial.python_executable` | 直读专用 Python；当前指向 Codex 自带解释器，null 表示复用入口 Python |
| `card_generator.pdf_direct_trial.text_extractor` | 当前 pypdf；该解释器需装有 pypdf，兼容选项 pdftotext 不自动切换 |
| `card_generator.pdf_reader` 中的工具路径 | 复用 pdfinfo、pdftoppm；仅选择 pdftotext 引擎时用它的路径，不启动 MCP |
| `paths.runtime_dir` / `paths.card_trials_dir` | 临时目录 / 保留报告的目录 |

进度打印在 stderr，JSON 在 stdout；本机命令开始/结束、模型回合与等待状态均可见。命令结束不等于模型已经看图或理解论文；等待心跳也不是实际进展证明。可用 `--no-progress` 关闭显示。

### 如何判断结果

`ok=true` 且 `validation_status=READING_REPORT_ACCEPTED`：报告结构符合协议，模型声明读完全部文字和页面图像，并返回了图表观察；不包含原文摘录核对。`protocol_version=pdf-direct-read-v2` 用于区分新规则和历史实验。需要评价实际理解质量时，可抽检 `model_report_path` 对应的图表观察，但这不是每篇人工审核要求。

`full_read_verified=false`、`visual_understanding_verified=false`、`production_eligible=false` 是故意保留的边界，不是程序故障：报告结构和模型声明不能证明全文认真读完或图表理解正确。模型报告中的 `COMPLETE` 不等于程序已经独立验证。读取方式已接入当前单 Agent；独立读取实验仍不能替代制卡、模板校验和保存。

### 失败如何处理

| 错误 | 含义与处理 |
|---|---|
| `PDF_DIRECT_TOOL_NOT_FOUND` | 本机缺少配置的 PDF 工具；修正工具路径后再试 |
| `PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED` | 沙箱内本机检查失败，model_invoked=false；查看 sandbox_preflight.checks 和 diagnostic，先修本机依赖/权限 |
| `PDF_DIRECT_TOOL_ACCESS_DENIED` | 模型读取未通过，且 stderr 记录真实权限拒绝；查看 first_policy_denial，不应盲目重跑或关闭隔离 |
| `PDF_DIRECT_SOURCE_UNAVAILABLE` / `PDF_INPUT_CHANGED` | 文件不可达或指纹变化；检查 Zotero 同步和源文件，不删除任务强行通过 |
| `PDF_DIRECT_ASSET_INVALID` | 检查实验提示词和 schema 路径及内容 |
| `PDF_DIRECT_READING_INCOMPLETE` | 模型报告部分页面或图像没有读到；看报告 limitations |
| `PDF_DIRECT_VISUAL_FINDING_MISSING` | 没有有效图表观察；检查是否读到图、论文是否本来无图表，不允许编造 |
| `PDF_DIRECT_EVENTS_INVALID` / `PDF_DIRECT_OUTPUT_INVALID` | 事件流或输出报告无效，不保存为通过结果 |
| `PDF_DIRECT_TIMEOUT` | 超过配置时限，已停止本次子进程；不自动重跑 |
| 服务、连接或本机访问错误 | 保留最终 JSON 与诊断，不能解释为读取成功；该实验不修复网络 |

失败时优先回传最终 JSON 和报告；不要无限重复运行。CLI 通常同时给出脱敏失败日志路径。准备阶段失败时可能没有模型报告，因为尚未调用模型。

进程退出码为零但阅读声明或 schema 校验失败时，也保存脱敏诊断，包含首个可识别的权限拒绝、命令事件数量以及模型自述的页数。`policy_denial_observed=false` 表示保存的底层信息中没有识别到拒绝，不证明完全没有拒绝；模型自己说“权限不足”也不会被当作已观测事实。

### 2026-09-08 修正版本机验收

旧配置的 MiKTeX `pdftotext` 在沙箱内可复现失败，提示先完成初始化，退出码 3221226505；这证明它不适合当前无人值守读取，但不能追认它就是上一轮所有命令拒绝的唯一原因。

只调整直读实验使用的 Python/pypdf 后，`--preflight-only` 通过：原 PDF 可读、16 页核对成功、首页提取 4,604 个字符、首页渲染为 335,195 字节 PNG、原始 PDF SHA-256 保持不变。`model_invoked=false`，未新增模型调用；正式卡片和任务未写入。结果目录：`.runtime/card-trials/pdf-direct-read/CEXH4PQA-ae9065a808e943a186f28a6c363d3c3b/`。页面渲染不等于模型已看图，模型端仍待真实验证。
