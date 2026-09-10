---
profile_schema: "evidence-source-profile-v1.2"
type_key: "engineering-report"
artifact_types: ["engineering_report", "feasibility_report", "design_report", "acceptance_report", "operation_report", "incident_report"]
default_evidence_roles: ["engineering_evidence"]
dynamic_source: true
conditional_method_modules: ["engineering-operation-safety", "hydrodynamic-simulation", "monitoring-quality-remote-sensing"]
---

#### 工程证据生成机制

1. 项目阶段、工程对象、工程等级、安全类别、系统边界和报告责任主体。
2. evidence_strata_present：基础资料、设计计算、数值模拟、模型试验、现场试验、施工／竣工、检测、验收、长期运行、故障或事故。
3. decision_relevant_stratum：当前工程命题实际依赖哪一层证据；不同层不得自动升级。
4. 设计与校核标准版本、设计事件／重现期、工况、边界、准则和安全裕度。
5. 设计值、施工／竣工值、当前运行状态、改造和变更之间的差异。
6. 独立审查、第三方检测、验收主体、质量控制及委托／利益关系。
7. 维护、老化、淤积、设备退化、异常运行、失效模式、后果等级和剩余风险。
8. 可迁移的机制、不可迁移的工程条件及敏感资料访问边界。

验收通过只能支持验收范围内的符合性，不能自动证明长期运行有效或极端工况安全。

