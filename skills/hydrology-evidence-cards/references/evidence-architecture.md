# Evidence architecture V1.2

## Three layers

Source records an exact manifestation or release once. Claim records an atomic proposition, locator, evidence origin, inference type, boundary, verification state and relations. Decision/Synthesis selects Claim IDs for a concrete question and records dependence, conflicts, coverage, transferability and the action taken.

The cardinality is Source 1:N Claim and Claim N:N Decision. Front-end pages may render a combined view, but the stored facts must not be duplicated.

## IDs

- source_work_id groups editions, preprints, accepted manuscripts, releases or revisions that represent one intellectual work.
- source_manifestation_id identifies the exact version actually read.
- card_id identifies the Markdown record.
- claim_id is globally unique and stable after publication.
- decision_id identifies one decision state as of a date.
- independence_group_ids mark shared data, station networks, projects, teams or model families.
- version_family_ids connect replaced or equivalent manifestations.

Changing wording without changing the proposition updates the claim in place with Git history. Changing the proposition creates a new claim ID and links supersedes. Never silently reuse an ID for a different proposition.

## Two classifications

artifact_type describes what the source object is. evidence_roles describe what its claims do. One source has one artifact type and may have several roles. This prevents a data paper, software paper or engineering study from being forced into one scientific role.

## Human view and machine audit

The visible card explains the source in ordinary scientific prose: the research problem, study design, evidence path, important findings, contribution, limitations and relevance to the current work. It must remain complete and understandable if the reader never opens the audit layer.

Frontmatter remains flat so Obsidian, Git and the standard-library validator can read it without a YAML dependency. Nested Claim, water_context and Decision objects use strict JSON blocks. Source-card calibration notes and machine JSON belong in separate HTML `<details>` elements without an `open` attribute, so readers see two closed summaries by default and may expand them when auditing. The JSON Schemas document their contracts; scripts/validate_card.py reads the raw Markdown and enforces the operational subset and R01-R08. Machine readability must not displace human comprehension.

## Four decision dimensions

Do not compress different questions into one usability score:

- relevance: central, supporting, peripheral, irrelevant;
- verification_readiness: verified, partially_verified, clue_only, currently_unusable;
- applicability: direct, conditional, transfer_check_required, not_applicable;
- decision_effect: strengthens, weakens, limits, contradicts, no_change.

Decision cards additionally use a six-dimension evidence profile: directness, internal validity, independence, precision, applicability and reproducibility. Each dimension records high, medium, low or unknown plus basis_claim_ids. There is no cross-source total score.

## Scientific status

Completion level, workflow status, AI extraction status, evidence certainty and applicability are different axes. A source can be fully extracted but scientifically weak; highly relevant but not checked; official but inapplicable; reproducible but not valid for the target basin.
