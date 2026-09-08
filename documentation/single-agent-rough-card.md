# 单 Agent、模板驱动、详细粗卡

生效决策：2026-09-08。替代默认六角色制卡方案，不追改历史结果。

## 目的与范围

用户没有逐卡科研复核的人力；粗卡供后续主题 Agent 使用。“粗”仅表示未围绕某个主题定向深化，不表示只读摘要或省略重要细节。本次止于单篇卡片生成，不实现主题、idea、调度或 Git 推送。

## 当前流程

Python 核对任务、原 PDF 和模板 → 一个 Codex 独立会话读取全部文字及页面图像、自动选型、按模板详细填写、同会话自检 → Python 验证来源记录、结构和归因格式 → 保存卡片、manifest、生成审计。

- 只有一次提供者 generate 调用；CLI 在本次会话内可能调用多次本机工具或自行重连，不是承诺一个网络请求。
- 不要求摘句、逐字匹配、固定事实数、批判条数或人工审批；不派生子 Agent。
- 保留八类模板的细节结构，版本升级为 1.1.0；原始来源 commit 和 blob 不变，适配内容重新计算哈希。
- 当前模型仍为总配置中的 gpt-5.6-sol / high；一个会话使用 generation_timeout_seconds，不再使用六个角色各自的配置。

## 内容及验收边界

| 层次 | 内容 | 程序能检查什么 |
| --- | --- | --- |
| 原文陈述 | 作者报告的结果、解释、假设和建议，区分其性质 | C 编号不重复、性质标记存在、来源位置等列非空 |
| 原文转述 | 当前论文引用的他人研究；不冒充已读被引原文 | 同上；不能凭格式证明归因真的正确 |
| AI 推理 | 单列依据的 C 编号、推导、额外假设、适用条件和边界 | 独立章节及标记、引用的 C 编号确实存在 |
| 信息边界 | 未报告、未取得或证据不支持的事项及具体影响 | 独立章节及标记；拒绝常见人工核验交办语句 |

模型应完整填写研究问题、数据、尺度、方法链、比较、关键结果和图表、局限。Python 要求保留模板二级章节（##）名称，但不再要求全部标题列表、章节顺序或表格数量与模板完全相同。允许额外图表解读、新增小节、调整普通表格布局及章节顺序；这些差异只记为提示，不阻止保存，也不改写正文。声明表的七列、C 编号及独立归因章节仍按内容协议检查。占位符、空正文、非法类型、来源不匹配仍拒绝；这些检查不能证明没有遗漏重要结果或所有推理正确。

结构策略版本为 template-major-sections-v1，报告位于最终 JSON 的 structure_validation、quality-audit.json 的同名字段，试运行还写入 trial.json。PASS_WITH_NOTES 表示存在允许的排版差异，不是质量失败，也不要求人工审批；缺少必需二级章节时才以 CARD_GENERATION_STRUCTURE_INVALID 返回具体 missing_sections。主标题和三级及以下小节变化不单独拒绝保存。

结果 quality_status=STRUCTURE_VALIDATED，workflow_protocol_version=rough-card-single-agent-v1，workflow_role_count=1。quality-audit.json 沿用文件名，实际是单会话生成记录；independent_review 和 scientific_correctness_verified 均为 false。source_access 中 full_read_verified、visual_understanding_verified 也保持 false，不伪装成独立验证。

## 操作

无需重新跑已经通过的独立 PDF 读取实验。当前 CEXH4PQA 已有正式卡，使用：

```powershell
Set-Location 'E:\phd\hydro-platform'
python automation/run.py evidence-generate-trial --item-key CEXH4PQA --json
```

结果保存到返回的 trial_path（默认 .runtime/card-trials/ 下）。正式卡、manifest 和任务不变。不自动把试运行结果替换为正式卡。

只有尚为占位卡的论文使用 evidence-generate；成功后任务变为 COMPLETED，重复运行跳过已有卡。归因合约失败进入 QUALITY_FAILED，需要修正配置或程序后显式重试，这是运维故障处理，不是逐卡科研人工审核。

## 输出保全与故障

- 模型返回的最后一条消息会先保存在 paths.runtime_dir/generation-drafts/<随机ID>.json，标为 UNVALIDATED_MODEL_OUTPUT，不是正式卡、不供主题读取。
- 保存位置由运行目录派生；不记录原始命令输出或认证信息。它含未校验模型内容，仅留本机，不提交 Git。
- 临时目录清理失败变为 SCRATCH_CLEANUP_FAILED 警告，继续校验及保存，不把成功调用判成模型失败、不重跑模型。不修复 ACL、不越权清理历史目录。
- 真正的进程/文件错误保留发生阶段、异常类型、errno/winerror；输出校验失败尽可能附上 draft_path。
- 已完成的单 Agent 草稿可通过 evidence-draft-export --draft <draft_path> --json 离线导出为 Markdown 预览，不调用模型、不重读 PDF、不更新正式卡或任务。只允许本机 generation-drafts 下的草稿，并核对当前证据包身份、当前模板结构和归因格式。正文原样保留，另存 export.json，状态 RECOVERED_DRAFT_PREVIEW。输出在 paths.card_trials_dir/recovered/ 下的新目录，重复导出不覆盖旧预览。
- 草稿没有完整执行审计，导出不是恢复生产验收：不补造原生成时间、模板版本、阅读回执，不自动将预览交给主题读取。export.json 保留原模型和原 prompt_sha256，当前模板版本只记作 checked_against_template_version。网络中断未产生完整输出时无法恢复不存在的结果。
- 新流程取消六次重复上下文开销，但真实时长和卡片质量仍须实跑确认，不能保证固定分钟数，更不能保证某等级期刊成果。

## 当前配置与兼容

总入口仍为 config/config.json。workflow_mode=single_agent，pdf_reader.adapter=local_path；单 Agent 模式不能同时提供 multi_agent_workflow，避免无效角色覆盖值误导。

旧配置未写 workflow_mode 时按 legacy multi_agent 解析，必须具备对应六角色协议与资产；仅用于兼容，不自动回退。主提示词为 evidence-card-generation-v7.md，v6 保留历史不改写；共用读取指引仍为 pdf-local-reading-v1.md。v7 只调整排版约束，不降低全文阅读和详细制卡要求。

读取解释器、shell、沙箱、文字引擎暂仍放在 pdf_direct_trial 对象中，与正式路径读取共用；该对象的 prompt_file/schema_file/timeout_seconds 只管独立读取实验。旧 MCP 字段在 local_path 下不执行。重命名配置与迁移可后置，不能为了命名好看中断已验证环境。

## 本次验证

全量 267 项离线测试通过；覆盖单次调用、来源身份、归因检查、正式幂等、旧卡试运行保护、历史 manifest 兼容、清理失败保全、原始 I/O 错误诊断，以及宽松排版保存和离线草稿导出。八类模板静态校验和 git diff --check 通过；无模型 generator-preflight 为前一轮记录。本次实际将 CEXH4PQA 已完成的草稿原样导出为独立 Markdown 预览，未重新调用模型；原 PDF、草稿、正式卡、manifest 和任务指纹保持不变，未提交或推送 GitHub。
