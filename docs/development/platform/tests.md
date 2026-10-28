# 验证地图

本页把项目文档中的关键规则与现有测试对应起来。历史测试数量、耗时和样本演示不再累加保留；Git 历史已经保存这些过程。

## 现有覆盖

| 用例 | 被固定的规则与否定情形 | 证据 | 状态 |
| --- | --- | --- | --- |
| 配置与路径 | 未知字段、越界路径、重叠安装目录和非布尔开关必须拒绝 | `test_config.py` | 已有自动测试 |
| 单篇论文输入 | 候选选择、个人/群组、父条目/附件、缺失或重复 PDF、未索引全文 | `test_paper_input.py` | 已有自动测试 |
| PDF 门禁与交付 | 缺失、过小、无可用文本、身份变化和越界文件不得进入制卡 | `test_pdf_gate.py`、`test_pdf_delivery.py` | 已有自动测试 |
| PDF→Markdown 转换 | 页锚点与页数一致、图资产与表格提取、中文/双栏/扫描件的覆盖率与 `CONVERTER_LOW_TEXT` fail-closed、同一 PDF 的 Markdown 哈希稳定 | `test_markdown_conversion.py`、`test_paper_store.py` | 已有自动测试 |
| 证据卡模板 | 九类模板的来源、版本、front matter 和内容指纹必须一致 | `test_evidence_templates.py` | 已有自动测试 |
| 单篇主体卡 | 来源错误、空输出、非法模板与引文不接地必须停止保存；旧 v1 草稿仍可只读校验 | `test_ai_config.py`、`test_card_draft.py`、`test_card_validation.py`、`test_markdown_workflow.py`、`test_legacy_removed.py` | 已有自动测试 |
| 执行者适配器 | `direct` 的 HTTP 契约、`in_session` 两阶段、脚本化替身、旧 CLI 流式解码与连接保护 | `test_direct_runner.py`、`test_in_session.py`、`test_scripted_runner.py`、`test_streaming_decoding.py`、`test_connection_guard.py` | 已有自动测试 |
| 执行者无关 | 注册表新增执行者只需 adapter + 注册；同一份 `PreparedPaper` 经 `direct` / `in_session` / 脚本化替身产出相同规范化草稿（除 `runner_id`） | `test_runner_registry.py`、`test_runner_agnostic.py`、`test_direct_runner.py`、`test_scripted_runner.py` | 已有自动测试 |
| 两阶段制卡协议 | 运行目录只含 `paper.md` / 图 / schema / 请求；`response.json` 缺失或非法、`paper.md` 被改动、Markdown 哈希或 canary 不符时结构化拒绝 | `test_in_session.py`、`test_text_only_runner.py` | 已有自动测试 |
| 引文接地 | 逐字引文命中页锚点、过短或错页引文不计入证据、覆盖率不足时 `production_eligible=false` | `test_grounding.py`、`test_markdown_workflow.py` | 已有自动测试 |
| 能力自查 | `cards doctor` 不调用模型；转换器 / 运行器 / 存储状态与 `fix`；缺可选运行器只 warn，全部缺失才 fail | `test_doctor.py` | 已有自动测试 |
| 主体卡校验门禁 | 最低内容、来源和版本绑定、旧 PASS 失效、失败不能进入主题输入 | `test_card_validation.py` | 已有自动测试 |
| 候选主题池 | CREATE / UPDATE / MERGE / SPLIT 的来源、编号、血缘和原子发布必须保持，旧粗卡不得被修改；历史批次从 `tests/fixtures/legacy_themes/` 静态读取且字节不变 | `test_themes.py`、`test_theme_pool.py` | 已有自动测试 |
| 任务与保存完整性 | 完成必须以内容与来源记录为准，不得只凭目录或任务标记；已有卡不得被覆盖 | `test_tasks.py`、`test_completion_records.py`、`test_evidence_packages.py` | 已有自动测试 |
| 模型预检与进度 | Zotero/模型预检失败可定位，进度心跳不泄漏凭据 | `test_preflight.py`、`test_progress.py` | 已有自动测试 |
| 仓库结构 | 代码、模板、文档和忽略的科研产物保持预期边界 | `tests/test_repo_structure.py` | 已有自动测试 |
| 分层边界 | `domain` 不得反向 import `adapters`/`application` 或 `subprocess`；共享层不得出现 provider 名称；已删除的 PDF 直读工具名与旧证据包栈不得回到 `hydrolitagent/cards`（`legacy/` 只读解码豁免） | `tests/test_import_boundaries.py`、`tests/test_legacy_removed.py` | 已有自动测试 |
| CLI 契约快照 | `ai-config` / `paper-input` 的 JSON 字段只增不减、退出码为 0；本机 Zotero 不可用时显式 skip | `tests/test_cli_characterization.py` | 已有自动测试 |
| 阅读方法策略 | 新产物可使用当前 method（含 `markdown_prepared`）；历史 method 只读可校验，不得写回新产物 | `tests/test_source_access_methods.py` | 已有自动测试 |

这些测试主要使用模拟供应者、临时目录和隔离配置。它们证明工程边界和失败保护，不证明模型理解论文正确或主题具有科学价值。

## 提议测试

| 优先级 | 测试类型 | 场景 | 预期结果 |
| --- | --- | --- | --- |
| P0 | 自动集成 | 正式主题建立、改名、合并、拆分和归档 | 没有人员、时间、理由和来源候选时拒绝；历史 ID 不丢失 |
| P0 | 自动集成 | 卡片—主题关系审核 | 自动化只能创建 `proposed`，只有人工动作能转为 `confirmed` |
| P1 | 受控真实验证 | 干净 Windows 机器安装、登录和恢复 | 仅依赖 Git 可复现资产、Zotero 和 Git 外产物备份即可恢复 |
| P1 | 受控真实验证 | PDF 仍在云端同步、Zotero 从未登录或 LLM API key 缺失/失效 | 系统显示可操作阻塞，不产生空卡或无限重试 |
| P1 | 人工科研评审 | 从多类文献抽样复核 Claim、数字、图表和结论边界 | 记录准确性、严重错误和模板类型差异，不把工程测试当作科学验证 |

## 当前缺口

- 没有 Obsidian Adapter、人工主题决定命令、卡片—主题关系库或 idea 模块，因此不存在相应实现测试。
- 现有自动测试不验证证据卡的科学正确性、候选主题的研究价值或 idea 创新性。
- 尚未完成干净异机、真实关机/重新登录、云端 PDF 延迟和大规模语料的端到端验收。
- `Release checks` 在 Ubuntu / macOS / Windows 三平台运行测试（不安装 Poppler），但仓库尚未配置必需状态检查；
  测试通过不会自动阻止未验证变更合入主分支。

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
