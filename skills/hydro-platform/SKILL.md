---
name: hydro-platform
description: |
  水利科研知识平台的运行入口：从共享 Zotero 库的文献生成可追溯的证据包与持续演化的主题池。
  面向「无人值守批处理」与「查看/排错已有成果」，不是交互式问答。
  Use when the user wants to run the platform, process Zotero papers into evidence cards,
  update the theme pool, read the daily report or contribution ledger, or diagnose the platform.
  Triggers: "跑一次平台", "制卡", "证据包", "证据卡", "主题池", "更新主题", "日报", "贡献账本",
  "hydro-platform", "run-once", "themes-run", "平台排错", "doctor".
---

# 水利科研知识平台（hydro-platform）

**本 skill 只是这个平台 CLI 的入口说明。所有能力都由平台的 Python 代码实现，本文件不重复实现任何逻辑，也不代你判断科研结论。**

## ⚠️ 适用范围（先读）

- **平台目前是 Windows-only。** 计划任务、Poppler 原生工具安装、PDF 沙箱探针都依赖 Windows 的 PowerShell 与 `.exe`。
  在 hermes 容器或 macOS/Linux 上，`setup`、`schedule-*`、`bootstrap-native`、`pdf-direct-read-trial` **不可用**。
  读取类与制卡类命令（`scan`、`pdf-gate`、`tasks-*`、`run-once`、`themes-run`）的**编排逻辑本身是跨平台的**，但 PDF 工具链未在非 Windows 上验证。
- **前置条件**：Zotero 已登录且目标共享库已同步；Codex CLI 已用账号登录。二者都不满足时命令会明确报错，不会静默降级。
- **平台不下载 PDF。** 它只读取共享库中**已经附好**的文件。下载与入库属于 `paper-to-zotero` / `download-pdf`（本仓库另一侧能力）。

## Contract

YOU MUST 通过本节列出的 CLI 子命令操作平台。**不要**直接读写平台的 JSON 状态文件（`.runtime/tasks.json`、`themes/_registry.json`），也不要手工编辑证据包或主题文件——这些由平台原子写入并校验哈希，手改会被判为漂移或人工改动。

YOU MUST 在运行前确认工作目录：命令一律**从仓库根目录**执行，用 `uv run hydro-platform …`。

YOU MUST 记住平台**不自动同步 Git、不自动登录、不唤醒关机电脑**。本地保存不等于已推送。

## 环境

平台的 Python 环境是 **uv workspace 的仓库根 `.venv`**，由 uv 独占管理：

```bash
uv sync --all-packages      # 从仓库根执行；一次装好两个包
```

**不要**用 `bootstrap --install` 去创建这个环境（那是给"与仓库依赖树隔离的部署"用的另一条路径）。在共享环境模式下，`bootstrap` 只做**校验**并提示 `uv sync`。

## 日常命令

| 需要做什么 | 命令（仓库根执行） |
|---|---|
| 跑完一整轮：检测 → 门禁 → 制卡 → 主题 → 账本 → 日报 | `uv run hydro-platform run-once --json` |
| 只预览已有本地任务，不扫 Zotero、不调模型 | `uv run hydro-platform run-once --dry-run --json` |
| 只跑主题部分 | `uv run hydro-platform themes-run --json` |
| 只读预览主题池与输入变化（不调模型） | `uv run hydro-platform themes-run --dry-run --json` |
| 只迁移已有完成主题（不调模型） | `uv run hydro-platform themes-run --migrate-only --json` |
| 集中检查配置、依赖、登录与 Zotero | `uv run hydro-platform doctor --json` |
| 从 Zotero 与已有成果重建本地任务状态 | `uv run hydro-platform recover --json` |

`run-once` 是**串行**处理本轮全部可制卡论文；已有非占位粗卡不会自动重做。实时进度输出到 stderr，最终 JSON 到 stdout，`--no-progress` 可关闭进度。

## 分步命令（排错或定向操作时用）

| 环节 | 命令 |
|---|---|
| 列出本机可见的 Zotero 群组库 | `discover-groups` |
| 检查目标群组能否被后台读取 | `preflight` |
| 扫描群组增量 | `scan` |
| PDF 全文门禁判定 / 交付 | `pdf-gate` / `pdf-delivery` |
| 任务状态机：同步 / 列表 | `tasks-sync` / `tasks-list` |
| 证据包骨架同步 | `packages-sync` |
| 校验八类卡片模板 | `evidence-templates-validate` |
| 制卡生成器预检 / 冒烟 | `generator-preflight` / `generator-smoke-test` |
| 生成单篇证据卡 | `evidence-generate` |
| 导出未保存草稿 | `evidence-draft-export` |
| 贡献账本同步 / 日报 | `activity-sync` / `daily-report` |
| 安装与调度（**Windows**） | `setup` / `bootstrap-native` / `schedule-plan` / `schedule-status` / `schedule-install` / `schedule-remove` / `schedule-tick` |

## 结果怎么读

平台的 JSON 结果里，**保存成功只表示流程通过，不代表科学正确性已被机器独立验证**。证据包的 `quality-audit.json` 同理。

- `ok: true` + `model_invoked: false` 的 `--dry-run` 结果**不代表**最新文献已被发现。
- 正式主题受保护，**不会**被自动覆盖；候选主题可以自动更新、合并、拆分。
- 平台当前**不生成科研 idea**，也不做期刊级质量认证。

## 深入阅读

平台文档在 `docs/hydro-platform/`：完整操作说明见 `platform-operations-guide.md`，排错见 `operator-manual.md`，工程状态与已知缺口见 `engineering-status.md`。
