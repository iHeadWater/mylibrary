---
name: hydrology-evidence-cards
description: Read a user-specified Zotero source and produce a source-grounded, human-readable water-research evidence card. Reconstruct the research question, study objects, actual data, method and validation chain, decisive results, mechanism, scientific contribution and conclusion boundaries; never replace them with a shallow abstract paraphrase or fixed template prose. Keep machine audit fields default-collapsed. Use for Zotero-to-Obsidian evidence work, source-card rewriting and evidence preparation for theme synthesis.
---

# Hydrology Evidence Cards V1.7

Build a scientifically rigorous card that a researcher can understand before seeing any audit machinery. Do not write a generic literature summary or expose a wall of schema fields as the main reading experience.

The invariant chain is:

Source version → Claim → locator and evidence-generating design → permitted inference and boundary → Decision/Synthesis.

Machine validation proves only that the structure and explicit rules pass. It never proves that a scientific claim is true.

## Human-readable output is the primary deliverable

The visible Markdown must let a researcher answer these questions in two minutes:

1. What problem does the source study, and why does it matter?
2. What data, objects, comparison and method does it actually use?
3. What are the three to five most important findings, with interpretable numbers where available?
4. What is the source's real scientific contribution and practical value for the current research?
5. What can and cannot be concluded, and what should be done next?

It must also remain useful during a 20-minute close reading. A card that merely restates the abstract, lists keywords, or gives one sentence each for “method” and “result” fails even if its schema passes. A full-text card must reconstruct at least one complete evidence path: **a named input or observation → a named operation/model step → a named intermediate or output → a stated comparison or check → the resulting claim and its boundary**.

For every claim of `reading_scope: full_text` or `partial_full_text`, the visible body must make the **research question, study object and boundary, data, method workflow, validation or comparison design, results, author interpretation, analyst assessment and conclusion boundary** easy to find. Headings and order must follow the source's scientific logic; do not force every source into identical prose. Write `not_reported`, `not_found_after_check`, `not_read` or `not_obtained` for a missing element and explain its consequence. Do not hide missing data behind “the authors conducted a case study” or “results show the method is effective.”

The data section must name, when the source reports them: source or acquisition route, place, period, sample or independent unit, spatial and temporal resolution, variables, labels or outcomes, preprocessing, calibration/validation/test split, and accessibility. The method section must explain the input → transformation/model → comparison/validation → output chain and identify assumptions or parameter sources. The results section must preserve direction, quantity, unit, denominator, comparator, uncertainty and locator for each decisive result. If the source reports no uncertainty, say so.

Write the paper's intellectual story first. Define technical terms in ordinary research language, connect methods to results, and explain why each major result matters. Put DOI, official source and Zotero links in a short source section.

For any substantive source actually read as `full_text` or `partial_full_text`, the **visible scientific narrative itself** must contain at least **5,000 non-whitespace characters at L1** and **6,000 at L2/L3**. Frontmatter, source-link lists, bibliography, calibration notes, machine-audit fields and every default-collapsed `<details>` block do not count. A rich original-research source should normally produce 5,000–7,500 visible characters at L1 and 6,000–10,000 at L2/L3. These are depth floors, not permission to pad. Use the space for the literature gap, actual observations and constructed inputs, independent unit, method and intermediate outputs, comparison/validation design, decisive numbers, important figures/tables, author explanation, contribution, uncertainty and concrete research value. Reviews and substantial investigation reports must reconstruct their search/investigation and synthesis chain. Short notices, catalogue pages and policy announcements may remain short only when `reading_scope` records the narrower material and the card states what the source does not contain.

The visible-length rule fails if length comes from repeated abstracts, generic domain background, paraphrases of the same result, copied bibliography, raw OCR or empty schema fields. Run `scripts/validate_batch.py` for multi-card work so reused reader-facing paragraphs and long template sentences fail before handoff. A researcher must still judge whether every paragraph adds source-specific evidence.

Do not create a universal `复现需要什么` section. Data, code or model availability belongs in the evidence-strength or source-information discussion only when it changes what can be checked. A software paper may discuss run evidence because execution is part of its claim, but that does not impose a reproduction section on ordinary literature cards.

The template is a coverage checklist, not a paragraph generator. Never reuse the same contribution, limitation or platform-value paragraph across papers. A section may be combined, renamed or omitted when the source's argument is clearer that way. The visible analysis should contain source-specific nouns, variables, comparison groups, data provenance, outputs and locators. If two visible paragraphs make the same point, keep the more precise one and delete the other.

