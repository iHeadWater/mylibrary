# hydro-platform 平台文档

水利科研知识平台：以团队共享 Zotero 库为文献入口，用可追溯的证据包和持续演化的主题池积累研究认识。

当前是本地文件型知识库与 Python 自动化程序，不是带网页登录和数据库权限的在线系统。一篇论文一个共享证据包，一个研究问题一个长期主题；不按学生或运行 batch 分隔知识。本页是平台文档入口，专项细节由下方各页承担。

## 先看哪里

- **第一次使用或需要完整交接**：[平台完整操作说明](platform-operations-guide.md)，覆盖目录、实现链路、配置、换机、日常运行和排错。
- **看研究方向和进展**：[统一主题池](unified-theme-pool.md)，进入主题后主要看 revised.md。
- **看单篇论文**：[证据包](evidence-packs.md)，card.md 是通用粗卡，readings/ 是定向精读。
- **改路径、共享库、模型、思考强度或制卡子进程代理**：`hydro-platform/config/config.json` 及[字段说明](config.md)。代理配置不修改 Codex 客户端或系统设置。
- **运行、排错或交接**：[操作手册](operator-manual.md)、[工程状态与缺口](engineering-status.md)。

## 当前工作流

~~~text
人工筛选论文并放入 Zotero 共享库
  → 检测新增条目和后补 PDF
  → 取得本机原始 PDF，单 Agent 生成模板驱动的详细粗卡
  → 全部有效粗卡 + 已有主题 + 适用历史精读，共同规划候选主题
  → 复用适用精读；必要时对原始 PDF 做新的定向精读
  → 回填修订候选，保存新版本并更新统一主题池
  → 人工确认才可成为正式主题（专用确认入口尚未实现）
~~~

- 入库论文都应制卡，但没有可读取的原始 PDF 时等待，不用摘要冒充全文。
- 日常一次命令串行处理本轮全部可制卡论文，完成即保存；已有非占位粗卡不自动重做。
- 粗卡由单 Agent 自动选择八类模板之一。当前协议 rough-card-single-agent-v2，主提示词 v8；旧六 Agent / PDF MCP 代码只保留兼容与历史用途，不是当前默认路径。
- 模板指导详细分析及区分原文与 AI 推理；Python 只检查来源、非空输出、路由、重复和安全写入，不用标题、表格、固定措辞或归因标签拦截正文。
- 候选允许自动更新、合并、拆分。正式主题受保护，不自动覆盖；当前不生成科研 idea。
- 保存成功仅表示流程通过，不代表科学正确性已由机器独立验证。

## 日常操作

在仓库根目录运行，命令前缀统一为 `uv run hydro-platform`（旧的直接调用脚本写法已废弃，请统一使用 uv 形式）：

~~~powershell
uv run hydro-platform run-once --json
~~~

当前配置启用了主题流程、关键贡献记录和日报，同一入口自动衔接。主题输入没有变化时不调用模型。

| 需要做什么 | 命令 |
|---|---|
| 只继续主题部分 | uv run hydro-platform themes-run --json |
| 只读预览主题池及输入变化 | uv run hydro-platform themes-run --dry-run --json |
| 只迁移已有完成主题，不调用模型 | uv run hydro-platform themes-run --migrate-only --json |
| 检查依赖、登录、共享库及计划 | uv run hydro-platform doctor --json |
| 从 Zotero 和已有成果重建本地任务状态 | uv run hydro-platform recover --json |
| 查看 Windows 计划的实际注册及运行状态 | uv run hydro-platform schedule-status --json |

run-once --dry-run 只预览已有本地任务，不扫描 Zotero，也不调用模型。实时进度输出到 stderr，最终 JSON 输出到 stdout；--no-progress 可关闭本次进度。

## 目录地图

