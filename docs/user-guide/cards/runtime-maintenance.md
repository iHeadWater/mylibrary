# 运行维护

**状态文件、配置与日志。** 日常不必看这一页 —— 出问题、换机器、想改配置时再来。

安装与凭据见[前提与配置](../../getting-started/installation.md)。

## 状态文件在哪

程序自己维护的状态都在**仓库根**：

| 位置 | 是什么 |
|---|---|
| `.runtime/` | 运行区（任务、锁、日志、快照） |
| `themes/` | 主题池 —— 从 `themes/index.md` 进，那是给人看的总入口 |

这些文件由程序**原子写入并校验哈希** —— **不要手工编辑**：手改会被判为漂移或冲突，
程序**保留现场而不覆盖**。`.runtime` 不存在是正常的，下次运行按需重建。

主题池只在一次变更的**全部**新版本就绪后才更新注册表；目录里有半成品**不代表**它已成为当前主题。

## 谁读哪份配置

| 命令 | 读什么 |
|---|---|
| `paper-input` | `configs/paper-input.toml` |
| `evidence-validate` | 包内资产 —— **不读**总配置 |
| `evidence-generate` / `themes-run` / `ai-config` | 总配置 `hydrolitagent/cards/assets/config/config.json` |

本机要覆盖后三者，用 `--config` 指向**另一份完整配置**（被 Git 忽略的 `config.local.json`）。它是**完整配置，不是只填几行的补丁文件**；系统**不做隐式合并**。

字段含义见[配置参考](../../development/platform/config.md)与[变量与密钥](../../development/platform/variables.md)。

## 日志

失败诊断写在 `.runtime/logs`，只含**已脱敏**的公开错误与上下文 ——
不保存原始事件、提示词或论文全文，且**不入库**。目录不可写时保留原失败结果并给出警告。

## 换机器

重新 `uv sync --all-packages --locked`、重新登录所选模型 CLI、重新配 Poppler 路径即可。
**不要复制别人的 `.venv`、登录文件或账号凭据。**

## 边界

- 只有 `evidence-generate` 与 `themes-run` 会**调用模型**；`paper-input` / `evidence-validate` / `ai-config` 不调用。
- 这些命令都**不改动 Zotero**、**不提交或推送 Git** —— **本地保存不等于已完成远端备份**。
- 想自查当前模型选择与产物落点：`uv run hydrolitagent cards ai-config --json`
  —— 它只读配置，**不证明**模型服务连通或 CLI 已登录。
