# 粗卡到修订候选主题

现行流程已改为[统一主题池](unified-theme-pool.md)：全池粗卡与已有修订主题共同参与规划，支持候选UPDATE/MERGE/SPLIT与跨运行精读复用，统一入口是themes/index.md。下方cards-to-refined-candidates-v1的BATCH布局与联调记录保留为历史说明，不再是日常主流程，也不再限制跨批次关联。

版本：cards-to-refined-candidates-v1，2026-09-09。

## 操作

```powershell
Set-Location 'E:\phd\hydro-platform'
python automation/run.py run-once --json
```

完整入口：扫描 Zotero → 已有卡跳过/缺卡生成 → 候选发现 → 各主题各论文定向精读 → 修订候选。制卡有失败、阻塞或限额延后时，不用临时不完整集合反复造新主题批次。

只对现有粗卡继续主题流程（不扫描 Zotero、不重制粗卡）：

```powershell
python automation/run.py themes-run --json
```

`themes-run --dry-run --json` 只读预览，不写文件、不访问 Zotero、不调用模型。真实精读需要 Zotero 已同步原始 PDF、已有任务清单、Codex 订阅账号可用。换机缺少任务时先按恢复手册执行 tasks-sync。

中断后再运行同一条命令。步骤返回后先保存 result.json，再生成 Markdown；下次自动补完写入或继续下一步，不从第一篇重跑。每步受模型超时及整轮可选时间预算限制，不无限循环重试。Ctrl+C 保留已完成工作。

## 保存位置

```text
themes/candidates/BATCH-<输入版本>/
  inputs.json                 来源标识、卡/PDF/提示词指纹、目标、模型设置
  discovery-result.json       候选发现结果与执行元数据
  problem-clusters.md          问题簇与未纳入文献说明
  index.md                    本批主题入口
  TH-<稳定编号>/
    plan.json                 初版与关联论文精读任务
    initial.md                粗卡形成的初版候选
    revision-result.json      回填的模型结果
    revised.md                主要阅读的修订候选主题
    manifest.json             CANDIDATE_REFINED、来源引用、保存指纹
  completion.json             全部步骤已保存的标记
evidence-packs/EV-<父Key>-<题名>/
  card.md                     原粗读卡：不覆盖
  manifest.json               原粗卡清单：不改写
  readings/TH-<稳定编号>/
    result.json               定向精读与来源流程记录
    reading.md                定向精读正文
    manifest.json             来源、主题、指纹、保存状态
.runtime/logs/theme-runs/      每轮摘要，不进入 Git
.runtime/theme-drafts/         纯文本调用原始输出，不进入 Git
```

未完成修订时 index 的修订链接可能还不存在，以 manifest 和终端摘要为准。主题不存 PDF 或粗卡副本；精读存在论文证据包内。路径从总配置推导，不以绝对路径作为文献/主题身份。

共享 result.json 保留模型成果以断点续跑；不是临时日志。无需上传本地队列才能复用完成结果。保存指纹只发现改动，不能证明科学结论正确。

## 总配置

config/config.json 的 theme_pipeline：

| 字段 | 作用 |
|---|---|
| enabled | true：run-once 继续主题；false：完整入口止于卡片，仍可显式 themes-run |
| research_goal | null：无预设目标；字符串：围绕该目标组织候选 |
| model | null：继承 card_generator.model；非空：覆盖主题模型 |
| reasoning_effort | null：继承制卡思考强度；非空：覆盖主题阶段 |
| timeout_seconds | null：继承 generation_timeout_seconds；数值：每次调用上限 |
| assets_dir | 三个 Markdown 模板及 schema 目录，相对项目根或绝对路径 |

paths.themes_dir / evidence_packs_dir / logs_dir / lock_file 控制保存位置。当前仅实现 Codex CLI + local_path，不能只改字符串就调用未实现的提供商。schema 只用于 JSON 传输和来源路由，不检查正文标题、表格、长度、标签或措辞。

## 边界与恢复

