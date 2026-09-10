# 证据卡科学架构与 Zotero Skill 使用 V1.2

## 1. 这次重构解决什么问题

V1.1 的八类长模板能提醒研究者检查大量细节，但一张卡同时承担来源登记、声明提取和研究决策，容易造成同一来源在多个问题下被重复复制。字段过多也会诱导人或 AI 填充空泛文字。

V1.2 把平台拆成三个对象：

```text
Source 来源版本 1 ── N Claim 原子声明 N ── N Decision 平台决策
```

- Source：一篇论文、一个报告版本、一套数据快照、一个软件发布或一个标准版本，只登记一次。
- Claim：一个可核查命题，带全局 ID、来源定位、证据生成机制、推断类型、支持边界和关系。
- Decision：平台围绕具体研究问题形成的综合判断，只引用 claim_id，不复制来源事实。

## 2. 当前文件组成

- [公共来源证据卡骨架 V1.7](../证据卡模板/00_公共来源证据卡骨架_V1.7.md)：唯一公共字段、人可读科学正文、L0—L3、折叠校勘和claim-json结构。底层schema继续兼容V1.2。
- [八类证据卡模板目录](../证据卡模板)：01—08 分别保存八类来源的证据生成机制，一个类型一个 Markdown。
- [平台证据综合与决策卡](../证据卡模板/09_平台证据综合与决策卡模板.md)：平台自己的跨来源综合，不等同于发表综述。
- [证据卡模块](../证据卡模块)：公共水利情境和五类方法模块。
- [可安装 Skill](https://github.com/iHeadWater/mylibrary/blob/main/skills/hydrology-evidence-cards/SKILL.md)：读取本机 Zotero、装配卡片、校验和导出关系图。
- [外部实践对照](06_证据卡架构外部实践对照_V1.2.md)：说明外部事实、可借鉴原则、Codex 推断和项目选择。

01—08 是独立的来源类型入口，不再各自复制一遍公共长表。生成器会把公共骨架、选中的类型入口、water_context 和方法模块装成一个可独立保存的 Markdown 来源卡。

## 3. 来源类型和证据角色分开

artifact_type 表示对象是什么，例如 journal_article、dataset、standard、software_release。evidence_roles 表示它在当前问题中提供什么，例如 original_research、dataset_quality、software_validation。

同一篇遥感数据产品论文可以是 journal_article，同时承担 original_research、dataset_quality 和 software_validation。无需复制三张来源卡；在一张来源卡中登记多个角色和对应声明。

## 4. L0—L3 四级工作量

| 级别 | 何时使用 | 必须完成 | 禁止事项 |
| --- | --- | --- | --- |
| L0 来源登记 | 新资料入库和去重 | 身份、版本、入口、取得状态 | 不形成证据结论 |
| L1 快速筛选 | 判断是否值得继续读 | 当前问题、潜在作用、结果线索、首要边界 | 不标记 verified 或 direct，不进入综合 |
| L2 可用证据 | 当前问题需要可核声明 | 至少一个已定位并核原文的 Cxx、范围、支持与不支持、核查记录 | 不跳过声明级核查 |
| L3 完整审计 | 高影响、争议、复现或工程安全决定 | 全部决定性声明、方法模块、冲突、附录／数据／代码／运行检查和独立复核 | 三门未同时满足不得为填表扩读 |

L3 三门是：存在明确高影响决策；决定性证据缺口已准确定位；新材料可能改变当前判断。

## 5. Cxx 声明必须回答什么

每个 claim-json 只写一个命题，至少包括：

1. claim_id 和 exact source_id；
2. source_fact、author_interpretation 或 analyst_judgment；
3. descriptive、comparative、association、causal、prediction、mechanism、transferability、normative 或 implementation 推断类型；
4. supported、partially_supported、not_supported、contradicted、unresolved、not_reported 或 not_checked；
5. 原文事实、证据来自什么设计／数据／条款／运行；
6. 对象或分母、空间、时间、比较条件；
7. 页、节、图表、条款、记录、变量或代码位置；
8. 直接支持、不能支持、作者解释和分析者判断；
9. supports、contradicts、qualifies、depends_on、reproduces、supersedes 关系；
10. 独立性组和核查人、时间、状态。

数值声明还必须有数值、原始单位和不确定性；原文没有不确定性时明确写 not_reported。快速摘要最多展示三条承重声明，完整卡中的 Cxx 数量不设上限。

## 6. 公共水利情境

当结论依赖具体流域、站点、工程、时段、洪旱事件或气候情景时加入 water-context-json，记录：

- 水体／工程对象、流域和站点标识；
- 空间范围、支持尺度、分辨率、坐标系和垂直基准；
- 起止时间、时间分辨率、聚合期、水文年和时区；
- 水文气候区、调控状态和主要人类干预；
- 洪水、干旱、台风、污染、设计工况或气候情景；
- 每个变量的原始单位、平台单位和显式转换规则。

不是所有字段都必填，但不能无痕改变单位、坐标、时区、基准或聚合方式。

## 7. 条件方法模块

方法模块由声明怎样产生和怎样推断触发，不由期刊栏目触发：

1. 水文预测与机器学习：起报、预见期、决策时信息、泄漏、独立切分、业务基线和极端表现。
2. 水文水动力模拟：方程、网格、初边条件、步长、收敛、参数、质量守恒和独立验证。
3. 洪水频率、干旱和气候变化：记录长度、平稳性、分布、重现期区间、情景、模式集合和不确定性。
4. 监测、水质和遥感：站点／传感器版本、率定、检出限、质量控制、云冰植被、地面验证和重采样误差。
5. 工程运行与安全：工程等级、设计／校核／极端工况、竣工与现状、独立检测、退化、剩余风险和保密。

## 8. 第九张平台决策卡

平台决策卡至少记录：问题、阈值、决定人、截止日、纳入和排除的 claim_id、排除理由、独立性组、版本家族、一致和冲突、覆盖范围、目标水利情境迁移、六维证据画像、当前结论、支持和不支持、剩余证据缺口及更新触发条件。

六维画像是直接性、内部有效性、独立性、精确性、目标适用性和可复核／可复现性。每项只用高／中／低／未知加 basis_claim_ids，不计算总分。

## 9. AI 和人工复核

AI 辅助卡必须记录 extraction_method、generator_or_pipeline_version、source_snapshot_hash、human_review_status、human_reviewer 和 verified_claim_ids。

以下三种判断不能共用一个置信度：AI 是否正确抽取文本；来源证据本身有多确定；证据对当前流域和决策是否适用。

机器 PASS 只表示结构和 R01—R08 通过。每条决定性声明仍要由人重新打开原始版本和 locator，核对方向、单位、分母、条件、不确定性和限定语。

## 10. R01—R08 硬校验

| 规则 | 阻断内容 |
| --- | --- |
| R01 | L0／L1 或仅 metadata／abstract 被标记为已核、直接适用或进入正式综合 |
| R02 | 数字缺值、单位、对象／分母、时空范围、比较条件、定位或不确定性；单位转换无规则 |
| R03 | 混淆 not_supported、contradicted、not_reported 和 not_checked |
| R04 | 因果、预测、迁移或规范声明缺少对应推断控制；L3 三门未通过 |
| R05 | 验收→长期有效、安装→复现、下载→适用、二手转述→一手已核等状态越级 |
| R06 | 动态标准、政策、数据、统计产品或软件缺版本、快照、有效性核查日和重查触发 |
| R07 | 存在未解决承重冲突却进入 approved、verified 或 direct |
| R08 | AI 提取缺生成器版本、来源快照、人审状态、复核人或已核 claim_id |

## 11. 实际使用

生成来源卡：

```text
python scripts/new_card.py --type original-research --level L2 --card-id EC-20260904-001 --title 示例 --source-work-id WORK-001 --manifestation-id SRC-001-V1 --source-version published-v1 --zotero-item-key ABCD1234 --research-question-id RQ-001 --role original_research --module hydro-forecast-ml --water-context --output EC-20260904-001_示例.md
```

生成平台决策卡：

```text
python scripts/new_card.py --type decision-synthesis --card-id DS-20260904-001 --title 决策示例 --decision-id DEC-001 --research-question-id RQ-001 --decision-owner 叶磊 --output DS-20260904-001_决策示例.md
```

草稿检查、交付检查和关系图导出：

```text
python scripts/validate_card.py CARD.md --mode draft
python scripts/validate_card.py CARD.md --mode final --index-root OBSIDIAN_OR_REPOSITORY_ROOT
python scripts/export_graph.py OBSIDIAN_OR_REPOSITORY_ROOT --output evidence-graph.json
```

## 12. 验收标准

- 同一 source_manifestation_id 没有第二张正式来源卡；
- artifact_type 和 evidence_roles 没有混为一个分类；
- L0／L1 没有越级进入决策；
- 所有进入决策的声明达到 L2 或 L3，并有原始定位和人工核查；
- 数值、因果、预测、迁移和规范声明满足相应条件；
- 独立性组和版本家族防止重复计数；
- 决策卡明确支持、不支持、冲突、适用边界和更新触发；
- AI 过程可追溯，机器状态没有冒充科研正确性；
- Git 中没有 PDF、Zotero 数据库、凭据、原始数据或受限工程资料。

V1.2 已取代 V1.1 作为当前证据卡架构。Git 历史保留旧设计，不在当前目录维护第二套旧模板。

