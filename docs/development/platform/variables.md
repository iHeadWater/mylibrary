# 配置、运行变量与密钥边界

“所有内容都放进一个配置文件”看似方便，但会把可调整参数、事实数据和秘密混成不可恢复也不可审计的一团。本项目采用一个总配置入口，但不把所有变量都当作配置。本页说明边界划分；逐字段含义、允许值和默认值见[总配置字段说明](config.md)。

| 类型 | 示例 | 保存位置 | 是否进入 Git |
|---|---|---|---|
| 团队级可调整配置 | 项目目录、运行区、证据卡模板与清单路径、**科研产物根（证据卡/主题/运行记录/文献链接的落点，可指向共享盘）**、Zotero 群组 ID、超时、PDF 门禁阈值、制卡适配器及运行参数 | `hydro-platform/config/config.json` | 是 |
| 本机覆盖配置 | 本机临时路径或不同端口 | `hydro-platform/config/config.local.json` | 否 |
| 运行时状态 | 运行区、锁、原始日志和可删除的临时处理文件 | `paths.runtime_dir` 指向的目录 | 否 |
| 证据事实 | 父条目/附件 Key、PDF 哈希、读取方式、来源检查、模型阅读声明、生成审计、版本与时间 | 草稿记录与 `validation.json` | 是 |
| 本机凭据与密钥 | Codex / Claude CLI 登录凭据、GitHub Token；未来可能使用的大模型 API Key | 凭据存储、环境变量 | 否 |
| 程序协议常量 | Zotero API 路由、事件名称、Schema 版本 | 代码及受版本控制的 Schema | 是 |

## 路径解析规则

本机配置需用 `--config hydro-platform/config/config.local.json`（或 HYDRO_PLATFORM_CONFIG）显式选择，并填写完整配置；当前没有自动覆盖/合并机制。

1. `paths.project_root` 相对于总配置文件所在目录解析，也可以填写绝对路径；
2. 其余项目路径相对于 `project_root` 解析，也可以填写位于项目根目录内的绝对路径；
3. 除下述第 8 条的科研产物根外，所有项目路径不得逃出 `project_root`；
4. `lock_file`、`logs_dir` 和 `card_trials_dir` 必须位于 `runtime_dir`；
5. `evidence_card_templates_dir` 必须位于 `templates_dir`，`evidence_card_template_catalog_file` 必须位于证据卡模板目录；
6. 配置中的环境变量会在启动时展开，但密钥不得通过路径配置间接写入仓库；
7. 所有路径字段必须显式存在；程序不会用散落在源码里的路径默认值补齐漏项；
8. `artifact_root` 是科研产物（证据卡 / 主题 / 运行记录 / 文献链接）的总落点，**默认解析到工作区根（仓库根）**。它若位于 `project_root` 之外，必须同时显式写出 `artifact_root_external = true`，否则加载即报错；
9. `evidence_cards_dir`、`themes_vault_dir`、`run_records_dir`、`literature_index_dir` 均相对 `artifact_root` 解析，且必须位于 `artifact_root` 内。四者必须同属一个产物根——证据卡与主题互相引用，只挪其一会让相对定位失效；
10. 归属随位置划分：产物根在项目内 = 平台所有（可清理）；产物根在项目外（共享盘等）= 操作者所有，平台只写不清理。

相对可执行程序路径基于项目根目录，裸命令名按 PATH 查找。当前 PDF Python 为 uv 工作区共享的仓库根 `.venv`（`../.venv/Scripts/python.exe`，相对项目根），三个原生工具在 `hydro-platform/.tools/poppler/Library/bin/`。[字段与默认值](config.md)。

## 配置与秘密风险

| 名称 | 使用者 / 范围 | 来源与更新 | 风险与处理 |
|---|---|---|---|
| `paths.*`、模板与清单路径 | 本机 Python | 总配置；迁移目录时同步 | 越界路径必须报错，不能逃出项目根或产物根 |
| `zotero.group_id/base_url` | 本机 Python | 总配置 | 错库/数据源风险；再次核对源身份，群组 ID 不是认证 |
| `card_generator.*` | 本机适配器 | 总配置；变更后检查 | 外部处理方/额度改变；不能填写未实现适配器 |
| Codex / Claude 登录信息 | 本机 CLI | 外部凭据存储；过期重新登录，泄露后撤销 | 不放 JSON/提示词/命令参数；项目不复制认证文件 |
| GitHub 令牌 | 操作者 Git | 外部凭据管理，泄露后轮换 | 日常链路不用、不主动推送；日志不得包含令牌 |

没有浏览器客户端包，不存在密钥打包进前端的路径；仓库、提示词和日志仍是泄露面，不能由此宣称完成秘密扫描。`config.local.json` 是完整替代配置，不是自动合并层。

## 当前限制

总配置驱动路径、Zotero、模板、模型和读取工具。当前 `workflow_mode=single_agent`；`model`、`reasoning_effort`、`generation_timeout_seconds` 直接控制一个会话。`card_generator.pdf_direct_trial` 中的读取环境与正式路径读取共用。运行区下保留未校验的模型输出，仅用于故障排查，不供主题使用、不提交 Git。账号凭据不得写入仓库。

## 新功能的配置验收规则

1. 凡是团队会主动调整且不敏感的参数，必须从 `hydro-platform/config/config.json` 读取，不得写死在源码中；
2. 新配置字段必须同时具有解析、类型或范围校验、使用该字段的实际代码、自动化测试和中文说明；
3. 配置只能选择已经实现并注册的适配器；填写未知适配器时必须启动失败，不能静默回退；
4. 路径、模型和工具切换后，不修改源码即可运行对应的已实现能力；
5. 密钥、账号凭据、运行状态和单篇文献事实不得因“可能变化”而被错误放入总配置；
6. 生效配置及其版本需要被运行日志和草稿记录追溯，但不得把秘密写入其中。
