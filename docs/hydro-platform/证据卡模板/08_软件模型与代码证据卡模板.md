---
profile_schema: "evidence-source-profile-v1.2"
type_key: "software-model-code"
artifact_types: ["software_release", "repository", "model_package", "workflow", "container", "model_weights"]
default_evidence_roles: ["implementation_identity", "software_verification", "software_validation", "reproducibility"]
dynamic_source: true
conditional_method_modules: ["hydro-forecast-ml", "hydrodynamic-simulation"]
---

#### 软件、模型与代码证据生成机制

1. 仓库、release、tag、commit hash、容器摘要、模型权重 hash 和许可证。
2. 科学模型、算法、训练权重、软件实现、配置与外部服务之间的对应关系。
3. 锁定依赖、操作系统／硬件、API 版本、随机种子和输入数据快照。
4. 输入／输出契约、单位、坐标、缺测、边界条件和配置文件。
5. 静态检查、安装、项目测试、示例运行、目标运行、论文复现和独立科学验证的分层证据。
6. 实际命令、开始／结束时间、退出码、日志、资源消耗、输出校验和和预设数值容差。
7. 基准数据与校准数据的独立性、适用工况、失败条件和科学有效性边界。
8. 上游漂移、依赖变化、模型权重替换和 recheck_trigger。

当前状态必须由状态证据表推导，不能人工直接选择高状态。可下载、可安装、能运行、能复现论文和独立科学有效是不同状态。

