# 单 Agent、模板驱动、详细粗卡

生效决策：2026-09-08。替代默认六角色制卡方案，不追改历史结果。

2026-09-09 最新决策：模板是 AI 写作指引，不是保存合约。程序仅检查流程，不校验正文格式或内容质量；替代此前所有二级章节、七列表格、标签、编号、占位词及措辞门禁。日常只需 run-once 一次，自动处理本轮全部可制卡论文并逐篇正式保存。已有正式卡不重做，不需逐批改配置或手动转正。

## 目的与范围

用户没有逐卡科研复核的人力；粗卡供后续主题 Agent 使用。“粗”仅表示未围绕某个主题定向深化，不表示只读摘要或省略重要细节。本次止于单篇卡片生成，不实现主题、idea、调度或 Git 推送。

## 当前流程

Python 核对任务、原 PDF 和模板索引 → 一个 Codex 独立会话读取文字及页面图像、自动选型、按模板详细写作 → Python 检查来源、执行完成、非空结果、重复/覆盖及写入状态 → 保存 card.md、manifest 与运行记录。

- 只有一次提供者 generate 调用；CLI 在本次会话内可能调用多次本机工具或自行重连，不是承诺一个网络请求。
- 不要求摘句、逐字匹配、固定事实数、批判条数或人工审批；不派生子 Agent。
- 保留八类模板的细节结构，版本升级为 1.1.0；原始来源 commit 和 blob 不变，适配内容重新计算哈希。
- 当前模型仍为总配置中的 gpt-5.6-sol / high；一个会话使用 generation_timeout_seconds，不再使用六个角色各自的配置。

## 内容及验收边界

| 层次 | 给 AI 的写作要求 | 程序保存时的处理 |
| --- | --- | --- |
| 原文陈述 | 作者报告的结果、解释、假设和建议，区分其性质 | 原样保存，不检查编号、标签或列数 |
| 原文转述 | 当前论文引用的他人研究；不冒充已读被引原文 | 原样保存，不声称机器已确认归因 |
| AI 推理 | 说清依据、推导、额外假设、适用条件和边界 | 不要求固定章节名或标签，不核对正文 C 编号 |
| 信息边界 | 客观说明缺失及影响，不向用户交办逐卡审核 | 作为写作指引，不用正则扫描措辞作为门禁 |

模板仍要求详细说明研究问题、数据、尺度、方法链、结果、图表和局限，并区分事实与推理。但标题、顺序、列数、数量、标签、编号、占位词和措辞既不拦截，也不额外做一轮机器内容检查或自动返工。正文按模型输出保存，包括模型自行给出的排版；可信身份和状态始终由 Python 从任务上下文写入，不用模型正文覆盖清单。

保留硬检查：目标群组/父条目/附件及 PDF 指纹正确、PDF 读取执行/报告满足既有流程、模型调用正常完成、交付 JSON 能被程序处理、模板 ID 指向已启用模板、Markdown 为非空文本、任务锁/幂等/不覆盖以及多文件保存完整性。模板 ID 只是运行记录索引，不校验其正文匹配度。可选分类理由和置信度缺失/不合格式记为未提供，不编造数值，也不因此丢弃正文；取消理由/阅读说明的字符上限。

新结果 quality_status=PROCESS_VALIDATED、workflow_protocol_version=rough-card-single-agent-v2、workflow_role_count=1；content_validation_performed=false。兼容保留 structure_validation 字段，但明确 status=NOT_CHECKED、policy_version=workflow-only-v1，不能解释成正文通过。quality-audit.json 沿用文件名，实际为运行记录，independent_review、scientific_correctness_verified、full_read_verified、visual_understanding_verified 均为 false。历史 v1/多 Agent/草稿恢复文件仍可读取，不追改既有产物。

## 操作

已新增 [统一入口 run-once](run-once.md)，适用于自动发现待制卡论文并串行处理；已有完整卡只对账跳过，不重新调用模型。下方单篇 trial 命令仍用于主动试读已有论文，不用于每日自动化。

无需重新跑已经通过的独立 PDF 读取实验。当前 CEXH4PQA 已有正式卡，使用：

```powershell
Set-Location 'E:\phd\hydro-platform'
python automation/run.py evidence-generate-trial --item-key CEXH4PQA --json
```

结果保存到返回的 trial_path（默认 .runtime/card-trials/ 下）。正式卡、manifest 和任务不变。不自动把试运行结果替换为正式卡。

只有尚为占位卡的论文使用 evidence-generate；成功后任务变为 COMPLETED，重复运行跳过已有卡。当前不再因正文格式或归因标记进入 QUALITY_FAILED；run-once 可按新的流程检查恢复历史被这些规则拦截的完整草稿，不自动重读 PDF。

