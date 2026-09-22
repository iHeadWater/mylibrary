---
template_id: "platform-decision-synthesis"
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

# 平台证据综合与决策卡：{{TITLE}}

# {{CARD_ID}} {{TITLE}}

> 本卡是平台形成的证据综合与决策记录，不是发表综述的来源卡。它只引用已存在的 claim_id，不复制来源元数据或改写成第二份事实。

## 决策定义

- 当前研究问题：
- 需要作出的决定：
- 决策阈值或停止线：
- 目标流域／对象／场景：
- 截止日期与下一次复核触发条件：

## 声明纳入、排除与谱系

~~~decision-json
{
  "decision_id": "{{DECISION_ID}}",
  "research_question_ids": {{RESEARCH_QUESTION_IDS}},
  "included_claims": [],
  "excluded_claims": [],
  "exclusion_reasons": {},
  "independence_groups": {},
  "version_families": {},
  "agreements": [],
  "conflicts": [],
  "unresolved_conflicts": [],
  "coverage": {
    "water_objects": [],
    "spatial": "",
    "temporal": "",
    "events_or_scenarios": [],
    "evidence_roles": []
  },
  "transferability": {
    "target_context": "",
    "matched_dimensions": [],
    "transfer_gaps": [],
    "judgment": "unknown"
  },
  "evidence_profile": {
    "directness": {"level": "unknown", "basis_claim_ids": []},
    "internal_validity": {"level": "unknown", "basis_claim_ids": []},
    "independence": {"level": "unknown", "basis_claim_ids": []},
    "precision": {"level": "unknown", "basis_claim_ids": []},
    "applicability": {"level": "unknown", "basis_claim_ids": []},
    "reproducibility": {"level": "unknown", "basis_claim_ids": []}
  },
  "current_conclusion": "",
  "supported": "",
  "unsupported": "",
  "decision_effect": "no_change",
  "remaining_evidence_gap": "",
  "next_update_trigger": ""
}
~~~

## 分析者综合判断

- 本段依据的 claim_id：[]
- 一致证据：
- 相反、限制和未解决证据：
- 是否存在共享数据、共享站网、共享项目、共享模型或版本重复计数：
- 当前结论及其强度：
- 允许采取的行动：
- 暂不允许采取的行动：
- 若要改变判断，最小新增证据是什么：

## 导师决定与版本记录

- 决定：继续／调整／停止／补证／暂缓
- 决定依据的 claim_id：[]
- 决定人和时间：
- 下一次复核条件：
- 被本版取代的 decision card：

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
