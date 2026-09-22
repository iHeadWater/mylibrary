---
template_id: "dataset-data-product"
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

# 数据集及数据产品证据卡：{{TITLE}}

#### 数据集及数据产品证据生成机制

1. 不可变数据快照 ID、版本、发布日期、文件清单 manifest、文件／元数据／样例校验和。
2. 数据生成链：原始观测、模型、反演、融合、再分析、插值或统计汇总。
3. 对象、变量、原始单位、平台单位、时空覆盖、分辨率、坐标系、垂直基准、时区和水文年。
4. 质量标记字典、缺测、异常、检出限、不确定性、验证资料和实际抽样检查结果。
5. 重采样、插值、融合、单位转换、修订和派生历史。
6. 查询参数、下载脚本、API 版本和切片条件；访问、许可、隐私与引用要求。
7. 与训练、验证、测试资料的重叠、空间／时间／事件泄漏风险。
8. 对当前任务的变量、尺度、时段、精度、延迟和可持续访问适配。

数据存在、可访问、可下载、质量良好、许可可用和适合当前任务是六个不同声明，必须分别给证据。

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
