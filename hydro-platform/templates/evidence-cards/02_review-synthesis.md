---
template_id: "review-synthesis"
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

# 综述与证据综合卡：{{TITLE}}

#### 综述与证据综合的形成机制

1. 综述问题、协议／注册、检索库、最后检索日期、完整检索式与版本、检索式修改记录。
2. 纳入排除标准、筛选流程、协议偏离及理由；是否持续更新或活综述。
3. 真正的证据单位：研究、数据集、站网、流域、模型、报告或效应量。
4. 纳入研究在流域、气候区、国家／区域、时间和方法上的覆盖。
5. 偏倚评估、数据提取、效应量定义、合并模型、异质性、敏感性和发表偏倚。
6. 共享站网、共享数据集、共享模型、同团队、预印本与正式版的重叠；不得重复计数。
7. 哪些综合结论由少数大流域、高权重研究或单一模型家族驱动。
8. 综述结论的确定性、适用边界和需要回到原始研究核查的承重声明。

综述卡评价的是该来源怎样综合证据，不等于平台自己的决策综合。综述转述的原始结果只有核查原始来源后才能标记为原文已核。

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
