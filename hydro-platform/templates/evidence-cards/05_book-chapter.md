---
template_id: "book-chapter"
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

# 图书与章节证据卡：{{TITLE}}

#### 图书与章节知识形成机制

1. 作品、版次、章节、页码、语言、译本和版本差异。
2. 原文定义、命题、公式或理论主张；原始术语与工作译名分列，记录翻译核查状态。
3. 前提、符号、单位、推导路径、适用域和例外。
4. 作者给出的证据、案例或引用链；追踪到上游原始来源的程度。
5. 教材化简、作者综合、历史性表述与一手研究结果分开。
6. 当前研究使用该定义／命题的具体位置和不能外推的边界。

轻量 L2 只需身份、原文命题、前提、精确定位、上游来源和使用边界。只有该公式、定义或理论命题影响研究设计时才进入 L3。图书转述不能自动升级为一手实证证据。

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
