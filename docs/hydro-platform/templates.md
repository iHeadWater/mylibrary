# 公共模板

团队维护一套公共模板，不按学生或证据包复制多套。模板指导“分析哪些内容”；`hydro-platform/automation/prompts/` 指导“如何阅读和执行”；Python 管理身份、流程及安全保存。模板中的详细写作要求不是正文标题/措辞的硬性验收门槛。

- `hydro-platform/templates/evidence-cards/`：八类 Markdown 粗卡模板；`_catalog.json` 保存来源提交、本地版本及内容指纹。
- `hydro-platform/templates/themes/`：已启用的统一主题规划、定向精读、回填模板和传输 schema，不再只是预留目录。

修改证据模板需同步版本和清单指纹。修改主题模板会产生新的输入版本，但不会另建独立主题池或自动重做全部旧精读；旧粗卡也不因模板升级自动覆盖。[证据包](evidence-packs.md) · [主题池](unified-theme-pool.md) · [总配置字段](config.md)。

## 证据卡模板库

`hydro-platform/templates/evidence-cards/` 保存平台当前可识别的八类 Markdown 证据卡模板。它们只提供科研内容结构，不接入来源仓库的脚本、目录、编号、状态或工作流。

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

八类模板当前都在 `_catalog.json` 中启用。启用只表示后续分类器可以选择该模板，不表示模板已经通过真实论文的科研质量验收。

### 来源与适配

- 来源仓库：`https://github.com/wangxinyu20429-dotcom/Water-Conservancy-Intelligent-Platform`
- 固定来源提交：`457d5a420959f543773fc0a5c955cc64b1ca0ecb`
- 来源仓库在读取时没有声明许可证；当前复用依据记录为用户确认的团队协作授权。
- `_catalog.json` 逐项记录来源路径、Git blob SHA、本地版本和适配后内容 SHA-256。
- 本地版本已升为 1.1.0：增加 AI 推理/信息边界分区，声明表区分原文陈述与转述，删除人工复查/独立检查及摘录要求；保留八类主体结构及来源版本。
- front matter 已改为本平台的证据 ID、Zotero 群组与父条目、PDF 指纹、自动分类和模板版本字段。

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

运行：

```powershell
uv run hydro-platform evidence-templates-validate --json
```

只有在模板数量、启用数量、来源、版本、文件路径、front matter 和内容哈希全部通过时才返回 `ok: true`。该命令不访问 Zotero、不调用 Codex，也不改写证据包。

## 主题模板

`hydro-platform/templates/themes/` 存放平台统一的主题模板。

当前主流程为 unified-theme-pool-v1：pool-discovery.md 结合全池粗卡、已有修订主题和历史精读，规划 CREATE / UPDATE / MERGE / SPLIT；discovery.md 保留研究问题组织指引；focused-reading.md 用于必要的原始 PDF 定向精读，refinement.md 用于回填修订。对应 `*.schema.json` 只规范 JSON 传输与来源路由，不检查 Markdown 正文格式。

主题只引用证据包，不复制论文或粗卡。模板改动会改变输入指纹并产生新的 CHANGE 处理记录，不另建独立主题池；已有主题和历史版本保留。精读是否仍适用由规划 Agent 根据研究问题、重点和正文判断，程序核对来源及引用，不因换批次强制重读。正式主题不能被自动修改。[现行流程](unified-theme-pool.md)。

方法来源：本机已安装 build-hydrology-theme-map 技能及其「问题簇卡模板V1_轻量画像」「候选主题卡模板V4_画像问题簇与研究决策」的研究问题组织、证据角色和尺度边界方法；2026-09-09 按本平台需求重新编写为本地版本 v1，不声称是原模板全文或固定上游提交。未采用与用户要求冲突的 JSONL 上游、L1/L2、固定主题数、逐卡人工审核、假设/实验设计门槛。原文与 AI 推理需要表达清楚，但不以固定词语卡住保存。

日常产物从`hydro-platform/themes/index.md`查看。模板负责研究问题、机制、证据和复用适用性判断；程序负责来源引用、正式主题保护与版本安全保存。JSON schema 不检查正文标题或措辞，不增加逐次合并审批。
