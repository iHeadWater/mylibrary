---
theme_schema: "hydrology-theme-v1.3"
theme_ref: "{{THEME_REF}}"
formal_theme_id: ""
theme_version: "1.3.0"
title: "{{TITLE}}"
theme_stage: "established"
lifecycle_state: "established_developing"
workflow_status: "draft"
as_of_date: "{{AS_OF_DATE}}"
intended_use: "{{INTENDED_USE}}"
research_direction_ids: []
research_question_ids: []
project_ids: []
discovery_route: "{{DISCOVERY_ROUTE}}"
workflow_run_refs: {{WORKFLOW_RUN_REFS}}
preliminary_theme_refs: {{PRELIMINARY_THEME_REFS}}
preliminary_theme_snapshot_hash: "{{PRELIMINARY_THEME_SNAPSHOT_HASH}}"
human_screening_decision_ref: "{{HUMAN_SCREENING_DECISION_REF}}"
human_screening_status: "approved"
input_card_ids: {{INPUT_CARD_IDS}}
included_claim_ids: {{INCLUDED_CLAIM_IDS}}
context_only_claim_ids: {{CONTEXT_ONLY_CLAIM_IDS}}
excluded_claim_ids: {{EXCLUDED_CLAIM_IDS}}
independence_group_ids: {{INDEPENDENCE_GROUP_IDS}}
version_family_ids: {{VERSION_FAMILY_IDS}}
source_snapshot_hash: "{{SOURCE_SNAPSHOT_HASH}}"
generated_by: "hydrology-theme-synthesis"
generator_version: "1.3.0"
narrative_depth: "deep"
narrative_status: "in_progress"
minimum_visible_scientific_chars: 10000
human_review_status: "not_started"
human_reviewer: ""
human_reviewed_at: ""
mentor_decision_status: "not_requested"
mentor_reviewer: ""
mentor_reviewed_at: ""
lifecycle_proposal_status: "not_proposed"
lifecycle_effect_status: "not_applicable"
load_bearing_conflict: false
unresolved_conflict_ids: []
last_evidence_refresh: "{{AS_OF_DATE}}"
next_review_trigger: ""
---

# {{TITLE}}

> 这是通过人工筛选门后建立的既定主题档案。`established`表示课题组已决定围绕该问题继续组织证据，并不表示每条结论已经成立。主题的事实必须回到原证据卡的Claim与定位；深度正文、反馈和生命周期变化都在同一既定主题中继续积累，不再生成第三类平行主题。

<!-- SCIENTIFIC_NARRATIVE_START -->

## A. 主题深度综合正文

> 完成正文后才把 `narrative_status` 改为 `ready_for_handoff`。可见科学正文至少10,000字符；材料不足时保持 `in_progress` 并写明 `BLOCKED_SOURCE_LIMIT`，不得填充套话。

### A.1 研究对象、核心矛盾与问题链

### A.2 概念边界和相邻主题关系

### A.3 当前证据构成与来源角色

### A.4 数据、观测、分析单位与尺度

### A.5 方法谱系、输入输出与关键假设

### A.6 主要结果、知识状态与适用边界

### A.7 发展脉络、异质性与负结果

### A.8 独立综合见解及其反证条件

### A.9 研究缺口与可检验问题

### A.10 反向补核、写作和Idea接口

<!-- SCIENTIFIC_NARRATIVE_END -->

## 0. 导师快速判断页

| 要回答的事 | 当前内容 |
| --- | --- |
| 来源初步主题 | {{PRELIMINARY_THEME_REFS}} |
| 人工筛选决定 | {{HUMAN_SCREENING_DECISION_REF}} |
| 主题一句话论证 | |
| 为什么值得独立讨论 | |
| 当前最稳的认识 | |
| 目前最关键的不确定性 | |
| 最重要的三项来源及原因 | |
| 最需要补核的原卡 | |
| 对后续综述／论文的直接帮助 | |
| 当前不能写成什么 | |
| 本轮需要导师决定什么 | |

## 1. 主题身份、问题与边界