Do not use stock filler such as “把上述输入按论文给出的规则转换为研究输出”, “该结果只在上述设定内成立”, or “这里真正需要回答的不是……”. Replace it with source-specific content. If the source text does not reveal the missing step, state exactly which step is unresolved and where it was searched.

Do not leave raw `claim-json`, schema names, relation arrays, verification enums or identifier machinery expanded in the main article. Put calibration/manual-review notes and machine audit in two separate HTML `<details>` blocks without the `open` attribute, so both are closed by default in Obsidian reading view and GitHub. A reader must understand the paper without opening either block.

Conflicts and missing fields are quality-control information, not the narrative center. Explain a conflict prominently only when it changes a main result or blocks the current decision. Put minor editorial inconsistencies in the collapsed calibration block. Never multiply one discrepancy into repeated warnings throughout the visible card.

## Required reading order

1. Read references/evidence-architecture.md.
2. Read references/evidence-boundaries.md.
3. Read references/source-classification.md and choose one source profile plus every applicable evidence role.
4. For Zotero input, read references/zotero-access.md.
5. Read references/workflow.md.
6. Read references/human-readable-core.md and use its source-type contract.
7. Create a card with scripts/new_card.py or assemble it from assets/base, one assets/templates profile, and conditional assets/modules.
8. Run scripts/validate_card.py in draft mode during work and final mode before handoff.
9. Reopen every decisive locator and complete the manual scientific review. A script PASS is not scientific approval.

## Object and granularity rules

- Register an exact source manifestation or release once. Use source_work_id to group manifestations of the same intellectual work and source_manifestation_id for the exact version used.
- Do not copy full source metadata for each research question. Add globally unique Claim objects to the single source card and link their claim_id values to multiple Decision cards.
- Separate artifact_type from evidence_roles. A journal article can supply original_research, dataset_quality, and software_validation roles at the same time.
- Each audit claim-json block contains one proposition. Preserve direction, unit, denominator, comparison, uncertainty, qualifiers and precise locator.
- A platform Decision/Synthesis card is a ninth card type. It references claim_id values, records inclusion, exclusion, dependence, conflicts, coverage, transferability and the current decision. It is not a published review source card.
- Use independence_group_ids and version_family_ids to prevent repeated counting of the same station network, dataset, project, model family, preprint/publication pair, report series or commissioned work.

## Completion levels

| Level | Purpose | Minimum content | Permitted use |
| --- | --- | --- | --- |
| L0 | identity, deduplication and version registration | exact source identity, manifestation, acquisition and access state | inventory only |
| L1 | analytical screening | abstract-level cards may stay short; any card claiming partial/full-text reading must expose research object, data, method, result and boundary in separate sections and state unresolved fields | discovery and prioritisation only |
| L2 | usable evidence | a complete human-readable analysis plus at least one located and source-checked audit claim with scope, support boundary and verification record | may enter Decision/Synthesis |
| L3 | full audit | all decisive claims, triggered method modules, conflicts, supplementary or run checks, independent review | high-impact, disputed or reproduction decisions |

L0 and L1 must not be marked verified or directly applicable. Enter L3 only when all three dynamic-reading gates are true: a clear high-impact decision exists, a decisive evidence gap is located, and opening new material may change the judgment.

## Source profiles

| Type key | Profile | Scientific center |
| --- | --- | --- |
| original-research | assets/templates/01_original-research.md | design, independent unit, information path, inference, decisive results and failure conditions |
| review-synthesis | assets/templates/02_review-synthesis.md | search universe, inclusion, overlap, bias, synthesis, heterogeneity and certainty |
| survey-monitoring-statistics | assets/templates/03_survey-monitoring-statistics.md | coverage, measurement, denominator, station history, uncertainty, revisions and comparability |
| engineering-report | assets/templates/04_engineering-report.md | evidence strata, criteria, boundary conditions, measured versus simulated evidence, failure and remaining risk |
| book-chapter | assets/templates/05_book-chapter.md | proposition, definition, derivation, translation, source lineage and domain |
| standard-guideline-policy | assets/templates/06_standard-guideline-policy.md | authority, clause, force, applicability, version, conformity and scientific boundary |
| dataset-data-product | assets/templates/07_dataset-data-product.md | immutable snapshot, generating process, variables, quality, licence and fitness |
| software-model-code | assets/templates/08_software-model-code.md | fixed artifact, environment, input/output contract, run evidence, reproduction and scientific validation |
| decision-synthesis | assets/templates/09_platform-decision-synthesis.md | cross-source claim synthesis, dependence, conflict, transferability and decision effect |

