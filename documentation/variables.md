# 配置、运行变量与密钥边界

“所有内容都放进一个配置文件”看似方便，但会把可调整参数、事实数据和秘密混成不可恢复也不可审计的一团。本项目采用一个总配置入口，但不把所有变量都当作配置。

| 类型 | 示例 | 保存位置 | 是否进入 Git |
|---|---|---|---|
| 团队级可调整配置 | 项目目录、运行区、证据包目录、证据卡模板与清单路径、Zotero 群组 ID、超时、分页大小、PDF 门禁阈值、任务租约和锁时长、制卡适配器及预检参数 | `config/config.json` | 是 |
| 本机覆盖配置 | 本机临时路径或不同端口 | `config/config.local.json` | 否 |
| 运行时状态 | 扫描快照、任务状态、锁、原始日志、试运行卡和可删除的临时处理文件 | `paths.runtime_dir` 指向的目录 | 否 |
| 证据事实 | 父条目/附件 Key、PDF 哈希、读取方式、来源检查、模型阅读声明、生成审计、版本与时间 | `manifest.json` 和 `quality-audit.json`；旧 MCP 才有页面交付回执 | 是 |
| 本机凭据与密钥 | Codex CLI 登录凭据、GitHub Token；未来可能使用的大模型 API Key | Codex 或操作系统凭据存储、环境变量 | 否 |
| 程序协议常量 | Zotero API 路由、事件名称、Schema 版本 | 代码及受版本控制的 Schema | 是 |

## 路径解析规则

1. `paths.project_root` 相对于总配置文件所在目录解析，也可以填写绝对路径；
2. 其余项目路径相对于 `project_root` 解析，也可以填写位于项目根目录内的绝对路径；
3. 所有项目路径不得逃出 `project_root`；
4. `snapshot_file`、`tasks_file`、`lock_file`、`logs_dir` 和 `card_trials_dir` 必须位于 `runtime_dir`；
5. `evidence_card_templates_dir` 必须位于 `templates_dir`，`evidence_card_template_catalog_file` 必须位于证据卡模板目录；
6. 配置中的环境变量会在启动时展开，但密钥不得通过路径配置间接写入仓库。
7. 所有路径字段必须显式存在；程序不会用散落在源码里的路径默认值补齐漏项。

## 当前限制

总配置驱动路径、Zotero、模板、模型和读取工具。当前 workflow_mode=single_agent；model、reasoning_effort、generation_timeout_seconds 直接控制一个会话。pdf_direct_trial 中的读取环境与正式路径读取共用，但实验的 prompt/schema/timeout 不用于制卡。

runtime_dir 下还保留 generation-drafts 未校验输出，仅用于故障排查，不供主题使用、不提交 Git。旧 multi_agent_workflow 仅用于旧模式，当前配置已移除；旧 MCP 专用字段在 local_path 下不执行。订阅总预算和每日频率限制尚未实现。账号凭据不得写入仓库。

## 新功能的配置验收规则

1. 凡是团队会主动调整且不敏感的参数，必须从 `config/config.json` 读取，不得写死在源码或计划任务命令中；
2. 新配置字段必须同时具有解析、类型或范围校验、使用该字段的实际代码、自动化测试和中文说明；
3. 配置只能选择已经实现并注册的适配器；填写未知适配器时必须启动失败，不能静默回退；
4. 路径、模型和工具切换后，不修改源码即可运行对应的已实现能力；
5. 密钥、账号凭据、运行状态和单篇文献事实不得因“可能变化”而被错误放入总配置；
6. 生效配置及其版本需要被运行日志和证据包 manifest 追溯，但不得把秘密写入其中。