- 相同卡片集合、目标、模型/强度和模板指纹产生相同批次；重跑复用完成步骤，不重复精读。
- 同一候选重复列同篇时合并 focus，只读一次；同篇服务不同候选时分别定向读。
- 新增卡或改目标/模型/模板另建批次，保留旧批次。首版不做跨批次语义去重、自动合并或增量演化；新批次可能再次读同篇，并不是每日无变化也重跑。
- 同机并发有运行锁；仅一台生产机，不提供跨电脑分布式写锁。
- 未知来源、空输出、PDF 不匹配、人工改动、进程/磁盘故障属于流程阻塞；保留已完成步骤。人工修改生成文件不被覆盖，需显式处理版本冲突。
- 模板指导原文/AI 推理/信息边界的表达，不以固定标签验收。程序不独立判断科学质量，不保证任何期刊级别成果。
- 小样本仅验证流程，不代表领域全貌；不强凑主题数，允许 NO_CANDIDATES。
- 回填可收窄、更正或建议撤回；不删初版、不自动转正式主题、不生成 idea 包。
- 未新建定时任务、未自动提交/推送 Git。共享成果必须在用户要求并实际推送后才能从 GitHub 恢复。

## 用户故事与流程验收

按 pm-execution:user-stories 的 Card/Conversation/Confirmation 拆分，不扩大到实验执行。

### TH-01 候选发现

作为老师/学生，我希望粗卡形成问题导向候选，了解文章关联与研究进展。

讨论：可以有/没有目标，先问题簇再候选，模板指导内容。

验收：当前群组完整粗卡参与；占位不参与；只路由提供过的 evidence_id；重复同篇路由合并；允许零候选；非空正文原样保存，无固定格式门槛。

### TH-02 逐篇定向精读

作为老师/学生，我希望系统针对候选重新读原始论文，不只概括粗卡。

讨论：每候选相关文献分别精读，保留原文/推理区别，不安排逐卡人工审查。

验收：逐篇交付当前原始 PDF；绑定父条目/附件/指纹；缺 PDF 不伪造精读；每个主题-文献独立保存；粗卡不改；失败后复用成功步骤。

### TH-03 回填候选

作为老师/学生，我希望精读能改变初版，不只是增加旁支笔记。

讨论：“回滚”是回填修订，不删初版；人只在升正式主题时参与。

验收：相关精读全完成才修订；修订输入包含精读；保留 initial/revised；保存来源引用；状态 CANDIDATE_REFINED、confirmed 不动；不生成 idea。

### TH-04 一键续跑

作为运行者，我希望一条命令完成且失败可续，减少重复等待。

讨论：不逐篇改配置，不加多 Agent 复核体系。

验收：run-once 按配置接入；themes-run 可单独运行；相同输入二次模型调用为零；部分保存失败后不重复模型；并发和人工编辑不覆盖；本地运行状态丢失可复用共享完成记录。

## 验证记录

2026-09-09：347 项自动测试通过（23.055 秒），包含模拟端到端、多篇/多主题、续跑、防覆盖、Windows Git 换行兼容、配置与命令入口。这是工程测试，不是科学质量验收；真实三篇联调另记。

### 已完成的真实联调

- 共享库：6618088 / qinjiajun；只使用现有 CEXH4PQA、7F8QLSNY、JUKFEIFC 三张粗卡和各自原始 PDF（16、17、43 页）。模型为 gpt-5.6-sol / high。
- 批次：BATCH-ae9692ecedb0a052a607。生成 2 个初版候选、3 份逐篇定向精读、2 个修订候选；三份精读仍明确记录 full_read_verified=false、visual_understanding_verified=false，流程报告不是独立科学核验。
- 首次发现候选后暴露 PDF 适配器 working_directory 接线错误（应传 PDF 所在目录，不是证据包目录），已修复并加测试。恢复时复用发现结果，没有重做候选。恢复这一轮为 1587.73 秒（约26分28秒），另有先前发现阶段约2分41秒；不是单篇卡片耗时。
- 完成记录：.runtime/logs/theme-runs/cd81b063d8a146dcbbb56c00c17a109e.json；恢复轮保存5个新步骤、复用1个发现步骤。共享 completion.json 标记本批完成，但 formal_confirmation=null。
- 再次 themes-run：0.05秒，model_call_count=0、reused_step_count=6、saved_step_count=0。
- 完整 run-once 真实复跑：1.14秒，3张旧卡全跳过，主题复用6步，模型调用0，status=COMPLETED、阻塞/失败均为0。记录：.runtime/logs/pipeline-runs/20260908T181151-35d8ee42af5f4dce806d9ccc2d0c9956.json。
- 原粗卡、原证据包清单/审计未覆盖；confirmed 仍仅有 README。未生成 idea，未提交或推送 Git。

[本批结果入口](../themes/candidates/BATCH-ae9692ecedb0a052a607/index.md)。两份 revised.md 才是本轮最终应看的修订候选，initial.md 留作对照。
