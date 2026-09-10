# 当前架构

## 目标链路

```text
团队成员的私人 Zotero 账号
        ↓
指定的 Zotero 共享群组库
        ↓
指定制卡机检测父条目和 PDF
        ↓
Python 调度与本地任务处理
        ↓
单 Agent 模板制卡与 Python 来源/写入流程检查（当前由 Codex CLI 提供）
        ↓
共享证据包粗卡 → 候选主题 → 逐篇原始 PDF 定向精读 → 回填修订候选
        ↓
人确认后才可转正式主题；代码不自动晋级
```

文件保存到本地共享仓库；只有用户明确要求才提交/推送GitHub。关键贡献账本和老师摘要已接入run-once，不额外调用AI；本机未提供身份时如实记未知。Windows每日计划已启用，调度门控后进入同一流水线；[调度](cron.md)。主题流程见 [主题工作流](themes-workflow.md)，进度记录见 [关键事件与日报](activities-and-daily-report.md)。

## 数据归属

| 内容 | 权威来源 | 是否进入 Git |
|---|---|---|
| 论文元数据和 PDF | Zotero 共享库 | PDF 不进入；必要元数据写入证据包清单 |
| 证据卡模板及来源清单 | GitHub 仓库 | 是 |
| 证据包 | GitHub 仓库 | 是 |
| 候选与正式主题 | GitHub 仓库 | 是 |
| 关键贡献事件 | GitHub 仓库 | 是 |
| 运行游标、队列、锁、原始日志 | 指定制卡机 `.runtime/` | 否 |
| Codex 登录凭据、密钥和令牌 | 制卡机本地凭据存储或密钥环境 | 否 |

## 已确认规则

- 取消 `students/` 目录，不按个人保存证据卡。
- 一篇论文只有一个团队共享证据包。
- 证据包骨架包含 manifest.json 和最小占位 card.md；占位卡不包含正式证据字段。
- 自动制卡只处理尚无非占位证据卡的论文；已有卡片在日常检测、补跑和恢复对账中均保持不变。
- 指定制卡机上的 Python 后台程序负责检测、门禁、调度和写入，并以非交互方式调用 Codex CLI 完成当前阶段的 AI 制卡。
- Codex CLI 使用制卡机上已登录的 Codex 订阅账号；运行不依赖人工打开 Codex 对话窗口，但当前阶段依赖该账号的有效登录状态和可用额度。
- 制卡分为两层：SingleAgentCardGeneratorAdapter 调用一次提供者并检查来源、非空输出，CodexLocalPdfAdapter 提供路径读取环境；保存层只执行流程与幂等保护，不检查正文格式。当前协议 rough-card-single-agent-v2，旧多 Agent 仅兼容，不自动回退。
- 主题按研究问题组织；粗卡→初版候选→每个主题所涉论文分别定向精读→修订候选。模板提示区分原文与 AI 推理，不用固定标签或标题作门槛。
- 新定向精读存于对应证据包 readings/RD-*/；历史 readings/TH-*/ 原样保留。主题只引用，不复制 PDF/粗卡，不修改原 card.md、原 manifest.json。
- 已完成步骤结果进入共享目录；本地锁和日志不进入 Git。全池输入不变时零模型调用；变化时保存 CHANGE 记录，候选可自动更新、合并、拆分并保留版本/演变链，不另起独立主题池。
- 八类证据卡模板来自固定外部提交，只复用内容模板；本平台保留来源、来源 blob、本地版本和适配后内容哈希，不复用来源脚本与工作流。
- Codex 自动选择唯一模板，不设置“待人工确认类型”；分类置信度和理由只用于追溯，非法类型按生成失败处理。
- 模板升级不自动批量重制历史卡；类型纠正或明确重制时生成新版本并保留旧版本。
- Zotero 父条目 Key 是指定群组库内的内部唯一标识。
- 论文新增者、PDF 补充者和系统制卡者分别记录。
- 只从监控系统启用之日起记录贡献，不追溯历史操作。
- 监控用于掌握进度和发现阻塞，不用于排名或绩效评价。
- 新电脑可依靠 GitHub、Zotero，并重新完成 Codex CLI 登录及其他本机凭据配置后恢复自动化流程。
- 可复现要求针对流程和已有结果的恢复，不要求 AI 重新生成的文字逐字相同。

## 恢复原则

- Zotero 和 GitHub 是可恢复数据源，本地 .runtime/ 只是可丢弃的派生状态。
- 恢复时先执行全量对账，再进入增量检测。
- 证据包以 Zotero 父条目 Key 定位；附件 Key 和 PDF 哈希用于确认输入版本，不作为自动覆盖已有卡片的授权。
- 恢复扫描必须幂等：重复执行不会新建第二个证据包或重复写入相同事件。
- 调度和环境安装必须由仓库中的脚本重建，不依赖只存在于旧电脑上的手工配置。
- 所有团队级可调整路径和固定参数由 `config/config.json` 集中提供；运行状态、证据事实和密钥按各自边界保存。