### 1.1 核心定义

- 当前主题名称：
- 一句话论证：
- 核心科研问题：{{QUESTION}}
- 次级问题：
- 目标水利对象／过程／工程系统：
- 目标区域、尺度、时期、事件或情景：
- 主题的理论、方法、数据、工程或管理用途：
- 预期支持的论文／综述／项目环节：

### 1.2 三类成立依据

- 文献依据及 Claim IDs：
- 方向依据：
- 使用依据：
- 为什么不是单一算法、数据集、地区、指标、期刊或关键词：
- 现有主题检索结果：
- 与最相邻主题的区别：
- 当前建议：并入已有／保留候选／建议观察／暂不成立

### 1.3 纳入和排除边界

| 维度 | 纳入 | 排除 | 边界依据 Claim IDs | 尚待确认 |
| --- | --- | --- | --- | --- |
| 科研问题 | | | | |
| 水利对象 | | | | |
| 空间范围与支持 | | | | |
| 时间、事件或情景 | | | | |
| 数据与观测 | | | | |
| 方法与信息集 | | | | |
| 比较对象／基线 | | | | |
| 结果或指标 | | | | |
| 验证与应用 | | | | |

### 1.4 结构化范围合同

~~~theme-scope-json
{
  "theme_ref": "{{THEME_REF}}",
  "one_sentence_argument": "",
  "core_question": "{{QUESTION}}",
  "secondary_questions": [],
  "literature_basis_claim_ids": [],
  "direction_basis": "",
  "use_basis": "",
  "existing_theme_comparison": {
    "searched_paths_or_indexes": [],
    "closest_theme_refs": [],
    "overlap": "",
    "difference": "",
    "recommended_destination": "established_developing"
  },
  "not_a_filter_dimension_because": "",
  "included_scope": {
    "water_objects": [],
    "spatial": "",
    "temporal": "",
    "events_or_scenarios": [],
    "data_or_measurements": [],
    "methods_or_exposures": [],
    "comparators": [],
    "outcomes_or_metrics": [],
    "validation_or_application": []
  },
  "excluded_scope": [],
  "target_water_context": {
    "object": "",
    "spatial_support": "",
    "temporal_support": "",
    "event_or_scenario": "",
    "operational_setting": ""
  },
  "key_concepts": [],
  "active_questions": [],
  "subthemes": [],
  "split_merge_assessment": {
    "recommendation": "keep_as_candidate",
    "evidence_chain_overlap": "",
    "boundary_effect": "",
    "decision_required": ""
  },
  "continuing_use": [],
  "next_update_trigger": ""
}
~~~

## 2. 输入快照与证据准入

### 2.1 输入来源账

以下由生成器预填后人工核对。发表年、来源类型、版本、独立性与可读范围不明时保持 unknown。

~~~source-manifest-json
{
  "as_of_date": "{{AS_OF_DATE}}",
  "input_snapshot_hash": "{{SOURCE_SNAPSHOT_HASH}}",
  "sources": {{SOURCE_MANIFEST_ITEMS}},
  "included_claims": {{INCLUDED_CLAIM_ITEMS}},
  "context_only_claims": {{CONTEXT_ONLY_CLAIM_ITEMS}},
  "excluded_claims": {{EXCLUDED_CLAIM_ITEMS}},
  "selection_limitations": [],
  "missing_source_types_or_contexts": []
}
~~~

### 2.2 准入检查表

| 来源卡 | 来源版本 | L级 | 实际读取范围 | 纳入Claim | 仅背景Claim | 排除Claim及原因 | 独立性／版本组 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

准入原则：只有L2/L3且 `source_checked` 或 `independently_reproduced` 的Claim能承重。标题、摘要、L0/L1或未核转述只可指导检索或成为 context_only。

## 3. 跨来源比较框架

先定义口径，再比较结果。每个表只放真正可比的来源；不能直接比较时单列原因。

| frame_id | 对象／独立单位 | 区域与空间支持 | 时间／事件 | 方法／暴露与信息集 | 比较对象／基线 | 指标、单位与分母 | 验证设计 | 目标场景与迁移差距 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CF-01 | | | | | | | | |

