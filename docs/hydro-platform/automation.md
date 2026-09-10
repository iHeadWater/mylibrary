# 自动化边界

2026-09-09：主题流程已接入，见 [主题工作流](themes-workflow.md)。只做候选→逐篇原始 PDF 精读→修订候选，不自动转正式主题，不生成 idea。正文不做格式/措辞质量门。

关键事件和老师日报也已接入同一入口，明确区分人新增/补PDF和系统完成/阻塞；首次只建基线。[事件与日报](activities-and-daily-report.md)。Windows每日计划已启用并完成按需触发验收；真实关机/重新登录恢复和异机完整部署仍待验证，见 [调度](cron.md)。

## 常用入口

当前完整流程：指定 Zotero 共享库 → PDF 就绪 → 单 Agent 详细粗卡 → 统一主题池规划 → 必要精读/适用精读复用 → 回填候选 → 关键事件与日报。日常不需要逐条运行 US-01～US-07；这些编号是历史实施拆分，不是使用步骤。

在仓库根目录运行，统一前缀为 `uv run hydro-platform`（旧的直接调用脚本写法已废弃，请统一使用 uv 形式）：

| 子命令 | 用途 / 副作用 |
|---|---|
| run-once --json | 一键处理本轮全部可制卡论文、衔接主题、记录贡献并刷新日报；可能调用模型 |
| run-once --dry-run --json | 只预览已有本机任务，不扫描、不调用模型 |
| themes-run --json | 单独推进统一主题池；输入变化时可能调用模型 |
| themes-run --dry-run --json | 只读主题预览，不写入、不调用模型 |
| themes-run --migrate-only --json | 接入已有完成主题并保存注册表，不调用模型 |
| doctor --json | 只读环境、登录、共享库及计划检查，不调用模型或启动应用 |
| recover --json | 全量对账 Zotero 与本地共享成果，重建派生任务/快照，不重做科研结果 |
| setup --json / setup --apply --json | 安装恢复的预览 / 执行；执行可能下载依赖、启动 Zotero、按配置恢复计划 |
| schedule-status --json | 查看真正的 Windows 计划定义与最近状态 |
| activity-sync --json / daily-report --json | 单独维护关键事件 / 日报，不调用模型 |

模型结果完成后直接正式保存，不要求逐篇手动搬文件。已有粗卡不覆盖；主题无变化不调用模型。实时进度写 stderr，最终 JSON 写 stdout，--no-progress 关闭本次进度。[完整操作手册](operator-manual.md)。

## 自动化所有者

- Zotero启动/等待：仅Python统一入口在整轮锁内按配置执行，不由Agent决定。固定程序无shell参数、一次启动、有限只读探测；不改账号/同步偏好。待处理项不误标全队列完成，[代码规则和验收](zotero-readiness.md)。
- 人工参与者：使用私人 Zotero 账号的老师和学生。
- 自动化执行者：`SYS-CARD-01`，即运行在唯一指定制卡机上的 Python 后台程序；当前已负责检测、门禁、任务、证据包骨架、PDF 交付、Codex CLI 预检、无论文探针、模板静态校验和单篇粗卡生成。
- Git 写入：日常程序不提交/推送；实际权限来自外部 GitHub 账号，只在用户明确授权时操作。

## 允许读取

- 指定 Zotero 共享群组库中的父条目、附件和必要身份信息；
- Zotero 已同步到制卡机的 PDF 全文；
- 仓库中已有的证据包与非敏感配置。

## 允许写入

- `evidence-packs/` 中的证据包；
- `evidence-packs/*/readings/` 的主题定向精读和 `themes/candidates/` 的候选、回填及步骤记录；不覆盖原粗卡；
- `activity/` 中的关键事件；
- 已启用的 `reports/` 摘要；
- 制卡机本地 `.runtime/` 状态。

## 禁止行为

- 未取得可读取的 PDF 全文时生成正式证据卡；
- 对已有非占位证据卡重复制卡或自动覆盖；主题定向精读另存 readings/，不是重制主卡；
- 把 PDF 原文、密钥或原始运行日志提交到 Git；
- 自动把候选主题升级为正式主题；
- 将活动数量解释为学生绩效。

## 当前实现与边界

US-11A 已新增统一入口 run-once：每轮扫描共享库及后补 PDF、对账完整证据包、默认自动串行处理本轮全部可制卡论文、有限重试并保存本地摘要；每篇成功即正式保存。持有整轮系统锁，新版写入使用可恢复的待保存记录，格式拦截的完整草稿可经重新结构检查后如实恢复。详情见 [统一运行](run-once.md)。dry-run 只读本地任务，不替用户启动模型批量制卡；当前仍不安装每日调度，也不自动提交或推送 Git。

当前默认单 Agent、模板驱动、详细粗卡；Python 只检查来源、非空输出、去重和安全写入，不检查归因标签和正文格式。PROCESS_VALIDATED 不是科学质量认证。旧六角色仅兼容。主题、事件/日报、项目Python安装、状态恢复与Windows计划已实现。真实关机/登录、同步等待和异机完整部署仍有缺口，Git自动同步不启用。[部署边界](deployment.md) 与 [跨边界操作流](flows.md)。