## 当前非目标

- 大规模模板重构及科研质量定稿；当前仅按用户确认适配归因与人工边界；
- 正式主题确认界面的开发（候选生成、定向精读和回填已在范围内）；
- 科研 idea 生成；
- 微信、邮件等外部通知；
- 对 Zotero 中每次细微编辑进行完整审计。

## 实现状态

主题层已改为[统一文献池与主题池](unified-theme-pool.md)：themes/index.md为入口，注册表保存长期主题身份和版本关系，候选可自动更新、合并、拆分；有适用旧精读时复用。旧BATCH只保留历史资料，不再决定主题身份或关联范围。真实旧成果迁移/无变化复用已过，合并/拆分目前有受控测试而非科学判断验收。

当前默认单 Agent、模板驱动、详细粗卡；Python只检查来源、非空输出、重复和安全写入，不检查归因标签或正文格式。PROCESS_VALIDATED是流程状态，不代表独立科学验证。主题、事件/日报、项目Python与Poppler安装、状态恢复与Windows计划已实现；Zotero未运行时单次启动后继续流水线已有本机实测。云端同步延迟、关机/登录恢复及干净异机验证仍未全面完成；Git自动同步不启用。

技术栈为 Python CLI、JSON/Markdown、Zotero 本地 API、Codex CLI 与 Poppler；没有 Web 登录或数据库权限层。模型凭据来自本机账号，不来自仓库。单机制卡机是部署约定，不是跨机授权系统，见权限/流程文档。

没有自动邮件，不建立 emails.md；没有公开网页，不建立 seo.md。Windows计划已启用，由 cron.md 记录；AI编排由 automation.md 记录。需要当前Windows用户登录，不等于关机/未登录时可运行。

详见 [当前单 Agent 规则](single-agent-rough-card.md)。GitHub 同步仍需用户明确授权，不能依据目标架构自动推送。

## 待确认

- 已实现单机每日计划和有限补跑；真实关机/登录及云端同步延迟场景的验收仍待完成；
- 真实论文验收后是否继续使用当前模型与推理强度、订阅额度保护阈值，以及论文 PDF 经 Codex 服务处理时的数据政策；
- 模板科研质量和跨页取证的小样本验收方法；
- 修订候选转正式主题的人工确认界面与版本操作；当前只保留人工确认边界，不自动晋级。

## 相关文档

- [technical-walkthrough-explained.md](technical-walkthrough-explained.md)：技术流程逐步解释版，用单篇论文的输入、状态、制卡、保存、异常和主题复用实例解释实现，附20分钟必讲内容。
- [mentor-blackboard-talk.md](mentor-blackboard-talk.md)：约 20 分钟技术实现黑板讲稿，按一键入口讲解接入、防重、模型调用、保存恢复与主题编排。
- [platform-operations-guide.md](platform-operations-guide.md)：整个平台的目录用途、实现链路、日常操作、换机权限、命令副作用、排错和备份说明。
- [unified-theme-pool.md](unified-theme-pool.md)：稳定主题身份、跨批次关联、自动合并/拆分、精读复用和迁移验收。

- [workstation-setup.md](workstation-setup.md)：统一安装/恢复入口、失败续跑和真实新路径演练。
- [native-deployment.md](native-deployment.md)：锁定下载、项目内PDF工具、故障保护与实际沙箱验证。
- [zotero-readiness.md](zotero-readiness.md)：应用启动、有限等待、待PDF补查与实际验收边界。
- [cron.md](cron.md)：已启用的每日计划、补跑、暂停与真实/待做验收。
- [flows.md](flows.md)：外部数据、模型与写入的实际检查顺序。
- [permissions.md](permissions.md)：单机角色、文件权限和跨机限制。
- [deployment.md](deployment.md)：项目依赖锁、独立安装与兼容性验证。
- [engineering-status.md](engineering-status.md)：需求—实现—证据及剩余缺口。
- [themes-workflow.md](themes-workflow.md)：候选、定向精读、回填与续跑。
- [activities-and-daily-report.md](activities-and-daily-report.md)：关键贡献和老师摘要。
- [PRD-zotero-to-evidence-pack.md](PRD-zotero-to-evidence-pack.md)：第一阶段无人值守自动化的正式需求。
- [user-stories-zotero-to-evidence-pack.md](user-stories-zotero-to-evidence-pack.md)：按实施顺序拆分的自动化用户故事。
- [recovery.md](recovery.md)：换机恢复步骤与验收标准。
- [tests.md](tests.md)：现有验证、拟建测试和当前缺口。
- [`automation.md`](automation.md)：自动化边界、身份和安全约束。
- [variables.md](variables.md)：总配置、运行变量、证据事实、协议常量与密钥的边界。
- [operator-manual.md](operator-manual.md)：当前可执行命令、结果解释、故障处理和真实验收记录。
- [task-state-machine.md](task-state-machine.md)：任务身份、状态转换、幂等、锁和崩溃恢复规则。