### 3.1 可比性裁决

- 可直接比较的 Claim IDs：
- 只能条件比较的 Claim IDs：
- 不可比较的 Claim IDs 及原因：
- 表面冲突是否来自对象、区域、时期、尺度、指标、基线或信息集差异：
- 真正冲突的最小共同问题：

## 4. 主题证据地图与当前认识

### 4.1 结构化综合

每个 statement 只表达一个平台综合命题。`statement`是分析者综合，必须由 Claim IDs 支撑，并写明最高允许强度和不支持内容。

~~~theme-synthesis-json
{
  "comparison_frames": [],
  "statements": [],
  "development_trajectory": [],
  "method_landscape": [],
  "data_and_measurement_landscape": [],
  "agreements": [],
  "contextual_differences": [],
  "true_conflicts": [],
  "negative_or_failure_evidence": [],
  "evidence_coverage": {
    "water_objects": [],
    "regions": [],
    "periods": [],
    "events_or_scenarios": [],
    "methods": [],
    "data_types": [],
    "validation_designs": [],
    "outcomes_or_metrics": [],
    "uncovered_dimensions": []
  },
  "transferability": {
    "target_context": "",
    "matched_dimensions": [],
    "transfer_gaps": [],
    "current_judgment": "unknown",
    "basis_claim_ids": []
  },
  "current_overall_judgment": "",
  "supported": "",
  "unsupported": "",
  "load_bearing_unknowns": []
}
~~~

一个完整 statement 使用以下字段：

~~~json
{
  "synthesis_id": "TS-01",
  "statement": "",
  "knowledge_state": "unknown",
  "wording_strength": "",
  "comparison_frame_id": "CF-01",
  "supporting_claim_ids": [],
  "limiting_claim_ids": [],
  "opposing_claim_ids": [],
  "context_only_claim_ids": [],
  "independence_group_ids": [],
  "version_family_ids": [],
  "evidence_profile": {
    "directness": {"level": "unknown", "basis_claim_ids": []},
    "internal_validity": {"level": "unknown", "basis_claim_ids": []},
    "independence": {"level": "unknown", "basis_claim_ids": []},
    "precision": {"level": "unknown", "basis_claim_ids": []},
    "applicability": {"level": "unknown", "basis_claim_ids": []},
    "reproducibility": {"level": "unknown", "basis_claim_ids": []}
  },
  "strongest_permitted_conclusion": "",
  "does_not_support": "",
  "change_trigger": ""
}
~~~

### 4.2 当前知识状态

| synthesis_id | 当前认识 | 状态 | 支持 | 限制／反证 | 水利边界 | 目前不能知道 |
| --- | --- | --- | --- | --- | --- | --- |
| TS-01 | | unknown | | | | |

### 4.3 发展脉络

按“问题—数据—方法—验证—适用范围—失败认识”的变化写，不以年份列表替代科学脉络。

| 阶段／年份 | 问题变化 | 数据或测量变化 | 方法／识别变化 | 验证变化 | 新增认识或边界 | Claim IDs |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

### 4.4 方法、数据和工程图景

- 主流方法及各自解决的问题：
- 方法比较是否公平：
- 关键数据、站网、版本和质量限制：
- 从论文验证到真实业务的差距：
- 工程、标准或政策来源只在哪一层有效：
- 当前最容易被误用的结论：

### 4.5 一致、差异与冲突

- 一致证据：
- 情境差异：
- 真正冲突：
- 负结果与失败条件：
- 同源数据、项目、模型或版本是否重复：
- 承重冲突是否阻断当前判断：

## 5. 证据卡形成后的关键文献补核排序

这里分开记录科学作用与证据卡形成后的补核／跟踪优先级。既定主题之间的主题层排序和全文阅读前的文献层排序记录在工作流运行账中。前沿关注分不包含主题增长率或引用信号，也不改变Claim可信度。