2026-09-09 完成判定修正：文件夹、空文件、占位卡或仅一个 COMPLETED 标记都不能证明制卡完成。单篇入口与统一入口、恢复、主题输入和贡献统计共用 validate_saved_package：核对正文非空且不等于系统占位卡、manifest 的有效生成记录及正文/已声明审计指纹；任务相关入口另核对当前来源身份。缺记录或冲突时保留文件并报错，不覆盖，也不作为已有卡成功跳过。任意正文标题、表格或措辞仍不受检查。

当前总配置的正式制卡总时限与无进展时限均为 1500 秒（25 分钟），等待心跳 60 秒；实际事件立即显示，结束时显示整轮汇总，不把别的论文失败归到最后一张卡的保存阶段。

## 输出保全与故障

新版正式包保存会先在任务锁同目录的 pending-publications 中写入完整待保存记录，统一入口可在中断后补齐文件和完成状态，不重跑模型。generation-drafts 的完整模型消息也可在格式失败修正后恢复，但必须使用独立的 DRAFT_RECOVERED 来源记录，不能伪造成完整执行审计。

- 模型返回的最后一条消息会先保存在 paths.runtime_dir/generation-drafts/<随机ID>.json，标为 UNVALIDATED_MODEL_OUTPUT，不是正式卡、不供主题读取。
- 保存位置由运行目录派生；不记录原始命令输出或认证信息。它含未校验模型内容，仅留本机，不提交 Git。
- 路径读取检查成功后，新草稿会尽量追加当次来源/阅读声明记录；追加失败只警告，不丢弃成功输出。旧草稿缺失的执行记录不能追补成事实。
- 临时目录清理失败变为 SCRATCH_CLEANUP_FAILED 警告，继续校验及保存，不把成功调用判成模型失败、不重跑模型。不修复 ACL、不越权清理历史目录。
- 真正的进程/文件错误保留发生阶段、异常类型、errno/winerror；输出校验失败尽可能附上 draft_path。
- 已完成的单 Agent 草稿可通过 evidence-draft-export --draft <draft_path> --json 离线导出预览，不调用模型、不更新正式卡或任务。只核对本机路径、完成输出、来源身份、模板索引及非空正文，不检查正文结构或归因。正文原样保留，另存 export.json，状态 RECOVERED_DRAFT_PREVIEW；输出在 paths.card_trials_dir/recovered/ 下的新目录，不覆盖旧预览。正常 run-once 无需使用该预览命令。
- 显式导出仍仅为预览。run-once 对符合条件的格式失败草稿会直接正式保存：保留原模型/提示词指纹，当前模板只记 checked_against_*，旧生成时间/版本未知记 null，独立阅读/科学正确性验证记 false。正式保存是存储状态，不是独立科研质量认证；网络中断未产生完整输出不能恢复不存在的结果。
- 新流程取消六次重复上下文开销，但真实时长和卡片质量仍须实跑确认，不能保证固定分钟数，更不能保证某等级期刊成果。

## 当前配置与兼容

总入口仍为 config/config.json。workflow_mode=single_agent，pdf_reader.adapter=local_path；单 Agent 模式不能同时提供 multi_agent_workflow，避免无效角色覆盖值误导。

旧配置未写 workflow_mode 时按 legacy multi_agent 解析，仅用于历史兼容，不自动回退。当前主提示词为 evidence-card-generation-v8.md，旧版保留历史不改写；共用读取指引仍为 pdf-local-reading-v1.md。v8 将详细写作要求与保存条件分开，不降低全文阅读范围，不增加模型复核或格式修复调用。总配置和示例已经更新，无需用户修改。

读取解释器、shell、沙箱、文字引擎暂仍放在 pdf_direct_trial 对象中，与正式路径读取共用；该对象的 prompt_file/schema_file/timeout_seconds 只管独立读取实验。旧 MCP 字段在 local_path 下不执行。重命名配置与迁移可后置，不能为了命名好看中断已验证环境。

## 本次验证

全量 267 项离线测试通过；覆盖单次调用、来源身份、归因检查、正式幂等、旧卡试运行保护、历史 manifest 兼容、清理失败保全、原始 I/O 错误诊断，以及宽松排版保存和离线草稿导出。八类模板静态校验和 git diff --check 通过；无模型 generator-preflight 为前一轮记录。本次实际将 CEXH4PQA 已完成的草稿原样导出为独立 Markdown 预览，未重新调用模型；原 PDF、草稿、正式卡、manifest 和任务指纹保持不变，未提交或推送 GitHub。
