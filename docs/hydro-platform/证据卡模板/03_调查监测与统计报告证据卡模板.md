---
profile_schema: "evidence-source-profile-v1.2"
type_key: "survey-monitoring-statistics"
artifact_types: ["government_report", "monitoring_bulletin", "statistical_product", "database_extract", "report"]
default_evidence_roles: ["descriptive_statistics", "monitoring_evidence"]
dynamic_source: true
conditional_method_modules: ["monitoring-quality-remote-sensing", "frequency-drought-climate"]
---

#### 调查、监测与统计证据生成机制

1. 目标总体、调查／监测对象、抽样框或站网覆盖，以及未覆盖部分。
2. 站点代码和版本、迁移、断面变化、站网调整、仪器替换和传感器版本。
3. 水位流量关系或率定曲线版本、适用期、维护与质量控制。
4. 指标定义、分子、分母、权重、估计量、重复观测／聚类结构和不确定性。
5. 缺测、低于检出限、异常值、插补、空间汇总和区域代表性。
6. 行政区调整、统计口径映射、制度变化、初值／修订值／最终值版本链。
7. 同比、环比、趋势或空间差异的可比前提；不得由描述性变化直接推因果。
8. 发布机构、数据生成机构、委托方、修订日期和当前有效入口。

L2 数字声明必须记录对象或分母、时空范围、比较条件、原始单位、精确定位及不确定性或 not_reported。

