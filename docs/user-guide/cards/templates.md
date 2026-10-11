# 公共模板

团队维护**一套**公共模板，不按学生或证据包复制多套。

分工：模板管「**分析哪些内容**」；`hydrolitagent/cards/assets/prompts/` 管「**如何阅读和执行**」；
Python 管身份、流程与安全保存。模板里的详细写作要求**不是**正文标题或措辞的验收门槛。

| 目录 | 内容 |
|---|---|
| `hydrolitagent/cards/assets/templates/evidence-cards/` | 九类 Markdown 粗卡模板；`_catalog.json` 记录来源提交、本地版本与内容指纹 |
| `hydrolitagent/cards/assets/templates/themes/` | 已启用的统一主题规划、定向精读、回填模板与传输 schema |

改证据模板要**同步升版本和清单指纹**；改主题模板会产生**新的输入版本**，但不会另建独立主题池、
也不会自动重做全部旧精读，旧粗卡同样不会因模板升级被自动覆盖。
相关：[统一主题池](unified-theme-pool.md) · [总配置字段](../../development/platform/config.md)

## 证据卡模板库

`hydrolitagent/cards/assets/templates/evidence-cards/` 保存平台当前可识别的**九类** Markdown 证据卡模板。
它们只提供科研内容结构，正文骨架采用本仓库 `skills/hydrology-evidence-cards/` 的 V1.7 版本；
模板**不接入**那个 Skill 的脚本、目录、编号、状态或工作流。

> **与 `skills/hydrology-evidence-cards/assets/templates/` 是什么关系**
>
> 那是这九类骨架的**源**，本目录是**派生**：9 个同名文件，正文结构沿用，但本目录这份替换/补充了
> **管线契约所需的 15 个 front matter 字段与占位符**（`evidence_id` / `card_state` /
> `zotero_group_id` / `zotero_parent_key` / `source_pdf_sha256` / `template_version` …），
> 由校验器 `evidence_templates.py` 强制要求。两份文件**内容不同，且刻意不同步**：
>
> | | `skills/…/assets/templates/` | `hydrolitagent/cards/assets/templates/evidence-cards/` |
> |---|---|---|
> | 面向 | **人读**证据卡 | **模型生成**粗卡 |
> | front matter | `profile_schema` / `artifact_types` / `default_evidence_roles` / `conditional_method_modules` | `evidence_id` / `card_state` / `zotero_*` / `source_pdf_sha256` / … |
> | 谁在用 | `skills/hydrology-evidence-cards/SKILL.md` | `evidence-generate` / `evidence-validate` |
>
> 改源目录的正文骨架**不会**自动同步到这里；要同步，须按下面的「版本规则」升版本，
> 并更新 `_catalog.json` 的来源 commit 与内容指纹。

### 当前九类模板

| 模板 ID | 文件 | 用途 |
|---|---|---|
| `original-research` | `01_original-research.md` | 原创研究论文 |
| `review-synthesis` | `02_review-synthesis.md` | 综述与证据综合 |
| `survey-monitoring-statistics` | `03_survey-monitoring-statistics.md` | 调查、监测与统计报告 |
| `engineering-report` | `04_engineering-report.md` | 工程项目报告 |
| `book-chapter` | `05_book-chapter.md` | 图书与章节 |
| `standard-guideline-policy` | `06_standard-guideline-policy.md` | 标准、指南与政策 |
| `dataset-data-product` | `07_dataset-data-product.md` | 数据集及数据产品 |
| `software-model-code` | `08_software-model-code.md` | 软件、模型与代码 |
| `platform-decision-synthesis` | `09_platform-decision-synthesis.md` | 平台证据综合与决策 |

九类当前都在 `_catalog.json` 中**启用**。启用只表示后续分类器**可以**选它，
**不表示**它已经通过真实论文的科研质量验收。

### 来源与适配

- 来源仓库：`https://github.com/iHeadWater/mylibrary`（模板层与 `skills/hydrology-evidence-cards/` 同仓同源）
- 固定来源提交：`7b0f2b7e209aa566f3c68db817d5c4a71d9f8b19`
- 模板最初从外部仓库 `wangxinyu20429-dotcom/Water-Conservancy-Intelligent-Platform`
  按团队协作授权复用；两分支合并后内容已进入本仓库，复用授权不再另需处理。
