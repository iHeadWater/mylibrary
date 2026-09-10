# 总配置字段说明

日常只编辑完整总配置，不改源码。默认使用 `hydro-platform/config/config.json`；`hydro-platform/config/config.example.json` 是可复制的完整示例。私人配置必须显式用 --config 或 HYDRO_PLATFORM_CONFIG 选择，不自动合并。字段与数据的边界划分（哪些属于配置、哪些属于运行状态、证据事实或密钥）见 [配置与密钥边界](variables.md)；目录与存储概览回到[文档入口](index.md)。

## 关键事件与日报

`activity_reporting.enabled=true` 让 run-once 在制卡前后记录关键事件并在结束后生成日报，不额外调用AI；`utc_offset_minutes=480` 按UTC+08:00划分日期，`system_actor_id=SYS-CARD-01` 标记系统行为。根目录分别使用 paths.activity_dir、paths.members_dir、paths.reports_dir。显式的 activity-sync / daily-report 命令可独立执行。[完整说明](activities-and-daily-report.md)。本项不是每日触发器；本机已注册的定时计划由scheduler配置。

`zotero.startup`控制统一入口的应用启动和有限等待：当前enabled=true、launch_if_missing=true、executable=null、wait_timeout_seconds=120、poll_interval_seconds=5。null按PATH/常用目录查找，也可填zotero.exe路径；不附加参数，不改账号/同步设置。doctor只核对路径、不启动。旧配置缺本节默认关闭。[字段、关闭方法与待PDF补查](zotero-readiness.md)。

## 统一主题池

`theme_pipeline.enabled=true` 已开启完整入口后半段。`research_goal=null` 表示无预设目标；`model`、`reasoning_effort`、`timeout_seconds` 为 null 时继承 card_generator 对应设置。`assets_dir` 指定主题模板与 schema 的目录，默认 `hydro-platform/templates/themes`，当前包含 discovery、pool-discovery、focused-reading、refinement。结果目录沿用 paths.themes_dir，定向精读保存在各论文证据包 readings/ 下。模型/目标/模板内容变化产生新的 CHANGE 记录，仍使用统一主题池；候选更新沿用编号，合并/拆分另建编号，适用旧精读可复用。[现行规则](unified-theme-pool.md)。

## 统一入口限额（US-11A）

`pipeline` 默认 `max_items_per_run=null`、`max_run_seconds=null`：一次命令处理本轮扫描到的全部可制卡论文，无需按篇数修改配置。只有主动限制一次运行的规模/时长时才填正整数，旧配置中的明确限额仍会遵守。`max_attempts_per_item=3`（当前输入累计次数含首次）、`retry_cooldown_seconds=3600`（暂时性失败后冷却）仍必须是正整数。省略字段采用默认值，未知字段拒绝；单篇模型超时仍由 `card_generator.generation_timeout_seconds` 控制。详见 [统一入口](run-once.md)。

整轮锁和待保存记录的目录由 `paths.lock_file` 派生，摘要由 `paths.logs_dir` 派生，均位于配置的 `runtime_dir`；没有写死某台电脑的盘符。每日时间、补查与启停已经由 scheduler 配置；修改 Windows 触发定义后需 schedule-install，不能把配置已填等同于计划已注册。

`config.json` 是自动化唯一的团队级总配置入口。需要迁移目录、更换 Zotero 本地接口、调整扫描参数时，只修改这个文件，不修改程序源码。所有路径字段必须显式填写；缺失时程序直接报配置错误，不使用源码中的隐含目录默认值。

制卡、主题、部署、调度及摘要的可调整参数已经集中在总配置；以后增加新适配器等能力时也必须由配置与实现共同交付。当前没有自动 Git 同步，普通运行不会提交或推送。新增配置项必须和对应的解析校验、功能实现、测试及本说明同时交付；禁止先放入程序并不读取的“假配置”。

