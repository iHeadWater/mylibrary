# 公共模板

团队维护**一套**模板，不按学生或证据包复制多套。

| 目录 | 内容 |
|---|---|
| `hydrolitagent/cards/assets/templates/evidence-cards/` | 九类**粗卡模板**（模型生成用） |
| `hydrolitagent/cards/assets/templates/themes/` | 主题的规划 / 定向精读 / 回填模板与传输 schema |

`_catalog.json` 记录每个模板的来源提交、本地版本与内容指纹。九类当前**都启用** ——
启用只表示分类器**可以**选它，**不表示**它已通过真实论文的科研质量验收。

## 九类粗卡模板

| 模板 | 用于 |
|---|---|
| `original-research` | 原创研究论文 |
| `review-synthesis` | 综述与证据综合 |
| `survey-monitoring-statistics` | 调查、监测与统计报告 |
| `engineering-report` | 工程项目报告 |
| `book-chapter` | 图书与章节 |
| `standard-guideline-policy` | 标准、指南与政策 |
| `dataset-data-product` | 数据集及数据产品 |
| `software-model-code` | 软件、模型与代码 |
| `platform-decision-synthesis` | 平台证据综合与决策 |

生成时由模型根据完整 PDF **自动选一类**（没有「待人工确认类型」这个状态）。
返回非法或未启用的类别会**直接报错停止** —— 不会静默改用默认模板。

## 与 `skills/hydrology-evidence-cards/` 的关系

那边是**人读证据卡**的骨架（**源**），这边是**模型生成粗卡**用的（**派生**）：
9 个同名文件，正文结构沿用，但这边替换/补充了管线契约所需的 **15 个 front matter 字段**
（`evidence_id` / `card_state` / `zotero_parent_key` / `source_pdf_sha256` …），由校验器强制要求。

两份**内容不同，且刻意不同步** —— 改源目录**不会**自动同步过来。

## 改模板要守的规矩

1. 升该模板的 `template_version` 和 `_catalog.json` 的 `local_version`，同步更新内容哈希；
2. 引入来源仓库的新版本时，更新来源 commit 与对应的 source blob SHA；
3. **升级不会自动重制历史卡片** —— 历史卡只在后续能力实现后标记「模板版本落后」；
4. 类型纠正或明确触发重制时**生成新版本并保留旧卡**，不能原地覆盖。

## 边界

- 模板只提供**内容结构**。程序校验模板的**数量 / 来源 / 版本 / 路径 / 哈希**，
  **不检查**正文标题、表格或措辞。
- 主题只**引用**证据包，不复制论文或粗卡。
- 科研正确性不由模板或校验保证。

## 相关

[统一主题池](unified-theme-pool.md) · [配置参考](../../development/platform/config.md)
