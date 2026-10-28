# 两阶段制卡与能力自查

`cards run` 把「读论文、写卡片」交给**任意**能读文件、写 JSON 的 agent：Claude Code、Codex、会话内助手都行。
Python 只负责准备材料、校验接线和保存草稿，**不调用模型**。

`cards doctor` 是同一层的只读自查：转换器在不在、运行器可不可用、产物根能不能写。它**不调用模型、不读你的 PDF**。

> 主题池也有同一套两阶段协议：`cards run prepare|finalize --theme`（发现 → 每篇精读 → 回填 → 提交），
> 不传 `--paper-input`。见[统一文献池与主题池](unified-theme-pool.md)的「在会话里分步跑」一节。

## 为什么分两阶段

`evidence-generate` 由平台直连 LLM API（默认 DeepSeek）。若你想用当前 agent、或不想配置 API key，
就让平台先**准备**好材料，agent 在本地**写答案**，平台再**收口**：

```text
cards run prepare  →  运行目录（paper.md / figures/ / request.json / output.schema.json / README.md）
agent 读论文、按 schema 写 response.json
cards run finalize →  校验接地 + 保存待校验草稿
```

两阶段使用与 `evidence-generate` 相同的 `PreparedPaper`、同一套引文 / 页锚点 / canary 接地规则。
`prepare` 与 `finalize` 都**不会**调用模型。

## 第一阶段：`cards run prepare`

```bash
uv run hydrolitagent cards run prepare \
  --paper-input paper-input.json \
  --run-dir <运行目录> \
  --json
```

- `--paper-input` 是[单篇输入](paper-input.md)产出的 READY 记录，也支持 `-` 从 stdin 读。
- `--run-dir` 由你指定；目录不存在会被创建，已存在则写入其中。
- `--output-root` 可选，决定收口时草稿写到哪个产物根（默认 `outputs/`）。

准备完成后，运行目录里是：

| 文件 / 目录 | 内容 |
|---|---|
| `paper.md` | Python 从 PDF 转换的 Markdown，含 `<!-- page: N -->` 页锚点与完整性 canary |
| `figures/` | 与卡片相关的图片资产 |
| `request.json` | run id、角色、页数、页锚点、canary 清单、图片清单、prompt |
| `output.schema.json` | agent 必须遵守的答案 JSON Schema |
| `README.md` | 给 agent 的最短操作说明 |

命令返回 `status: AWAITING_SESSION_OUTPUT`、`markdown_sha256`、`page_count`、`canaries` 与文件路径。
此时**还没有草稿**，也**没有内容通过校验**。

## agent 要写的 `response.json`

在本目录写入 `response.json`（文件名固定），至少满足：

1. **完整读完 `paper.md`**，不要修改它 —— 平台会重新计算哈希。
2. 按 `output.schema.json` 生成 JSON 对象。
3. 顶层 `reading_receipt.markdown_sha256` **回显** `request.json` 的 `markdown_sha256`。
4. `reading_receipt.canaries_seen` 列出 `request.json` 的 `reading_canaries` **全部值**。
5. 顶层 `source_locations` 放**逐字原文**引文；每条引文必须能在对应页锚点范围内命中。

不要依赖「写得像」：`verified` 只表示程序检查通过，**不表示科学正确**。

## 第二阶段：`cards run finalize`

```bash
uv run hydrolitagent cards run finalize \
  --run-dir <运行目录> \
  --paper-input paper-input.json \
  --json
```

`finalize` 会：

1. 重新解析同一份 `--paper-input` 并复用已缓存的 Markdown 转换；
2. 读取运行目录的 `request.json`，要求其中的 `markdown_sha256` 与当前论文一致；
3. 重新计算 `paper.md` 的哈希，拒绝被改动的论文；
4. 检查 `response.json` 的 `reading_receipt`、canary 与引文接地；
5. 通过后写**待校验**主体卡草稿（`DRAFT_PENDING_VALIDATION`），返回 `card_path`、`draft_path`、`literature_root`
   与 `reading_status`。

失败时返回结构化 `error.code` 与 `error.diagnostic`，**不偷偷重试、不改写你的 `response.json`**。
`response.json` 与 `paper.md` 都保留在现场，便于人工核对 agent 实际看到了什么。

## 失败排查

