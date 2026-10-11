# 执行与交付

## 输入

记录研究问题、intended_use、目标水利情境、处理路线、语料或Zotero范围、检索与配置引用、初步主题、人工筛选决定、既定主题、证据卡路径和版本、Decision卡、复核者、期刊与引用指标来源。没有实际证据卡时可以生成初步主题和筛选队列，但不能生成承重Claim或事实性主题结论。

## 创建工作流运行账

~~~text
python scripts/init_workflow_run.py --workflow-ref run:regionalization --title "无资料流域文献发现到主题形成" --question "哪些证据能够解释空间独立测试下的泛化差异？" --intended-use "初步主题发现、人工筛选和既定主题综合" --route hybrid --output 运行记录/区域化工作流.md
python scripts/validate_workflow_run.py 运行记录/区域化工作流.md --mode draft
~~~

运行账是路线、初步主题、人工筛选、既定主题、两级排序、关键全文、证据卡交接、三类反馈、重算和导师决定的审计入口。它不能替代检索日志、语料、证据卡或主题档案。

## 创建初步主题并完成人工筛选

~~~text
python scripts/init_preliminary_theme.py --preliminary-theme-ref pt:regionalization --title "无资料流域泛化（初步主题）" --discovery-route hybrid --workflow-run-ref run:regionalization --output 主题/初步主题_无资料流域泛化.md
python scripts/validate_preliminary_theme.py 主题/初步主题_无资料流域泛化.md --mode draft
~~~

初步主题只用于筛选。人工必须在文件中记录决定、依据、决定者和日期。只有建立、改名后建立或合并决定产生的既定主题引用，才能进入下一步。

## 创建草稿

`build_theme.py`只读取元数据和 Claim，分类可进入综合的声明，生成输入快照和空结构。它不自动写跨文献结论或决定正式状态。

~~~text
python scripts/build_theme.py --theme-ref et:regionalization --title "无资料流域泛化与区域化" --question "在空间独立测试下，哪些因素决定无资料流域泛化？" --intended-use "研究现状梳理与后续问题形成" --preliminary-theme-file 主题/初步主题_无资料流域泛化.md --card 文献/EC-001.md --card 文献/EC-002.md --output 主题/既定主题_无资料流域泛化.md
~~~

`--cards-dir`递归发现Markdown，但非证据卡、L0/L1和未核声明只进入排除/背景账。

## 人机分工

机器可抽取字段、发现重复/谱系、计算完整分数、提出候选结构和反馈、检查引用与公式。

人必须阅读承重定位，判断可比性、边界和研究价值，核对指标，决定是否补核，并复核文本没有扩大原义。

导师或授权者决定初步主题是否建立为既定主题，以及既定主题的激活、拆分、合并、语义改名、归档和研究方向。

## 存储

初步主题放筛选区，已通过人工筛选的既定主题放主题区；反馈账保存在既定主题文件；原卡修订写回原证据卡；指标来源留在主题文献账。PDF、Zotero数据库、全文摘录和受限项目文件不进Git。

## 最终检查

1. 输入快照列出卡、版本和状态；
2. 一语论证由已核 Claim 支撑；
3. 每条综合声明有支持、限制和不支持边界；
4. 同源研究、数据和版本未重复计数；
5. 冲突处于同一 comparison frame；
6. 水利情境和迁移差距明确；
7. 旧奠基与新前沿来源按作用保留；
8. JIF/分区带年份、类别和来源；
9. 新近性/期刊只影响关注顺序；
10. 反馈指向原卡、Claim、最小材料和停止条件；
11. 已应用反馈有原卡修订且主题重算；
12. idea/写作接口只写当前证据可支持内容；
13. 每个初步主题都有人工筛选决定，既定主题能回链该决定；
14. AI、人审、导师决定和生命周期分开；
15. 机器PASS未冒充科研正确性。

## 失败处理

| 情况 | 处理 |
| --- | --- |
| 小样本没有足够年度切片 | 主题增长率not_applicable，不运行伪DTM |
| 大语料没有检索与去重日志 | 停在语料登记，不输出趋势 |
| 主题模型不稳定 | 降级为探索性候选簇，不能生成正式方向结论 |
| 只有原始引用数 | citation_signal=unknown，不跨年份学科比较 |
| 候选发现权重未冻结 | 记录分项与理由，不输出综合总分 |
| 无Claim JSON | 输入受阻，不从散文猜声明 |
| L0/L1或未核 | 仅搜索线索/context_only |
| 指标缺失 | unknown并报告区间 |
| 原始JIF不可跨学科比 | 不计算V |
| 表面冲突 | 先拆比较框架 |
| 原卡字段不足 | 按三门建反馈请求 |
| 补核推翻原卡 | 改原卡、留Git历史、重算主题 |
| 只有一篇来源 | 局部草稿，不称领域共识 |
| 无可用证据 | 写受阻和最小补证 |
| 初步主题可能重复 | 人工决定合并、拆分、观察或拒绝，不自动建立既定主题 |
| 承重冲突未解决 | 保持草稿/争议，停止强结论 |
| 当前集合未见工作 | 不得改写为“尚无人研究” |

## 验证边界

`validate_theme.py --mode draft`检查结构、引用和指标使用；`--mode final`检查承重完整性，并可用 `--index-root` 验证 Claim 的L2/L3与source-checked状态。

`validate_preliminary_theme.py`检查初步主题只能用于筛选，并在final模式要求完整人工决定。`validate_workflow_run.py --mode draft`检查路线、两种主题、人工筛选门、主题层与文献层用途、趋势字段和反馈目标；`--mode final`还要求边界、全部初步主题处理完毕和导师决定闭环。

验证器不能判断检索覆盖、主题模型科学有效性、原文理解、方法质量、主题价值、空白真实性或导师批准，必须由语料审查、原文复核、领域判断、必要检索和授权决定。