配置只能在程序已经实现的能力之间切换。例如将制卡后端从 `codex_cli` 改为另一种适配器，前提是仓库中已经存在并测试过该适配器；任意填写一个 API 名称不能凭空获得相应能力，程序必须对不支持的值立即报错。

其中 `paths.project_root` 相对于 `config.json` 所在目录解析；其余路径相对于 `project_root` 解析。因此，从仓库外部工作目录调用程序时，产物仍会写入正确项目。为避免误写，所有项目路径必须位于 `project_root` 内，运行快照、任务、锁和原始日志还必须位于 `runtime_dir` 内。当前 `paths.project_root` 为 `..`，即 `hydro-platform/` 目录本身。

当前可配置项：

- `paths`：项目根目录、运行区、快照、任务、锁、日志、试运行结果，以及证据包、模板、证据卡模板目录、模板清单、主题、成员、事件、报告、提示词和数据结构目录；
- `zotero`：本地 API 地址、目标共享群组 ID、HTTP 超时和进程检查超时；
- `scan.page_size`：每页读取条目数；
- `pdf_gate`：最小 PDF 体积、最小可提取文字数和计算哈希时的分块大小；
- `tasks`：处理租约时长、死锁恢复时间和每篇论文保留的最大状态历史条数。
- `card_generator`：制卡提供者、Codex CLI/认证/模型/推理强度/超时、本机 PDF 读取方式、共用读取环境及 workflow_mode。

证据卡模板路径：

| 字段 | 当前含义 | 规则 |
|---|---|---|
| `paths.templates_dir` | 所有公共模板的根目录 | 必须位于项目根目录内 |
| `paths.evidence_card_templates_dir` | 八类证据卡 Markdown 模板目录 | 必须位于 `templates_dir` 内 |
| `paths.evidence_card_template_catalog_file` | 模板来源、版本和内容哈希清单 | 必须位于证据卡模板目录内 |
| `paths.evidence_card_generation_prompt_file` | 正式制卡提示词 | 必须位于 `paths.prompts_dir` 内，并声明 `prompt_version` |
| `paths.card_generation_output_schema_file` | Codex 结构化输出约束 | 必须位于 `paths.schemas_dir` 内 |
| `paths.card_trials_dir` | 既有卡制卡试运行结果 | 必须位于 `paths.runtime_dir` 内，不提交 Git |

修改路径后可运行 `uv run hydro-platform evidence-templates-validate --json` 验证。目录位置可以调整，但不得将证据卡模板或清单配置到项目之外。

其他已启用配置类别：

- `theme_pipeline`：全池主题规划、研究目标和模型继承；
- `pipeline`：整轮数量/时间限额、逐条重试次数与冷却；
- `activity_reporting`：关键事件和日报、系统身份、日期时区；
- `deployment`：项目 Python/PDF 工具与下载/依赖锁；
- `scheduler`：每日运行时间、补跑和并发规则。

尚未实现任意提供者 API、总 token 预算、自动 Git 同步或可配置的日报清理策略；不要添加程序不读取的配置冒充已有能力。

Codex 登录凭据、Zotero API Key、GitHub Token 等秘密只能存放在制卡机本地凭据存储或环境变量中，不得提交到仓库。`config.json` 最多记录所使用的凭据类型或环境变量名称，不能记录秘密本身。

## Codex 子进程独立代理

`card_generator.proxy` 只影响本平台启动的 Codex CLI 子进程环境，不修改 Python 主进程的 `os.environ`、系统/用户环境变量、Windows 系统代理、Clash/TUN、Codex 个人配置或客户端，也不重启客户端。Zotero 本地 API 与其他独立程序保持原有网络设置。Codex 内部启动的后代进程可能继承该环境，原有工具网络沙箱仍保留。

当前制卡机已配置为读取到的 Clash 本地 HTTP 监听地址；不是模型服务/API 地址：

```json
"proxy": {
  "enabled": true,
  "url": "http://127.0.0.1:7897",
  "no_proxy": ["localhost", "127.0.0.1", "::1"]
}
```