| 错误码 | 含义 | 怎么办 |
|---|---|---|
| `CARD_DRAFT_INPUT_INVALID` | `--paper-input` 不是可读的 JSON | 重新生成[单篇输入](paper-input.md)记录 |
| `CARD_DRAFT_CONFIG_OR_INPUT_INVALID` | 配置或输入记录无效 | 检查 `--config`、转换器配置与输入字段 |
| `IN_SESSION_RUN_DIR_INVALID` | 运行目录无法创建，或被同名文件占用 | 换一个空目录 |
| `MARKDOWN_SOURCE_INVALID` | 转换缓存里找不到与摘要一致的 `paper.md` | 重新运行 `prepare`；必要时清理转换缓存 |
| `IN_SESSION_REQUEST_MISSING` | 运行目录没有 `request.json` | 先执行 `cards run prepare` |
| `IN_SESSION_REQUEST_INVALID` | `request.json` 不是 JSON 对象或缺字段 | 重新 `prepare`，不要手改 |
| `MARKDOWN_SHA_MISMATCH` | 运行目录或回执的 Markdown 哈希与当前论文不一致 | 用**同一份** `--paper-input` 与**同一个** `--run-dir`；不要混用两次准备 |
| `MARKDOWN_CHANGED` | 运行目录里的 `paper.md` 被改动 | 重新 `prepare`，让 agent 在只读副本上重做 |
| `IN_SESSION_RESPONSE_MISSING` | agent 还没写 `response.json` | 等 agent 写完再 `finalize` |
| `IN_SESSION_RESPONSE_INVALID` | `response.json` 不是 JSON 对象 | 按 `output.schema.json` 重写 |
| `IN_SESSION_READING_RECEIPT_MISSING` | 缺少 `reading_receipt` | 补上完整的阅读回执 |
| `IN_SESSION_MARKDOWN_SHA_MISSING` | 回执没有 `markdown_sha256` | 回显 `request.json` 中的值 |
| `IN_SESSION_CANARY_MISSING` | `canaries_seen` 不完整 | 列出全部 canary |
| `MARKDOWN_RUNNER_OUTPUT_INVALID` | 收口到的输出不是 JSON 对象 | 检查 schema 版本与顶层结构 |

引文不合规（不在 Markdown 中、页号不符、过短）不会伪造成功：要么该引文不计入证据，
要么整卡因覆盖率不足而 `production_eligible=false`。详见[主体卡校验](subject-card-validation.md)。

## 能力自查：`cards doctor`

```bash
uv run hydrolitagent cards doctor --json
```

它默认**不联网、不调用模型、不读取用户 PDF**，只检查：

| 检查 | 能力 | 说明 |
|---|---|---|
| `converter.pymupdf` | `pdf.convert` | PyMuPDF 可 import、版本与能力（文本 / 版面 / 表格 / 图） |
| `runner.<id>` | `runner.<id>` | 注册表中的执行者，只有两个：`direct`、`in_session` |
| `storage.output_root` | `storage.write` | 产物根能否写入；可用 `--output-root` 检查另一个根 |
| `storage.runtime_lock` | `storage.lock` | 运行锁能否取得并释放 |
| `zotero.*` | `zotero.read` | 仅在 `--network` 时检查 Zotero Local API 与目标群组 |

每个检查给出 `status`：

- `pass`：可用。
- `warn`：可选能力缺失，但平台仍可用（例如缺一个可选运行器，而另一个可用）。
- `fail`：这条能力不可用；**存在任一 `fail` 时整体 `ok=false`，退出码为 3**。
- `skip`：主动跳过（例如未配置群组时的联网检查）。

`fix` 是可操作的修复建议（安装依赖、设置环境变量、检查配置路径），不是自动修复动作。
JSON 结果里 `model_invoked` **永远为 `false`**。

> 自查通过只说明**工具链**可用，不证明模型能理解论文，也不证明已有草稿通过内容校验。

## 边界

- `cards run` 不下载 PDF；输入记录必须来自已附好 PDF 的 Zotero 条目。
- `prepare` 不生成草稿；`finalize` 也只生成 `DRAFT_PENDING_VALIDATION`，下一步仍需[代码校验](subject-card-validation.md)。
- 平台不自动提交或推送 Git；运行目录与产物都在本机。
- `doctor` 不替代真实论文的端到端验证。

## 相关

← [单篇主体卡草稿](subject-card-draft.md) · → [主体卡代码校验](subject-card-validation.md) · [统一主题池](unified-theme-pool.md)
