# mylibrary — 水文水资源研究知识平台

以 **Zotero 文献库**为入口，把「读到的论文」沉淀成可追溯的长期科研资产：证据卡、主题池、知识图谱、精读分析卡。

本仓库由三条并行的线合并而成，共享同一个 **uv workspace**、同一个 `.venv` 与同一份 `uv.lock`。

> 详细能力表见 [`README-zh.md`](README-zh.md)；完整文档站在 [`docs/`](docs/index.md)。

## 三条线

| 线 | 做什么 | 代码 / 数据 | 入口 |
|---|---|---|---|
| **工具链** | 入库与消费：DOI/arXiv/标题 → PDF → Zotero 条目；读库、精读、知识图谱、公众号/播客/B 站 | `hydrolitagent/`、`scripts/`、`skills/`（9 个技能） | [文档](docs/user-guide/mcp-tools.md) |
| **自动化平台** | 无人值守的长期知识资产：检测共享 Zotero 库新增 → 全文门禁 → 逐篇证据包 → 主题池 → 日报。确定性、不需手工编辑。**运行时 Windows-only** | `hydro-platform/`、`skills/hydro-platform/` | [`hydro-platform` 文档](docs/hydro-platform/index.md) |
| **科研工作流** | 人读证据卡与主题综合：来源 → 证据卡 → 初步主题 → **人工筛选门** → 既定主题 → Claim 准入 → 万字综合。纯标准库脚本，人工决策不可绕过 | `skills/hydrology-evidence-cards/`、`skills/hydrology-theme-synthesis/`、`docs/hydro-platform/`（中文规范） | [平台总览](docs/hydro-platform/research-platform-overview.md) |

**两条线解决的问题不同**，不要混用：`hydro-platform` 追求「无人值守地产出粗卡与候选主题」，科研工作流追求「每一条科学表述都回链可核对的原文，且正式主题必须由人签字」。前者自动化强、不做法学裁决；后者有完整人工决策门，但没有调度器。

## Zotero 有四种读法，用途不同

这是最容易搞混的地方。它们读的是**同一台 Zotero Desktop 的本地 HTTP 服务**（`127.0.0.1:23119`），但库、前缀与用途不同：

| 读法 | 位置 | 目标 | 用途 |
|---|---|---|---|
| MCP Server（12 工具，端口 8002） | `hydrolitagent/zotero/server.py` | 元数据走 Web API，全文/附件走本地 API | 容器内或跨机调用 |
| 裸机脚本直连 | `hydrolitagent/literature/` | 本地 API `…/api/users/0/` | 裸 host 上的入库与简报 |
| 共享群组客户端 | `hydro-platform/…/zotero.py` | 共享群组（`/api/groups/<id>/`） | 自动化平台扫描与 PDF 门禁 |
| 只读阅读器 | `skills/hydrology-evidence-cards/scripts/zotero_reader.py` | 个人库 `…/api/users/0/` | 证据卡取材，只读、不改库、不读 SQLite |

**分工而非二选一**：容器里走 8002 的 MCP，裸 host 直连 `23119`。本地 API 基址的环境变量首选名是 `ZOTERO_LOCAL_BASE_URL`（`ZOTERO_API_URL` 是旧名）。

## 科研产物路径与当前边界

合并后的配置同时保留了两组产物路径：

- `hydro-platform` 自动化当前实际写入 `paths.evidence_packs_dir`、`themes_dir`、`activity_dir`、`reports_dir` 等目录，默认位于 `hydro-platform/` 下。
- `paths.artifact_root` 及其下的 `证据卡/`、`主题/`、`运行记录/`、`文献链接/` 已能解析和校验，可指向仓库根或显式允许的外部共享位置，但自动化发布尚未接入这四个目录。

所有实际科研产物、原始 PDF、Zotero 数据库、`.runtime` 和本机路径均不进入 Git。目标是在两组目录之间建立明确的准入与发布边界，再将 `artifact_root` 作为 Obsidian 阅读层；不应把当前的配置字段理解为两套工作流已经打通。

字段、现状和目标设计见[总配置字段说明](docs/hydro-platform/config.md)、[自动化边界](docs/hydro-platform/automation.md)和[项目级设计](docs/hydro-platform/project-design.md)。

## 快速开始

### 只想用自己的论文生成主体卡？从这里开始（Windows PowerShell）

这是可复用的**本地命令行接口**，不是作者电脑上的专用程序，也不是需要开放公网端口的服务。你使用自己的 Zotero 文献、Codex 或 Claude 登录和产物目录；无需作者的账号、目录、`.venv`、Obsidian 或群组库权限。私有仓库仍需获得 GitHub 访问权限。

先安装 Git、Python 3.12–3.14 和 uv。在你自己选择的父目录中执行下面命令；目标 `mylibrary` 应尚不存在。每条成功后再执行下一条：

