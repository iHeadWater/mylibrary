# 公共模板

团队维护一套公共模板，不按学生或证据包复制多套。模板指导“分析哪些内容”；`hydro-platform/automation/prompts/` 指导“如何阅读和执行”；Python 管理身份、流程及安全保存。模板中的详细写作要求不是正文标题/措辞的硬性验收门槛。

- `hydro-platform/templates/evidence-cards/`：九类 Markdown 粗卡模板；`_catalog.json` 保存来源提交、本地版本及内容指纹。
- `hydro-platform/templates/themes/`：已启用的统一主题规划、定向精读、回填模板和传输 schema，不再只是预留目录。

修改证据模板需同步版本和清单指纹。修改主题模板会产生新的输入版本，但不会另建独立主题池或自动重做全部旧精读；旧粗卡也不因模板升级自动覆盖。[统一主题池](unified-theme-pool.md) · [总配置字段](../../development/platform/config.md)。

## 证据卡模板库

`hydro-platform/templates/evidence-cards/` 保存平台当前可识别的九类 Markdown 证据卡模板。它们只提供科研内容结构，正文骨架已采用本仓库 `skills/hydrology-evidence-cards/` 的 V1.7 版本；模板不接入该 Skill 的脚本、目录、编号、状态或工作流。

> **与 `skills/hydrology-evidence-cards/assets/templates/` 是什么关系**
>
> 那是这九类骨架的**源**，本目录是**派生**：9 个同名文件，正文结构沿用，但本目录这份替换/补充了
> **管线契约所需的 15 个 front matter 字段与占位符**（`evidence_id` / `card_state` /
> `zotero_group_id` / `zotero_parent_key` / `source_pdf_sha256` / `template_version` …），
> 由校验器 `evidence_templates.py` 强制要求。两份文件**内容不同且刻意不同步**：
>
> | | `skills/…/assets/templates/` | `hydro-platform/templates/evidence-cards/` |
> |---|---|---|
> | 面向 | **人读**证据卡 | **模型生成**粗卡 |
> | front matter | `profile_schema` / `artifact_types` / `default_evidence_roles` / `conditional_method_modules` | `evidence_id` / `card_state` / `zotero_*` / `source_pdf_sha256` / … |
> | 谁在用 | `skills/hydrology-evidence-cards/SKILL.md` | `evidence-generate` / `evidence-validate` |
>
> 改源目录的正文骨架**不会**自动同步到这里；要同步需按下面「版本规则」升版本、更新 `_catalog.json`
> 的来源 commit 与内容指纹。

### 当前模板

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

九类模板当前都在 `_catalog.json` 中启用。启用只表示后续分类器可以选择该模板，不表示模板已经通过真实论文的科研质量验收。

### 来源与适配

- 来源仓库：`https://github.com/iHeadWater/mylibrary`（模板层与 `skills/hydrology-evidence-cards/` 同仓同源）
- 固定来源提交：`7b0f2b7e209aa566f3c68db817d5c4a71d9f8b19`
- 合并前模板曾从外部仓库 `wangxinyu20429-dotcom/Water-Conservancy-Intelligent-Platform` 按团队协作授权复用；两分支合并后该内容已进入本仓库，复用授权问题随之消失。
- `_catalog.json` 逐项记录来源路径、Git blob SHA、本地版本和适配后内容 SHA-256。
- 本地版本已升为 2.0.0：正文骨架采用 `skills/hydrology-evidence-cards/` 的 V1.7 版本（六段式/形成机制 + 可见深度规则），并新增第 9 类 `platform-decision-synthesis`；1.1.0 时期的「区分原文陈述、转述、AI 推理与信息边界」要求保留。
- 本地版本 2.0.1：九类模板正文各补一条「数学公式与金额」LaTeX 转写规则（真实公式写 `$...$` / `$$...$$`、行内不用 `\(...\)`、金额一律转义为 `\$`），正文骨架其余不变。
- front matter 保留本平台的证据 ID、Zotero 群组与父条目、PDF 指纹、自动分类和模板版本字段——这些是管线契约，校验器 `evidence_templates.py` 强制要求，不得删改。

### 自动分类边界

当前由单 Agent 根据完整 PDF 自动选择唯一模板，不设置“待人工确认类型”。系统记录 `classification_confidence` 和 `classification_reason`，但置信度本身不阻塞生成。返回非法或未启用的模板 ID 时，按模板路由错误停止，不能静默使用默认模板。

当前默认单 Agent、模板驱动、详细粗卡，Python 只校验来源、非空输出、有效模板路由、重复和安全写入，不检查正文标题、表格、固定措辞或归因标签。科研正确性及下游主题收益尚待验证，不设置逐卡人工核验任务。

### 版本规则

1. 修改任一模板时，必须提升该模板的 `template_version` 和 `_catalog.json` 中的 `local_version`；
2. 同时更新模板内容的 `content_sha256`，并在需要时提升 `catalog_version`；
3. 引入来源仓库的新版本时，必须更新来源 commit、对应 source blob SHA 和适配说明；
4. 模板升级不自动批量重制历史卡片；历史卡只在后续能力实现后标记模板版本落后；
5. 类型纠正或明确触发重制时必须生成新版本并保留旧卡，不能原地覆盖。版本化重制尚未在 US-07B2 实现。

### 校验

平台在生成（`evidence-generate`）与校验（`evidence-validate`）时会读取模板目录与 `_catalog.json`，并强制要求模板数量、启用数量、来源、版本、文件路径、front matter 和内容哈希一致；任一项不符即按模板错误停止。校验模板不访问 Zotero、不调用模型，也不改写既有产物。

## 主题模板

`hydro-platform/templates/themes/` 存放平台统一的主题模板。

当前主流程为 unified-theme-pool-v1：pool-discovery.md 结合全池粗卡、已有修订主题和历史精读，规划 CREATE / UPDATE / MERGE / SPLIT；discovery.md 保留研究问题组织指引；focused-reading.md 用于必要的原始 PDF 定向精读，refinement.md 用于回填修订。对应 `*.schema.json` 只规范 JSON 传输与来源路由，不检查 Markdown 正文格式。

主题只引用证据包，不复制论文或粗卡。模板改动会改变输入指纹并产生新的 CHANGE 处理记录，不另建独立主题池；已有主题和历史版本保留。精读是否仍适用由规划 Agent 根据研究问题、重点和正文判断，程序核对来源及引用，不因换批次强制重读。正式主题不能被自动修改。[现行流程](unified-theme-pool.md)。

主题设计曾参考 `build-hydrology-theme-map` 中的问题簇、证据角色和尺度边界方法，但该外部 Skill 未纳入本仓库版本控制，不能作为运行依赖或可复现来源。平台实际执行只以本仓库的主题模板、Schema、配置和测试为准；未采用 JSONL 上游、固定主题数、逐卡人工审核或假设/实验设计门槛。原文与 AI 推理需要表达清楚，但不以固定词语卡住保存。

日常产物从`hydro-platform/themes/index.md`查看。模板负责研究问题、机制、证据和复用适用性判断；程序负责来源引用、正式主题保护与版本安全保存。JSON schema 不检查正文标题或措辞，不增加逐次合并审批。
