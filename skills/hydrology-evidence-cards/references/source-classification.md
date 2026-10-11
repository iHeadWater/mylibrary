# Source classification V1.2

Choose an artifact type from the object actually fixed by source_manifestation_id. Then choose all evidence roles used in the current work.

| Dominant object | Type key | Common artifact types | Typical evidence roles |
| --- | --- | --- | --- |
| empirical, modelling, theoretical or methods study | original-research | journal_article, thesis, conference_paper, preprint | original_research, method_validation, mechanism |
| a published or commissioned synthesis | review-synthesis | journal_article, report | review_synthesis, evidence_map |
| official or institutional measurement summary | survey-monitoring-statistics | government_report, monitoring_bulletin, statistical_product | descriptive_statistics, monitoring_evidence |
| one engineering project or asset stage | engineering-report | design_report, acceptance_report, operation_report, incident_report | engineering_evidence, operational_performance, safety |
| a stable conceptual or teaching treatment | book-chapter | book, chapter, handbook, textbook | concept_definition, theory_background |
| a normative instrument | standard-guideline-policy | standard, guideline, regulation, policy | normative_requirement, conformity |
| a released collection or product used as data | dataset-data-product | dataset, data_product, database, api | dataset_identity, dataset_quality, fitness_for_purpose |
| a released implementation or model artifact | software-model-code | repository, software_release, model_package, container | implementation_identity, verification, validation, reproducibility |

The platform Decision/Synthesis card is not a source type. It is a derived decision object and must reference claims from source cards.

Ambiguous examples:

- A journal data paper is artifact_type journal_article. If used to establish dataset quality, add dataset_quality and use the dataset profile requirements for those claims.
- A software paper tested against observations may have original_research and software_validation roles. The exact code release must still have its own source manifestation if implementation claims depend on it.
- A government report containing a scientific model may have descriptive_statistics and model_validation claims. Do not treat the issuing authority as methodological validation.
- A review that quotes an original study remains secondary evidence until the original manifestation and locator are checked.

