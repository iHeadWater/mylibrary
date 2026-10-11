---
preliminary_theme_schema: "hydrology-preliminary-theme-v1.0"
preliminary_theme_ref: "{{PRELIMINARY_THEME_REF}}"
title: "{{TITLE}}"
discovery_route: "{{DISCOVERY_ROUTE}}"
workflow_run_refs: {{WORKFLOW_RUN_REFS}}
status: "draft"
allowed_use: "screening_only"
as_of_date: "{{AS_OF_DATE}}"
generated_by: "hydrology-theme-synthesis"
generator_version: "1.3.0"
human_screening_status: "not_started"
---

# {{TITLE}}

> 初步主题只用于人工筛选和安排下一步调查。它可以来自机器聚类、小样本文献分组或两者结合，允许边界不稳定、成员重叠和证据不足。它不等于既定主题，不能承载领域结论，也不能直接进入Idea或论文写作。

~~~preliminary-theme-json
{
  "preliminary_theme_ref": "{{PRELIMINARY_THEME_REF}}",
  "provisional_name": "{{TITLE}}",
  "formation_basis": {
    "candidate_cluster_refs": [],
    "representative_source_refs": [],
    "machine_or_manual_grouping_basis": "",
    "topic_stability": "unknown",
    "trend_record_refs": []
  },
  "scientific_focus_hypothesis": {
    "water_object_or_system": "",
    "process_or_mechanism": "",
    "candidate_problem": "",
    "why_more_than_a_keyword_or_method_label": ""
  },
  "boundary_hypothesis": {
    "tentative_inclusion": [],
    "tentative_exclusion": [],
    "adjacent_preliminary_theme_refs": [],
    "cross_theme_source_refs": [],
    "ambiguous_source_refs": []
  },
  "screening_evidence": {
    "corpus_pattern_summary": "",
    "representative_literature_summary": "",
    "research_question_relevance": "",
    "coverage_or_gap_signal": "",
    "known_biases_and_uncertainties": []
  },
  "human_screening_decision": {
    "status": "not_started",
    "decision_ref": "",
    "decision": "",
    "rationale": "",
    "reviewer": "",
    "reviewed_at": "",
    "resulting_established_theme_refs": [],
    "merge_with_preliminary_theme_refs": [],
    "split_into_preliminary_theme_refs": [],
    "required_supplement": [],
    "conditions_or_next_review_trigger": ""
  },
  "audit_log": []
}
~~~

## 人工筛选时必须回答

1. 这一组材料是否围绕同一个可持续研究的科学问题，而不只是共享方法、地区、数据或关键词？
2. 主题对象、过程、尺度、时间、空间及应用边界能否写清？
3. 代表文献是否足以说明方向存在，还是由一两篇离群文献或机器误分造成？
4. 与其他初步主题的关系是相邻、重叠、桥接、应合并还是应拆分？
5. 当前材料支持建立既定主题，还是应观察、补检索或拒绝？
6. 如果建立既定主题，它要回答的核心问题、明确排除项和首批关键全文是什么？

允许的人工决定：`establish`、`rename_then_establish`、`merge`、`split_and_rescreen`、`watch`、`supplement_before_decision`、`reject`。完成筛选时同时填写唯一`decision_ref`，把文件状态改为`screened`，并填写决定者、日期和理由；建立类决定还必须填写产生的既定主题引用。