US-07A 已在 `hydro-platform/automation/src/hydro_platform/card_generators/` 建立首个真实适配边界，并注册 `codex_cli`。预检只运行版本和登录状态检查，不运行模型，不读取论文，也不把登录命令原始输出写入结果。它使用制卡机上已登录的 ChatGPT 账号，不使用项目配置中的 API Key，也不依赖 Codex 对话窗口。

US-07B1 在预检后，在系统临时创建的空目录中使用 `codex exec --json --ephemeral --sandbox read-only --skip-git-repo-check` 执行固定探针，不把项目仓库设为工作目录。程序从总配置读取模型和推理强度，分别通过 `--model` 和显式 `--config model_reasoning_effort="..."` 覆盖 Codex 默认；两者为 `null` 时保留模型默认值。程序额外忽略用户配置和规则，拒绝命令执行、文件修改、MCP 调用或联网搜索事件；只接受固定响应，不保存原始 CLI 输出，并在结束后删除临时目录。真实验收已用 `gpt-5.6-sol / low` 成功完成，但固定探针仍消耗 16,324 个输入 token；它不能进入每日调度，只能用于安装或配置变化后的受控验收。

US-07B2 已从固定来源提交接入八类 Markdown 模板。`_catalog.json` 记录来源 commit、逐文件 blob SHA、本地版本、启用状态和适配后内容 SHA-256；静态校验还要求平台身份、PDF 指纹、自动分类理由和模板版本字段完整。路径来自总配置，不得写死。模板来源仓库在读取时未声明许可证，当前使用依据按用户确认记录为团队协作授权。

US-07B4 历史六角色流程已被当前单 Agent 流程替代；保留旧代码与历史审计读取能力。当前逻辑、失败保全和诚实验收边界见 [单 Agent 说明](single-agent-rough-card.md)。

无人值守制卡前进行提供者预检；run-once 在需要模型时自动预检。额度、限流、超时等运行故障按任务状态处理，不立即无限循环调用。QUALITY_FAILED 保留历史兼容；现流程不因正文格式或标签产生这一失败。未来独立 API 必须实现提供者接口并继续遵守来源身份、非空输出、重复和安全写入等流程检查，不额外增加正文格式门槛。

## 可复现要求

- 源代码、提示词、结构定义、非敏感配置和依赖锁定文件必须进入 Git。
- 每次生成都要记录使用的流程版本；不要求大模型输出逐字确定。
- 自动化不能把本地游标当作唯一事实来源。
- 本地状态丢失后，必须通过全量对账安全恢复，之后才能继续增量处理。
- 安装脚本必须能够重建 Windows 调度任务，避免只有旧电脑知道如何运行。

## 代码地图

核心代码位于 `hydro-platform/automation/src/hydro_platform/`：

| 模块 | 职责 |
|---|---|
| cli.py、pipeline.py | 命令解析、完整流水线、整轮锁与数量/时间/重试限制 |
| zotero.py、zotero_readiness.py、snapshot.py | 只读群组访问、单次启动/有限等待、条目与附件变化检测 |
| pdf_gate.py、pdf_delivery.py | PDF 就绪、身份/指纹检查及原始路径交付 |
| tasks.py、evidence_packages.py | 派生任务状态、证据包骨架、重复与已完成保护 |
| card_generation.py、card_generators/single_agent.py | 详细粗卡编排、来源和非空输出检查 |
| card_generators/codex_local_pdf.py、codex_text.py | 当前 Codex CLI 的 PDF 路径读取和纯文本步骤适配 |
| themes.py、theme_pool_runner.py、theme_pool.py | 主题入口、全池规划、精读/回填、稳定编号、版本/演变及原子发布 |
| publication.py、draft_recovery.py、runtime_recovery.py 等 | 安全保存、草稿和本地状态恢复；冲突不覆盖 |
| activity.py、daily_report.py | 关键贡献账本和面向老师的摘要 |
| scheduled.py、windows_schedule.py | 到期检查、有限补查、Windows 计划安装/查询/移除 |
| deployment.py、native_deployment.py、workstation_setup.py | 锁定 Python/PDF 依赖安装和统一恢复 |
| doctor.py、progress.py、failure_records.py | 环境检查、实时进度及脱敏失败记录 |

`run.py` 是用户命令入口，`scheduled_run.py` 是 Windows 的固定后台入口。它们进入同一套流水线，不另建知识池。

## 提示词、模板与机器协议

