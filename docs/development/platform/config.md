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

平台只提供**流程**，LLM 动作由两种执行者之一完成，没有第三种：

1. `in_session`（默认）：`cards run prepare` 准备 `paper.md`，当前 agent 写 `response.json`，
   `cards run finalize` 校验后保存草稿。**不需要任何 API key。**
2. `direct`：直连 OpenAI 兼容 API，默认 DeepSeek（`base_url=https://api.deepseek.com`、
   `model=deepseek-chat`、key 取 `DEEPSEEK_API_KEY`）。

| 字段 | 当前含义 | 允许值或规则 |
|---|---|---|
| `runner` | 执行者 id（注册表名） | `in_session`（默认）或 `direct`；未知值在构建管线时报错 |
| `model` | 所选执行者的模型名 | `null` 表示使用该执行者的默认值 |
| `reasoning_effort` | 思考强度 | `null` 或 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`；实际支持范围取决于模型 |
| `generation_timeout_seconds` | 一次制卡的最长等待秒数 | 大于 0；当前为 1500，即 25 分钟 |
| `progress.enabled` | 制卡是否显示 stderr 实时进度 | `true` / `false`；默认 `true`；`--no-progress` 可关闭本次显示 |
| `progress.heartbeat_interval_seconds` | 定期报告等待状态的间隔 | 1–300 秒；默认及当前值为 60；不改变模型超时和重试策略 |

`progress` 在旧配置中整体缺失时使用上述默认值；一旦填写，必须同时提供两个字段。心跳表示本地程序仍在等待，不证明远端模型健康。进度不会写入最终 JSON，也不会回显模型正文、原始工具输出或凭据。

`--ai-provider` / `configs/ai.toml` 的 `provider`（别名 `runner`）会覆盖 `card_generator.runner`；
单篇 `evidence-generate` 与 `themes-run` 使用同一套选择契约。API key 不是配置项：`direct` 自己从环境变量读取，
`in_session` 不需要，配置文件从不保存凭据。

单篇制卡的失败只出现在本次 JSON 的 `error` 块（`code` / `message` / 可选 `diagnostic`），不写额外日志文件，也不保存提示词或论文全文；主题轮次的 run report 仍写入 `paths.logs_dir/theme-runs/`，且不提交 Git。

## PDF 读取方式

单篇制卡与主题定向精读都由 Python 先把 PDF 转成 Markdown（PyMuPDF），执行者阅读 `paper.md` 与图资产。平台自身不调用 `pdfinfo` / `pdftotext` / `pdftoppm`。转换器的选择在 `converter` 配置组，缓存目录在 `paths.project_root` 下。

`evidence-generate --paper-input` 是受支持的单篇路径；旧证据包栈（`--item-key`、`--pipeline legacy` 与
启动子进程的 CLI 执行者）已整体移除。历史 v1 草稿仍可由 `evidence-validate` 只读校验。

父条目 Key、附件 Key、PDF 哈希、任务状态和运行时间不是配置，它们由系统运行时写入 `.runtime/` 或草稿记录。API 路由、事件类型和数据结构版本属于程序协议，也不是用户路径配置。详细边界见 [variables.md](variables.md)。

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

模型 API key（默认 `DEEPSEEK_API_KEY`）、Zotero API Key、GitHub Token 等秘密只能存放在本机凭据存储或环境变量中，不得提交到仓库。`config.json` 不记录任何凭据，也不记录代理地址。

新增配置字段必须同时具有解析、类型或范围校验、使用该字段的实际代码、自动化测试和中文说明；`runner` 只能选择注册表里已实现并注册的执行者，填写未知执行者时必须启动失败，不能静默回退。

## 科研产物路径与当前边界

配置同时保留**两组**产物路径：

- **单篇流程**写入 `--output-root`（默认仓库 `outputs/`），**主题池**写入 `paths.themes_dir`。
- `paths.artifact_root` 及其下的 `证据卡/`、`主题/`、`运行记录/`、`文献链接/` **已能解析和校验**，
  可指向仓库根或显式允许的外部共享位置，但**自动化发布尚未接入这四个目录**。

所有实际科研产物、原始 PDF、Zotero 数据库、`.runtime` 和本机路径均**不进入 Git**。
目标是在两组目录之间建立明确的准入与发布边界，再把 `artifact_root` 作为 Obsidian 阅读层 ——
**不应把当前的配置字段理解为两套工作流已经打通**。

相关：[自动化边界](automation.md) · [项目级设计](project-design.md)