~~~literature-priority-json
{
  "as_of_year": {{AS_OF_YEAR}},
  "score_purpose": "frontier_reading_and_recheck_priority_only",
  "weights": {
    "evidence_quality_and_independence": 25,
    "question_directness": 20,
    "decisive_gap_closure": 15,
    "recency": 25,
    "verified_field_normalized_journal_signal": 15
  },
  "items": []
}
~~~

每个 item 使用：

~~~json
{
  "source_card_id": "",
  "source_manifestation_id": "",
  "source_type": "",
  "publication_year": null,
  "eligible_claim_ids": [],
  "scientific_roles": [],
  "load_bearing": false,
  "foundational_exception": {
    "applies": false,
    "reason": "",
    "basis_claim_ids": []
  },
  "journal_metric": {
    "status": "unknown",
    "metric_name": "",
    "metric_value": null,
    "metric_year": null,
    "category": "",
    "percentile_or_quartile": "",
    "metric_resolution": "",
    "source": "",
    "checked_at": ""
  },
  "components": {
    "evidence_quality_and_independence": null,
    "question_directness": null,
    "decisive_gap_closure": null,
    "recency": null,
    "verified_field_normalized_journal_signal": null
  },
  "component_basis": {
    "evidence_quality_and_independence": "",
    "question_directness": "",
    "decisive_gap_closure": "",
    "recency": "",
    "verified_field_normalized_journal_signal": ""
  },
  "not_applicable_components": [],
  "unknown_components": [],
  "frontier_attention_score": null,
  "provisional_min": null,
  "provisional_max": null,
  "ranking_completeness": "",
  "priority_tier": "",
  "priority_reason": "",
  "next_action": ""
}
~~~

### 5.1 排序结果

| 顺位／并列 | 来源卡 | 科学作用 | 承重Claim | E/D/G/R/V | 关注分或区间 | 指标来源 | 为什么优先 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

### 5.2 保留的旧文献与非期刊来源

- 奠基概念／方法：
- 长序列、历史基线或经典数据：
- 标准、政府报告、工程记录、数据集和软件：
- 为什么它们不应因年份或无JIF被排除：

## 6. 主题反推的三类反馈与修整

~~~evidence-feedback-json
{
  "requests": [],
  "applied_change_log": [],
  "recalculation_required": false,
  "last_recalculated_at": "",
  "remaining_blockers": []
}
~~~

每个 request 使用：

~~~json
{
  "request_id": "EFR-01",
  "feedback_type": "source_recheck",
  "source_card_id": "",
  "source_card_path": "",
  "affected_claim_ids": [],
  "triggering_synthesis_ids": [],
  "problem_type": "targeted_recheck",
  "problem": "",
  "theme_consequence": "",
  "pre_check_judgment": "",
  "decisive_gap": "",
  "three_gate_check": {
    "decision_exists": false,
    "gap_is_locatable": false,
    "new_material_may_change_judgment": false
  },
  "required_material": {
    "source_version": "",
    "minimum_path": "",
    "expected_locator": ""
  },
  "allowed_action": "targeted_recheck",
  "retrieval_or_scope_ref": "",
  "affected_stage": "",
  "configuration_ref": "",
  "validation_sample_ref": "",
  "expected_theme_change": "",
  "stop_condition": "",
  "status": "proposed",
  "source_check_result": "",
  "application_result": "",
  "changed_claim_ids": [],
  "card_revision_before": "",
  "card_revision_after": "",
  "evidence_card_validation": "",
  "theme_recalculation": ""
}
~~~

### 6.1 本轮反馈队列

| 优先级 | request_id | 反馈类型 | 反馈目标 | 为什么影响主题 | 最小材料／修改 | 可能改变什么 | 停止条件 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

### 6.2 补核后主题重算

- 原主题判断：
- 原卡修改：
- 新的已核事实：
- 受影响 synthesis_id：
- 判断加强／缩窄／推翻／未改变：
- 关注排序变化：
- 尚未解决：

## 7. 面向论文综述、Idea与研究写作

