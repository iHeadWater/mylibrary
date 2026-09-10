---
profile_schema: "evidence-source-profile-v1.2"
type_key: "dataset-data-product"
artifact_types: ["dataset", "data_product", "database", "data_paper", "api"]
default_evidence_roles: ["dataset_identity", "dataset_quality", "fitness_for_purpose"]
dynamic_source: true
conditional_method_modules: ["monitoring-quality-remote-sensing", "frequency-drought-climate"]
---

#### 数据集及数据产品证据生成机制

1. 不可变数据快照 ID、版本、发布日期、文件清单 manifest、文件／元数据／样例校验和。
2. 数据生成链：原始观测、模型、反演、融合、再分析、插值或统计汇总。
3. 对象、变量、原始单位、平台单位、时空覆盖、分辨率、坐标系、垂直基准、时区和水文年。
4. 质量标记字典、缺测、异常、检出限、不确定性、验证资料和实际抽样检查结果。
5. 重采样、插值、融合、单位转换、修订和派生历史。
6. 查询参数、下载脚本、API 版本和切片条件；访问、许可、隐私与引用要求。
7. 与训练、验证、测试资料的重叠、空间／时间／事件泄漏风险。
8. 对当前任务的变量、尺度、时段、精度、延迟和可持续访问适配。

数据存在、可访问、可下载、质量良好、许可可用和适合当前任务是六个不同声明，必须分别给证据。

