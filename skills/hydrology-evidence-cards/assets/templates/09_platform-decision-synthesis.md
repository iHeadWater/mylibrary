---
card_schema: "evidence-card-v1.2"
card_id: "{{CARD_ID}}"
card_version: "1.7.0"
card_type: "decision_synthesis"
artifact_type: "platform_synthesis"
workflow_status: "draft"
completion_level: "L2"
decision_id: "{{DECISION_ID}}"
research_question_ids: {{RESEARCH_QUESTION_IDS}}
project_ids: {{PROJECT_IDS}}
as_of_date: "{{AS_OF_DATE}}"
decision_owner: "{{DECISION_OWNER}}"
load_bearing_conflict: false
unresolved_conflict_ids: []
included_claim_ids: []
excluded_claim_ids: []
independence_group_ids: []
version_family_ids: []
---

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