```powershell
git clone --branch literature-platform https://github.com/iHeadWater/mylibrary.git mylibrary
if ($LASTEXITCODE -ne 0) { throw '克隆失败，请检查仓库权限及目标目录' }
Set-Location -LiteralPath .\mylibrary
uv sync --all-packages --locked
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请先处理上面的错误' }
Test-Path .\.venv\Scripts\python.exe
```

最后应显示 `True`。**所有后续相对路径命令都在这个仓库根目录执行**；不是直接在 `C:\Users\你的用户名` 中执行。新开终端后先进入你自己的仓库目录。

先跑不需要 Zotero、原始 PDF、模型账号的合成示例：

```powershell
.\.venv\Scripts\python.exe scripts/paper_validate.py --draft hydro-platform/automation/examples/subject-card-validation/draft.json --paper-input hydro-platform/automation/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
$LASTEXITCODE
```

修复版本应返回 `status: PASS`、退出码 `0`；合成示例的短正文提示不影响通过。**不要把文档中的预期结果或 `# passed` 注释当成实际输出。** PR #46 未合并时，需先按[完整上手说明](docs/hydro-platform/single-paper-quickstart.md)切到该 PR 分支，才能验证其修复版示例。

三个公开入口如下（安装后可运行 `--help` 查看参数）：

| 阶段 | 入口 | 输入与输出 | 是否调用模型 |
| --- | --- | --- | --- |
| 取得论文 | `python scripts/paper_input.py` | 自己的题名/DOI 或条目 Key → 候选或单篇 READY JSON | 否 |
| 生成草稿 | `python -m hydro_platform evidence-generate` | READY JSON + `--ai-provider` → `draft_path`、`card_path` | 是 |
| 代码校验 | `python scripts/paper_validate.py` | READY JSON + `draft_path` → PASS/FAIL、报告路径 | 否 |

表中 `python` 使用上面安装的 `.\.venv\Scripts\python.exe`。**完整步骤、CLI 认证、Poppler、个人/群组库、模型与输出目录覆盖、自动传递 draft_path、返回码及排错见[单篇流程首次配置](docs/hydro-platform/single-paper-quickstart.md)。** 单篇本地流程不需要先填工具链的 DeepSeek/Zotero Web API 密钥，不需要启动 MCP Server。

### 其他工具链与批量自动化

```bash
git clone git@github.com:iHeadWater/mylibrary.git
cd mylibrary
uv sync --all-packages   # 装 workspace 的两个包：hydrolitagent（根）与 hydro-platform
cp .env.example .env     # 填入 DEEPSEEK_API_KEY、ZOTERO_API_KEY、ZOTERO_LIBRARY_ID 等
```

> 裸 `uv sync` 只装根包依赖，`uv run hydro-platform …` 会不可用。请用 `uv sync --all-packages`。

```bash
# 工具链：启动 12 个工具的 MCP Server（端口 8002）
uv run python -m hydrolitagent.zotero.server

# 工具链：DOI / arXiv / 标题 → PDF → Zotero
bash scripts/run_paper_pipeline.sh "10.1016/j.jhydrol.2023.130249"

# 自动化平台：一轮串行处理（Windows）
uv run hydro-platform run-once --json

# 科研工作流：先自测，再制卡
python skills/hydrology-evidence-cards/tests/self_test.py
python skills/hydrology-theme-synthesis/tests/self_test.py
```

## 目录地图

| 位置 | 存什么 |
|---|---|
| `hydrolitagent/` | Python 包：Zotero MCP Server、下载/入库、文献处理、知识图谱 |
| `hydro-platform/` | 自动化平台：`automation/`（代码与测试）、`config/`、`templates/`（9 类证据卡模板 + 主题模板）、`pyproject.toml` |
| `skills/` | 12 个技能：9 个工具链技能 + `hydro-platform` + 两个水利科研技能 |
| `docs/` | 文档站源码（mkdocs）：英文技术文档 + `docs/hydro-platform/`（平台与科研规范，含中文子目录） |
| `scripts/`、`configs/`、`docker/` | 入库脚本、图谱提示词、MCP Server 镜像 |
| `tests/`、`hydro-platform/automation/tests/` | 两套 pytest 测试 |
| `证据卡/`、`主题/`、`运行记录/`、`文献链接/` | 科研产物（**路径可配**，默认在此，不入 Git） |
| `_legacy/`、`equation_from_data/`、`google_floodhub/` | 历史代码与论文复现 |
| `docs/hydro-platform/research-platform-overview.md` | 科研工作流层的完整说明（原王新宇线 README） |

## 文档与测试

```bash
uv run mkdocs serve     # 本地预览文档站
uv run pytest           # 两套测试：tests/ 与 hydro-platform/automation/tests/
```

`tests/test_zotero_local_api_integration.py` 是依赖本机 Zotero 在线及特定文献样本的集成测试，不是所有新用户都能复现同一结果。本次环境有一项因指定样本只有一篇 PDF、测试要求至少两篇而失败。只验证平台代码可运行 `python -m pytest hydro-platform/automation/tests`；完整测试出现失败时应看具体原因，不把排除测试后的结果称为完整全绿。
