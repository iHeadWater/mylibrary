# 验证地图

本页把项目文档中的关键规则与现有测试对应起来。历史测试数量、耗时和样本演示不再累加保留；Git 历史已经保存这些过程。

## 现有覆盖

| 用例 | 被固定的规则与否定情形 | 证据 | 状态 |
| --- | --- | --- | --- |
| 配置与路径 | 未知字段、越界路径、重叠安装目录和非布尔开关必须拒绝 | `test_config.py` | 已有自动测试 |
| 单篇论文输入 | 候选选择、个人/群组、父条目/附件、缺失或重复 PDF、未索引全文 | `test_paper_input.py` | 已有自动测试 |
| PDF 门禁与交付 | 缺失、过小、无可用文本、身份变化和越界文件不得进入制卡 | `test_pdf_gate.py`、`test_pdf_delivery.py`、`test_pdf_sandbox.py` | 已有自动测试 |
| 证据卡模板 | 九类模板的来源、版本、front matter 和内容指纹必须一致 | `test_evidence_templates.py` | 已有自动测试 |
| 单 Agent 制卡 | 来源错误、空输出、非法模板、重复生成和人工改动必须停止保存 | `test_ai_config.py`、`test_card_draft.py`、`test_card_generation.py`、`test_card_saving.py`、`test_single_agent.py` | 已有自动测试 |
| 模型适配器 | Claude 只读回执、Codex 本地 PDF 读取、代理与连接保护 | `test_claude_cli.py`、`test_codex_local_pdf.py`、`test_codex_proxy.py`、`test_connection_guard.py`、`test_codex_text.py` | 已有自动测试 |
| 主体卡校验门禁 | 最低内容、来源和版本绑定、旧 PASS 失效、失败不能进入主题输入 | `test_card_validation.py` | 已有自动测试 |
| 候选主题池 | CREATE / UPDATE / MERGE / SPLIT 的来源、编号、血缘和原子发布必须保持，旧粗卡不得被修改 | `test_themes.py`、`test_theme_pool.py` | 已有自动测试 |
| 任务与保存完整性 | 完成必须以内容与来源记录为准，不得只凭目录或任务标记；已有卡不得被覆盖 | `test_tasks.py`、`test_completion_records.py`、`test_evidence_packages.py` | 已有自动测试 |
| 模型预检与进度 | Zotero/模型预检失败可定位，进度心跳不泄漏凭据 | `test_preflight.py`、`test_progress.py` | 已有自动测试 |
| 仓库结构 | 代码、模板、文档和忽略的科研产物保持预期边界 | `tests/test_repo_structure.py` | 已有自动测试 |

这些测试主要使用模拟供应者、临时目录和隔离配置。它们证明工程边界和失败保护，不证明模型理解论文正确或主题具有科学价值。

## 提议测试

| 优先级 | 测试类型 | 场景 | 预期结果 |
| --- | --- | --- | --- |
| P0 | 自动集成 | 正式主题建立、改名、合并、拆分和归档 | 没有人员、时间、理由和来源候选时拒绝；历史 ID 不丢失 |
| P0 | 自动集成 | 卡片—主题关系审核 | 自动化只能创建 `proposed`，只有人工动作能转为 `confirmed` |
| P1 | 受控真实验证 | 干净 Windows 机器安装、登录和恢复 | 仅依赖 Git 可复现资产、Zotero 和 Git 外产物备份即可恢复 |
| P1 | 受控真实验证 | PDF 仍在云端同步、Zotero 从未登录或 CLI 账号失效 | 系统显示可操作阻塞，不产生空卡或无限重试 |
| P1 | 人工科研评审 | 从多类文献抽样复核 Claim、数字、图表和结论边界 | 记录准确性、严重错误和模板类型差异，不把工程测试当作科学验证 |

## 当前缺口

- 没有 Obsidian Adapter、人工主题决定命令、卡片—主题关系库或 idea 模块，因此不存在相应实现测试。
- 现有自动测试不验证证据卡的科学正确性、候选主题的研究价值或 idea 创新性。
- 尚未完成干净异机、真实关机/重新登录、云端 PDF 延迟和大规模语料的端到端验收。
- 当前没有 CI 合并门禁；本地测试通过不会自动阻止未验证变更合入主分支。

## 运行命令

```powershell
# 文档站与链接
uv run mkdocs build --strict

# 平台自动测试
uv run pytest tests

# 两个科研 Skill 的独立自测
uv run python skills/hydrology-evidence-cards/tests/self_test.py
uv run python skills/hydrology-theme-synthesis/tests/self_test.py
```

仓库根的全量 `uv run pytest` 还包含依赖本机 Zotero 在线及特定样本的集成测试（如 `tests/test_zotero_local_api_integration.py`）；这类测试可能因本地库不同而失败，不能与平台单元测试混为一谈。
