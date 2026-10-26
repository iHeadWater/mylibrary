# 从单篇 PDF 生成主体卡草稿

拿到一篇论文的 READY 记录后，用**一次模型调用**读出正文、生成主体卡草稿。

模型负责读论文、写内容，命令行负责组织工作。**生成成功只是「待校验」草稿 —— 还没通过校验。**

## 怎么用

跟 agent 说「把《某某》这篇做成卡」时，它接着上一步往下跑。自己敲的话：

```bash
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider codex --json
# 或用 Claude —— 无需同时安装 Codex
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider claude --json
```

- `paper-input.json` 是上一页产出的 READY 记录。**不能**传搜索候选列表，也**不能**传批处理的外层结果。
- 也支持 `--paper-input -` 从 stdin 读。
- 用 `uv run hydrolitagent cards ai-config --json` 可以确认当前默认管线（`ai.pipeline` 为
  `markdown` 或显式回退的 `legacy`）。

**前提**：一种**已登录**的模型 CLI（Codex 或 Claude），见[前提与配置](../../getting-started/installation.md)。

**默认走 Python 转换的 Markdown 路径**：程序先用 PyMuPDF 把 PDF 转成 `paper.md`（含页锚点、
完整性 canary 与图资产），按 PDF 哈希缓存，再把 Markdown 交给所选运行器阅读。**不再需要
Poppler**；`--ai-provider` 只决定由哪个运行器执行，两条路径读到的都是同一份 Markdown。
需要回退到旧的「运行器自己读 PDF」路径时，设置环境变量 `CARD_PIPELINE=legacy`（该路径仍需要
`pdfinfo` / `pdftoppm`，只保留一个版本）。

> Claude CLI 需支持**隔离模式与结构化输出**（本机验证版本 **2.1.280**）；版本过旧会直接失败，
> **不会**退回不受限模式。

> **`--ai-provider` 选的是「运行器」，不是模型厂家。** 可用值以 `ai-config --json` 的
> `runners` 为准：当前为 `claude`、`codex`（本机已登录的 CLI）与 `openai_compatible`
> （OpenAI 兼容的 `/chat/completions`；需要 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`，
> 模型名用 `--ai-model`）。不要填某个模型厂家的名字。
>
> `openai_compatible` **不发送图片**。若卡片引用了图，程序会把 `visual_content_status`
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
- Claude 以**隔离的只读模式**运行，**不加载**你的项目插件或命令；`evidence-generate` 也不改动
  Codex / Claude 本身，不提交账号或登录文件。

## 相关

← 上一步 [单篇论文输入](paper-input.md) · → 下一步 [主体卡代码校验](subject-card-validation.md)