| 字段 | 含义与修改方法 |
|---|---|
| `enabled` | `true`：只对子进程显式设置代理；`false`：恢复原来的环境继承方式，不等于强制直连。旧配置缺失本节也按 `false` 处理 |
| `url` | 本机代理软件的 HTTP/HTTPS 监听地址，须含端口；换端口只改此处。启用时必填；关闭时可为 `null`。当前不支持 SOCKS-only 地址 |
| `no_proxy` | 额外直连主机名/IP 数组；本机三项始终补齐，避免本地流量外送。不能填 URL、逗号拼接字符串或 `*` |

启用时，程序在传给 Codex 子进程的环境副本中设置大小写两套 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`WS_PROXY`、`WSS_PROXY`，并以本节覆盖该子进程的 `NO_PROXY`。这样不会因原终端存在 `NO_PROXY=*` 而绕过显式代理。关闭时不删除终端已有的代理配置。

正式制卡、制卡试运行、PDF 直读实验、主题生成/修订/定向精读及 `generator-smoke-test` 共用本项。下次启动命令生效；不会热更新或中断已经运行的客户端、队列。自动调度的下一轮也会读取它。不改模型、推理强度、超时、重试次数和账号登录方式。

`generator-preflight --json` 返回的 `proxy` 只展示配置及作用范围，`connectivity_verified=false` 表示**没有验证到模型服务的连通性**。这项改动不能保证消除重连、降低单篇处理时间或修复节点故障。代理未启动/端口错误时不会自动删掉显式配置并改走另一出口。

换机请填写新机器的代理端口或设置 `enabled=false`；示例配置默认关闭且地址为 `null`，不强迫新机器使用这台电脑的端口。不要把节点订阅链接、带用户名/密码或令牌的 URL 写入 Git；配置会拒绝这些 URL，错误消息不回显输入。

## 制卡字段

当前 `card_generator` 字段说明：

