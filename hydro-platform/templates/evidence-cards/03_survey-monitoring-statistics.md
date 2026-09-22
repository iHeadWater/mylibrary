---
template_id: "survey-monitoring-statistics"
template_version: "2.0.0"
template_source_commit: "7b0f2b7e209aa566f3c68db817d5c4a71d9f8b19"
evidence_id: "{{EVIDENCE_ID}}"
card_state: "{{CARD_STATE}}"
title: "{{TITLE}}"
zotero_group_id: "{{ZOTERO_GROUP_ID}}"
zotero_parent_key: "{{ZOTERO_PARENT_KEY}}"
zotero_attachment_key: "{{ZOTERO_ATTACHMENT_KEY}}"
source_pdf_sha256: "{{PDF_SHA256}}"
classification_confidence: "{{CLASSIFICATION_CONFIDENCE}}"
classification_reason: "{{CLASSIFICATION_REASON}}"
reading_scope: "{{READING_SCOPE}}"
generated_at: "{{GENERATED_AT}}"
updated_at: "{{GENERATED_AT}}"
---

# 调查、监测与统计报告证据卡：{{TITLE}}

#### 调查、监测与统计证据生成机制

1. 目标总体、调查／监测对象、抽样框或站网覆盖，以及未覆盖部分。
2. 站点代码和版本、迁移、断面变化、站网调整、仪器替换和传感器版本。
3. 水位流量关系或率定曲线版本、适用期、维护与质量控制。
4. 指标定义、分子、分母、权重、估计量、重复观测／聚类结构和不确定性。
5. 缺测、低于检出限、异常值、插补、空间汇总和区域代表性。
6. 行政区调整、统计口径映射、制度变化、初值／修订值／最终值版本链。
7. 同比、环比、趋势或空间差异的可比前提；不得由描述性变化直接推因果。
8. 发布机构、数据生成机构、委托方、修订日期和当前有效入口。

L2 数字声明必须记录对象或分母、时空范围、比较条件、原始单位、精确定位及不确定性或 not_reported。

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
