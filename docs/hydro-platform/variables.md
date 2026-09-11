# 配置、运行变量与密钥边界

“所有内容都放进一个配置文件”看似方便，但会把可调整参数、事实数据和秘密混成不可恢复也不可审计的一团。本项目采用一个总配置入口，但不把所有变量都当作配置。本页说明边界划分；逐字段含义、允许值和默认值见[总配置字段说明](config.md)。

| 类型 | 示例 | 保存位置 | 是否进入 Git |
|---|---|---|---|
| 团队级可调整配置 | 项目目录、运行区、证据包目录、证据卡模板与清单路径、**科研产物根（证据卡/主题/运行记录/文献链接的落点，可指向共享盘）**、Zotero 群组 ID、超时、分页大小、PDF 门禁阈值、任务租约和锁时长、制卡适配器及预检参数 | `hydro-platform/config/config.json` | 是 |
| 本机覆盖配置 | 本机临时路径或不同端口 | `hydro-platform/config/config.local.json` | 否 |
| 运行时状态 | 扫描快照、任务状态、锁、原始日志、试运行卡和可删除的临时处理文件 | `paths.runtime_dir` 指向的目录 | 否 |
| 证据事实 | 父条目/附件 Key、PDF 哈希、读取方式、来源检查、模型阅读声明、生成审计、版本与时间 | `manifest.json` 和 `quality-audit.json`；旧 MCP 才有页面交付回执 | 是 |
| 本机凭据与密钥 | Codex CLI 登录凭据、GitHub Token；未来可能使用的大模型 API Key | Codex 或操作系统凭据存储、环境变量 | 否 |
| 程序协议常量 | Zotero API 路由、事件名称、Schema 版本 | 代码及受版本控制的 Schema | 是 |

## 路径解析规则

`zotero.startup`由统一入口读取，作用域是制卡机，来源为总配置，不含密码、不需要密钥轮换。可执行程序路径只由维护者配置/安装目录定位，不接受模型输出；开关/等待时间在下一轮生效。运行环境和账号仍属外部前提；[字段与风险](zotero-readiness.md)。

本机配置需用 `--config hydro-platform/config/config.local.json`（或 HYDRO_PLATFORM_CONFIG）显式选择，并填写完整配置；当前没有自动覆盖/合并机制。

1. `paths.project_root` 相对于总配置文件所在目录解析，也可以填写绝对路径；
2. 其余项目路径相对于 `project_root` 解析，也可以填写位于项目根目录内的绝对路径；
3. 除下述第 8 条的科研产物根外，所有项目路径不得逃出 `project_root`；
4. `snapshot_file`、`tasks_file`、`lock_file`、`logs_dir` 和 `card_trials_dir` 必须位于 `runtime_dir`；
5. `evidence_card_templates_dir` 必须位于 `templates_dir`，`evidence_card_template_catalog_file` 必须位于证据卡模板目录；
6. 配置中的环境变量会在启动时展开，但密钥不得通过路径配置间接写入仓库。
7. 所有路径字段必须显式存在；程序不会用散落在源码里的路径默认值补齐漏项。
8. `artifact_root` 是科研产物（证据卡 / 主题 / 运行记录 / 文献链接）的总落点，**默认解析到工作区根（仓库根）**。它若位于 `project_root` 之外，必须同时显式写出 `artifact_root_external = true`，否则加载即报错；
9. `evidence_cards_dir`、`themes_vault_dir`、`run_records_dir`、`literature_index_dir` 均相对 `artifact_root` 解析，且必须位于 `artifact_root` 内。四者必须同属一个产物根——证据卡与主题互相引用，只挪其一会让相对定位失效；
10. 归属随位置划分：产物根在项目内 = 平台所有（可清理）；产物根在项目外（共享盘等）= 操作者所有，平台只写不清理。

