---
workflow_schema: "hydrology-literature-to-theme-v1.1"
workflow_ref: "{{WORKFLOW_REF}}"
workflow_version: "1.1.0"
title: "{{TITLE}}"
route: "{{ROUTE}}"
status: "draft"
as_of_date: "{{AS_OF_DATE}}"
generated_by: "hydrology-theme-synthesis"
generator_version: "1.3.0"
human_review_status: "not_started"
mentor_decision_status: "not_requested"
---

# {{TITLE}}

> 本文件记录一次“问题—初步主题—人工筛选—既定主题—全文—证据—深化—反馈—决策”运行。初步主题只用于筛选；只有带人工筛选记录的既定主题才能进入全文证据和深度综合。排序不等于证据可信度，机器状态不能替代人工和导师决定。

~~~workflow-run-json
{
  "research_task": {
    "question": "{{QUESTION}}",
    "intended_use": "{{INTENDED_USE}}",
    "scope": {
      "time": "",
      "spatial_or_basin": "",
      "water_objects_or_processes": [],
      "languages": [],
      "source_types": [],
      "inclusion": [],
      "exclusion": []
    },
    "boundary_frozen": false,
    "allowed_conclusion_level": "preliminary_theme_screening_only"
  },
  "route_selection": {
    "route": "{{ROUTE}}",
    "rationale": "",
    "small_sample": {
      "zotero_collection_or_list": "",
      "record_count": null,
      "metadata_version_fulltext_checked": false,
      "topic_growth_status": "not_applicable_unless_adequate_time_slices"
    },
    "large_corpus": {
      "corpus_snapshot_ref": "",
      "retrieval_log_ref": "",
      "initial_record_count": null,
      "deduplicated_record_count": null,
      "normalized_text_version": "",
      "llm_extraction": {
        "status": "not_run",
        "model": "",
        "prompt_version": "",
        "fields": [],
        "validation_sample_ref": ""
      },
      "rule_extraction": {
        "status": "not_run",
        "dictionary_version": "",
        "rule_version": "",
        "validation_sample_ref": ""
      },
      "topic_model": {
        "status": "not_run",
        "method": "DTM",
        "topic_count": null,
        "stability_status": "not_checked",
        "configuration_ref": ""
      },
      "topic_trend": {
        "status": "not_run",
        "popularity_definition": "annual_relative_topic_share_sums_to_one",
        "slope_estimator": "Theil-Sen",
        "significance_test": "Mann-Kendall",
        "raw_counts_reported": false,
        "annual_denominator_reported": false,
        "multiple_testing_recorded": false,
        "result_ref": ""
      }
    }
  },
  "preliminary_theme_review": {
    "status": "not_started",
    "preliminary_theme_refs": [],
    "watch_cluster_refs": [],
    "search_facets": [],
    "false_or_unstable_cluster_refs": [],
    "human_boundary_reviewed": false
  },
  "theme_screening_gate": {
    "status": "not_started",
    "allowed_decisions": [
      "establish",
      "rename_then_establish",
      "merge",
      "split_and_rescreen",
      "watch",
      "supplement_before_decision",
      "reject"
    ],
    "decision_links": [],
    "all_preliminary_themes_decided": false
  },
  "established_themes": [],
  "theme_level_priority": {
    "purpose": "allocate_full_text_review_across_established_themes_only",
    "composite_weight_status": "not_frozen",
    "dimensions": [
      "question_relevance",
      "topic_growth_trend",
      "topic_stability",
      "corpus_coverage",
      "basin_or_object_gap"
    ],
    "items": []
  },
  "document_level_priority": {
    "purpose": "rank_documents_within_an_established_theme_for_full_text_review_only",
    "composite_weight_status": "not_frozen",
    "dimensions": [
      "question_directness",
      "decisive_gap_value",
      "expected_scientific_role",
      "recency",
      "field_year_normalized_citation_signal",
      "verified_field_year_normalized_journal_signal"
    ],
    "items": []
  },
  "full_text_queue": [],
  "evidence_card_handoff": [],
  "claim_admission": {
    "included_claim_ids": [],
    "context_only_claim_ids": [],
    "excluded_claim_ids": [],
    "established_theme_dossier_refs": []
  },
  "feedback_loops": [],
  "recalculation": {
    "required": false,
    "affected_stages": [],
    "last_completed_at": "",
    "before_after_summary": ""
  },
  "human_and_mentor_decision": {
    "human_review_status": "not_started",
    "mentor_decision_status": "not_requested",
    "decision": "",
    "conditions": ""
  },
  "limitations": [],
  "audit_log": []
}
~~~

`theme_screening_gate.decision_links`只保存导航字段：`decision_ref`、`preliminary_theme_refs`、`source_file_refs`、`decision`及产生的既定主题引用；完整理由、决定者和日期只写在初步主题文件中。`established_themes`只保存`established_theme_ref`、`source_preliminary_theme_refs`、`screening_decision_ref`和`theme_file_ref`，避免在运行账重复保存主题正文和边界。

## 当前运行说明

- 当前完成到哪一步：
- 当前最重要的输入：
- 当前最重要的输出：
- 当前决定性缺口：
- 下一步及停止条件：

## 初步主题人工筛选

| 初步主题 | 形成依据 | 人工判断 | 决定 | 理由 | 产生的既定主题 | 决定者与日期 |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

## 既定主题与关键全文队列

| 既定主题 | 核心问题与边界 | 主题层优先理由 | 全文名额 | 关键全文 | 入选理由 | 当前状态 |
| --- | --- | --- | ---: | --- | --- | --- |
| | | | | | | |

## 三类反馈

| feedback_type | 触发判断 | 反馈目标 | 最小材料或修改 | 预期改变 | 停止条件 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |
