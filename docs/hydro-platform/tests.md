# 验证地图

本页把项目文档中的关键规则与现有测试对应起来。历史测试数量、耗时和样本演示不再累加保留；Git 历史已经保存这些过程。

## 现有覆盖

| 用例 | 被固定的规则与否定情形 | 证据 | 状态 |
| --- | --- | --- | --- |
| 配置与路径 | 未知字段、越界路径、重叠安装目录和非布尔开关必须拒绝 | `test_config.py`、`test_deployment.py` | 已有自动测试 |
| Zotero 增量检测 | 分页、基线、补 PDF、重复条目和群组身份不得混淆 | `test_snapshot.py`、`test_tasks.py`、`test_zotero_readiness.py` | 已有自动测试 |
| PDF 门禁与交付 | 缺失、过小、无可用文本、身份变化和越界文件不得进入制卡 | `test_pdf_gate.py`、`test_pdf_delivery.py`、`test_pdf_sandbox.py` | 已有自动测试 |
| 证据卡模板 | 九类模板的来源、版本、front matter 和内容指纹必须一致 | `test_evidence_templates.py` 与 `evidence-templates-validate` | 已有自动测试 |
| 单 Agent 制卡 | 来源错误、空输出、非法模板、重复生成和人工改动必须停止保存 | `test_single_agent.py`、`test_card_generation.py`、`test_card_saving.py` | 已有自动测试 |
| 任务、锁与中断恢复 | 并发运行不得双写，完整待发布记录可恢复，损坏或冲突记录不得覆盖 | `test_pipeline.py`、`test_draft_recovery.py`、`test_runtime_recovery.py` | 已有自动测试 |
| 候选主题池 | CREATE / UPDATE / MERGE / SPLIT 的来源、编号、血缘和原子发布必须保持，旧粗卡不得被修改 | `test_themes.py`、`test_theme_pool.py`、`test_codex_text.py` | 已有自动测试 |
| 活动与日报 | 首次只建基线，事件去重，未知身份不猜测，日报冲突不覆盖 | `test_activity_reporting.py` | 已有自动测试 |
| 调度与安装 | 同一时槽不重复运行，失败有限补查，计划和依赖可查询、验证和恢复 | `test_scheduled.py`、`test_windows_schedule.py`、`test_workstation_setup.py` | 已有自动测试 |
| 仓库结构 | 代码、模板、文档和忽略的科研产物保持预期边界 | `tests/test_repo_structure.py` | 已有自动测试 |

这些测试主要使用模拟供应者、临时目录和隔离配置。它们证明工程边界和失败保护，不证明模型理解论文正确或主题具有科学价值。

## 提议测试

| 优先级 | 测试类型 | 场景 | 预期结果 |
| --- | --- | --- | --- |
| P0 | 自动集成 | 统一发布器把自动粗卡与人工审核结果发布到 `artifact_root` | 只有通过准入的对象进入 Obsidian 知识区，双方修改冲突时停止 |
| P0 | 自动集成 | 正式主题建立、改名、合并、拆分和归档 | 没有人员、时间、理由和来源候选时拒绝；历史 ID 不丢失 |
| P0 | 自动集成 | 卡片—主题关系审核 | 自动化只能创建 `proposed`，只有人工动作能转为 `confirmed` |
| P1 | 受控真实验证 | 干净 Windows 机器安装、登录、恢复和定时启动 | 仅依赖 Git 可复现资产、Zotero 和 Git 外产物备份即可恢复 |
| P1 | 受控真实验证 | PDF 仍在云端同步、Zotero 从未登录或 Codex 账号失效 | 系统显示可操作阻塞，不产生空卡或无限重试 |
| P1 | 人工科研评审 | 从多类文献抽样复核 Claim、数字、图表和结论边界 | 记录准确性、严重错误和模板类型差异，不把工程测试当作科学验证 |
| P2 | 性能验证 | 数千到上万篇索引的候选主题更新 | 在可说明的时间、成本和内存边界内完成，并保留增量处理 |

## 当前缺口

- 没有测试证明 `artifact_root` 四目录已与 `hydro-platform` 的证据包、候选主题、活动和日报发布链统一；当前代码尚未接入。
- 没有 Obsidian Adapter、人工主题决定命令、卡片—主题关系库或 idea 模块，因此不存在相应实现测试。
- 现有自动测试不验证证据卡的科学正确性、候选主题的研究价值或 idea 创新性。
- 尚未完成干净异机、真实关机/重新登录、云端 PDF 延迟和大规模语料的端到端验收。
- 当前没有 CI 合并门禁；本地测试通过不会自动阻止未验证变更合入主分支。

## 运行命令

```powershell
# 文档站与链接
uv run mkdocs build --strict

# 两套自动测试
uv run pytest --ignore=tests/test_zotero_local_api_integration.py

# 两个科研 Skill 的独立自测
uv run python skills/hydrology-evidence-cards/tests/self_test.py
uv run python skills/hydrology-theme-synthesis/tests/self_test.py
```

`tests/test_zotero_local_api_integration.py` 目前与已安装 `mcp` 包的服务类接口不兼容，因此上述默认命令明确忽略它。这个例外是未解决缺口，不能记为该集成测试通过。
