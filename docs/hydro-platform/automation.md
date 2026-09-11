# 自动化边界

`hydro-platform` 把可确定的扫描、全文门禁、任务状态、去重、恢复和安全保存交给 Python，把证据卡提炼和候选主题综合交给 Codex。自动化产出建议和候选知识，不替代研究者确认正式主题、科学结论或 research idea。

## 自动化清单

| 能力 | 触发方式 | 可读输入 | 会产生什么 | 人工门 |
| --- | --- | --- | --- | --- |
| 共享库扫描与 PDF 门禁 | `run-once`或定时任务 | 指定 Zotero 群组、条目、附件和本地 PDF | 快照、任务状态、PDF 指纹 | 不需逐条确认，但越界群组或不完整 PDF 必须拒绝 |
| 单 Agent 证据粗卡 | 存在通过门禁且未完成的任务 | 当前 PDF、九类模板、制卡提示词 | 证据包、`card.md`、manifest 和审计记录 | 可自动保存；`PROCESS_VALIDATED`只表示流程通过 |
| 统一候选主题池 | 制卡阶段完成或显式 `themes-run` | 全池粗卡、候选主题和适用精读 | CREATE / UPDATE / MERGE / SPLIT 候选及版本记录 | 不得自动晋级为正式主题 |
| 活动与日报 | `run-once`或显式维护命令 | 任务、成果、贡献者元数据 | 去重事件账本与当日摘要 | 不猜测身份，不用于排名 |
| Windows 每日调度 | 已安装的计划任务 | 本机配置与账号状态 | 到期运行、有限补查和运行记录 | 安装和移除调度需显式命令 |

## 可调用的外部表面

- Zotero Desktop Local API：只读配置指定的共享群组及本地附件，不修改 Zotero 数据库和同步偏好。
- Codex CLI：使用已登录的 ChatGPT 账号处理 PDF 和文本；模型、推理强度、超时和代理来自配置。
- 本地文件系统：只写入经配置解析和边界检查后的目录，对人工改动和来源冲突保留现场。
- Windows Task Scheduler：通过固定命令安装、查询和移除，不由模型自由构造命令。
- Git 不属于日常自动化表面；程序不自动 commit 或 push。

## 强制规则

- 没有可读原始 PDF 时，不生成正式证据粗卡。
- 已有非占位卡片不因模型或模板更新而被覆盖。
- 候选主题可自动演化，正式主题必须经人工决定。
- Python 核对来源身份、模板路由、非空输出、Schema 传输、重复和安全写入；它不证明正文科学正确。
- PDF、密钥、`.runtime`、证据包、主题池、事件账本和日报均不进入 Git。
- 可重试故障按次数、冷却和超时上限处理；认证、配置、来源或写入冲突不盲目重试。

## 产物与路径现状

当前配置存在两组路径，必须区分：

| 路径组 | 当前使用者 | 现状 |
| --- | --- | --- |
| `paths.evidence_packs_dir`、`themes_dir`、`activity_dir`、`reports_dir`、`members_dir` | `hydro-platform` 自动化 | 已接入运行代码，默认在 `hydro-platform/` 下 |
| `paths.artifact_root` 下的 `evidence_cards_dir`、`themes_vault_dir`、`run_records_dir`、`literature_index_dir` | 合并后的科研工作流目录契约 | 配置已能解析和校验，但自动化发布尚未接入这四个目录 |

因此，目前不能宣称“只修改 `artifact_root` 就能把自动证据包和候选主题全部发布到 Obsidian”。目标设计是新增统一发布边界，把通过准入的证据卡、正式主题和关系记录发布到 `artifact_root`，而不是让两套流程同时写同一文件。

## 操作与控制

| 命令 | 用途 |
| --- | --- |
| `uv run hydro-platform run-once --json` | 扫描、制卡、候选主题、事件和日报的统一入口 |
| `uv run hydro-platform run-once --dry-run --json` | 只预览已有本机任务，不扫描、不调模型、不写入 |
| `uv run hydro-platform themes-run --json` | 显式推进候选主题池 |
| `uv run hydro-platform doctor --json` | 只读检查环境、账号、模板和路径 |
| `uv run hydro-platform recover --json` | 从 Zotero 和完整持久化成果重建派生运行状态 |
| `uv run hydro-platform schedule-status --json` | 读取本机计划任务和最近状态 |

当前团队配置的 `scheduler.enabled=true`，但“配置开启”不等于任意机器已安装计划任务，必须以 `schedule-status` 实机结果为准。调度、失败恢复、模型配置和验证证据分别见[每日调度](cron.md)、[运行一轮](run-once.md)、[配置](config.md)和[验证地图](tests.md)。
