---
template_id: "standard-guideline-policy"
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

# 标准、指南与政策证据卡：{{TITLE}}

#### 标准、指南与政策规范证据机制

1. document_id、发布机关、层级、编号、版本、发布日期、生效／失效日期及有效性核查日。
2. clause_id、clause_version、强制／推荐／说明属性、规范词和精确原文定位。
3. 适用主体、对象、工程类别、地域、时期、前置条件、例外和地方实施细则。
4. 新旧条款对应、替代关系、官方解释及 superseded_by。
5. 国家、行业、地方、团体或单位规则的适用优先级和项目判定链。
6. 符合性所需证据、检验方法、责任主体和保留记录。
7. 条款的技术依据或引用来源；规范效力与科学有效性分开。

normative 声明只能直接支持规范要求及其适用范围。官方或强制状态不能自动证明方法科学最优、工程长期有效或对当前流域可迁移。

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
