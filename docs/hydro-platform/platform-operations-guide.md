# hydro-platform 平台完整操作说明

这份说明面向老师、学生和接手维护的人，回答三个问题：**每个文件夹做什么、文献如何逐步变成主题、在本机或另一台电脑上怎样操作。**

核对基线：代码提交 `48a9130`，以及本次检查时本地实际保存的成果。目录、命令和实现以仓库当前代码为依据，不把历史方案当成现有功能。后续改动应同时维护本说明；旧命令输出和验收记录继续保留在专项文档中。

## 阅读导航

- [1. 平台现在能做什么](#overview)
- [2. 每个文件夹怎么用](#directories)
- [3. 一篇论文和一个主题怎样保存](#storage)
- [4. 各个环节怎样实现](#workflow)
- [5. 日常怎么操作](#daily-use)
- [6. 换电脑安装、配置和权限](#new-computer)
- [7. 命令速查与副作用](#commands)
- [8. 怎样判断完成、等待和失败](#results)
- [9. 常见问题怎么处理](#troubleshooting)
- [10. 每日自动运行](#schedule)
- [11. GitHub 共享、备份和恢复](#backup)
- [12. 维护者代码地图与验证边界](#maintenance)

<a id="overview"></a>
## 1. 平台现在能做什么

这是一个 **Windows 本地文件型知识平台 + Python 自动化程序**，不是网页登录系统。PDF 由 Zotero 管理；科研结果是 Markdown 和 JSON；GitHub 用于保存、版本管理和分发已提交的成果。

```text
人在 Zotero 群组库中收录论文并附上 PDF
                    ↓
程序扫描本机已同步的群组库，识别新增及后补 PDF
                    ↓
检查 PDF 可读性、来源身份，建立或更新任务
                    ↓
无完整粗卡：单 Agent 读原始 PDF → 按模板写详细粗卡 → Python 保存
已有完整粗卡：核对记录后复用，不重新制卡
                    ↓
所有有效粗卡 + 已有主题 + 可复用精读 → 统一主题池规划
                    ↓
对必要论文做定向精读；仍适用的旧精读直接复用
                    ↓
依据精读修订候选主题 → 保存版本、来源引用和演变关系
                    ↓
刷新主题入口、关键贡献记录和老师日报
```

### 当前已经实现

- 指定 Zotero 群组库的检测、PDF 门禁和任务管理。
- 单 Agent、模板驱动、详细粗卡；自动选论文类型，不设置类型人工审批。
- 一次命令串行处理本轮全部可处理论文，逐篇完成即正式保存。
- 统一文献池与主题池；候选可自动补充、合并、拆分，并保留历史。
- 定向精读复用、主题回填、已保存步骤的续用。
- 关键贡献事件、每日摘要、项目依赖安装、状态恢复和 Windows 调度。

### 当前成果与边界

本次只读检查确认：**7 个完整证据包、8 份已保存的定向精读、4 个精读回填候选主题**。同一份精读可能被多个主题引用，不能把引用次数当成精读文件数。

结果从 `hydro-platform/themes/index.md` 查看。已有主题为：

1. 洪水—电力—排水互依系统的时变双向反馈与静态级联近似边界。
2. 城市洪涝级联关系的语义—证据—量化方法匹配：从文本事件网络到可检验机制。
3. 短历时极端降雨向山洪响应传递的尺度与条件约束。
4. 洪水物损向人口服务中断的模型传递：道路可达性、互依结构与验证边界。

**尚未实现或不能承诺的内容：**

- RSS/期刊推荐到 Zotero 的入库链路不在本仓库当前自动化入口中。
- 不支持把 Zotero 个人“我的文库”直接当群组库使用；当前对接的是群组接口。
- 没有自动 OCR；不能保证扫描型 PDF 能通过当前门禁。
- 不生成科研 idea；没有正式主题的专用人工确认命令或界面。
- 没有多机共同任务锁、平台角色权限系统或自动 GitHub 同步。
- 正文保存成功不等于科学正确性已验证，更不代表能够保证子刊级成果。

“单 Agent”指一篇粗卡不再走六角色流水线，**不代表整个平台只调用一次模型**。主题规划、各次必要精读、各主题回填仍是独立模型步骤。

<a id="directories"></a>
## 2. 每个文件夹怎么用

### 2.1 根目录总览

以下是逻辑目录树；自动生成的编号目录按同一种规则管理，不逐个重复说明。

平台自身不再保留 README 文件；全部文档集中在仓库根的 `docs/hydro-platform/`，本说明是其中的综合入口。Python 环境是 uv 工作区的共享 `.venv`，位于仓库根而不是平台目录内。

```text
hydro-platform/
├─ config/                        总配置与字段解释
├─ evidence-packs/                统一论文证据包
├─ themes/                        统一主题池
│  ├─ candidates/                 候选及其版本
│  ├─ changes/                    全池变更和迁移记录
│  └─ confirmed/                  正式主题预留区
├─ templates/                     科研内容模板
│  ├─ evidence-cards/             八类粗卡模板及来源清单
│  └─ themes/                     规划、精读、回填模板与传输结构
├─ automation/                    可执行程序
│  ├─ src/hydro_platform/         实现模块
│  │  └─ card_generators/         模型调用与制卡适配层
│  ├─ prompts/                    制卡和 PDF 阅读提示词
│  ├─ schemas/                    输出与清单结构
│  ├─ setup/                      依赖版本、来源和哈希锁
│  └─ tests/                      自动化测试
├─ members/                       可选的成员身份映射
├─ activity/                      共享关键贡献账本
├─ reports/daily/                 每日摘要
├─ pyproject.toml                 平台包与命令入口声明（uv workspace 成员）
├─ .runtime/                      本机任务、运行记录、草稿和临时文件
├─ .tools/                        本项目 PDF 工具
└─ .git/                          Git 本地历史与远端信息
```

| 文件夹 | 谁、什么时候使用 | 是否进入 Git / 是否手工维护 |
|---|---|---|
| `hydro-platform/config/` | 操作者换机、改模型、路径、代理、调度时；[字段说明](config.md) | 团队配置提交；`config.local.json` 不提交。允许编辑配置，不存密码 |
| `hydro-platform/evidence-packs/` | AI 做主题输入，老师/学生必要时查看论文分析；[说明](evidence-packs.md) | 共享成果提交；由程序维护，不随便改名或移动 |
| `hydro-platform/themes/` | 老师/学生查看研究问题、进展、边界和证据；[说明](unified-theme-pool.md) | 共享成果提交；主要读 `index.md` 链接到的当前版本 |
| `hydro-platform/templates/` | 模板维护者调整科研分析要求；[说明](templates.md) | 提交；模板有版本与来源，不能仅改正文而忽略清单 |
| `hydro-platform/automation/` | 日常通过入口运行，开发者维护实现；[说明](automation.md) | 源码、测试、依赖锁提交；日常不用改源码 |
| `hydro-platform/members/` | 需要把实际 Zotero 用户 ID 映射到成员编号时；[说明](permissions.md) | 可提交必要映射；不是学生工作区，不赋予权限 |
| `hydro-platform/activity/` | 程序记录论文新增、补 PDF、卡片完成和阻塞事件；[说明](activities-and-daily-report.md) | 共享账本提交；不手改哈希或把它当临时缓存 |
| `hydro-platform/reports/daily/` | 老师查看当天新增、完成、等待和阻塞；[说明](activities-and-daily-report.md) | 摘要提交；由程序刷新，不在生成文件里直接写个人笔记 |
| `docs/hydro-platform/` | 初次使用、交接、排错及维护时；[架构](architecture.md) | 提交；本说明是综合入口，专项文档提供细节 |
| `.runtime/` | 程序记录状态，排错时按终端返回的路径查看 | 不提交。部分内容可重建，但未发布草稿不能凭空找回，不能整目录随意清空 |
| `.venv/`（仓库根，不在平台目录内） | 程序使用 uv 工作区共享的 Python 和依赖 | 不提交、不从旧电脑搬运，用仓库根的 `uv sync --all-packages` 重建 |
| `.tools/` | 程序使用 Poppler 的 PDF 信息和页面渲染工具 | 不提交，用锁文件重建，不需要改系统 PATH |
| `.git/` | Git 管理版本和远端 | Git 自己管理；不是普通知识文件夹，不手工修改 |

根目录另外几个文件：

- `hydro-platform/pyproject.toml`：Python 项目元数据、入口和版本范围。
- `hydro-platform/.python-version`：Python 版本提示；安装器还会检查依赖锁的要求。
- `hydro-platform/.gitignore`：排除运行区、环境、私人配置和证据包中的 PDF 等。
- `.venv.bootstrap.lock`：依赖安装锁；有锁文件不必然表示进程仍在运行，不要据此直接删除。

**没有 `students/` 目录。** 老师和学生共同使用证据包与主题池，不按姓名复制知识。

### 2.2 automation 下各分区

| 位置 | 作用 | 普通操作者要做什么 |
|---|---|---|
| `hydro-platform/automation/run.py` | 用户命令入口，加载 `src` 下代码并进入 `cli.py` | 日常在仓库根运行 `uv run hydro-platform ...`（旧式直接调用脚本的写法已废弃） |
| `hydro-platform/automation/scheduled_run.py` | Windows 计划固定入口，进入相同调度逻辑 | 由计划调用，不手写第二套流水线 |
| `src/hydro_platform/` | 扫描、任务、制卡、主题、恢复等实现 | 排错/开发才查看，详见第 12 节 |
| `src/hydro_platform/card_generators/` | 单 Agent 包装、Codex PDF/文本调用、代理和进度控制 | 模型配置在 `config`，不用为换路径改这些代码 |
| `hydro-platform/automation/prompts/` | 当前 `evidence-card-generation-v8.md` 和 `pdf-local-reading-v1.md` 等；[提示词](automation.md#提示词) | 当前文件由配置选定，旧 v3–v7、六角色提示词不是每日运行步骤 |
| `hydro-platform/automation/schemas/` | JSON 传输和证据清单协议；[数据结构与流程检查](automation.md#数据结构与流程检查) | 是程序接口，不是强制每张 Markdown 的标题、表格或固定措辞 |
| `hydro-platform/automation/setup/` | `dependencies.lock.json`、`native-tools.lock.json`；[安装配置](deployment.md) | 安装按来源、版本和 SHA-256 校验，不直接运行锁文件 |
| `tests/` | 单元与受控集成测试 | 开发改动后回归；测试通过不等于真实网络或科学质量通过 |
| `verify_*.py` | 安装、恢复、调度等专项演练工具 | 非日常入口；有的下载依赖，有的创建/触发调度探针，不能当只读体检随意运行 |

### 2.3 templates 下各分区

`templates/evidence-cards/` 当前有八类模板，全部启用：

| 模板 ID | 文件 | 对应材料 |
|---|---|---|
| `original-research` | `01_original-research.md` | 原创研究 |
| `review-synthesis` | `02_review-synthesis.md` | 综述/证据综合 |
| `survey-monitoring-statistics` | `03_survey-monitoring-statistics.md` | 调查、监测、统计 |
| `engineering-report` | `04_engineering-report.md` | 工程报告 |
| `book-chapter` | `05_book-chapter.md` | 图书章节 |
| `standard-guideline-policy` | `06_standard-guideline-policy.md` | 标准、指南、政策 |
| `dataset-data-product` | `07_dataset-data-product.md` | 数据集/数据产品 |
| `software-model-code` | `08_software-model-code.md` | 软件、模型、代码 |

`_catalog.json` 保存来源仓库/提交/文件、来源 blob、本地版本和模板内容哈希。当前本地模板版本是 `1.1.0`。这里只复用并适配同门的模板，没有接入对方的程序工作流；来源记录详见 `hydro-platform/templates/evidence-cards/_catalog.json`，[模板说明](templates.md)。

`templates/themes/` 的四组内容：

- `discovery.md`：按研究问题组织候选的基础指引，当前仍与全池提示词一起使用。
- `pool-discovery.md`：结合全池卡片、已有主题、历史精读，规划新建/更新/合并/拆分。
- `focused-reading.md`：对指定论文围绕当前候选及重点做精读。
- `refinement.md`：用精读结果回填候选，调整论断及边界。
- 对应 `*.schema.json`：约定机器返回字段、来源和操作结构，不强行规定科研正文排版。

### 2.4 .runtime 下是什么

这些文件由运行生成，未运行过的副本可能没有相应目录。

| 文件/目录 | 用途 | 注意 |
|---|---|---|
| `tasks.json` | 各条目的状态、输入指纹、处理次数、租约与历史 | 本机派生任务，不是共享证据卡总表 |
| `zotero-snapshot.json` | 独立扫描/恢复用的 Zotero 基线 | `run-once` 会直接同步任务，不需要先手动 `scan` |
| `worker.lock*`、`scheduler.lock` | 整轮、主题、事件、安装等本机互斥 | 不代表跨机互斥；不要手删仍被使用的锁 |
| `scheduler-state.json`、`scheduler-last-result.json` | 每日任务时段、尝试、冷却和最近结果 | 删掉可能丢失去重和重试记忆 |
| `logs/pipeline-runs/` | 完整流水线最终报告 | 优先查看当前终端返回的 `report_path` |
| `logs/theme-runs/` | 主题流程报告 | 看模型调用、复用和失败阶段 |
| `logs/setup-runs/`、`logs/recovery-runs/` | 安装和恢复报告 | 区分哪步成功、哪步失败 |
| `logs/generation-failure-*.json` | 脱敏失败诊断 | 并非每条错误都有同样详细的诊断，缺失时保留终端输出 |
| `generation-drafts/` | 模型返回但尚未正式接受/保存的草稿 | 不能视为已完成卡片；可能是失败后唯一保留的正文 |
| `pending-publications/` | 多文件发布的待完成记录 | 下次对账可用于补完已准备好的写入 |
| `card-trials/`、`theme-drafts/` | 试运行、导出预览及主题失败材料 | 不会因为目录存在就自动成为共享成果 |
| `wheel-cache/`、`native-cache/` | Python/PDF 工具下载缓存 | 可用依赖锁重新下载；清理前确认安装未运行 |
| `pdf-role-*`、`pdf-sandbox-check-*`、`pdf-quote-check-*` | 当前或历史 PDF 阅读/沙箱/实验临时目录 | 原始 PDF 仍在 Zotero；清理异常可能留下目录，不按名字盲删 |
| `deployment-trials/`、`native-trials/`、`recovery-trials/`、`readiness-trials/`、`setup-trials/`、`schedule-probes/`、`release-check-*` | 过去的安装、迁移、调度及检出验证材料 | 不是新的生产知识池，也不是新电脑必需拷贝的目录 |

### 2.5 documentation 怎么找

| 需要了解什么 | 文档 |
|---|---|
| 当前整体结构、操作流、权限和自动化边界 | [architecture](architecture.md)、[flows](flows.md)、[permissions](permissions.md)、[automation](automation.md)、[variables](variables.md) |
| 本说明之外的详细命令、历史输出和演进记录 | [operator-manual](operator-manual.md) |
| 完整流水线和当前粗卡规则 | [run-once](run-once.md)、[single-agent-rough-card](single-agent-rough-card.md) |
| 统一主题池及早期主题链路 | [unified-theme-pool](unified-theme-pool.md)、[themes-workflow](themes-workflow.md) |
| 换机、依赖、PDF 工具、状态恢复 | [workstation-setup](workstation-setup.md)、[deployment](deployment.md)、[native-deployment](native-deployment.md)、[runtime-maintenance](runtime-maintenance.md)、[recovery](recovery.md) |
| 调度、Zotero 就绪、老师摘要 | [cron](cron.md)、[zotero-readiness](zotero-readiness.md)、[activities-and-daily-report](activities-and-daily-report.md) |
| 需求、任务拆分、状态协议、风险和验证 | [PRD](PRD-zotero-to-evidence-pack.md)、[用户故事](user-stories-zotero-to-evidence-pack.md)、[状态机](task-state-machine.md)、[风险预演](PreMortem-hydro-platform-2026-09-08.md)、[工程状态](engineering-status.md)、[验证地图](tests.md) |

部分旧文档仍包含“2 个主题”“六 Agent”“正文格式门禁”“调度尚未接入”等历史描述。本说明按当前入口核对；**不要将旧 US 实施顺序、旧状态机说明中的未接入清单，理解为现在还必须手动逐步操作。**

<a id="storage"></a>
## 3. 一篇论文和一个主题怎样保存

### 3.1 一篇论文一个共享证据包

```text
evidence-packs/
└─ EV-父条目Key-标题简写/
   ├─ card.md                  通用详细粗卡
   ├─ manifest.json            论文身份、来源、状态和生成记录
   ├─ quality-audit.json       部分包有的流程/生成回执
   └─ readings/
      ├─ RD-编号/              新版定向精读
      │  ├─ reading.md
      │  └─ result.json
      └─ TH-旧主题编号/        历史精读，保留原位置及旧 manifest
```

- `card.md`：供主题规划使用的通用论文分析。“粗读”是相对于主题定向精读，不是只读摘要。
- `manifest.json`：绑定共享库、父条目、附件、PDF 指纹、实际模板/模型及保存记录。程序用它定位和校验成果。
- `quality-audit.json`：名字不等于科学认证。当前单 Agent 保存的是 `PROCESS_VALIDATED` 等流程信息；历史包可能是其他协议或没有此文件。
- `readings/`：同一篇论文可有多个分析重点；新精读不覆盖原粗卡。多个主题可以引用一份适用精读。

**判重依据不是论文标题或文件名：**

| 标识 | 表示什么 |
|---|---|
| `group_id + parent_key` | 指定共享库里的一条论文记录 |
| `EV-父条目Key` | 对应证据包编号 |
| `attachment_key + pdf_sha256` | 实际输入 PDF 的身份与版本 |
| `task_id` | 群组、父条目、附件和 PDF 哈希共同决定的处理输入 |

同一条 Zotero 记录不会反复制卡；但同一论文如果被重复入库成两个不同父条目，本平台不自动认定它们是同一篇。文献层面的查重仍需在入库环节处理。

当前没有另一个人工维护的 `evidence-packs/_registry.json`。证据包通过各自的 `manifest.json` 查找；`themes/_registry.json` 只负责主题。

### 3.2 一个研究问题一个长期主题

```text
themes/
├─ index.md                          当前主题和历史入口
├─ _registry.json                    当前指针、版本、前身后继与处理指纹
├─ candidates/
│  ├─ TH-长期编号/
│  │  └─ versions/CHANGE-编号/
│  │     ├─ initial.md               精读前的候选
│  │     ├─ revised.md               精读回填后的候选，优先阅读
│  │     ├─ plan.json                本次操作、原因及论文精读安排
│  │     ├─ manifest.json            状态、来源及精读引用
│  │     └─ revision-result.json     回填结果及执行记录
│  └─ BATCH-旧编号/                  历史成果位置，不代表独立主题池
├─ changes/
│  ├─ CHANGE-编号/
│  │  ├─ inputs.json                 本次输入与原主题池状态
│  │  ├─ discovery-result.json       规划模型结果
│  │  ├─ plan.json                   经流程校验的演化安排
│  │  ├─ problem-clusters.md         研究问题归纳
│  │  └─ commit.json                 完整主题池发布记录，不是 Git commit
│  └─ IMPORT-编号/                   旧成果接入统一池的记录
└─ confirmed/                        正式主题预留目录
```

主题目录只引用论文粗卡与精读，不复制原 PDF，也不把每个主题再变成一套文献库。

补充/修正沿用 `TH` 编号并增加版本；合并/拆分产生新编号，旧主题转入历史并保留前后关系。目录存在不等于该版本已成为当前版本：**以统一入口和注册表为准**，因为中断时可能已有准备好的子目录、但全池还未发布。

所有当前主题仍是候选。`CANDIDATE_REFINED` 不是“正式主题”；目前不能靠手动搬进 `confirmed/` 来代替尚未实现的正式确认流程。

<a id="workflow"></a>
## 4. 各个环节怎样实现

### 4.1 启动与配置

`hydro-platform/automation/run.py → cli.py → config.py`：解析子命令与总配置。默认读取平台的 `hydro-platform/config/config.json`；显式 `--config` 可选择另一份完整配置。

配置包含路径、模型、代理、时间限制、共享库和调度。来源指纹、任务状态、科研内容不是配置项，不应人工塞进总配置。`config.local.json` 不自动发现、不与默认配置合并。

### 4.2 发现论文和后补 PDF

`zotero.py` 通过本机 Zotero API 查看群组；`snapshot.py` 分页读取群组条目及附件，并支持与旧快照比较。访问范围是 `/api/groups/{group_id}/...`，不是网页搜索，也不是个人库接口。

`run-once` 使用 `tasks.sync_tasks` 直接扫描并更新任务，不必先手动运行 `scan`。它会重新观察没有 PDF 的已有条目，因此之后补上的 PDF 不会因为论文“不是今天新增”而永远漏掉。

这是**定时/手动触发的轮询**，不是 Zotero 向本程序主动推送实时消息。看见的也是本机同步状态；本地 API 可用不证明云端已全部同步。

### 4.3 PDF 门禁与原始路径交付

`pdf_gate.py` 检查：

1. 父条目是否有 PDF；当前多个 PDF 附件会阻塞，不自动猜主文/补充材料。
2. Zotero 是否返回本地文件地址，文件是否存在且可读。
3. 文件大小、基础 PDF 结构和 SHA-256。
4. Zotero 全文索引是否就绪，文字量是否达到配置阈值。

当前默认最小体积 `1024` 字节、最小索引文字量 `1000`。门禁读取全文索引是为了判断就绪，**不是拿索引或摘要代替 AI 阅读原始 PDF**。不自动 OCR，不支持直接把网络共享文件地址当成本机 PDF。

`pdf_delivery.py` 再次核对任务与证据包来源，返回原 PDF 路径、父条目/附件 Key、PDF 哈希和目标包位置。PDF 继续留在 Zotero；不复制进共享证据包。

### 4.4 任务、重复检查与排队

`tasks.py` 保存状态、处理次数、输入指纹和租约；`pipeline.py` 取得整轮锁，按创建时间等顺序串行处理本轮任务。默认整轮篇数/时长不设总上限，但每篇会话有时限、失败有重试预算。

程序会先核对已有证据包和可恢复记录：有完整卡则跳过；有合格待发布结果则对账恢复；没有完成成果且任务可处理时才调用模型。

“已经完成”的依据包含有效来源清单、非空非占位正文、正文与记录指纹一致，以及已声明的生成审计一致。**文件夹存在、文件名叫 `card.md`，或者只有任务状态 `COMPLETED`，都不能单独证明完成。**

### 4.5 单 Agent 全文阅读与详细粗卡

`card_generation.py` 读取当前制卡提示词和八类模板，构造请求。`SingleAgentCardGeneratorAdapter` 包装 `CodexLocalPdfAdapter`，后者负责实际调用 Codex CLI。

当前阅读方式：

1. Python 确认原 PDF 页数和输入哈希。
2. 在本机临时工作区先检查沙箱能否读 PDF、提取文字和渲染页面；失败时不花模型额度。
3. 将原 PDF 路径、已安装工具路径、模板和任务要求交给 Codex。
4. Codex 在隔离会话中通过本机 shell、项目 Python/pypdf、Poppler 和看图工具处理 PDF；中间页面图像或文字可放在临时工作区。
5. 返回模板类型、阅读声明、Markdown 正文和必要机器字段。

当前正常调用不启动 `hydro_pdf_reader` MCP，不启用旧六 Agent，也不要求用户在聊天窗口逐篇粘贴路径。CLI 显式配置沙箱和工具边界，并关闭本次调用中的额外 apps/plugins、多 Agent 和网页搜索；换电脑不需要复制这里聊天所用的 PM skills 或 Zotero 插件。

“只给路径”仍需要实际读取工具。模型接收到路径字符串不等于已经读到了文件；本地读取测试和模型阅读声明也不等于独立证明它理解了全部图表。

### 4.6 Python 保存 Markdown

模型返回的 Markdown 是 JSON 结果中的一个字段。Python 核对返回结构、有效模板、来源/阅读记录和非空正文，再负责正式发布，而不是授权模型直接随意改证据包目录。

`publication.py` 与保存模块通过待发布记录、临时文件和原子替换，协调正文、清单与审计。成功后任务进入 `COMPLETED`，正式成果直接在证据包中，不需要手动搬运。

正文不再受固定标题顺序、表格列数、原文摘录数量或“AI 推理”固定标签限制；但 JSON 无法解析、无效模板、来源不符、空结果和冲突写入仍会拒绝。这是接口/数据完整性检查，不是重新引入科研正文格式门禁。

### 4.7 全池候选主题规划

`themes.py` 收集目标库所有有效粗卡，`theme_pool_runner.py` 组合以下材料：所有粗卡、已有主题当前版本、仍匹配论文来源的历史精读、可选研究目标。

群组、卡片来源、研究目标、模型/强度、主题模板和共用 PDF 阅读提示词共同参与输入指纹。输入未变就复用；因此“没有新论文”不一定意味着零模型调用，**改研究目标、模型或主题模板也可能触发重新规划**。

规划 Agent 根据研究问题、机制和证据关系提出 `CREATE / UPDATE / MERGE / SPLIT`。程序校验编号、操作对象、来源及正式主题保护，不以关键词相似直接强行合并。

### 4.8 定向精读与回填

每个候选有论文任务和分析重点：

- 规划认为已有精读适用时，引用它；程序检查来源及文件一致性。
- 没有适用精读时，重新交付对应原 PDF，围绕当前重点精读，保存到论文包的 `readings/RD-*/`。
- 汇总精读结果、初版候选和原主题，调用回填步骤写 `revised.md`。

不保证每次都对所有论文重读，也不保证第一次已精读就永远不重读。是否复用取决于问题/重点与证据是否适用；机器流程不能独立证明这项判断的科学质量。

`theme_pool.py` 待所有替代版本准备完成后发布全池注册表和索引。中断时旧主题保持有效，已保存且输入匹配的步骤下次可续用；并非把模型未完成的半个会话从断点继续。

### 4.9 贡献记录、日报与定时

`activity.py` 在整轮前后记录关键事件并去重；`daily_report.py` 根据事件、有效卡片、任务和本轮报告生成 Markdown/JSON。它们不再调用额外模型，也不自动通知微信或邮箱。

成员身份只能采用 Zotero 接口明确给出的操作者 ID，再通过 `members/members.json` 映射；缺失时记未知，不从论文作者推断是谁入库。当前成员目录没有真实映射文件，成员编号也不是权限令牌。

`windows_schedule.py` 管理 Windows 计划，`scheduled.py` 判断是否到期、是否已完成、是否需要有限补查，再进入同一个 `run_once`。没有第二套隐蔽的知识生成路径。

<a id="daily-use"></a>
## 5. 日常怎么操作

### 5.1 只看成果

不需要运行 Python、安装依赖或消耗模型额度：

- 看方向和研究进展：打开 `hydro-platform/themes/index.md`，进入当前 `revised.md`。
- 看论断来自哪里：沿修订主题末尾的“粗卡 / 定向精读”链接查看。
- 看单篇通用分析：打开对应证据包的 `card.md`。
- 看运行进度和阻塞：打开 `hydro-platform/reports/daily/` 下对应日期的 Markdown；[事件与日报](activities-and-daily-report.md)。

GitHub 展示的是已推送版本，不会实时显示另一台电脑刚写出的本地成果。

### 5.2 已安装好的原制卡机

先将经人工筛选的论文和原 PDF 放入目标 Zotero 群组，在本机完成同步。在仓库根目录运行：

```powershell
uv run hydro-platform run-once --json
```

这是一轮“扫描 → 制卡 → 主题 → 报告”。不用先跑 `scan`、`tasks-sync`、`packages-sync`，也不用每加入一篇就修改配置中的数量。

默认串行：第一篇完成即保存，再做下一篇。论文队列在本轮扫描时确定，扫描之后才同步进来的新条目需要下一轮。程序只处理已同步到本机的资料。

### 5.3 使用另一台电脑的私人配置

第 6 节创建完整 `hydro-platform/config/config.local.json` 后，所有命令都明确选择它：

```powershell
uv run hydro-platform run-once --config hydro-platform/config/config.local.json --json
```

本文未带 `--config` 的命令默认指原团队配置；不要在测试机上忽略这一点。

### 5.4 只继续主题

```powershell
uv run hydro-platform themes-run --config hydro-platform/config/config.local.json --json
```

只处理当前已有的有效粗卡，不替缺卡论文生成粗卡。它可能复用或新建主题步骤，并非只读操作。

如只想本轮制卡、不推进主题，先在所选配置中将 `theme_pipeline.enabled` 设为 `false`，再运行 `run-once`；重新设为 `true` 后可继续主题。不要在进程运行中改配置。

### 5.5 看等待进度

当前周期等待提示每 `60` 秒一次；工具开始/结束、单篇保存、错误等真实事件立即显示，所以两条信息间隔短于一分钟也是正常的。

进度写到 stderr，最终 JSON 写到 stdout；使用 `--json` 不意味着终端不会显示进度。`--no-progress` 只关闭这次提示，不关闭超时或其他检查。等待心跳只说明本地还在等，不证明远端模型一直正常。

<a id="new-computer"></a>
## 6. 换电脑安装、配置和权限

### 6.1 当前适用环境

现有统一安装路径针对 **Windows x86_64、基础 Python >=3.12 且 <3.15**；PDF 工具锁为 Windows 包。不能把“Python 是跨平台语言”当作本项目已支持 macOS/Linux/其他架构的证明。

新电脑需准备 Git、符合版本范围的基础 Python、Zotero 和 Codex CLI。平台的 `setup` 只安装项目依赖及 PDF 工具，不替你安装所有基础软件、登录账号或完成沙箱首次授权。

### 6.2 获取仓库

**平台不是独立仓库** —— 它在 `mylibrary` 的 `hydro-platform/` 目录下，是 uv workspace 的成员。所以要取回的是**整个 `mylibrary` 仓库**，再在仓库根同步一次依赖：

```powershell
Set-Location 'E:\phd'
git clone <mylibrary 仓库地址> mylibrary
Set-Location 'mylibrary'
uv sync --all-packages
```

仓库地址见仓库根 `README.md` 的「快速开始」。仓库路径不必与旧电脑相同；目标目录若已存在，不要覆盖。只克隆旧版本不会出现新命令。原始 PDF 不在 Git 中，需要在 Zotero 同步。

### 6.3 复制完整私人配置

在新仓库根目录执行；已有私人配置不会被本示例覆盖：

```powershell
if (-not (Test-Path -LiteralPath 'hydro-platform/config/config.local.json')) {
    Copy-Item -LiteralPath 'hydro-platform/config/config.json' -Destination 'hydro-platform/config/config.local.json'
}
notepad hydro-platform/config/config.local.json
```

只修改对应字段，保留 JSON 其余内容。JSON 不支持注释，布尔值用 `true/false`，空值用 `null`；Windows 绝对路径建议写为 `D:/实际目录/程序.exe`，避免单个反斜杠转义错误。

| 配置项 | 同群组手动测试时怎么填 |
|---|---|
| `scheduler.enabled` | `false`，暂不注册第二台自动制卡机 |
| `zotero.group_id` | 仍为 `6618088`；对方接受 `qinjiajun` 邀请后，同群组编号不变 |
| `zotero.base_url` | 通常保留 `http://127.0.0.1:23119`，读新电脑自身 Zotero，不填旧电脑 IP |
| `paths.project_root` | 保留 `..`；它相对于配置文件所在的 `config` 目录解析 |
| 其余项目相对路径 | 保留；成果写到新仓库，不要求旧盘符或用户名 |
| `card_generator.proxy.enabled/url` | 填新电脑实际 HTTP/HTTPS 代理监听地址，或关闭显式代理；不要照抄旧 `7897` 端口 |
| `card_generator.executable` | 先保留 `codex`；找不到时再填新电脑实际 CLI 可执行路径 |
| `zotero.startup.executable` | 先保留 `null` 自动查找；安装位置特殊且查找失败时再填实际路径 |
| `card_generator.model/reasoning_effort` | 先保留 `gpt-5.6-sol/high`；对方账号能否使用需运行验证，不默认保证 |
| `theme_pipeline.model/reasoning_effort/timeout_seconds` | `null` 时继承制卡配置；无需重复填一套 |
| `theme_pipeline.research_goal` | `null` 表示无预设目标；也可填写研究目标文本，但会改变主题输入 |
| `generation_timeout_seconds` 与 `connection_guard.idle_timeout_seconds` | 当前均 `1500` 秒；是每次模型步骤的保护，不是整轮预计时长 |
| `progress.heartbeat_interval_seconds` | `60`，每分钟等待提示 |
| `deployment` 和 PDF 工具路径 | 先保留 `../.venv`、`.tools/poppler` 的配套相对路径，由 `uv sync --all-packages` / setup 重建 |

代理对象位于 `card_generator` 内。例如新电脑 HTTP/Mixed 监听端口实际为 7890 时：

```json
"proxy": {
  "enabled": true,
  "url": "http://127.0.0.1:7890",
  "no_proxy": ["localhost", "127.0.0.1", "::1"]
}
```

这是局部示例，不是完整配置。端口必须实际存在；当前不接受 SOCKS-only 地址。无需显式代理时设置 `enabled=false`、`url=null`，恢复继承终端环境，不等于强制直连。

代理配置只影响本平台启动的 Codex 子进程，不修改系统、VPN 或桌面客户端设置；也不自动替 Python 下载依赖、Git 和 Zotero 配置网络。不要填写节点订阅链接、密码或令牌。

完整字段解释见[总配置字段说明](config.md)。

### 6.4 权限分别准备

| 权限/前提 | 最小需要及验证边界 |
|---|---|
| GitHub | 能读取私有仓库才能直接克隆/更新；本地制卡不依赖推送权限 |
| Zotero | 用自己的账号接受群组邀请，能读取群组，PDF 本地可打开；添加论文另外受群组编辑权限约束 |
| Zotero 本地 API | 在新电脑可访问目标群组；群组页面可见不代替 API 检查 |
| Codex CLI | 本人完成登录；模型/强度与账号额度允许本次调用，桌面聊天正常不替代 CLI 验收 |
| Windows 文件与执行 | 当前用户可读 Zotero PDF，可在仓库写成果、创建环境并运行 Python/PDF 工具 |
| Windows 沙箱 | 当前使用 `elevated`；首次初始化可能需要管理员批准，受管电脑可能被策略拦截 |
| Windows 调度 | 手动测试关闭调度时不需要注册；正式部署再核对任务归属、当前用户和实际触发 |
| 数据处理许可 | 论文内容会进入配置的外部模型服务；不要将无权提供给外部服务的保密材料用于测试 |

`elevated` 沙箱的初始化授权不等于每次都应管理员运行整套程序。不要复制别人的登录凭据、全盘开放文件权限或关闭沙箱来省略排错。Windows 沙箱权限说明参考 [OpenAI 官方文档](https://learn.chatgpt.com/docs/windows/windows-sandbox)。

平台没有独立登录账号、数据库权限或跨机授权；`SYS-CARD-01`、`STU-001` 等只是记录用标识，不是安全凭据。

### 6.5 安装并恢复已有成果

以下命令均在新仓库根目录执行：

```powershell
uv run hydro-platform setup --config hydro-platform/config/config.local.json --json
uv run hydro-platform setup --apply --config hydro-platform/config/config.local.json --json
```

第一条只读预检；第二条依次进行配置绑定、基础程序/登录/群组检查、项目依赖安装、环境检查、任务恢复和按配置处理调度。关闭调度时预期得到 `READY_MANUAL`。

setup 本身不调用科研模型，但启用调度后将来可能触发模型，因此手动测试保持关闭。已完成的安装阶段可以复用；失败看 `failed_step`，修好再执行同一条命令，不清空旧状态强行重来。

### 6.6 验证新电脑到底恢复到了哪一层

安装后先检查环境：

```powershell
uv run hydro-platform doctor --config hydro-platform/config/config.local.json --json
```

用共享库中已存在的 `CEXH4PQA` 检查本机 PDF 沙箱读取和渲染，不调用模型：

```powershell
uv run hydro-platform pdf-direct-read-trial --item-key CEXH4PQA --preflight-only --config hydro-platform/config/config.local.json --json
```

需要单独核对账号、模型和网络能否完成一次最小调用时，可执行下列命令；它会使用模型额度，但不制卡：

```powershell
uv run hydro-platform generator-smoke-test --config hydro-platform/config/config.local.json --json
```

最后运行：

```powershell
uv run hydro-platform run-once --config hydro-platform/config/config.local.json --json
```

原来的 7 张粗卡应复用；主题输入不变也应复用。**复用了旧成果，只证明恢复路径，不证明这台电脑已经生成新卡。** 要测试真正制卡，由用户往群组加入一篇带原始 PDF 的新论文，再运行；测试期间避免原制卡机同时处理同一篇。

### 6.7 如果将来测试另一个库

另一个群组库需要更换 `group_id`，并为证据包、主题、事件、日报、任务和日志配置独立位置。不能只改库编号、却继续复用原群组的注册表与运行状态；程序会因来源不一致拒绝。

Zotero 个人“我的文库”不是另一种可直接填写的群组 ID，当前没有对应适配器。若测试账号按当前计划加入 `qinjiajun` 并完成同步，就属于同群组换机，不需要做这项切换。

<a id="commands"></a>
## 7. 命令速查与副作用

所有下表命令使用前缀 `uv run hydro-platform`，在仓库根目录运行。使用私人配置时在子命令后追加 `--config hydro-platform/config/config.local.json --json`；默认配置则用 `--json`。带 `--item-key` 的位置填写 Zotero **父条目 Key**，不是附件 Key、DOI 或标题。

### 7.1 日常、安装与诊断

| 子命令 | 做什么 | 调用模型 | 写入/外部副作用 |
|---|---|---|---|
| `run-once` | 完整本轮流程 | 有待处理步骤时 | 任务、粗卡、主题、事件/日报、日志；可按配置启动 Zotero |
| `run-once --dry-run` | 预览已有本机任务 | 否 | 不扫描 Zotero、不写文件，不代表最新库状态 |
| `themes-run` | 单独推进统一主题池 | 输入变化且需要步骤时 | 精读、主题版本、注册表、日志 |
| `themes-run --dry-run` | 预览当前粗卡与主题池输入变化 | 否 | 只读，不写入、不重新扫描 Zotero |
| `themes-run --migrate-only` | 接入已完成历史主题 | 否 | 可写统一注册表/索引及报告，不重新制卡 |
| `setup` | 首次安装/恢复预检 | 否 | 只读检查本机程序、账号及群组，不下载、不注册 |
| `setup --apply` | 安装项目依赖并对账恢复 | 否 | 下载/安装、派生状态、可启动 Zotero；启用时注册/核对计划 |
| `doctor` | 环境、资产、账号、群组、状态及可选计划检查 | 否 | 只读，不自动安装/修复，不执行完整模型制卡 |
| `recover --dry-run` | 预览 Zotero 与成果对账 | 否 | 读取本机库/PDF，不写状态 |
| `recover` | 恢复任务与扫描基线 | 否 | 只写派生运行状态和报告，不生成知识、不从 GitHub 下载 |
| `generator-preflight` | CLI 程序、登录与适配环境检查 | 否 | 只读，不证明模型网络连接 |
| `generator-smoke-test` | 最小模型往返调用 | 是 | 消耗额度，使用隔离环境，不发布科研成果 |
| `pdf-direct-read-trial --item-key CEXH4PQA --preflight-only` | 本机 PDF/沙箱测试 | 否 | 可创建临时材料和试验报告；不生成卡片 |
| `activity-sync` | 同步贡献基线与关键事件 | 否 | 可写共享账本，不修改 Zotero |
| `daily-report` | 更新当天老师摘要 | 否 | 可写日报；不能替代制卡 |

### 7.2 分步维护入口

这些不是每日必须按顺序运行的步骤。

| 子命令 | 用途 | 模型与写入边界 |
|---|---|---|
| `discover-groups` | 列出本机可见的群组 ID 和名称 | 无模型、只读 |
| `preflight` | 验证指定 Zotero 群组可读取 | 无模型、只读 |
| `scan` | 保存基线并列出条目/附件变化 | 无模型，写快照；不会制卡 |
| `pdf-gate --item-key CEXH4PQA` | 查看某条目的 PDF 是否就绪 | 无模型、只读，不创建卡 |
| `tasks-sync` | 按扫描和 PDF 门禁更新任务 | 无模型，写本机任务 |
| `tasks-list` | 查看本机任务 | 无模型、只读，不访问最新 Zotero 状态 |
| `packages-sync` | 为符合条件的任务创建包骨架 | 无模型，写占位卡/清单；不算完成 |
| `pdf-delivery --item-key CEXH4PQA` | 核对并交付原 PDF 路径 | 无模型、只读，不复制 PDF 到证据包 |
| `evidence-templates-validate` | 验证模板类型、版本、来源和内容哈希 | 无模型、只读；不判科研质量 |
| `evidence-generate --item-key CEXH4PQA` | 正式生成指定条目的首张粗卡 | 需要时调用模型、写正式成果；完整旧卡跳过 |
| `evidence-generate-trial --item-key CEXH4PQA` | 对指定论文进行制卡试运行 | 调用模型，写本机试运行结果，不替换正式卡 |
| `pdf-direct-read-trial --item-key CEXH4PQA` | 独立阅读实验，不带 preflight-only | 调用模型，写报告，不是正式制卡 |
| `evidence-draft-export --draft PATH` | 查看/导出失败后保留的草稿 | 无模型，写预览，不把任意草稿强行认定正式成果；PATH 用实际失败返回值 |
| `bootstrap` / `bootstrap --install` | Python 依赖预览 / 校验或安装 | 无模型；环境是仓库根共享 `.venv` 时只校验并提示 `uv sync`，指向平台内环境时才按锁安装 |
| `bootstrap-native` / `bootstrap-native --install` | PDF 工具预览 / 安装 | 无模型；只有 install 下载并校验项目工具 |

`evidence-generate --retry-quality-failed` 是历史质量失败任务的显式重试选项，不是普通网络失败的一键万能修复，也不会取消来源/完整旧卡保护。

`--timeout`（支持该参数的命令）调整的是 Zotero 请求时限，**不是 Codex 模型会话时限**。模型时限在配置中修改。

### 7.3 调度命令

| 子命令 | 作用 | 会不会立即运行模型 |
|---|---|---|
| `schedule-plan` | 读取并预览计划定义 | 不会 |
| `schedule-status` | 查询实际注册、最近结果和下次唤醒 | 不会 |
| `schedule-install` | 按所选配置安装/更新/禁用本项目任务 | 本身不会；启用后到期可能运行 |
| `schedule-remove` | 明确移除本项目任务，保留成果 | 不会；不是删除知识库 |
| `schedule-tick` | 立即执行一次到期判断 | 如果到期且允许处理，可能调用模型 |

<a id="results"></a>
## 8. 怎样判断完成、等待和失败

### 8.1 先看整轮，再看每篇

最终 JSON 重点看：`ok`、`status`、`counts`、`items`、`theme_pipeline`、`activity_reporting` 和 `report_path`。不能只看终端最后一篇 `COMPLETED`，就认定整轮全部成功。

| 整轮状态 | 含义 |
|---|---|
| `COMPLETED` | 本轮已完成可要求的处理，仍需结合主题和报告字段理解产出 |
| `COMPLETED_WITH_PENDING` | 可处理部分完成，但还有等待/延后；即使 `ok=true` 也不等于全部论文完成 |
| `COMPLETED_WITH_BLOCKERS` | 有失败、阻塞、主题失败或贡献/日报保存问题；已经成功的卡片不会撤销 |
| `ALREADY_RUNNING` | 同一副本已有整轮运行，本次没有另开扫描或模型 |
| `CANCELLED` | 用户中止；已保存成果和可恢复记录保留 |
| `FAILED` | 整轮前置或运行失败，查看 `error`、`failed_stage` |
| `LOCAL_PREVIEW` | 只读预览，不是正式执行结果 |

`counts.completed` 是**本轮新完成数**，不是仓库累计卡片数；`skipped` 通常包含已有成果复用。`recovered` 表示已有结果经对账恢复，并非一定重新调用了 AI。

### 8.2 单篇任务常见状态

| 状态 | 意义与处理 |
|---|---|
| `WAITING_FOR_PDF` | 尚未给父条目添加 PDF |
| `WAITING_FOR_FILE_SYNC` | 有附件记录，但本机文件未同步好 |
| `WAITING_FOR_FULLTEXT` | 当前 Zotero 全文索引未就绪 |
| `BLOCKED` | 多 PDF、文件不可读、记录冲突等不能直接处理的问题 |
| `READY_FOR_EXTRACTION` | 旧协议名称；当前表示原始 PDF 已就绪，不要求先制造一份全文缓存 |
| `PROCESSING` | 任务已被领取且有租约 |
| `RETRY_PENDING` | 失败后等待重试资格；是否会重试还受原因、冷却和次数限制 |
| `QUALITY_FAILED` | 历史质量/协议失败状态；不代表当前又启用了六 Agent 或正文格式门禁 |
| `COMPLETED` | 任务完成，仍要与有效证据包记录一起核对 |
| `REMOVED` | 父条目不在目标库；不是授权删除已保存知识 |

### 8.3 主题何时会暂缓

整轮有失败、阻塞、重试冷却/限额延后，或附件同步/索引未就绪等情况时，会暂缓主题，保留已有版本，避免反复针对暂时不完整的资料集规划。

只有“还没有添加 PDF”的条目，不一定阻止其他有效粗卡形成主题。需要明确只处理现有粗卡时，可单独运行 `themes-run`。

日报中的 `TASK_BLOCKED` 当日事件数可能包含已经解决的历史阻塞。判断当前阻塞看当前任务和 `open_item_count` 等字段，不把累计事件数当成仍失败的论文数。

### 8.4 当前实测耗时怎样理解

最近完整运行 `f3463b8326604f08b843c8185f6e4954` 补齐 3 张粗卡、跳过 4 张，并推进全池主题；整轮约 **81 分 35 秒**，主题部分约 **53 分 19 秒**。这是一次实测，不是耗时承诺，也不是每篇粗卡要花 81 分钟。

`1500` 秒是当前单次模型步骤时限，不是“所有论文和主题必须 25 分钟内结束”。重连、长 PDF、主题数量和新的精读次数都会影响整轮耗时。延长时限不能修好不稳定的网络节点。

<a id="troubleshooting"></a>
## 9. 常见问题怎么处理

先保留终端最终 JSON、条目 Key、所用配置文件名及返回的日志路径。不要为了“重新开始”删除卡片、改写完成状态或清空 `.runtime`。

| 现象/错误 | 优先检查 | 不要怎么做 |
|---|---|---|
| 找不到 Codex CLI / 未登录 | CLI 是否可执行、当前 Windows 用户的登录状态、`card_generator.executable` | 不复制别人认证文件，不把桌面能聊天当作 CLI 已通过 |
| 找不到群组 / 无访问权限 | 邀请是否接受、是否登录正确 Zotero 账号、群组 ID、本地 API | 不把个人用户 ID 填成 group_id |
| `PDF_FILE_NOT_SYNCED` | 在 Zotero 中实际打开附件并等本地同步完成 | 不仅凭文献标题和附件图标判断 PDF 已就绪 |
| `FULLTEXT_NOT_INDEXED` / 文字不足 | Zotero 索引、PDF 是否为扫描图、是否可提取文字 | 不为了让扫描件通过而把门槛随意降到零 |
| `MULTIPLE_PDFS` | 父条目下哪些是主文、哪些是补充材料，确认输入安排 | 不让系统随便挑一个，也不要未经确认删除附件 |
| `PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED` | Windows 沙箱初始化、原文件读取权、项目 Python/Poppler 执行权 | 不先花长时间跑模型，不全盘放开权限 |
| 模型/推理强度不可用、额度不足 | 实际账号权限、配置模型、最小模型测试结果 | 不无限重试或换错误拼写的模型名 |
| `CODEX_SERVICE_UNAVAILABLE` / 重连 | 实际代理端口、连接、服务状态；保留日志 | 不把群组授权当作网络修复，不认为延长超时一定有效 |
| `CODEX_GENERATION_TIMEOUT` | 单篇/当前主题步骤时限、最近事件、网络和材料规模 | 不将整轮耗时误认为某篇超时；当前已是 25 分钟保护 |
| `RETRY_COOLDOWN` | 当前失败原因和冷却时间；默认 3600 秒 | 不认为再次敲命令就一定立即重跑 |
| `ATTEMPT_LIMIT` / `NON_RETRYABLE_FAILURE` | 失败原因、累计尝试和是否有有效草稿；先定位再决定后续 | 不直接把 tasks.json 的次数清零或强改完成 |
| `EVIDENCE_*_MISMATCH/CHANGED/INCONSISTENT` | PDF、正文、清单和输入是否被改动，是否换了群组 | 不手改哈希让检查“变绿”，不覆盖旧科研结果 |
| `THEME_POOL_CONFLICT` / 来源引用错误 | 主题注册表、被引用版本/精读是否缺失、人工改动或 Git 冲突 | 不手删旧 BATCH、CHANGE、RD 目录 |
| 最后一篇保存成功，但整轮 `ok=false` | 其他论文、主题状态、`activity_reporting.errors`、`report_warning` | 不重做已经成功保存的卡 |
| `SETUP_READER_BINDING_MISMATCH` | deployment 环境/工具目录与 PDF 读取配置是否配套 | 不只改一个工具路径，不让安装器接管未知目录 |

`run-once` 可自动恢复部分已完成但被旧正文规则拦截的历史草稿，必须同时满足已实现的恢复条件与来源检查；不是所有失败或半成品都能恢复。中断后的新模型会话也不保证复用上一次全部推理。

如果只是要看保留的草稿，使用实际错误返回的路径替换 `PATH`：

```powershell
uv run hydro-platform evidence-draft-export --draft PATH --config hydro-platform/config/config.local.json --json
```

不要直接运行一个 JSON 文件路径。要阅读报告可用编辑器或 PowerShell `Get-Content -LiteralPath '实际报告路径' -Raw -Encoding UTF8`。

<a id="schedule"></a>
## 10. 每日自动运行

原制卡机配置启用了 `HydroPlatform-qinjiajun`：默认当地时间 `09:00` 为每日任务时点，`30` 分钟一次轻量唤醒检查，登录后延迟 `120` 秒检查最近到期任务。实际注册与状态必须在那台机器上查询，不能只看 Git 中的 `enabled=true`。

当前需要 Windows 用户已登录、Zotero/CLI 账号有效、文献/PDF 可同步；不需要人工打开 Codex 对话窗口，不会唤醒关机电脑或代登录。

失败/待处理按调度的 `retry_interval_minutes=60` 冷却，每个日任务时段最多 `3` 次。它与论文输入的 `pipeline.max_attempts_per_item=3` 是两层不同限制；30 分钟检查不等于每 30 分钟调用模型。

### 查询

原制卡机默认配置示例：

```powershell
uv run hydro-platform schedule-status --config hydro-platform/config/config.json --json
```

### 暂停原制卡机

先在**这个计划实际绑定的配置**中将 `scheduler.enabled` 改为 `false`，再按原绑定执行：

```powershell
uv run hydro-platform schedule-install --config hydro-platform/config/config.json --json
```

暂停影响之后的新轮次，不会中断已在处理的论文。新电脑自己的 `config.local.json` 设为 false，不能暂停旧电脑的任务。

### 将来正式移交

先暂停旧机器并确认没有正在运行的制卡；在新机器完成手动验证后，才在新配置中启用调度，再执行对应配置的 `schedule-plan`、`schedule-install`、`schedule-status`。程序按项目/配置核对任务归属，不应复制创建多个同名/异名任务来绕过冲突。

不要把首次注册成功当成已经验收关机、重新登录和所有网络故障恢复。[完整调度说明](cron.md)。

<a id="backup"></a>
## 11. GitHub 共享、备份和恢复

### 应上传什么

代码、模板、依赖锁、非敏感团队配置、证据包、主题及历史、成员必要映射、关键贡献账本、日报和文档。

**不上传：**原 PDF、账号凭据/令牌、`.runtime`、仓库根 `.venv`、`.tools`、`hydro-platform/config/config.local.json`。现有忽略规则不等于任何位置的新敏感文件都自动安全，提交前仍须检查。

### 本地保存与 GitHub 的区别

`run-once` 的保存是在当前电脑文件系统中完成；`git_modified=false` 表示程序未做 Git 操作，**不表示工作区没有新增或修改文件**。只有实际 commit/push 后，其他电脑才能拉到这些结果。

维护者发布时先 `git status --short`、检查差异，再选择明确文件提交，确认无私密内容后推送。程序不会自动 push；本说明编写也不构成授权替你推送。

其他副本更新前先看：

```powershell
git status --short
```

没有需要保护的未提交改动、且确认应更新时，才使用：

```powershell
git pull --ff-only
```

有本地生成成果或分支分叉时先保留并处理差异；不要使用 `reset --hard` 或删除结果来强行同步。

### 换机到底靠什么恢复

1. Git 恢复已经提交的代码、配置结构、模板和共享成果。
2. Zotero 恢复同一群组的条目及原 PDF。
3. 新电脑自己登录 Codex，并准备权限/网络。
4. `setup --apply` 按依赖锁重建工具环境，并对账恢复本机任务状态。
5. 日常流水线复用已完成知识，按需处理新资料。

草稿若只在旧电脑 `.runtime`、尚未发布或单独备份，不能仅靠 GitHub 恢复。复现指流程与已保存结果可恢复，不承诺再次生成逐字一致。

<a id="maintenance"></a>
## 12. 维护者代码地图与验证边界

### 12.1 核心模块对应关系

下表名称相对于 `automation/src/hydro_platform/`；文件是模块，不是要用户逐个运行的脚本。

| 模块 | 实际职责 |
|---|---|
| `__init__.py`、`__main__.py`、`cli.py` | 包初始化、模块入口、子命令/参数/结果渲染 |
| `config.py` | 配置结构、路径约束、适配器和参数验证 |
| `zotero.py`、`zotero_readiness.py` | 本地 API、群组预检、缺失时单次启动和有限等待 |
| `snapshot.py` | 分页条目/附件快照、差异和可用操作者字段 |
| `pdf_gate.py`、`pdf_delivery.py` | PDF 门禁、来源核对、原始路径交付 |
| `tasks.py` | 任务输入身份、状态转换、锁、租约和完成对账 |
| `evidence_packages.py` | EV 目录定位、占位包、manifest 验证、重复保护 |
| `evidence_templates.py` | 八类模板清单、版本、内容/来源指纹校验 |
| `pipeline.py` | 本轮队列、逐篇保存/复用、有限重试、主题衔接、事件/日报汇总 |
| `card_generation.py` | 请求组装、单篇正式/试运行、结果字段验证、正式保存协调 |
| `publication.py` | 待发布记录、原子文本写入、已保存卡片完整性与恢复 |
| `draft_export.py`、`draft_recovery.py`、`recovered_manifest.py` | 草稿预览、受限历史恢复和恢复来源记录 |
| `source_access.py` | 当前与历史来源访问记录的接受规则，不证明科学理解 |
| `pdf_direct_trial.py`、`pdf_sandbox.py` | 独立阅读实验、无模型沙箱读 PDF/提取/渲染检查 |
| `themes.py` | 主题入口、材料读取、输出记录、路径/来源保护及旧流程辅助 |
| `theme_pool.py` | 主题注册表、历史链、复用引用、演化操作和全池发布 |
| `theme_pool_runner.py` | 统一规划 → 必要精读 → 回填的实际编排 |
| `activity.py`、`daily_report.py` | 关键事件/身份映射/去重与老师摘要 |
| `runtime_recovery.py` | 对账恢复派生任务与扫描基线，不生成知识 |
| `deployment.py`、`native_deployment.py` | 锁定 Python 依赖和 Poppler 的安装、复用及漂移保护 |
| `workstation_setup.py`、`doctor.py` | 安装恢复编排与只读环境检查 |
| `scheduled.py`、`windows_schedule.py` | 日任务时段/补查/去重和 Windows 注册/查询/移除 |
| `progress.py`、`failure_records.py` | 阶段/心跳/整轮摘要及脱敏失败记录 |
| `pdf_reader_mcp.py` | 历史专用 PDF MCP，保留兼容测试，不是当前正常读取路径 |

`card_generators/` 内部：

| 文件 | 作用 |
|---|---|
| `__init__.py`、`base.py` | 适配器选择/组合和基础接口 |
| `single_agent.py` | 当前单 Agent 包装、来源/非空结果检查、流程回执 |
| `codex_cli.py` | CLI 查找、登录/模型探针、结果解析和共享调用基础，包含历史路径 |
| `codex_local_pdf.py` | 当前原 PDF 路径交付、沙箱预检、隔离 CLI 会话 |
| `codex_text.py` | 主题规划与回填的文本调用 |
| `proxy.py` | 为 Codex 子进程构建独立代理环境 |
| `streaming.py` | 流式子进程事件、进度、结束和清理 |
| `connection_guard.py` | 可配置的连接/无进展等停止保护，不修复 VPN 节点 |
| `multi_agent.py` | 历史多角色编排，仅兼容/测试，不因当前失败自动启用 |

源码里仍有旧标题/归因检查函数，不代表当前生产入口在调用。判断规则时要看实际入口与调用链，而不是只搜到一个函数名就认定它仍生效。

### 12.2 改模板、模型或程序时

- 改模板：同时维护模板版本、`_catalog.json` 和内容哈希，再运行 `evidence-templates-validate`。历史卡不自动重制；版本化强制重制入口尚未实现。
- 改模型/强度：修改总配置；真实账号是否支持由最小模型测试确认。配置接受一个名字，不等于服务支持它。
- 改主题目标/模板：会改变输入指纹；旧主题和适用精读仍按统一池规则处理，不能另起互不相通的 batch。
- 改依赖目录：同步修改 deployment 与 PDF 读取器配套路径；统一安装不偷偷替用户改配置。
- 改实现：更新相关测试、配置说明和本手册，保留已生成知识与历史协议。

项目现有回归测试可在环境已安装时运行：

```powershell
.venv/Scripts/python.exe -m unittest discover -s hydro-platform/automation/tests -q
```

### 12.3 已验证、未验证和已知限制

**已有证据：**

- 上次提交前全量 `567` 项自动测试通过；本次只编写说明，没有重跑模型或再次执行全量测试。
- 本次调用现有校验函数，只读验证 7 个证据包、主题版本/精读引用及模板清单。
- 最近真实整轮已完成新增 3 卡、复用 4 卡及统一池主题演化。
- 上次发布前在本机全新 Git 检出副本中核对 7 卡、4 主题及历史引用通过；副本没有继承原 `.runtime/.venv/.tools`，但那不是干净异机完整安装/模型运行。

**仍不能视为通过：**

- 干净另一台电脑的账号、沙箱、依赖下载、新论文模型制卡全链路，仍需实际演练。
- 长期网络稳定、不同模型的科研分析质量、真实主题合并/拆分的科学判断，没有因为测试通过就自动获得保证。
- 无论文件哈希、模型阅读声明还是 `PROCESS_VALIDATED`，都不是独立科学审稿。
- 当前全池规划一次组合材料，大规模资料的上下文、耗时及质量尚未验收。
- 没有 CI 合并门禁、跨机任务协调、自动 Git 合并/同步，也没有正式主题确认界面。
- 部分错误的嵌套诊断可能被整轮汇总压缩；排错需保留原终端和实际返回的日志/草稿路径。

日常使用只需记住：**Zotero 放论文和 PDF → `run-once` → `themes/index.md` 看成果；第一次换机先配账号/权限和总配置，再 `setup`。**