| 位置 | 存什么 / 做什么 |
|---|---|
| `hydro-platform/evidence-packs/` | 团队唯一证据包存储区：论文粗卡、来源清单、定向精读；[说明](evidence-packs.md) |
| `hydro-platform/themes/` | 主题总入口、注册表、候选版本、演变历史和正式主题预留区；[说明](unified-theme-pool.md) |
| `hydro-platform/templates/` | 八类证据卡模板、主题规划/精读/回填模板及来源版本；[说明](templates.md) |
| `hydro-platform/automation/` | 检测、制卡、主题、保存、恢复、安装、调度和测试；[说明](automation.md) |
| `hydro-platform/config/` | 团队非敏感配置与完整示例；不保存密码或令牌；[说明](config.md) |
| `hydro-platform/members/` | 可选成员身份映射，不是学生独立知识工作区；[说明](permissions.md) |
| `hydro-platform/activity/` | 可共享、可去重的关键贡献账本 |
| `hydro-platform/reports/daily/` | 老师看的每日新增、完成、等待与阻塞摘要；[说明](activities-and-daily-report.md) |
| `docs/hydro-platform/` | 架构、权限、操作、配置、测试、恢复和已知缺口（本目录） |
| `hydro-platform/.runtime/` | 本机快照、任务、锁、日志、未保存草稿和试运行目录；不进入 Git |
| `hydro-platform/.tools/`、`.venv/` | PDF 原生工具（`hydro-platform/.tools/`）与 uv 工作区共享 Python 环境（仓库根 `.venv/`）；按锁/清单重建，不进入 Git |
| `hydro-platform/pyproject.toml`、仓库根 `.python-version` | Python 项目元数据与版本要求 |

## 证据卡与主题的存储逻辑

### 一篇论文，一个证据包

目录为 `hydro-platform/evidence-packs/EV-父条目Key-简短标题/`。EV 编号来自指定共享库的 Zotero 父条目 Key；标题只方便识别，不负责判重。

- card.md：通用的详细粗卡；粗读仍基于原始 PDF 全文，不等于只读摘要。
- manifest.json：共享库、父条目、附件、PDF 指纹、卡片状态及生成来源。
- quality-audit.json：部分包有生成/恢复记录；历史格式不同，不是科学质量认证。
- readings/RD-编号/reading.md：论文面向特定问题的精读；result.json 保存来源、重点、模型结果和执行记录。

同一论文可以有多份不同重点的精读，也可以让多个主题复用同一份适用精读。新精读不覆盖主粗卡。现有旧 readings/TH-编号/ 保留原位置和链接。PDF 始终由 Zotero 管理，不复制为仓库知识附件。[详细说明](evidence-packs.md)。

### 一个研究问题，一个长期主题

- `hydro-platform/themes/index.md`：给人看的总入口。
- `hydro-platform/themes/_registry.json`：主题编号、当前版本、历史版本、前身与后继。
- `hydro-platform/themes/candidates/TH-编号/versions/CHANGE-编号/`：新建或更新的候选版本；initial.md 是初版，revised.md 是精读回填后的候选。
- `hydro-platform/themes/changes/`：本次输入、规划及完整提交记录；CHANGE 不是独立主题库，也不是 Git commit。
- `hydro-platform/themes/confirmed/`：正式主题预留目录；目前没有正式确认命令。

补充/修正保留编号、增加版本；合并/拆分建立新编号，旧主题转历史但不删除，前后关系可追溯。所有替代结果完成后才发布全池变更，中途失败不先废弃旧主题。

早期两个主题的历史版本仍在原 BATCH 目录中，其中一个当前版本已更新到长期编号目录；保留旧目录是为了不断开引用，不是继续分 batch 生长。新版本采用长期编号目录。[规则与验收](unified-theme-pool.md)。

## 每日自动运行

指定制卡机已启用 Windows 任务 HydroPlatform-qinjiajun：日常 09:00 到期运行，30 分钟轻量检查，登录后检查最近到期任务。30 分钟检查不等于反复调用模型。

需要 Windows 用户已登录、Zotero/Codex 账号有效。run-once 按配置在 Zotero 未运行时启动一次并有限等待；API 可读不代表云端全部同步完成，PDF 仍逐篇检查。计划不唤醒关机电脑、不代登录、不自动推 Git。[调度与暂停](cron.md) · [启动及等待](zotero-readiness.md)。