Zotero itemType is only a clue. Choose artifact_type from what the object is and evidence_roles from what its claims do in the current research decision.

## Conditional modules

- Add assets/modules/water-context.md when the evidence concerns a concrete water object, basin, station, period, event, scenario or engineering system.
- Add method-hydro-forecast-ml.md for forecasting or machine-learning claims.
- Add method-hydrodynamic-simulation.md for hydrologic or hydrodynamic simulation.
- Add method-frequency-drought-climate.md for frequency analysis, drought or climate projections.
- Add method-monitoring-quality-remote-sensing.md for monitoring, water quality or remote sensing.
- Add method-engineering-operation-safety.md for engineering operations and safety.

Conditional modules follow the inference and method, not the publication format. Include only relevant modules, but do not omit a module that carries a decisive inference assumption.

## Hidden claim audit rules

- Distinguish source_fact, author_interpretation and analyst_judgment.
- Distinguish descriptive, comparative, association, causal, prediction, mechanism, transferability, normative and implementation inference types.
- Distinguish supported, partially_supported, not_supported, contradicted, unresolved, not_reported and not_checked. Never merge these states.
- Numeric claims require value, reported unit, denominator or object, temporal and spatial scope, comparator, locator, and uncertainty or the literal not_reported.
- Causal claims require identification design, confounding assessment and alternative explanations.
- Prediction claims require issue time, lead time, information available at decision time and independent validation.
- Transfer claims require a target-context match and explicit transfer gaps.
- Normative claims support clauses and applicability. Normative force does not establish scientific validity.
- Use relations supports, contradicts, qualifies, depends_on, reproduces and supersedes to build a graph between claims.

## Non-upgrade rules

- Engineering acceptance does not prove long-term effectiveness or safety in untested extreme conditions.
- Software installation or example execution does not prove paper reproduction or scientific validity.
- Data access does not prove quality or fitness for the current task.
- A review's paraphrase does not become source-checked primary evidence until the original source is checked.
- A book's paraphrase does not become primary empirical evidence.
- An official source proves identity, clause, release or record only within that source's authority.

## Missing information and AI provenance

Use only: not_applicable, not_obtained, not_read, not_reported, not_found_after_check, conflict_pending. Never fill a gap from general knowledge or a similar source.

AI-assisted or automated extraction must record extraction_method, generator_or_pipeline_version, source_snapshot_hash, human_review_status, human_reviewer and verified_claim_ids. AI extraction confidence, scientific evidence certainty and applicability to the current decision are separate concepts. Never call a batch card `full_text` merely because an index returned many characters: confirm that the main text contains usable methods and results. If only a landing page, abstract, references or OCR fragments were usable, record the narrower scope.

## Manual scientific review

For each decisive finding in the visible analysis, reopen the named source version and locator and verify:

1. The fact preserves direction, unit, denominator, comparison, uncertainty and qualifiers.
2. The independent unit and evidence-generating design support the stated inference type.
3. Training, calibration, validation, testing and operational information are separated where relevant.
4. Negative results, failure settings, internal conflicts and unsupported transfer are visible.
5. Source fact, author interpretation and analyst judgment remain distinct.
6. Independence groups and version families prevent duplicated evidence.
7. What the claim supports and does not support is explicit.
8. An unresolved load-bearing conflict blocks approved, verified or direct status.

## Output and storage contract

Return one human-readable Markdown source card per exact source version and one Decision/Synthesis card per platform decision. The source card contains the readable analysis and its default-collapsed calibration and machine-audit blocks in the same file. Use stable file names such as EC-20260904-001_Short_Title.md and DS-20260904-001_Decision.md.

For a bounded batch, also create a manifest containing the requested scope, matched Zotero keys, source and manifestation IDs, output paths, levels, reading coverage, validation result and unresolved blockers. Do not expand the batch beyond the user's item list or collection.

Git may store bibliographic identity, source links, cards, manifests and derived graph JSON. Keep licensed full text, Zotero databases, credentials, temporary extracts, restricted project files and large datasets in their authorised systems.
