# 文献卡与主题卡

把**你自己 Zotero 里的**一篇论文变成一张可校验的**文献卡**，再把若干文献卡组织成持续演化的**主题卡**。

产出的是**长期可追溯**的知识资产（不同于公众号文章、播客这类当期内容）。
模型负责读论文、写内容；**代码负责身份核对、门禁、校验与安全写入**。

## 怎么用

**配一次**（见[前提与配置](../../getting-started/installation.md)），之后直接跟 agent 说人话就行：

> 「把《某某》这篇做成卡」 · 「这几篇都做一下」 · 「看看能聚出哪些主题」

agent 走的是这条链路：

```text
你的 Zotero 论文 → 输入记录 → 主体卡草稿 → 代码校验 → 若干卡 → 候选主题
                   paper-input   evidence-generate  evidence-validate  themes-run
```

也可以自己敲（命令一律**从仓库根**执行）：

```bash
uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --json
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider codex --json
uv run hydrolitagent cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json
uv run hydrolitagent cards themes-run --json
uv run hydrolitagent cards ai-config --json          # 看模型选择与产物落点，不调模型

# 任意能读文件、写 JSON 的 agent 也能制卡：先准备，再由 agent 写答案，最后收口
uv run hydrolitagent cards run prepare --paper-input paper-input.json --run-dir <运行目录> --json
uv run hydrolitagent cards run finalize --run-dir <运行目录> --paper-input paper-input.json --json

# 只读自查转换器、运行器与存储；不调模型、不读你的 PDF
uv run hydrolitagent cards doctor --json
```

完整清单：`uv run hydrolitagent cards --help`（当前 7 个子命令；`run` 含 `prepare` / `finalize` 两个阶段）。

## 自查（不需要你的论文，也不需要模型）

仓库带一份合成示例，装完就能验证入口通了：

```bash
uv run python scripts/paper_validate.py \
  --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json \
  --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json \
  --report-dir outputs/validation-demo
```

返回 `status: PASS` 就说明入口可用。它只验证**代码**，**不代表**真实论文能生成。

## 前提与产物

**前提**：Zotero 里该论文**已附好可读的 PDF**；一种运行器可用 —— 已登录的模型 CLI（Codex 或 Claude），
或配置好的 OpenAI 兼容接口，或会话内 agent（`cards run`）。默认路径是 **PDF→Markdown**（Python + PyMuPDF），
**不需要 Poppler**，macOS / Linux / Windows 行为一致。

**产物**：单篇流程写到**产物根**（默认仓库 `outputs/`）；主题池写到 `themes/`。
查主题从 `themes/index.md` 进 —— 那是给人看的总入口。

## 边界

- **通过校验只表示确定性规则通过，不证明科研内容正确。**
- 正式主题必须**人工确认**；`themes-run` 只产出候选，不自动晋级。
- 平台**不下载** PDF；缺 PDF 先走[入库那条线](../paper-pipeline.md)。
- 程序**不会**自动提交或推送 Git —— **本地保存不等于已完成远端备份**。

## 相关

| 想看什么 | 去哪 |
|---|---|
| 开工前的公共前提与凭据 | [前提与配置](../../getting-started/installation.md) |
| 单篇：输入 / 草稿 / 校验 | [单篇论文输入](paper-input.md) · [主体卡草稿](subject-card-draft.md) · [主体卡校验](subject-card-validation.md) |
| 任意 agent 两阶段制卡 / 能力自查 | [两阶段制卡与自查](run-and-doctor.md) |
| 主题池 | [统一主题池](unified-theme-pool.md) |
| 模板 | [公共模板](templates.md) |
| 运行维护 | [运行维护](runtime-maintenance.md) |
| 技术实现（开发者向） | [项目级设计](../../development/platform/project-design.md) · [技术架构](../../development/platform/architecture.md) |