| 字段 | 当前含义 | 允许值或规则 |
|---|---|---|
| `workflow_mode` | 制卡编排方式 | 当前 single_agent；兼容旧 multi_agent，不自动回退；单 Agent 必须移除 multi_agent_workflow |
| `adapter` | Python 调用哪一种制卡运行时适配器 | 当前只能是 `codex_cli` |
| `executable` | 要查找和运行的 Codex CLI 命令名或路径 | 默认为 `codex`；非空字符串 |
| `auth_mode` | 本阶段能够确认的认证方式 | 当前只能是 `chatgpt_account` |
| `preflight_timeout_seconds` | 版本和登录状态两项检查各自的最长等待秒数 | 大于 0 |
| `model` | 单 Agent 制卡及探针模型 | `null` 表示使用 Codex 内置默认；也可填写非空模型名称 |
| `reasoning_effort` | 单 Agent 制卡及探针思考强度 | `null` 表示使用模型默认；可选 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`，实际支持范围取决于模型 |
| `smoke_test_timeout_seconds` | US-07B1 单次最小模型调用的最长等待秒数 | 大于 0；当前为 120 |
| `generation_timeout_seconds` | 单 Agent 一次模型会话的最长等待秒数 | 大于 0；当前为 1500，即 25 分钟 |
| `progress.enabled` | 正式制卡及试运行是否显示 stderr 实时进度 | `true` / `false`；默认 `true`；`--no-progress` 可关闭本次显示 |
| `progress.heartbeat_interval_seconds` | 无论是否收到模型事件，定期报告等待状态的间隔 | 1–300 秒；默认及当前值为 60；不改变模型超时和重试策略 |

`progress` 在旧配置中整体缺失时使用上述默认值；一旦填写，必须同时提供两个字段。当前进度包含 1/1 单 Agent 启动、工具调用、流程检查和最终保存状态，不含归因或正文结构检查。心跳表示本地程序仍在等待，不证明远端模型健康。进度不会写入最终 JSON，也不会回显模型正文、原始工具输出或凭据。

2026-09-09 最新要求：本机配置、示例和缺省心跳统一改为 60 秒。只减少周期性的“等待中”提示；工具开始/结束、单篇保存、错误等实际事件仍立即显示。下次启动命令生效，不热更新现有队列。显式填写其他合法间隔的自定义配置仍按其原值执行。`run-once` 结尾独立显示“整轮汇总”，按本轮新完成、恢复、跳过、失败、阻塞、等待和延后分别统计，并列出未完成项与主题状态，不沿用最后一篇的保存阶段。

`card_generator.workflow_mode=single_agent` 是当前模式，主提示词 evidence-card-generation-v8.md、八类模板 1.1.0。模型、强度和超时直接用上表。v8 保留详细写作要求，但保存只检验流程，不校验正文标题、表格、标签、编号或措辞；没有另一个需要用户开启的“宽松模式”。当前配置与示例已更新，仍使用 run-once。草稿预览目录由 `paths.card_trials_dir` 控制。

旧配置未填 workflow_mode 时按 multi_agent 解释，必须提供完整 multi_agent_workflow，且 local_path/v2 或 project_mcp/v1 配套。当前 single_agent 要求 local_path，若仍提供 multi_agent_workflow 则配置报错，避免看似生效的角色设置误导；不会自动回退。未知提供者仍报错，不凭空支持任意 API。

`card_generator.connection_guard` 是 Python 对每个制卡 Agent 子进程实施的停止保护，不依赖 Codex 自身的重试次数，也不受 `progress.enabled` 或 `--no-progress` 影响：

| 字段 | 当前配置 / 示例值 | 含义与边界 |
|---|---|---|
| `reconnect_stop_enabled` | `false` | 是否因重连次数或恢复超时停止；必须为布尔值。当前关闭，仅记录重连状态，不执行下面两项停止条件；不关闭其他保护。旧配置不填此字段时为 `true` |
| `reconnect_event_limit` | `10` | 仅在开关为 `true` 时生效：同一角色累计收到第 10 条重连事件时停止；1–10 的整数；不是底层 TCP 尝试次数，中间工具返回不会清零计数 |
| `recovery_timeout_seconds` | `300` | 仅在开关为 `true` 时生效：每次进入断线状态后等待模型进展恢复的最长秒数；1–300；再次重连、心跳和本地工具返回不延长这个期限 |
| `idle_timeout_seconds` | `1500` | 无可识别进展事件的最长秒数；1–3600；当前与单 Agent 总时限同为 25 分钟。不是模型思考计时器 |
| `pdf_tool_call_limit` | `2` | 每个角色的整篇 PDF 工具调用预算；1–5 的整数；检测到超额调用开始事件后终止子进程，防止反复整篇回传 |

2026-09-08 按用户要求关闭 `reconnect_stop_enabled`，当时无进展/会话上限为 1200 秒；2026-09-09 最新要求将两项同时延长至 1500 秒。`10 / 300` 仍保存以便重新启用，但开关为 `false` 时不会因这两项终止。当前单 Agent 总时限为 25 分钟，不因重连重新计时；总超时、无进展时限、PDF 调用预算等仍生效，先触发者停止。底层 CLI 如果自行退出、`turn.failed` 或输出无效，仍按失败处理；没有新增会话内自动重跑机制。延长时间不保证连接恢复，逐条重试仍受 pipeline 冷却和次数约束。

旧配置整体缺失本节时，程序仍兼容保守后备值 `2 / 60 / 300 / 2` 且开关为 `true`；只有四个限额字段的旧配置也继续启用原保护。填写本节时必须包含全部四个限额字段，新开关可选；即使关闭也不接受非法限额值。修改后从下一次启动命令生效，不会热更新已运行的子进程。该节只影响连接保护，不改变 PDF 阅读流程。正文格式/归因门禁已由最新产品决策独立移除。这不改变 Codex/ChatGPT 桌面客户端自身的重连行为，也不保证网络恢复。

本节描述本项目对子进程的停止保护，不修改个人 Codex 配置、登录、代理或服务端地址，也不等于控制服务端重试或修复网络。

失败诊断由 CLI 保存到 `paths.logs_dir`（默认 `hydro-platform/.runtime/logs`），最终 JSON 的 `diagnostic_log_path` 给出位置。只保存已脱敏的公开错误和上下文，不保存原始事件、提示词或论文全文；首个工具错误和最后一个连接错误分开保留，避免被整体摘要截断。日志不提交 Git。日志目录不可写时保留原失败结果并给出 `diagnostic_log_warning`。

`card_generator.pdf_reader` 字段说明：

| 字段 | 当前含义 | 允许值或规则 |
|---|---|---|
| `adapter` | 原始 PDF 的读取方式 | 当前 `local_path`；兼容历史 `project_mcp`，与工作流协议版本配套，不自动回退 |
| `server_name` | 本次 Codex 调用中注册的 MCP 服务名 | 只能含字母、数字、下划线和连字符 |
| `python_executable` | 启动项目内置 MCP 的 Python | `null` 表示复用运行统一入口的解释器；也可填命令名或绝对路径 |
| `server_file` | 项目内置 PDF MCP 服务脚本 | 相对 `paths.project_root` 解析，且必须位于项目内 |
| `pdfinfo_executable` | 获取 PDF 页数的程序 | 命令名、项目相对路径或绝对路径 |
| `pdftotext_executable` | 逐页提取文字的程序 | 命令名、项目相对路径或绝对路径 |
| `pdftoppm_executable` | 逐页渲染页面图像的程序 | 命令名、项目相对路径或绝对路径 |
| `render_dpi` | 页面图像渲染分辨率 | 72–300；当前为 120 |
| `max_pages_per_call` | 完整读取工具内部每批处理多少页 | 1–10；当前为 4；不会暴露成需要模型自行循环的步骤 |
| `output_token_limit` | 完整 PDF 工具结果的 Codex 输出预算 | 大于 0 且不超过 200000；当前为 60000 |
| `startup_timeout_seconds` | MCP 启动超时 | 大于 0 |
| `tool_timeout_seconds` | 单次 MCP 工具调用及底层 PDF 工具的超时上限 | 大于 0 |

当前配置与示例均使用项目相对工具路径 `hydro-platform/.tools/poppler/Library/bin/`，PDF Python 使用 uv 工作区共享的仓库根 `.venv`（`../.venv/Scripts/python.exe`，相对项目根），由 `uv sync --all-packages` 恢复。也支持明确配置已有工具路径，但统一 setup 对工具/环境归属有检查；改目录时须同步对应字段，不需要改 Python 源码。

例如，使用 GPT-5.6 Sol 和高推理强度：

```json
"model": "gpt-5.6-sol",
"reasoning_effort": "high"
```

使用 GPT-5.5 和模型默认推理强度：

```json
"model": "gpt-5.5",
"reasoning_effort": null
```

程序会把显式推理强度转换为 Codex CLI 的 `--config model_reasoning_effort="..."` 参数。配置校验只能防止未知档位和拼写错误；账号是否能使用指定模型、该模型是否支持指定档位，必须由 `generator-smoke-test` 真实验收。

修改后可运行 `uv run hydro-platform generator-preflight --json`。当前 `local_path` 检查共用指引和本机工具位置，不检查 MCP 脚本；旧 `project_mcp` 才检查 MCP 及其依赖。未知适配器或认证方式会报错，不静默回退。

注意：`chatgpt_account` 只表示 CLI 明确报告为 ChatGPT 登录。US-07B1 的 `generator-smoke-test` 可以验证一次真实模型调用是否成功，但仍不能证明订阅档位或未来一直有剩余额度。

父条目 Key、附件 Key、PDF 哈希、任务状态和运行时间不是配置，它们由系统运行时写入 `hydro-platform/.runtime/` 或证据包 `manifest.json`。API 路由、事件类型和数据结构版本属于程序协议，也不是用户路径配置。详细边界见 [variables.md](variables.md)。

## PDF 路径读取与实验配置

### 独立 PDF 路径直读实验配置

#### 正式单 Agent 与实验共用的读取环境

当前 `card_generator.pdf_reader.adapter` 为 `local_path`，单 Agent 使用与已通过实验相同的读取环境。为避免两套工具路径漂移，沿用下方 `pdf_direct_trial` 对象中的 `windows_sandbox`、`shell_executable`、`python_executable`、`text_extractor`、`preflight_timeout_seconds`。新增 `reading_prompt_file` 指向 `hydro-platform/automation/prompts/pdf-local-reading-v1.md`，用于正式制卡共用读取指引。

`prompt_file`、`schema_file`、`timeout_seconds` 仍只属于独立读取实验。当前单 Agent 使用 generation_timeout_seconds（1500 秒）及总配置 paths 中的制卡提示词/schema；不会套用实验报告字段。独立 `pdf-direct-read-trial` 实验的时限仍单独配置为 1200 秒，本次不改。运行目录统一来自 `paths.runtime_dir`。迁移电脑只需改总配置中的工具位置并重新登录 Codex，不把账号凭据写入 Git。

旧 `pdf_reader` 中的 `server_name`、`server_file`、`python_executable`、MCP 批次/输出预算/启动超时只对历史 `project_mcp` 生效，当前不调用。`pdf_tool_call_limit` 也只统计旧 MCP 整篇调用，不限制新路径的 shell/看图次数；总超时和无进展保护保留。

`pdf-direct-read-trial` 读取同一份总配置，模型和思考强度复用 `card_generator.model`、`card_generator.reasoning_effort`，不读取历史多 Agent 的角色覆盖值。

```json
"pdf_direct_trial": {
  "prompt_file": "automation/prompts/pdf-direct-read-trial-v2.md",
  "reading_prompt_file": "automation/prompts/pdf-local-reading-v1.md",
  "schema_file": "automation/schemas/pdf-direct-read-trial-output.schema.json",
  "timeout_seconds": 1200,
  "windows_sandbox": "elevated",
  "shell_executable": "powershell",
  "preflight_timeout_seconds": 120,
  "python_executable": null,
  "text_extractor": "pypdf"
}
```

以上对象位于 `card_generator` 内。两个文件路径相对 `paths.project_root`，必须分别位于配置的 `paths.prompts_dir`、`paths.schemas_dir` 内；旧配置未填该对象时采用这些默认文件名和 1200 秒。超时必须大于零。

`windows_sandbox` 显式传给 CLI，不依赖被 `--ignore-user-config` 忽略的个人设置；只接受 `elevated` / `unelevated`，不自动降级，默认使用现有的 `elevated`。`shell_executable` 是 PowerShell 的命令名或绝对路径。`preflight_timeout_seconds` 是不调用模型的本机沙箱检查时限。

`python_executable` 是正式路径制卡与直读实验共用的 Python 命令名或路径，`null` 表示复用运行入口的 Python。当前总配置与示例为 `../.venv/Scripts/python.exe`，即 uv 工作区共享的仓库根 `.venv`；该环境由 `uv sync --all-packages` 管理，所需 pypdf 6.18.0 已在 `hydro-platform/pyproject.toml` 中声明为正式依赖，因此不需要再为它单独自举安装。旧 Codex 环境保留不动，不需初始化 MiKTeX。相对工具路径基于项目根目录，不受当前 PowerShell 目录影响；不能指向缺依赖的 Python。

## 项目安装配置 deployment

每日计划另由 `scheduler` 控制：enabled（本机true、示例false）、task_name、daily_time、poll_interval_minutes、retry_interval_minutes、max_attempts_per_slot、logon_delay_seconds、execution_time_limit_seconds、powershell_executable、command_timeout_seconds。字段含义、修改后是否需重新install和暂停方式见 [调度配置表](cron.md#总配置字段)。仅填配置不代表新机器已经注册任务，需读回schedule-status。

`environment_dir` 选择项目 Python 环境：可以是平台内目录，也可以是 uv 工作区根的共享 `.venv`（当前为 `../.venv`，指向平台目录之外），其他取值会被拒绝。`dependency_lock_file` 选择版本/来源/哈希锁；`wheel_cache_dir` 选择下载缓存；`base_python` 是已有基础 Python（null 为当前解释器）；`install_timeout_seconds` 与 `download_timeout_seconds` 分别限制子进程等待和下载套接字。均在总配置修改，无需编辑代码。[字段与换机边界](deployment.md)。环境位于工作区根 `.venv` 时由 uv 管理（`uv sync --all-packages`），平台的 bootstrap 只做核对；为与仓库依赖树隔离而使用平台内环境时，才由平台按锁文件自举安装。更改环境目录后同步改 `pdf_direct_trial.python_executable`，安装器不改生产配置。

`native_tools_dir` 选择项目 PDF 工具目录（默认 `hydro-platform/.tools/poppler`）；`native_lock_file` 为 `hydro-platform/automation/setup/native-tools.lock.json`；`native_cache_dir` 为 `hydro-platform/.runtime/native-cache`。运行 `uv run hydro-platform bootstrap-native --install --json` 安装。当前三项读取工具均为 `.tools/poppler/Library/bin/` 下的同名 exe，不依赖旧用户 Codex/MiKTeX 缓存。改工具目录时在本配置同步改三项 exe 路径；未知目录不会被安装器接管。[原生工具安装、校验与限制](native-deployment.md)。

旧配置未填写文字引擎时仍为 `pdftotext`；当前总配置显式为 `pypdf`，不自动换引擎。`pdfinfo_executable`、`pdftoppm_executable`、`render_dpi` 和单工具超时复用 `card_generator.pdf_reader`；仅 pdftotext 引擎使用它的路径。路径模式不启动或检查 MCP 服务脚本。模型收到原 PDF 路径和工具位置，不预塞全文，也不要求固定页摘录。自定义配置仍引用旧直读实验提示词时，应改为 v2；当前单 Agent 使用主提示词 v8 与 workflow_mode=single_agent。

临时目录位于 `paths.runtime_dir`；报告位于 `paths.card_trials_dir/pdf-direct-read/`。继承现有进度和连接保护配置；不使用旧 MCP 的整篇读取次数限制，不自动重新启动一次失败实验。`--timeout` 仍只是 Zotero HTTP 请求超时，模型调用时限应改上述 `timeout_seconds`。

仅检查本机，不花模型额度：`uv run hydro-platform pdf-direct-read-trial --item-key CEXH4PQA --preflight-only --json`。正常直读命令也会自动先做同一检查，失败就停止。

团队目标库已经确定为 qinjiajun，群组 ID 为 6618088，保存在可复现的 `hydro-platform/config/config.json` 中。群组 ID 不是密钥，可以进入 Git。

`hydro-platform/config/config.example.json` 用于解释配置结构。只有本机需要覆盖团队配置时，才复制为被 Git 忽略的 `hydro-platform/config/config.local.json`。

`config.local.json` 是完整的另一份配置，不会被自动发现，也不会与 `config.json` 合并。使用时显式传入 `--config hydro-platform/config/config.local.json`，或令 `HYDRO_PLATFORM_CONFIG` 指向该文件；无需改代码。环境检查与恢复也使用同一选择规则。[操作说明](runtime-maintenance.md)。

如果还不知道群组 ID，可以先运行发现命令：

    uv run hydro-platform discover-groups --json

然后执行目标群组预检：

    uv run hydro-platform preflight --json

程序默认定位同一项目中的 `hydro-platform/config/config.json`。如果以安装包方式运行或临时使用另一份总配置，可设置 `HYDRO_PLATFORM_CONFIG`，也可显式传入 `--config`；这些只是总配置入口，不保存第二套业务参数。
