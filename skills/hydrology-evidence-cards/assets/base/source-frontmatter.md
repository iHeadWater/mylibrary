---
card_schema: "evidence-card-v1.2"
card_id: "{{CARD_ID}}"
card_version: "1.7.0"
card_type: "source_evidence"
artifact_type: "{{ARTIFACT_TYPE}}"
evidence_roles: {{EVIDENCE_ROLES}}
workflow_status: "{{WORKFLOW_STATUS}}"
completion_level: "{{COMPLETION_LEVEL}}"
source_work_id: "{{SOURCE_WORK_ID}}"
source_manifestation_id: "{{SOURCE_MANIFESTATION_ID}}"
source_version: "{{SOURCE_VERSION}}"
source_snapshot_hash: "{{SOURCE_SNAPSHOT_HASH}}"
source_provenance: "{{SOURCE_PROVENANCE}}"
acquired_via: "{{ACQUIRED_VIA}}"
acquired_at: "{{ACQUIRED_AT}}"
validity_checked_at: "{{VALIDITY_CHECKED_AT}}"
language: "{{LANGUAGE}}"
access_level: "{{ACCESS_LEVEL}}"
zotero_item_key: "{{ZOTERO_ITEM_KEY}}"
project_ids: {{PROJECT_IDS}}
research_question_ids: {{RESEARCH_QUESTION_IDS}}
decision_ids: {{DECISION_IDS}}
related_card_ids: []
independence_group_ids: []
version_family_ids: []
reading_scope: "{{READING_SCOPE}}"
extraction_method: "{{EXTRACTION_METHOD}}"
generator_or_pipeline_version: "{{GENERATOR_VERSION}}"
verified_claim_ids: []
verified_by: ""
verified_at: ""
human_review_status: "not_started"
human_reviewer: ""
funding: []
commissioning_party: []
declared_conflicts: []
review_independence: "unknown"
confidentiality: "{{CONFIDENTIALITY}}"
water_context_status: "{{WATER_CONTEXT_STATUS}}"
method_modules: {{METHOD_MODULES}}
l3_gate_decision: false
l3_gate_gap: false
l3_gate_change: false
relevance: "{{RELEVANCE}}"
verification_readiness: "{{VERIFICATION_READINESS}}"
applicability: "{{APPLICABILITY}}"
decision_effect: "no_change"
load_bearing_conflict: false
unresolved_conflict_ids: []
recheck_trigger: "{{RECHECK_TRIGGER}}"
---

# {{CARD_ID}} {{TITLE}}

> 用一句话说明这篇文献研究了什么、最重要的发现是什么，以及它对当前科研工作有什么价值。

## 文献信息与原文入口

- **题名：** {{TITLE}}
- **作者／责任机构：** {{CREATORS}}
- **年份／发布日期：** {{DATE}}
- **期刊／出版者／仓库：** {{VENUE}}
- **DOI／ISBN／正式标识：** {{IDENTIFIER}}
- **官方入口：** {{SOURCE_URL}}
- **Zotero入口与已读材料：**
- **尚未取得或未读的材料：**
- **当前复核状态：**

技术状态词只写入文末默认折叠的机器审计区；这里用正常语言告诉读者实际读了什么、没读什么。
