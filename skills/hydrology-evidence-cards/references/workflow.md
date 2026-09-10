# Zotero to Source-Claim-Decision workflow V1.2

## 1. Bind the request

Record the user-specified Zotero item key or collection, current research question, intended decision, allowed output location and batch boundary. Do not broaden the literature set.

## 2. Establish source identity

Use Zotero read-only metadata and the official identifier or source when available. Assign source_work_id and source_manifestation_id. Check whether the same manifestation already has a card before creating one. Record acquisition channel separately from provenance.

## 3. Select level

- L0 for identity and deduplication.
- L1 for whether continued reading is justified.
- L2 when a located, source-checked claim is needed for a live question.
- L3 only after the three dynamic-reading gates pass.

Start at the least expensive level that answers the current decision. Do not fill empty fields merely because a template contains them.

## 4. Choose profile, roles and modules

Choose one source profile. Add all evidence roles that matter. Add the common water-context module when a specific water setting matters and every method module carrying a decisive assumption.

Example:

    python scripts/new_card.py --type original-research --level L2 --card-id EC-20260904-001 --title Example --manifestation-id SRC-2026-0042-V1 --source-work-id WORK-2026-0042 --source-version published-v1 --zotero-item-key ABCD1234 --research-question-id RQ-001 --role original_research --role software_validation --module hydro-forecast-ml --water-context --output EC-20260904-001_Example.md

## 5. Read only what supports the current level

For L0, use identity records. For abstract-only L1, read the abstract or executive material and label it honestly. A partial/full-text L1 is an analytical screening card: it must still expose the actual object, data, method, validation, results and missing fields using references/human-readable-core.md. For L2, open the exact pages, tables, figures, clauses, rows, metadata or logs needed for each decisive claim. For L3, follow the stated minimum path through methods, supplements, data, code, versions or runs and stop at the predeclared condition.

## 6. Write the human analysis

Write the visible card before the audit objects and follow references/human-readable-core.md. Lead with a one-sentence takeaway, then reconstruct the literature gap, research questions, study design, data-generation path, method in plain scientific language, validation/comparison logic, three to five decisive findings, important figures/tables, contribution, evidence strength, relevance to the current work and conclusion boundaries. Put numbers in small tables where that improves interpretation. A reader must understand the source without reading any identifier or schema field. If data, method or result information is missing, state the missing field and how it limits the conclusion; never replace it with a generic summary sentence.

For a substantive source actually read as full or partial main text, require at least 5,000 non-whitespace characters in the visible L1 scientific narrative and at least 6,000 at L2/L3. Frontmatter, source-link lists, bibliography, calibration notes, machine fields and every default-collapsed `<details>` block are excluded from the count. Rich original research should normally reach 5,000–7,500 visible characters at L1. Include an identifiable evidence chain joining named inputs, transformations, intermediate outputs, checks, results and boundaries; it need not use fixed headings. Do not count repeated metadata, copied references, raw OCR, generic background or paraphrases of the same conclusion. When the source is only a short notice, catalogue page or policy announcement, record the narrower reading scope and source-level reason instead of manufacturing length. Do not add a universal reproduction section.

## 7. Build the default-collapsed claim audit

After the human analysis is coherent, create one claim-json block per proposition. Use a globally unique claim_id. Record source fact, evidence origin, exact scope, locator, permitted inference, support, non-support, interpretations, relations, independence groups and verification. Add the method_requirements demanded by the inference type.

Put calibration/manual-review notes in one `<details>` block and all machine-only objects in a second `<details>` block. Omit the `open` attribute so both are closed by default. Do not cap the complete record at three claims. Visible findings should normally focus on the three to five result groups needed to understand the source; the audit claim count may be larger because numbers and boundaries remain atomic.

## 8. Validate and review

During drafting:

    python scripts/validate_card.py CARD.md --mode draft

Before handoff:

    python scripts/validate_card.py CARD.md --mode final --index-root VAULT_OR_REPOSITORY

For a multi-card batch, also reject reused reader-facing paragraphs and long template sentences:

    python scripts/validate_batch.py BATCH_OR_REPOSITORY_ROOT --mode draft

Then reopen every decisive locator and perform the manual scientific review in SKILL.md. Confirm that every visible number and conclusion maps to a claim in the collapsed audit block. Check that both `<details>` blocks are closed by default and that the expanded main text contains no claim JSON. Fix R01-R08 failures; do not waive them with prose.

## 9. Synthesize decisions

Only L2 or L3 claims may enter a Decision/Synthesis card. Create it with type decision-synthesis, list included and excluded claim IDs, group dependence and versions, expose conflicts, describe coverage and transferability, and record the six-dimension evidence profile with basis claim IDs.

    python scripts/new_card.py --type decision-synthesis --card-id DS-20260904-001 --title Decision --decision-id DEC-001 --research-question-id RQ-001 --decision-owner USER --output DS-20260904-001_Decision.md

An unresolved load-bearing conflict blocks approved status. The decision card must say what is supported, what remains unsupported and what evidence would change the decision.

## 10. Export the relation graph

    python scripts/export_graph.py VAULT_OR_REPOSITORY --output evidence-graph.json

Unresolved edges mean a referenced Source, Claim or Decision object is absent from the scanned root. The graph is a derived view and never becomes a second source of scientific facts.

## 11. Store and synchronize

Keep one formal Markdown per source manifestation and one per decision. Commit cards, rules, manifests and graph views to Git. Keep full text, Zotero databases, credentials, raw data, restricted reports, caches and run outputs in their authorised systems.