## 首次安装或换电脑

先准备支持的基础 Python（当前 >=3.12,<3.15）、Zotero、Codex CLI，并由本人完成账号登录和目标共享库/PDF 同步。取回完整仓库，检查总配置。

环境由 uv 工作区统一管理：`hydro-platform` 是仓库根 `pyproject.toml` 中声明的 workspace 成员，与主包共享仓库根的 `.venv` 和 `uv.lock`，所以在仓库根执行一次同步即可得到平台运行环境。

~~~powershell
uv sync --all-packages
uv run hydro-platform setup --json
uv run hydro-platform setup --apply --json
~~~

`uv sync --all-packages` 是规范的环境安装命令：uv 是共享 `.venv` 的唯一管理者，`bootstrap` 不再创建该环境，只核对它是否可用并在缺失时指向 `uv sync`。第一条 setup 只读预览，第二条顺序安装/复用项目依赖、检查就绪、恢复本地状态，并按配置安装或核对每日计划。安装本身不调用科研模型，但启用的计划随后到期可能调用模型。

需要与仓库依赖树隔离的部署（例如平台独立交付到另一台机器），仍可使用平台自带的哈希锁定安装：`uv run hydro-platform bootstrap --install --json` 与 `uv run hydro-platform bootstrap-native --install --json`，把环境装到平台内的 `deployment.environment_dir`。共享环境模式下 `deployment.environment_dir` 为 `../.venv`，指向平台目录之外的仓库根 `.venv`；它只允许是平台内目录或工作区根的 `.venv`，两者之外的取值会被拒绝。[安装配置](deployment.md)。

另一台查看资料或手动复现的电脑先关闭制卡计划；指定制卡机是当前部署约定，不是分布式权限系统。示例配置默认关闭调度，团队 `config.json` 则是当前制卡机配置，且启用了本机代理 `http://127.0.0.1:7897`，换机必须检查端口。建议使用不上传的完整 `hydro-platform/config/config.local.json`，每条命令显式用 `--config` 选择。[换机操作步骤与真实验证边界](workstation-setup.md)。

## 共享与备份

- 代码、模板、依赖锁、非敏感配置、证据包、主题、贡献账本及日报属于应提交的共享成果。
- 原始 PDF、账号凭据、密钥、`hydro-platform/.runtime/`、仓库根 `.venv/` 和 `hydro-platform/.tools/` 不进入 Git。
- 本地保存不等于 GitHub 已更新。仅在用户明确要求时由维护者提交/推送；程序不会自动同步 Git。
- 本地任务和快照可按已有成果重建，但尚未正式保存的草稿可能只在 `hydro-platform/.runtime/` 中，不能不经检查整目录删除。
- 换机只能恢复实际备份过的成果。可复现指流程和已有结果能恢复，不承诺再次生成的文字逐字相同。

## 验证范围与已知限制

当前真实样本为 7 张完整粗卡、4 个完成定向精读回填的候选主题。运行 `f3463b8326604f08b843c8185f6e4954` 补齐 3 张卡、跳过已有 4 张，失败/阻塞/等待/延后均为 0；主题基于 7 篇文献演化，复用适用精读。全轮约 81 分 35 秒，其中主题约 53 分 19 秒。保存成果已只读核对，不代表科学质量经过独立验证。早期 3 篇样本还验证过无变化零模型调用和 Zotero 自动启动后的快速复用，不应把该耗时当作新论文生成耗时。

自动测试覆盖跨文献更新、合并/拆分、精读复用、失败恢复、完成记录校验、子进程代理隔离及正式主题保护；数量随交付轮次增长，各阶段的具体数量与验收范围见[验证地图](tests.md)。真实新增文献后的流程已跑通，但 AI 关联/合并判断的科研质量、大规模上下文处理、干净异机及关机/登录/云端同步恢复仍未全面验收。没有 CI 合并门禁，不保证期刊级科研成果。

[验证地图](tests.md) · [当前工程状态](engineering-status.md) · [单 Agent 规则](single-agent-rough-card.md)
