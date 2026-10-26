# 总配置字段说明

日常只编辑完整总配置，不改源码。默认使用 `hydrolitagent/cards/assets/config/config.json`；`hydrolitagent/cards/assets/config/config.example.json` 是可复制的完整示例。私人配置必须显式用 --config 或 HYDROLITAGENT_CARDS_CONFIG 选择，不自动合并。字段与数据的边界划分（哪些属于配置、哪些属于运行状态、证据事实或密钥）见 [配置与密钥边界](variables.md)；目录与存储概览回到[文档入口](../../user-guide/cards/index.md)。

`config.json` 是自动化唯一的团队级总配置入口。需要迁移目录、更换 Zotero 本地接口或调整制卡参数时，只修改这个文件，不修改程序源码。所有路径字段必须显式填写；缺失时程序直接报配置错误，不使用源码中的隐含目录默认值。

`paper-input` 是例外：它只按 `configs/paper-input.toml` 读取 `zotero` + `pdf_gate` 两表，不加载模型配置，也不读取 `HYDROLITAGENT_CARDS_CONFIG`。详见[单篇论文输入](../../user-guide/cards/paper-input.md)。

## 路径

`paths.project_root` 相对于 `config.json` 所在目录解析；其余路径相对于 `project_root` 解析。因此，从仓库外部工作目录调用程序时，产物仍会写入正确项目。为避免误写，所有项目路径必须位于 `project_root` 内，运行状态和原始日志还必须位于 `runtime_dir` 内。当前 `paths.project_root` 为 `../../../..`，即仓库根目录。

**唯一例外是科研产物根 `paths.artifact_root`**（证据卡 / 主题 / 运行记录 / 文献链接的落点）。它默认解析到工作区根（仓库根）。若要指向仓库外的共享位置（共享盘、OneDrive 等），必须同时显式写出 `paths.artifact_root_external = true`。这样外部位置是写明的意图，而不是被 `../outside` 这类相对路径悄悄带出去的。归属也随之划分：**产物根在项目内 = 平台所有**（正常写入、可清理）；**产物根在项目外 = 操作者所有**（平台只写不清理，不管理其生命周期）。

科研产物根字段：

| 字段 | 当前含义 | 默认值 | 规则 |
|---|---|---|---|
| `paths.artifact_root` | 科研产物总落点（证据卡、主题、运行记录、文献链接的共同父目录） | `../`，即工作区根（仓库根） | 位于 `project_root` 之外时必须显式开启下一行的开关 |
| `paths.artifact_root_external` | 是否允许产物根位于项目之外（共享盘场景） | `false`（本仓库配置为 `true`） | 布尔值；未开启时产物根超出 `project_root` 直接报错 |
| `paths.evidence_cards_dir` | 证据卡目录 | `证据卡` | 必须位于 `artifact_root` 内 |
| `paths.themes_vault_dir` | 主题档案目录 | `主题` | 必须位于 `artifact_root` 内 |
| `paths.run_records_dir` | 主题工作流运行账目录 | `运行记录` | 必须位于 `artifact_root` 内 |
| `paths.literature_index_dir` | 来源链接索引目录 | `文献链接` | 必须位于 `artifact_root` 内 |

四个子目录必须同属一个 `artifact_root`：证据卡与主题之间存在交叉引用，只把其中一个挪到别处会让相对定位失效。

证据卡模板路径：

| 字段 | 当前含义 | 规则 |
|---|---|---|
| `paths.templates_dir` | 所有公共模板的根目录 | 必须位于项目根目录内 |
| `paths.evidence_card_templates_dir` | 九类证据卡 Markdown 模板目录 | 必须位于 `templates_dir` 内 |
| `paths.evidence_card_template_catalog_file` | 模板来源、版本和内容哈希清单 | 必须位于证据卡模板目录内 |
| `paths.evidence_card_generation_prompt_file` | 正式制卡提示词 | 必须位于 `paths.prompts_dir` 内，并声明 `prompt_version` |
| `paths.card_generation_output_schema_file` | 模型结构化输出约束 | 必须位于 `paths.schemas_dir` 内 |
| `paths.card_trials_dir` | 制卡试运行结果 | 必须位于 `paths.runtime_dir` 内，不提交 Git |

