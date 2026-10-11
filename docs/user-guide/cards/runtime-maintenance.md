# 运行维护

单篇与主题流程的**环境、状态文件边界与排障入口**。

所有命令读同一份总配置 `hydrolitagent/cards/assets/config/config.json`
（`paper-input` 只用其中的 Zotero 与 PDF 门禁两段）。这些命令
**不调用模型、不改动 Zotero、不提交或推送 Git**。

## 运行前置条件

在**仓库根**执行：

```bash
uv sync --all-packages --locked
```

- Zotero Desktop 已启动，并启用「允许此计算机上的其他应用程序与 Zotero 通信」。
- 用 `paper-input` 时：目标论文及其 PDF 已在本机 Zotero 中可用。
- 用 `evidence-generate` 时：另需一种**已登录**的 CLI（Codex 或 Claude），以及 Poppler 的
  `pdfinfo` / `pdftoppm` / `pdftotext`。

**只做离线校验（`evidence-validate`）不需要** Zotero、PDF、群组、Poppler 或 CLI 登录。

自查当前模型选择与产物根：

```bash
uv run hydrolitagent cards ai-config --json
```

它只读配置 —— 不消耗模型额度，也**不证明**模型服务当前连通或 CLI 已登录。

## 状态文件

程序自己维护的状态都落在**仓库根**：运行区是 `paths.runtime_dir`（默认 `.runtime/`），
主题池注册表在 `paths.themes_dir`。这些文件由程序**原子写入并校验哈希**，
**不要手工编辑** —— 手改会被判为漂移或冲突，程序保留现场而不覆盖。

- `.runtime` 不存在是正常的，下次运行按需重建。
- 主题池只在一次变更的**全部**新版本就绪后才更新注册表；目录里有半成品**不代表**它已成为当前主题。
- 查当前候选与历史版本请看 `themes/index.md`；不要靠移动文件或手改索引来模拟状态变更。

## 换一份配置

所有命令默认读 `hydrolitagent/cards/assets/config/config.json`。本机要覆盖时，
用另一份**完整**配置（被 Git 忽略的 `config.local.json`），并显式指定：

```bash
uv run hydrolitagent cards themes-run --config hydrolitagent/cards/assets/config/config.local.json --json
```

`--config` 或环境变量 `HYDROLITAGENT_CARDS_CONFIG` 二选一，系统**不做隐式合并**。
`config.local.json` 是**另一份完整总配置，不是只填几行的补丁文件**；
字段含义见[字段说明](../../development/platform/config.md)与[变量与密钥](../../development/platform/variables.md)。

## 运行日志

失败诊断写在 `paths.logs_dir`（默认 `.runtime/logs`），只含**已脱敏**的公开错误与上下文 ——
不保存原始事件、提示词或论文全文，日志不入库。日志目录不可写时，保留原失败结果并给出警告。

## 换机器 / 恢复环境

Python 环境是**仓库根 `.venv`**，由 `uv sync --all-packages` 准备。换机后重新
`uv sync --all-packages --locked`、重新登录所选 CLI、重新配置 Poppler 路径即可。
**不要复制别人的 `.venv`、登录文件或账号凭据。**