- `hydro-platform/automation/prompts/`：当前 v8 制卡指引和共用 PDF 路径阅读指引，见下方[提示词](#提示词)。
- `hydro-platform/automation/schemas/`：模型传输结构及证据包清单格式，见下方[数据结构与流程检查](#数据结构与流程检查)。
- `hydro-platform/templates/evidence-cards/`：八类详细粗卡模板及来源版本，见 [公共模板](templates.md)。
- `hydro-platform/templates/themes/`：统一主题规划、定向精读及回填模板，见 [公共模板](templates.md)。
- `hydro-platform/automation/setup/`：依赖下载来源、版本和 SHA-256 锁，见 [安装配置](deployment.md)。
- `hydro-platform/automation/tests/`：自动化回归；verify_*.py：显式运行的环境/恢复演练，可能创建隔离目录或下载依赖，不是每日工作步骤。

当前协议 rough-card-single-agent-v2 / unified-theme-pool-v1。原多 Agent、MCP 和按批次生成的旧路径保留历史兼容/迁移测试用途，不由当前正常配置自动选择或失败回退。

### 提示词

提示词负责指导分析方式，程序负责来源、路由、重复和写入保护；不把提示词要求误当成已经独立验证的科学质量。

| 文件 | 用途 |
|---|---|
| `hydro-platform/automation/prompts/evidence-card-generation-v8.md` | 单 Agent 自动选型、完整阅读并按模板生成详细粗卡；协议 rough-card-single-agent-v2 |
| `hydro-platform/automation/prompts/pdf-local-reading-v1.md` | 制卡与主题精读共用的本机 PDF 路径读取指引，允许读取文字和看页面图像 |
| `hydro-platform/templates/themes/` | 全池关联规划、定向精读和精读后回填的提示模板；见 [公共模板](templates.md) |

主制卡指引由 paths.evidence_card_generation_prompt_file 选择；共用阅读指引由 card_generator.pdf_direct_trial.reading_prompt_file 选择。Python 读取[八类模板](templates.md)并组装请求，不需要每个学生复制一套提示词。

当前要求把原文陈述与 AI 推理表达清楚，但不做固定摘录、章节/标签匹配、数量门槛或逐卡人工复核。不因为排版差异重跑模型。

pdf-direct-read-trial-v2.md 仅供独立读取实验使用，不是正常制卡入口。v3～v7、事实提取/裁决、批判/对抗提示词保留历史；六 Agent 与旧 MCP 不是当前默认流程，也不会在失败后自动回退。

生成/精读记录保留实际模型、提示词指纹、来源和输出。旧成果保留原来的协议，不因新提示词上线自动重制。提示词修改与版本更新应同步维护配置、测试和说明，不修改原有证据结果。[制卡规则](single-agent-rough-card.md) · [总配置字段](config.md)

### 数据结构与流程检查

当前制卡协议 rough-card-single-agent-v2，正常生成使用 card-generation-output.schema.json（版本2）；PROCESS_VALIDATED 表示流程通过，不是科学质量认证。历史记录中的 STRUCTURE_VALIDATED、VALIDATED 或 DRAFT_RECOVERED 保留原含义，不追改成新协议。

| 文件 / 位置 | 用途 |
|---|---|
| `hydro-platform/automation/schemas/evidence-manifest.schema.json` | 证据包身份、PLACEHOLDER/ROUGH 状态、当前或历史生成/恢复记录 |
| `hydro-platform/automation/schemas/card-generation-output.schema.json` | PDF 阅读声明、模板路由、分类说明和 Markdown 正文的传输结构 |
| `hydro-platform/automation/schemas/pdf-direct-read-trial-output.schema.json` | 独立 PDF 读取实验报告；不替代正式制卡，不要求原文摘录 |
| `hydro-platform/templates/themes/*.schema.json` | 全池 CREATE/UPDATE/MERGE/SPLIT 规划、定向精读与回填传输 |
| fact-extraction、fact-adjudication、critical-analysis、adversarial-review 的 schema | 旧多 Agent 兼容与测试，非当前默认流程 |

Python 核对原始来源、非空结果、有效模板/引用、重复和完整写入，不检查 Markdown 标题层级、归因措辞、表格形式或固定数量。主题操作数量、父子关系、正式主题保护属于流程约束，仍必须检查。

本地任务、主题注册表、事件和运行报告已经有版本字段与对应 Python 读写校验，并非每种记录都有本目录下的独立 JSON Schema。清单损坏或来源不符不能静默覆盖。

模型声称“读完”与独立证明“理解正确”不同；当前路径读取保留来源与执行记录，不伪造历史 MCP 的逐页工具回执。详见[配置与密钥边界](variables.md)、[验证地图](tests.md)。

## 维护与边界

模型、思考强度、超时和路径来自 [总配置字段](config.md)。当前适配器仅 codex_cli；填写另一个 API 名称不会自动得到新适配器。

日常命令不改 Zotero 文献/偏好，不自动转正式主题、不生成 idea、不执行 Git 提交或推送。制卡可按配置启动本机 Zotero，并调用登录的 Codex 账号处理 PDF；不是完全离线运行。Windows 计划的启用不依赖 Codex 对话窗口，但依赖已登录的 Windows 用户与有效账号。

程序只校验来源、非空输出、路由和写入流程，不以正文排版/归因标签作为保存门槛。保存通过不代表机器已独立验证论文理解。

[统一主题池](unified-theme-pool.md) · [每日调度](cron.md) · [安装恢复](workstation-setup.md) · [验证与缺口](tests.md)
