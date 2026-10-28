# 总配置字段说明

日常只编辑完整总配置，不改源码。默认使用 `hydrolitagent/cards/assets/config/config.json`；`hydrolitagent/cards/assets/config/config.example.json` 是可复制的完整示例。私人配置必须显式用 --config 或 HYDROLITAGENT_CARDS_CONFIG 选择，不自动合并。字段与数据的边界划分（哪些属于配置、哪些属于运行状态、证据事实或密钥）见 [配置与密钥边界](variables.md)；目录与存储概览回到[文档入口](../../user-guide/cards/index.md)。

`config.json` 是自动化唯一的团队级总配置入口。需要迁移目录、更换 Zotero 本地接口或调整制卡参数时，只修改这个文件，不修改程序源码。所有路径字段必须显式填写；缺失时程序直接报配置错误，不使用源码中的隐含目录默认值。

`paper-input` 是例外：它只按 `configs/paper-input.toml` 读取 `zotero` + `pdf_gate` 两表，不加载模型配置，也不读取 `HYDROLITAGENT_CARDS_CONFIG`。详见[单篇论文输入](../../user-guide/cards/paper-input.md)。

## 路径

`paths.project_root` 相对于 `config.json` 所在目录解析；其余路径相对于 `project_root` 解析。因此，从仓库外部工作目录调用程序时，产物仍会写入正确项目。为避免误写，所有项目路径必须位于 `project_root` 内，运行状态和原始日志还必须位于 `runtime_dir` 内。当前 `paths.project_root` 为 `../../../..`，即仓库根目录。

科研产物根只有一处：项目级 `configs/paths.toml` 解析出的 `paths.literature_root`（详见本节末尾「科研产物路径：一个根，其余派生」）。cards 配置里的其余路径都不允许逃出 `project_root`。旧平台的 `paths.artifact_root`、`artifact_root_external` 及其四个子目录字段（证据卡 / 主题 / 运行记录 / 文献链接）已随本次清理删除，不再解析。

证据卡模板路径：

| 字段 | 当前含义 | 规则 |
|---|---|---|
| `paths.templates_dir` | 所有公共模板的根目录 | 必须位于项目根目录内 |
| `paths.evidence_card_templates_dir` | 九类证据卡 Markdown 模板目录 | 必须位于 `templates_dir` 内 |
| `paths.evidence_card_template_catalog_file` | 模板来源、版本和内容哈希清单 | 必须位于证据卡模板目录内 |
| `paths.evidence_card_generation_prompt_file` | 正式制卡提示词 | 必须位于 `paths.project_root` 内，并声明 `prompt_version` |

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

## 科研产物路径：一个根，其余派生

**产物根只有一个定义处**：项目级 `configs/paths.toml` 的 `[literature] root`（可用
`HYDROLITAGENT_LITERATURE_ROOT` 覆盖，`uv run hydrolitagent paths` 可查实际解析结果）。
cards 的 `config.json` 只写**子目录名**，全部相对这个根解析：

| cards 字段 | 值 | 解析结果 |
|---|---|---|
| `paths.themes_dir` | `themes` | `<literature_root>/themes` |
| `paths.evidence_packs_dir` | `evidence-packs` | `<literature_root>/evidence-packs` |
| 单篇草稿（无配置字段） | — | `<literature_root>/zotero/...` |

`paths.literature_root` 是**可选的显式覆盖**，只用于测试或非常规部署；正常使用不要写它，
否则又会变成两处定义。**产物根只有 `paths.literature_root` 一处**；旧平台的
`paths.artifact_root` 及其下的 `证据卡/`、`主题/`、`运行记录/`、`文献链接/` 等 artifact
路径字段已从代码与配置中移除，不再解析。

代码、模板、`configs/`、`.runtime/`（缓存与日志）仍相对 `paths.project_root` 解析，不属于产物。
临时输入与 `cards run --run-dir` 放在 `.runtime/` 下。

所有实际科研产物、原始 PDF、Zotero 数据库、`.runtime` 和本机路径均**不进入 Git**。

相关：[自动化边界](automation.md) · [项目级设计](project-design.md)