目录位置可以调整，但不得将证据卡模板或清单配置到项目之外。

## Zotero

`zotero`：本地 API 地址（默认 `http://127.0.0.1:23119`）、目标文库或共享群组 ID、HTTP 超时和进程检查超时。`paper-input --user-library` 只读个人库；需要群组库时才填写 `group_id` 并改用 `--group-id`。群组 ID 不是密钥，可以进入 Git。

## PDF 门禁

`pdf_gate`：最小 PDF 体积、最小可提取文字数和计算哈希时的分块大小。门禁不通过时停止并说明原因，不生成草稿。

## 制卡字段 card_generator

当前 `card_generator` 字段说明：

| 字段 | 当前含义 | 允许值或规则 |
|---|---|---|
| `workflow_mode` | 制卡编排方式 | 当前 `single_agent`；单 Agent 必须移除 `multi_agent_workflow` |
| `adapter` | 旧版 PDF 直读管线用的适配器名（兼容键） | 当前只能是 `codex_cli`；Markdown 管线的运行器由 `configs/ai.toml` 的 `provider`（别名 `runner`）经注册表选择，不看这个字段 |
| `executable` | 要查找和运行的 Codex CLI 命令名或路径 | 默认为 `codex`；非空字符串 |
| `auth_mode` | 本阶段能够确认的认证方式 | 当前只能是 `chatgpt_account` |
| `preflight_timeout_seconds` | 版本和登录状态两项检查各自的最长等待秒数 | 大于 0 |
| `model` | 单 Agent 制卡模型 | `null` 表示使用 Codex 内置默认；也可填写非空模型名称 |
| `reasoning_effort` | 单 Agent 思考强度 | `null` 表示使用模型默认；可选 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`，实际支持范围取决于模型 |
| `generation_timeout_seconds` | 单 Agent 一次模型会话的最长等待秒数 | 大于 0；当前为 1500，即 25 分钟 |
| `progress.enabled` | 制卡是否显示 stderr 实时进度 | `true` / `false`；默认 `true`；`--no-progress` 可关闭本次显示 |
| `progress.heartbeat_interval_seconds` | 定期报告等待状态的间隔 | 1–300 秒；默认及当前值为 60；不改变模型超时和重试策略 |

`progress` 在旧配置中整体缺失时使用上述默认值；一旦填写，必须同时提供两个字段。心跳表示本地程序仍在等待，不证明远端模型健康。进度不会写入最终 JSON，也不会回显模型正文、原始工具输出或凭据。

`card_generator.workflow_mode=single_agent` 是当前模式，主提示词 `evidence-card-generation-v8.md`、九类模板。模型、强度和超时直接用上表。程序只检验流程，不校验正文标题、表格、标签、编号或措辞。

例如，使用 GPT-5.6 Sol 和高推理强度：

```json
"model": "gpt-5.6-sol",
"reasoning_effort": "high"
```

程序会把显式推理强度转换为 Codex CLI 的 `--config model_reasoning_effort="..."` 参数。配置校验只能防止未知档位和拼写错误；账号是否能使用指定模型、该模型是否支持指定档位，必须由真实生成验收。

`card_generator.connection_guard` 是 Python 对每个制卡子进程实施的停止保护，不依赖 CLI 自身的重试次数，也不受 `progress.enabled` 或 `--no-progress` 影响：

| 字段 | 当前配置 / 示例值 | 含义与边界 |
|---|---|---|
| `reconnect_stop_enabled` | `false` | 是否因重连次数或恢复超时停止；必须为布尔值。当前关闭，仅记录重连状态 |
| `reconnect_event_limit` | `10` | 仅在开关为 `true` 时生效：同一角色累计收到第 10 条重连事件时停止 |
| `recovery_timeout_seconds` | `300` | 仅在开关为 `true` 时生效：每次进入断线状态后等待进展恢复的最长秒数 |
| `idle_timeout_seconds` | `1500` | 无可识别进展事件的最长秒数；1–3600；当前与单 Agent 总时限同为 25 分钟 |
| `pdf_tool_call_limit` | `2` | 每个角色的整篇 PDF 工具调用预算；1–5；检测到超额后终止子进程，防止反复整篇回传 |

填写本节时必须包含全部四个限额字段，`reconnect_stop_enabled` 可选；即使关闭也不接受非法限额值。修改后从下一次启动命令生效，不热更新已运行的子进程。这不改变 Codex/ChatGPT 桌面客户端自身的重连行为，也不保证网络恢复。

失败诊断由 CLI 保存到 `paths.logs_dir`（默认 `.runtime/logs`），最终 JSON 的 `diagnostic_log_path` 给出位置。只保存已脱敏的公开错误和上下文，不保存原始事件、提示词或论文全文；日志不提交 Git。日志目录不可写时保留原失败结果并给出 `diagnostic_log_warning`。

## 本地 PDF 读取方式

`card_generator.pdf_reader` 字段说明：

| 字段 | 当前含义 | 允许值或规则 |
|---|---|---|
| `adapter` | 原始 PDF 的读取方式 | 当前 `local_path`；与工作流协议版本配套，不自动回退 |
| `server_name` | 本次调用中注册的 MCP 服务名 | 只能含字母、数字、下划线和连字符（历史字段，`local_path` 下不生效） |
| `python_executable` | 启动项目内置 MCP 的 Python | `null` 表示复用运行入口的解释器（历史字段） |
| `server_file` | 项目内置 PDF MCP 服务脚本 | 相对 `paths.project_root` 解析，且必须位于项目内（历史字段） |
| `pdfinfo_executable` | 获取 PDF 页数的程序 | 命令名、项目相对路径或绝对路径 |
| `pdftotext_executable` | 逐页提取文字的程序 | 命令名、项目相对路径或绝对路径 |
| `pdftoppm_executable` | 逐页渲染页面图像的程序 | 命令名、项目相对路径或绝对路径 |
| `render_dpi` | 页面图像渲染分辨率 | 72–300；当前为 120 |
| `max_pages_per_call` | 完整读取工具内部每批处理多少页 | 1–10；当前为 4 |
| `output_token_limit` | 完整 PDF 工具结果的输出预算 | 大于 0 且不超过 200000；当前为 60000 |
| `startup_timeout_seconds` | MCP 启动超时 | 大于 0（历史字段） |
| `tool_timeout_seconds` | 单次工具调用及底层 PDF 工具的超时上限 | 大于 0 |

当前配置与示例均使用项目相对工具路径 `.tools/poppler/Library/bin/`，PDF Python 使用仓库根 `.venv`（`.venv/Scripts/python.exe`，相对项目根），由 `uv sync --all-packages` 恢复。也支持明确配置已有工具路径；改目录时须同步对应字段，不需要改 Python 源码。

`card_generator.pdf_direct_trial` 对象名为兼容历史保留，其运行环境字段（`windows_sandbox`、`shell_executable`、`python_executable`、`text_extractor`、`preflight_timeout_seconds`）与正式路径读取共用；该对象中的 `prompt_file`、`schema_file`、`timeout_seconds` 不用于正式制卡。

父条目 Key、附件 Key、PDF 哈希、任务状态和运行时间不是配置，它们由系统运行时写入 `.runtime/` 或草稿记录。API 路由、事件类型和数据结构版本属于程序协议，也不是用户路径配置。详细边界见 [variables.md](variables.md)。

## Codex 子进程独立代理

`card_generator.proxy` 只影响本平台启动的 Codex CLI 子进程环境，不修改 Python 主进程的 `os.environ`、系统/用户环境变量、Windows 系统代理或 Codex 个人配置，也不重启客户端。Zotero 本地 API 与其他独立程序保持原有网络设置。

| 字段 | 含义与修改方法 |
|---|---|
| `enabled` | `true`：只对子进程显式设置代理；`false`：恢复原来的环境继承方式，不等于强制直连 |
| `url` | 本机代理软件的 HTTP/HTTPS 监听地址，须含端口；换端口只改此处。启用时必填；关闭时可为 `null` |
| `no_proxy` | 额外直连主机名/IP 数组；本机三项始终补齐，避免本地流量外送 |

启用时，程序在传给 Codex 子进程的环境副本中设置大小写两套 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`WS_PROXY`、`WSS_PROXY`，并以本节覆盖该子进程的 `NO_PROXY`。换机请填写新机器的代理端口或设置 `enabled=false`。不要把节点订阅链接、带用户名/密码或令牌的 URL 写入 Git；配置会拒绝这些 URL，错误消息不回显输入。

## 主题池 theme_pipeline

`theme_pipeline.enabled=true` 已开启主题入口。`research_goal=null` 表示无预设目标；`model`、`reasoning_effort`、`timeout_seconds` 为 null 时继承 `card_generator` 对应设置。`assets_dir` 指定主题模板与 schema 的目录，默认 `hydrolitagent/cards/assets/templates/themes`。结果目录沿用 `paths.themes_dir`，定向精读保存在各论文记录下。模型/目标/模板内容变化产生新的 CHANGE 记录。[现行规则](../../user-guide/cards/unified-theme-pool.md)。

## 不要加「假配置」

`config.json` 的**每一个**顶层节都被 `config.py` 解析 —— 当前是 `schema_version`、`paths`、
`zotero`、`pdf_gate`、`tasks`、`pipeline`、`theme_pipeline`、`card_generator` 八个。
**没有**只作 schema 兼容、无人读取的遗留节。

**不要添加程序不读取的「假配置」来冒充已有能力**；新增配置项必须和对应的解析校验、功能实现、
测试及本说明**同时交付**。

Qinjiajun 目标库的群组 ID 保存在可复现的 `hydrolitagent/cards/assets/config/config.json` 中；群组 ID 不是密钥，可以进入 Git。

`hydrolitagent/cards/assets/config/config.example.json` 用于解释配置结构。只有本机需要覆盖团队配置时，才复制为被 Git 忽略的 `hydrolitagent/cards/assets/config/config.local.json`。`config.local.json` 是完整的另一份配置，不会被自动发现，也不会与 `config.json` 合并；使用时显式传入 `--config hydrolitagent/cards/assets/config/config.local.json`，或令 `HYDROLITAGENT_CARDS_CONFIG` 指向该文件。

## 密钥与配置验收边界

Codex 登录凭据、Zotero API Key、GitHub Token 等秘密只能存放在本机凭据存储或环境变量中，不得提交到仓库。`config.json` 最多记录所使用的凭据类型或环境变量名称，不能记录秘密本身。

新增配置字段必须同时具有解析、类型或范围校验、使用该字段的实际代码、自动化测试和中文说明；配置只能选择已经实现并注册的适配器，填写未知适配器时必须启动失败，不能静默回退。

## 科研产物路径与当前边界

配置同时保留**两组**产物路径：

- **单篇流程**写入 `--output-root`（默认仓库 `outputs/`），**主题池**写入 `paths.themes_dir`。
- `paths.artifact_root` 及其下的 `证据卡/`、`主题/`、`运行记录/`、`文献链接/` **已能解析和校验**，
  可指向仓库根或显式允许的外部共享位置，但**自动化发布尚未接入这四个目录**。

所有实际科研产物、原始 PDF、Zotero 数据库、`.runtime` 和本机路径均**不进入 Git**。
目标是在两组目录之间建立明确的准入与发布边界，再把 `artifact_root` 作为 Obsidian 阅读层 ——
**不应把当前的配置字段理解为两套工作流已经打通**。

相关：[自动化边界](automation.md) · [项目级设计](project-design.md)