- `_catalog.json` 逐项记录来源路径、Git blob SHA、本地版本与适配后内容 SHA-256。
- **本地版本 2.0.0**：正文骨架采用 `skills/hydrology-evidence-cards/` 的 V1.7
  （六段式 / 形成机制 + 可见深度规则），新增第 9 类 `platform-decision-synthesis`；
  保留 1.1.0 时期「区分原文陈述、转述、AI 推理与信息边界」的要求。
- **本地版本 2.0.1**：九类模板正文各补一条「数学公式与金额」LaTeX 转写规则
  （真实公式写 `$...$` / `$$...$$`、行内不用 `\(...\)`、金额一律转义为 `\$`），正文骨架其余不变。
- front matter 里的证据 ID、Zotero 群组与父条目、PDF 指纹、自动分类与模板版本字段是**管线契约**，
  校验器 `evidence_templates.py` 强制要求，**不得删改**。

### 自动分类的边界

单 Agent 根据完整 PDF 自动选择**唯一**模板，**没有**「待人工确认类型」这个状态。
系统记录 `classification_confidence` 与 `classification_reason`，但置信度本身**不阻塞**生成。
返回非法或未启用的模板 ID 时，按模板路由错误**停止** —— 不会静默改用默认模板。

Python 只校验来源、非空输出、有效模板路由、重复与安全写入；
**不检查**正文标题、表格、固定措辞或归因标签。科研正确性与下游主题收益尚待验证，
因此不设逐卡人工核验任务。

### 版本规则

1. 改任一模板，必须提升该模板的 `template_version` 和 `_catalog.json` 里的 `local_version`；
2. 同时更新模板内容的 `content_sha256`，必要时提升 `catalog_version`；
3. 引入来源仓库的新版本时，必须更新来源 commit、对应的 source blob SHA 与适配说明；
4. 模板升级**不自动批量重制历史卡片**；历史卡只在后续能力实现后标记模板版本落后；
5. 类型纠正或明确触发重制时必须**生成新版本并保留旧卡**，不能原地覆盖。

### 校验

生成（`evidence-generate`）与校验（`evidence-validate`）时都会读模板目录与 `_catalog.json`，
并强制要求**模板数量、启用数量、来源、版本、文件路径、front matter 与内容哈希**一致；
任一项不符即按模板错误停止。校验模板不访问 Zotero、不调用模型，也不改写既有产物。

## 主题模板

`hydrolitagent/cards/assets/templates/themes/` 存放平台统一的主题模板。

当前主流程是 **unified-theme-pool-v1**：`pool-discovery.md` 结合全池粗卡、已有修订主题与历史精读，
规划 CREATE / UPDATE / MERGE / SPLIT；`discovery.md` 保留研究问题组织指引；
`focused-reading.md` 用于必要的原始 PDF 定向精读；`refinement.md` 用于回填修订。
对应的 `*.schema.json` **只规范 JSON 传输与来源路由**，不检查 Markdown 正文格式。

- **主题只引用证据包**，不复制论文或粗卡。
- 模板改动会改变输入指纹、产生新的 CHANGE 处理记录，但**不另建独立主题池**；已有主题与历史版本保留。
- 精读是否仍适用，由规划 Agent 根据研究问题、重点和正文判断；程序只核对来源与引用，
  **不因换批次强制重读**。
- **正式主题不能被自动修改。**

主题设计曾参考 `build-hydrology-theme-map` 里的问题簇、证据角色与尺度边界方法，
但那个外部 Skill **未纳入本仓库版本控制**，不能作为运行依赖或可复现来源。
平台实际执行只以本仓库的主题模板、Schema、配置和测试为准；**未采用** JSONL 上游、固定主题数、
逐卡人工审核或假设/实验设计门槛。原文与 AI 推理要表达清楚，但不靠固定词语卡住保存。

日常产物请从 `themes/index.md` 查看。模板负责研究问题、机制、证据与复用适用性判断；
程序负责来源引用、正式主题保护与版本安全保存。JSON schema 不检查正文标题或措辞，也不增加逐次合并审批。