部署配置 `deployment` 的 Python 字段见[项目依赖安装](deployment.md)，三个 native 字段见[PDF 工具安装](native-deployment.md)。新增字段有集中兼容默认值，实际配置/示例均显式列出；旧 `paths` 必填规则不变。相对可执行程序路径基于项目根目录，裸命令名按 PATH 查找。当前 PDF Python 为 uv 工作区共享的仓库根 `.venv`（`../.venv/Scripts/python.exe`，相对项目根），三个原生工具在 `hydro-platform/.tools/poppler/Library/bin/`，不再依赖旧 Windows 用户的解释器或 Codex 缓存绝对路径。[字段与默认值](config.md)。

## 配置与秘密风险

每日计划的 `scheduler.*` 参数来自同一总配置，使用者为本机注册器与日任务门控。Windows当前身份只在安装时解析，不将密码写入仓库/任务。计划名称归属、时间、重试上限及停用规则见 [cron.md](cron.md)；配置enabled=true不是安装证据，须查询Windows真实定义。运行进度是`.runtime/scheduler-state.json`，不是共享配置。

| 名称 | 使用者 / 范围 | 来源与更新 | 风险与处理 |
|---|---|---|---|
| `deployment.*`、依赖锁 | 本机安装器 | 总配置/锁文件；新环境验证 | 供应链输入；环境位于工作区根 `.venv` 时由 uv 托管（只校验），位于平台内时只安装核对后的 wheel/Poppler 包；不是密钥，不执行任意远程脚本 |
| `zotero.group_id/base_url` | 本机 Python | 总配置 | 错库/数据源风险；再次核对源身份，群组 ID 不是认证 |
| `card_generator.*` | 本机适配器 | 总配置；变更后检查 | 外部处理方/额度改变；不能填写未实现适配器 |
| Codex 登录信息 | 本机 CLI | 外部凭据存储；过期重新登录，泄露后撤销 | 不放 JSON/提示词/命令参数；项目不复制认证文件 |
| GitHub 令牌 | 操作者 Git | 外部凭据管理，泄露后轮换 | 日常链路不用、不主动推送；日志不得包含令牌 |
| 成员映射 | 事件记录/报告 | `hydro-platform/members/` 明确映射 | 可共享身份信息；无来源不猜身份 |

没有浏览器客户端包，不存在密钥打包进前端的路径；仓库、提示词和日志仍是泄露面，不能由此宣称完成秘密扫描。启用前核对 Git 暂存范围、忽略运行/环境/PDF目录、登录本机账号、检查共享库和处理方、验证恢复与实际触发。`config.local.json` 是完整替代配置，不是自动合并层。

## 当前限制

总配置驱动路径、Zotero、模板、模型和读取工具。当前 workflow_mode=single_agent；model、reasoning_effort、generation_timeout_seconds 直接控制一个会话。pdf_direct_trial 中的读取环境与正式路径读取共用，但实验的 prompt/schema/timeout 不用于制卡。

runtime_dir 下还保留 generation-drafts 未校验输出，仅用于故障排查，不供主题使用、不提交 Git。旧 multi_agent_workflow 仅用于旧模式，当前配置已移除；旧 MCP 专用字段在 local_path 下不执行。订阅总预算和每日频率限制尚未实现。账号凭据不得写入仓库。

## 新功能的配置验收规则

1. 凡是团队会主动调整且不敏感的参数，必须从 `hydro-platform/config/config.json` 读取，不得写死在源码或计划任务命令中；
2. 新配置字段必须同时具有解析、类型或范围校验、使用该字段的实际代码、自动化测试和中文说明；
3. 配置只能选择已经实现并注册的适配器；填写未知适配器时必须启动失败，不能静默回退；
4. 路径、模型和工具切换后，不修改源码即可运行对应的已实现能力；
5. 密钥、账号凭据、运行状态和单篇文献事实不得因“可能变化”而被错误放入总配置；
6. 生效配置及其版本需要被运行日志和证据包 manifest 追溯，但不得把秘密写入其中。
