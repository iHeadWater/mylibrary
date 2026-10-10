# 运行维护

本页说明运行 `hydro-litagent cards` 单篇与主题流程所需的环境、状态文件边界和排障入口。所有命令读取同一个 `hydrolitagent/cards/assets/config/config.json`（`paper-input` 只读 Zotero 与 PDF 门禁两表），不调用模型、不修改 Zotero、不提交或推送 Git。

## 运行前置条件

在仓库根目录运行：

```powershell
uv sync --all-packages --locked
```

- Zotero Desktop 已启动，并启用「允许此计算机上的其他应用程序与 Zotero 通信」。
- 使用 `paper-input` 时，目标论文及其 PDF 必须在本机 Zotero 中可用。
- 使用 `evidence-generate` 时，还需要已安装并登录的一种 CLI（Codex 或 Claude），以及 Poppler 的 `pdfinfo` / `pdftoppm` / `pdftotext`。

只做离线校验（`evidence-validate`）不需要 Zotero、PDF、群组、Poppler 或 CLI 登录。

自查当前模型选择与产物根：

```powershell
uv run hydrolitagent cards ai-config --json
```

它只读检查配置，不消耗模型额度，也不证明模型服务当时连通或 CLI 已登录。

## 状态文件与共享产物

平台的状态与运行区位于 `paths.runtime_dir`（默认 `.runtime/`），主题池注册表位于 `paths.themes_dir`。这些文件由程序原子写入并校验哈希，**不要手工编辑**——手改会被判为漂移或冲突，程序保留现场而不覆盖。

- 缺失的 `.runtime` 是允许的；下次运行按需重建。
- 主题池只在一次变更的全部新版本准备完成后才更新注册表；目录中出现半成品不代表它已成为当前主题。
- 请从 `themes/index.md` 查当前候选与历史版本，不要通过移动文件或手改索引来模拟状态变更。

## 配置选择

所有保留命令默认读取 `hydrolitagent/cards/assets/config/config.json`；本机覆盖使用被 Git 忽略的完整 `config.local.json`，并通过 `--config` 或 `HYDRO_PLATFORM_CONFIG` 显式选择；系统不进行隐式配置合并。

```powershell
uv run hydrolitagent cards themes-run --config hydrolitagent/cards/assets/config/config.local.json --json
```

**`config.local.json` 是另一份完整总配置，不是只填几个覆盖字段的补丁文件。** 路径字段、密钥边界和字段含义见[总配置字段说明](../../development/platform/config.md)与[变量与密钥](../../development/platform/variables.md)。

## 运行日志

失败诊断由 CLI 保存到 `paths.logs_dir`（默认 `.runtime/logs`），只保存已脱敏的公开错误和上下文，不保存原始事件、提示词或论文全文；日志不提交 Git。日志目录不可写时保留原失败结果并给出警告。

## 环境与依赖恢复

Python 环境是 仓库根 `.venv`（由 `uv sync --all-packages` 准备）。换机时重新执行 `uv sync --all-packages --locked`，并重新登录所选 CLI、重新配置 Poppler 路径即可；不要复制别人的 `.venv`、登录文件或账号凭据。
