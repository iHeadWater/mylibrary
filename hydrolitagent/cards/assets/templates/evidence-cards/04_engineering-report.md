---
template_id: "engineering-report"
template_version: "2.0.1"
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

# 工程项目报告证据卡：{{TITLE}}

#### 工程证据生成机制

1. 项目阶段、工程对象、工程等级、安全类别、系统边界和报告责任主体。
2. evidence_strata_present：基础资料、设计计算、数值模拟、模型试验、现场试验、施工／竣工、检测、验收、长期运行、故障或事故。
3. decision_relevant_stratum：当前工程命题实际依赖哪一层证据；不同层不得自动升级。
4. 设计与校核标准版本、设计事件／重现期、工况、边界、准则和安全裕度。
5. 设计值、施工／竣工值、当前运行状态、改造和变更之间的差异。
6. 独立审查、第三方检测、验收主体、质量控制及委托／利益关系。
7. 维护、老化、淤积、设备退化、异常运行、失效模式、后果等级和剩余风险。
8. 可迁移的机制、不可迁移的工程条件及敏感资料访问边界。

验收通过只能支持验收范围内的符合性，不能自动证明长期运行有效或极端工况安全。

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
