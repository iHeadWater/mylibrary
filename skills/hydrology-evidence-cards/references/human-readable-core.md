# Human-readable scientific core V1.7

This contract controls the visible part of every source card. It exists to prevent a structurally valid card from being scientifically empty.

## Common opening

Start with a one-sentence takeaway that identifies the object, the action taken by the source, the main result or output, and the largest boundary. Follow it with a short “先看结论” block that answers: what was studied, what data were used, how the study worked, what it found, and why the present project should care.

## Original empirical or modelling research

Cover the following scientific questions. The headings and order may change with the paper's own argument; the template must never generate stock prose.

1. `研究要解决什么问题` — practical/scientific problem, author's gap, explicit question or hypothesis, and novelty claimed by the source.
2. `研究对象与边界` — water object/system, site, event/scenario, time span, scale, independent unit and comparator.
3. `数据到底是什么` — a compact table with source/acquisition, period, sample, resolution, variables/outcomes, preprocessing, calibration/validation/test use, and access. Separate observed, derived, simulated and assumed inputs.
4. `方法是怎样一步步得到结果的` — numbered input → model/analysis → coupling/inference → validation/comparison → output steps. Name equations, algorithms or software only after explaining their scientific role.
5. `验证和比较是否站得住` — baseline/comparator, calibration and validation independence, evaluation metrics, sensitivity/uncertainty analysis, negative controls or missing checks.
6. `最关键的结果` — three to five result groups. For each, give the finding, supporting number or qualitative evidence, comparator, uncertainty status, locator, and interpretation. State `no located numeric result` rather than inventing precision.
7. `作者如何解释这些结果` — keep author mechanism explanations separate from measured/simulated facts; omit a separate section when no distinct mechanism is argued.
8. `这篇研究真正贡献了什么` — conceptual, data, method and empirical contribution; do not replace contribution with a sentence about platform usage.
9. `对当前水利科研平台的用途` — identify the exact variable, method component, comparator, hypothesis or falsification test that can be inherited.
10. `结论边界` — design, data, spatial, temporal, measurement, model, inference and transfer limits, tied to affected findings.

The main depth test is one complete path from a concrete source input to a concrete conclusion. It may sit inside `研究设计与方法链` instead of a fixed `全文证据链展开` section. Explain why the data can address the question; how each model or analytical stage transforms them; which parameter, threshold or assumption controls the transition; what comparison or observation checks the output; how decisive figures/tables support the result; and which link remains weak. Name the actual variables, modules, study groups, scenarios and outputs.

## Review or evidence synthesis

Replace data/method sections with `综述问题与范围`, `检索与纳入是怎样做的`, `纳入证据由什么构成`, `作者怎样分类或综合`, `最关键的综合结果`, `异质性、偏倚与证据确定性`, `哪些承重结论必须回原始研究核查`, and the common contribution/use/boundary sections. Record databases, final search date, strings, screening flow, included counts, study/data/model overlap and synthesis method when reported. A narrative review with no reproducible search must be labelled as such.

## Government, incident and engineering reports

Use `报告要回答什么`, `事件／工程对象与时间线`, `调查材料和数据来源`, `调查或评估方法`, `已确认事实与关键数字`, `原因／责任／机制结论的证据层级`, `仍未回答的问题`, `对平台的用途`, and `结论边界`. Separate contemporaneous facts, later verified facts, expert judgment, simulated counterfactuals and normative conclusions.

## Standards, guidelines, policy and official web records

Use `文件解决什么治理问题`, `发布机关、版本和适用对象`, `本轮实际读取范围`, `可确认的条款／事实`, `执行或符合性所需证据`, `科学证据边界`, and `后续补核`. A catalog page or announcement with no substantive attachment has no research data, research method or effect result; say this clearly and do not inflate it into a research card.

## Results discipline

- A table row must correspond to one interpretable result, not a keyword.
- Keep denominators: nodes, people, events, grid cells, runs, catchments and papers are not interchangeable.
- Keep time and place attached to numbers.
- Distinguish calibration fit, internal consistency, validation, external validation and operational performance.
- Treat overall accuracy cautiously when classes are imbalanced; report class-specific metrics when available.
- Simulation counts are not independent empirical events.
- Feature importance, correlation and sensitivity are not causal effects.
- “No uncertainty reported” is a substantive finding about evidence precision.

## Depth rule

Depth comes from reconstructing the evidence path, not from word count alone. A substantive `full_text` or `partial_full_text` card must contain at least 5,000 non-whitespace characters in the visible L1 scientific narrative and at least 6,000 visible characters at L2/L3. Frontmatter, source-link lists, bibliography, calibration notes, machine fields and default-collapsed `<details>` blocks do not count. Rich original studies should normally reach 5,000–7,500 visible characters at L1. A review must reconstruct its evidence universe and synthesis logic; a substantial investigation report must reconstruct materials, chronology, calculations and conclusion levels. Short official notices may be much shorter only when the narrower `reading_scope` is explicit and the source genuinely contains no research design or results. Repetition, generic domain background, raw abstracts, bibliography and raw OCR do not count as scientific depth.

For normal original research, the visible **data**, **method/evidence chain**, **validation** and **results** sections should collectively reconstruct the study. Use 500, 1,200, 350 and 1,000 non-whitespace characters as drafting targets when the source has that much substance. A shorter section is acceptable only when another named section carries the detail or the card identifies the source-level reason and resulting limitation. Do not satisfy a minimum by repeating the abstract, repeating another section, or adding a stock boundary sentence.

Run a duplication check before handoff. Identical or near-identical paragraphs in `科学贡献`, `对后续研究的价值` and `证据边界` are a failure: contribution explains what the paper adds to knowledge; research value explains what a later study can inherit or test; boundary explains which inference would become invalid and why.

## Final self-check

Before handoff, a reader should be able to point to one visible place for each of these questions: What exactly was studied? On what observations or constructed inputs? What transformations produced the outputs? Against what was it checked? What were the actual results? Which statements are authors' explanations? What does the paper add? Which part can a later study inherit? Where does the conclusion stop? If any answer is missing, state the missing fact and its consequence.
