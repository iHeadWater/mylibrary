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

**前提**：一种**已登录**的模型 CLI（Codex 或 Claude），见[前提与配置](../../getting-started/installation.md)。
后端二选一 —— **Codex** 用本地 PDF 适配器（需要 `pypdf` 与 Poppler 的 `pdfinfo` / `pdftoppm`）；
**Claude** 走原生 PDF Read（需要 PATH 里的 `pdftoppm`；**缺它就不能算「完整读过了」**）。

> **`--ai-provider claude` 选的是「命令行适配器」，不是模型厂家。** 用 CC Switch 把 Claude Code
> 接到 DeepSeek 时仍然填 `claude`，**不要**填 `deepseek` —— 当前命令只接受 `claude` 或 `codex`。

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
