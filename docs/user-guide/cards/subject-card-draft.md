# 从单篇 PDF 生成主体卡草稿

拿到一篇论文的 READY 记录后，用**一次模型调用**读出正文、生成主体卡草稿。

模型负责读论文、写内容，命令行负责组织工作。**生成成功只是「待校验」草稿 —— 还没通过校验。**

## 怎么用

跟 agent 说「把《某某》这篇做成卡」时，它接着上一步往下跑。自己敲的话：

```bash
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider direct --json
# 或让当前 agent 读写文件（不需要 API key）
uv run hydrolitagent cards run prepare --paper-input paper-input.json --run-dir <运行目录> --json
```

- `paper-input.json` 是上一页产出的 READY 记录。**不能**传搜索候选列表，也**不能**传批处理的外层结果。
- 也支持 `--paper-input -` 从 stdin 读。
- 用 `uv run hydrolitagent cards ai-config --json` 可以确认当前默认管线（`ai.pipeline` 为
  `markdown` 或显式回退的 `legacy`）。

**前提**：两种执行者之一。`direct` 需要 `DEEPSEEK_API_KEY`（可换其它 OpenAI 兼容 endpoint）；
`in_session` 不需要 key，改用[两阶段制卡](run-and-doctor.md)。

**走 Python 转换的 Markdown 路径**：程序先用 PyMuPDF 把 PDF 转成 `paper.md`（含页锚点、
完整性 canary 与图资产），按 PDF 哈希缓存，再把 Markdown 交给所选执行者阅读。**不需要
Poppler**；`--ai-provider` 只决定由哪个执行者执行。旧的 CLI「自己读 PDF」直读适配器
已移除，`--paper-input` 不再回退到读取原始 PDF。

> **`--ai-provider` 选的是「执行者」，不是模型厂家。** 可用值以 `ai-config --json` 的
> `runners` 为准，只有两个：
>
> - `direct`：直连 OpenAI 兼容的 `/chat/completions`，默认 DeepSeek
>   （`https://api.deepseek.com`、`deepseek-chat`），key 取 `DEEPSEEK_API_KEY`；
>   换 endpoint 用 `base_url` / `--ai-model` 或 `DIRECT_LLM_BASE_URL` / `DIRECT_LLM_MODEL`。
> - `in_session`：由 `cards run prepare|finalize` 交给当前 agent，不需要 key。
>
> `direct` **不发送图片**。若卡片引用了图，程序会把 `visual_content_status`
> 记为 `NOT_REVIEWED` 并追加警告：它读到了图注，但没有看过图。

## 产物

写到**产物根**下的 `zotero/<user|group>-<文库ID>-<父条目Key>/drafts/<版本ID>/`，**每次生成新建一个版本**：

```text
draft.json    结构化草稿（下一步校验用）
card.md       给人读的正文
```

产物根默认是仓库 `outputs/`。实际落点用 `uv run hydrolitagent cards ai-config --json` 查。

## 边界

- 草稿始终是 **`DRAFT_PENDING_VALIDATION`** —— 不自称已通过内容校验、科学正确或正式发布。
- 这一步会**调用模型、消耗额度**；只处理你**有权上传**的材料。
- 失败返回**结构化失败** —— **不偷偷换模型、不自动重试**。
- **阅读工具的活动不等于科研理解已被独立验证。**
- `direct` 只做一次 API 补全：不启动子进程、不加载你的项目插件或命令，也不提交账号文件。

## 相关

← 上一步 [单篇论文输入](paper-input.md) · → 下一步 [主体卡代码校验](subject-card-validation.md)
