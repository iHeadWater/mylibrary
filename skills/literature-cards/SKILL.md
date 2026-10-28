---
name: literature-cards
description: |
  文献卡与主题卡平台的运行入口：从自己的 Zotero 文献生成可追溯的证据卡与持续演化的主题池。
  命令是 `uv run hydrolitagent cards …` 这一组（7 个子命令），不是交互式问答。
  Use when the user wants to run the cards platform, turn Zotero papers into evidence cards,
  update the theme pool, or check model/output configuration.
  Triggers: "跑一次平台", "制卡", "证据卡", "主题池", "更新主题", "文献卡",
  "literature-cards", "paper-input", "themes-run", "平台排错", "ai-config",
  "cards doctor", "两阶段制卡", "run prepare", "run finalize".
---

# 文献卡与主题卡（literature-cards）

**本 skill 只是这组 `cards` 命令的入口说明。所有能力都由 `hydrolitagent/cards/` 的 Python 代码实现，本文件不重复实现任何逻辑，也不代你判断科研结论。**

## ⚠️ 适用范围（先读）

- **默认路径跨平台，不需要 Poppler。** PDF 先由 Python（PyMuPDF）确定性转换成 Markdown，
  再由注册表中的任意运行器阅读；macOS / Linux / Windows 行为一致。
- **前置条件**：Zotero 已登录且目标库已同步（`paper-input` 走 Local API 读本地 PDF）；
  `evidence-generate` 需要 `direct` 执行者可用（`DEEPSEEK_API_KEY`，可换其它 OpenAI 兼容 endpoint），
  或改用 `cards run prepare|finalize`（`in_session`，不需要 key）让当前 agent 读写文件。不满足时命令会明确报错，不会静默降级。
  不确定缺什么时先跑 `uv run hydrolitagent cards doctor --json`。
- **平台不下载 PDF。** 它只读取共享库中**已经附好**的文件。下载与入库属于 `paper-to-zotero` / `download-pdf`（本仓库另一侧能力）。

## Contract

YOU MUST 通过本节列出的 CLI 子命令操作平台。**不要**直接读写平台的 JSON 状态文件（`.runtime/tasks.json`、`themes/_registry.json`），也不要手工编辑证据包或主题文件——这些由平台原子写入并校验哈希，手改会被判为漂移或人工改动。

YOU MUST 在运行前确认工作目录：命令一律**从仓库根目录**执行，用 `uv run hydrolitagent cards …`。

YOU MUST 记住平台**不自动同步 Git、不自动登录、不唤醒关机电脑**。本地保存不等于已推送。

## 环境

平台的 Python 环境是**仓库根 `.venv`**，由 uv 独占管理：

```bash
uv sync --all-packages      # 从仓库根执行
```

**不要**手工创建或复制别人的 `.venv`；换机后重新 `uv sync` 并重新登录所选模型 CLI。

## 单篇主体卡草稿（#30）

收到 #29 的单篇 READY JSON 后，在仓库根运行：

~~~powershell
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider direct --json
~~~

此入口要求 single_agent + local_path；个人库和群组库均可使用，无需再次扫描 Zotero。
一次调用同时生成详细正文和固定机器字段。输出仅为 DRAFT_PENDING_VALIDATION，
不代表 #31 校验通过，不自动执行 #32 修正或 #35 正式保存，不触发主题或 idea。
文件按 #27 的统一规则写入精读产物根下 zotero/<文库类型>-<文库ID>-<父条目key>/drafts/<草稿ID>/。
根目录通过 configs/paths.toml 或 HYDROLITAGENT_LITERATURE_ROOT 配置；默认 outputs/。
输入失败、PDF 不可读或输出不可解析时报告结构化失败，不自动重试模型。
完整协议及运行前提见 docs/user-guide/cards/subject-card-draft.md。

## 主体卡代码校验（#31）

生成主体卡草稿后，使用 evidence-validate --draft <draft.json> --paper-input <READY.json> --json。
该入口离线运行，检查最低内容、字段、原文位置及版本绑定，单独追加保存 validation.json。
PASS 只表示当前代码规则通过，不能声称科学结论正确或正式发布。字数仅作提示。
主题侧读取这些草稿必须使用 themes.load_subject_card_sources；不要仅检查 JSON 中的 PASS 字样。
任何草稿、输入或规则变化都需要重新校验，不能沿用旧报告。失败修正由 #32 处理。
完整协议见 docs/user-guide/cards/subject-card-validation.md。

## 日常命令

命令一律从**仓库根**执行。

| 需要做什么 | 命令 |
|---|---|
| 查一篇自己的论文（个人库；群组库去掉 `--user-library`） | `uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --json` |
| 从 READY JSON 生成主体卡草稿 | `uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider direct --json` |
| 离线校验主体卡（不调模型） | `uv run hydrolitagent cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json` |
| 从粗卡生成候选主题 | `uv run hydrolitagent cards themes-run --json` |
| 只读预览主题池与输入变化（不调模型） | `uv run hydrolitagent cards themes-run --dry-run --json` |
| 只迁移已有完成主题（不调模型） | `uv run hydrolitagent cards themes-run --migrate-only --json` |
| 只读查看模型选择与产物根（不调模型） | `uv run hydrolitagent cards ai-config --json` |
| 只读自查转换器、运行器与存储（不调模型、不读用户 PDF） | `uv run hydrolitagent cards doctor --json` |
| 准备两阶段运行目录（不调模型） | `uv run hydrolitagent cards run prepare --paper-input paper-input.json --run-dir <运行目录> --json` |
| 收口 agent 写好的 `response.json`（不调模型） | `uv run hydrolitagent cards run finalize --run-dir <运行目录> --paper-input paper-input.json --json` |

> 完整清单以 `uv run hydrolitagent cards --help` 为准（**当前 7 个子命令**；`run` 含 `prepare` / `finalize`）。
> `cards` 是 `hydrolitagent` CLI 的子命令组；平台已并入 `hydrolitagent` 包
> （`hydrolitagent/cards/`）—— 它是一组子命令，不是独立的包或命令行工具。

## 结果怎么读

平台的 JSON 结果里，**保存成功只表示流程通过，不代表科学正确性已被机器独立验证**。证据包的 `quality-audit.json` 同理。

- `ok: true` + `model_invoked: false` 的 `--dry-run` 结果**不代表**最新文献已被发现。
- 正式主题受保护，**不会**被自动覆盖；候选主题可以自动更新、合并、拆分。
- 平台当前**不生成科研 idea**，也不做期刊级质量认证。

## 深入阅读

平台文档在 `docs/user-guide/cards/`：完整操作说明与文档导航见 `docs/user-guide/cards/index.md`，工程实现与已知缺口见 `docs/development/platform/`（以 `index.md` 导航为准）。
