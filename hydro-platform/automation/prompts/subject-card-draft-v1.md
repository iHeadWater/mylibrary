---
prompt_version: "subject-card-draft-v1"
---

# 单篇主体卡草稿的补充交付协议

本任务在一次单 Agent PDF 阅读中，同时返回详细 card_body_markdown 和固定 machine_fields。
二者使用同一篇 PDF、同一次阅读所得信息。不得再调用 AI 提取比较表，不生成跨论文综合决策卡、候选主题或 research idea。
仅可从本次提供的八类单篇来源模板中选型。综述论文可总结该综述的内容，但不能冒充独立读取其引用的论文。

## 固定机器字段（schema_version = 1）

- research_questions：论文研究问题。
- study_objects_and_scales：研究对象、样本及时间和空间尺度。
- data_and_methods：数据、方法、实验过程、关键参数和假设。
- comparison_baselines：论文实际使用的比较基线；不适用或未报告时说明原因。
- findings：主要结果，每条提供 finding_id，例如 F001。正文采用的结果标识与此一致，供后续按结果追溯。
- boundaries：原文限制、适用条件与推断边界。
- missing_information：原文未报告、无法取得或不适用的信息及影响。

上述七项均为数组。每条具有 statement、statement_role、information_status 和 source_locations；findings 额外具有 finding_id。
statement_role 为 original_statement（原文陈述）、original_paraphrase（原文转述他人研究）、ai_inference 或 information_boundary。
information_status 为 reported、not_reported、not_applicable 或 unavailable。
每条 source_locations 记录 PDF 物理页码（从 1 开始），以及 section、figure、table；不适用的定位项为 null。
同一结果可以有多个原文位置。缺失或不适用信息不能捏造页码，source_locations 可为空；statement 解释缺失性质及影响。
保留定量值、单位、比较条件和不确定性；不得把模型推理标成原文结果，也不得把“没有报告”改为“没有发生”。
原文没有足够信息时如实记录，不能为填满数组虚构结论。

## 正文与状态

正文继续采用既有详细模板。真实数学表达写成 $...$ 或 $$...$$；金额美元符转义为 \$。
主体内容只描述本论文，不针对研究主题重写。论文元数据、来源、提示词及模板版本由程序从真实上下文记录，不在正文里伪造已校验或已发布状态。
输出严格遵守给定 JSON schema；正文和机器字段一次交付，不添加额外回复。

程序仅确认来源、执行与可解析的交付结构。此次产物永远是 DRAFT_PENDING_VALIDATION，不是 PASS。
字段内容完整性、页码范围、finding_id 唯一性、正文一致性和证据是否支持结论属于后续 #31；程序能接收草稿不代表其科研内容正确。