~~~writing-readiness-json
{
  "usable_for_background": [],
  "usable_for_review_state": [],
  "usable_for_problem_framing": [],
  "usable_for_method_choice": [],
  "usable_for_limitations": [],
  "opportunity_signals": [],
  "claims_blocked_from_writing": [],
  "novelty_search_status": "not_started",
  "citation_identity_check_status": "not_started",
  "overall_readiness": "not_ready"
}
~~~

每个 opportunity signal 至少写：

~~~json
{
  "signal_id": "OS-01",
  "signal_type": "",
  "candidate_question": "",
  "basis_synthesis_ids": [],
  "basis_claim_ids": [],
  "nearest_known_work_in_current_set": [],
  "specific_difference": "",
  "disconfirming_evidence": [],
  "missing_novelty_search": "",
  "data_dependencies": [],
  "method_dependencies": [],
  "feasibility_unknowns": [],
  "next_verification": "",
  "stop_condition": "",
  "status": "signal_only"
}
~~~

### 7.1 可进入写作的内容

| 写作用途 | 可用 synthesis_id／Claim IDs | 允许写到什么强度 | 必须带的边界 | 尚不能写 |
| --- | --- | --- | --- | --- |
| 背景 | | | | |
| 研究现状 | | | | |
| 发展趋势 | | | | |
| 问题提出 | | | | |
| 方法选择 | | | | |
| 局限讨论 | | | | |

### 7.2 机会信号

- 当前证据暴露的具体缺口：
- 当前卡片集中最接近的工作：
- 差异是什么：
- 尚未完成的新颖性检索：
- 哪些证据会否定该信号：
- 最小下一步：
- 为什么现在仍不是正式Idea：

## 8. 人工复核、导师决定与变更历史

~~~theme-review-json
{
  "human_source_review": {
    "status": "not_started",
    "reviewer": "",
    "reviewed_at": "",
    "verified_synthesis_ids": [],
    "reopened_claim_ids": [],
    "notes": ""
  },
  "mentor_decision": {
    "status": "not_requested",
    "reviewer": "",
    "reviewed_at": "",
    "decision": "",
    "basis_synthesis_ids": [],
    "conditions": ""
  },
  "lifecycle": {
    "proposal_status": "not_proposed",
    "effect_status": "not_applicable",
    "event_ref": "",
    "base_revision": "",
    "applied_revision": ""
  },
  "change_log": []
}
~~~

### 8.1 人工复核清单

- [ ] 承重Claim逐条回到原卡和原文定位
- [ ] 数值方向、单位、分母、比较与不确定性一致
- [ ] 因果、预测、迁移和规范性推断未越级
- [ ] 真冲突的比较框架一致
- [ ] 同源数据、项目、模型和版本未重复计数
- [ ] 期刊指标年份、学科、百分位／分区和来源已核
- [ ] 主题增长率只用于主题层资源分配，未复制为单篇论文质量
- [ ] 引用指标已按学科和发表年份归一化，原始被引量未直接跨文献比较
- [ ] 新论文和高期刊指标只改变关注顺序
- [ ] 旧奠基、长序列和非期刊关键来源未被错误排除
- [ ] 补核结果写回原卡并保留版本历史
- [ ] 语料补充和发现模型纠偏已重跑对应上游阶段
- [ ] Idea与写作部分没有虚构新颖性或共识

### 8.2 本轮导师决定

- 决定：待审／继续深化／并入已有／拆分重审／建立观察／激活／退回修改／停止
- 决定依据：
- 允许应用的范围：
- 不允许应用的范围：
- 再次讨论触发条件：

### 8.3 变更记录

| 时间 | 输入卡版本变化 | 主题判断变化 | 排序变化 | 反馈应用 | 人工／导师决定 |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## 9. 最终交付说明

- 实际使用的卡片和读取范围：
- 可以回到原文的核心认识：
- 仍然受阻的承重问题：
- 最重要文献排序的用途与限制：
- 已提出／已应用的原卡反馈：
- 后续写作可用内容：
- 当前绝对不能声称的内容：
- 机器校验结果：
- 人工复核结果：
- 导师／授权者决定：
