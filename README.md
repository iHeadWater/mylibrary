# mylibrary — 水文水资源研究知识平台

**围绕文献的一条线** —— 从收到用，一路都在这个仓库里：

| ① 收进来 | ② 读进去 | ③ 组织起来 | ④ 产出内容 | ⑤ 沉淀成资产 |
|---|---|---|---|---|
| 下载 PDF · 建 Zotero 条目 | 检索 · 精读 · 分析卡 | 主题分类 · 知识图谱 | 公众号 · 播客 · B 站 | 证据卡 · 主题池 |

入口是 **Zotero 文献库**；进入 Zotero **之前**的情报采集由上游兄弟仓库 **dailyinfo** 负责。
现在是**单个包 `hydrolitagent`**，共用一份 `.venv` 与 `uv.lock`。

> 详细能力表见 [`README-zh.md`](README-zh.md)；完整文档站在 [`docs/`](docs/index.md)。

## 开工前先配好这些

| 你要做的 | 先得有 |
|---|---|
| **所有**能力 | Git · Python 3.12–3.14 · [uv](https://docs.astral.sh/uv/) · `uv sync --all-packages` |
| 读 / 写 Zotero 库 | Zotero **API key**（放 `.env`） |
| **文献卡与主题卡** | Zotero 桌面版开着，并在设置里**允许其他应用通信** · 一个**已登录**的 AI 命令行工具（Codex 或 Claude） · 读论文 PDF 页面用的小工具 [Poppler](https://poppler.freedesktop.org/) |
| 论文入库 | 论文 PDF 所在的 GDrive 目录 + Zotero 里对应的「**链接附件根目录**」设置 |

逐条说明与凭据清单见 **[前提与配置](docs/getting-started/installation.md)** —— **配一次就够**。

## 能让 agent 做什么

配好之后，多数事**直接说人话**就行：

| 你对 agent 说 | 会发生什么 | 详情 |
|---|---|---|
| 「把这篇论文**下载并入库**」 | DOI / arXiv / 标题 → 下载 PDF → 建 Zotero 条目 + `linked_file` 附件 | [论文入库流水线](docs/user-guide/paper-pipeline.md) |
| 「去我的库里找找 X 相关的文献」 | 搜 / 读 Zotero 库（含全文、附件与批注） | [MCP Server 工具](docs/user-guide/mcp-tools.md) |
| 「把这批论文精读成分析卡 / 出一期公众号+播客」 | 每周综述：精读全文 → 分析卡 → 主题聚类 → 文章 → 播客 | [文献深度处理](docs/user-guide/literature.md) |
| 「把《某某》这篇做成卡」 | 从你的 Zotero 找到它 → 读 PDF → 出主体卡草稿 → 代码校验 | [文献卡与主题卡](docs/user-guide/cards/index.md) |
| 「这几篇都做一下」 | 同一条链路逐篇跑，一篇失败不拖累其余 | [单篇论文输入](docs/user-guide/cards/paper-input.md) |
| 「看看能聚出哪些主题」 | 由已有的文献卡生成候选主题、必要时定向精读并回填 | [统一主题池](docs/user-guide/cards/unified-theme-pool.md) |
| 「主题池现在什么样」 | 报当前候选与历史版本 | [统一主题池](docs/user-guide/cards/unified-theme-pool.md) |
| 「当前用哪个模型 / 产物放哪」 | 报模型选择与产物落点，不调模型 | [运行维护](docs/user-guide/cards/runtime-maintenance.md) |

> 前三行是**入库与当期内容**线；后五行是**文献卡与主题卡**线（底层是 `uv run hydrolitagent cards …`
> 的 5 条子命令）。无论哪条 —— **你不需要读那些详情页**，只在想自己动手或排错时才去。
>
> 付费墙（SD / Wiley / Nature 等）的下载需要浏览器 + 机构会话，见[论文 PDF 下载](docs/user-guide/download-pdf.md)。

> **代码怎么组织**（分三支 / Zotero 四种读法 / 目录地图 / 产物路径边界）见
> [模块架构](docs/development/architecture.md) 与 [配置字段说明](docs/development/platform/config.md)。

## 快速开始

```bash
git clone --branch literature-platform https://github.com/iHeadWater/mylibrary.git mylibrary
cd mylibrary
uv sync --all-packages --locked
cp .env.example .env      # 按需填 ZOTERO_API_KEY / ZOTERO_LIBRARY_ID / GDRIVE_PAPERS_PATH
```

上面只装了**通用部分**；每条能力额外要什么、凭据放哪，见[前提与配置](docs/getting-started/installation.md)。

不用自己的论文也能先跑通入口（合成示例，**不调用模型**）：

```bash
uv run python scripts/paper_validate.py --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
```

返回 `status: PASS`、退出码 `0` 即入口可用。**不要把文档里的预期结果当成实际输出。**

### 文献卡与主题卡（Windows）

配好之后跟 agent 说「把《某某》这篇做成卡」即可。自己敲是这 5 条：

```bash
uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --json
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider codex --json
uv run hydrolitagent cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json
uv run hydrolitagent cards themes-run --json
uv run hydrolitagent cards ai-config --json          # 看模型选择与产物落点
```

用 **CC Switch 接入 DeepSeek** 时**仍选 `--ai-provider claude`** —— 选的是**命令行适配器**，不是模型厂家。
详见[文献卡与主题卡](docs/user-guide/cards/index.md)（**你通常不需要读它**）。

单篇本地流程**不需要**先填工具链的 Zotero Web API 密钥，也**不需要**启动 MCP Server。

### 其他工具链与批量自动化

```bash
git clone git@github.com:iHeadWater/mylibrary.git
cd mylibrary
uv sync --all-packages   # 装依赖（workspace 成员已并入 hydrolitagent/cards）
cp .env.example .env     # 填入 DEEPSEEK_API_KEY、ZOTERO_API_KEY、ZOTERO_LIBRARY_ID 等
```

> 本仓库只有**一个包** —— `uv sync` 与 `uv sync --all-packages` 等价。

```bash
# 工具链：启动 12 个工具的 MCP Server（端口 8002）
uv run python -m hydrolitagent.zotero.server

# 工具链：下载论文并入库 —— DOI / arXiv ID / 标题 → 下载 PDF → Zotero 条目 + linked_file 附件
uv run python scripts/download_paper.py --setup-check                                  # 新机器先自检一次
uv run python scripts/download_paper.py --doi "10.1016/j.jhydrol.2023.130249" --sync
uv run python scripts/download_paper.py --arxiv 2501.08086 --sync

# 容器（myopenclaw hermes）里用打包好的流水线；逐条细节见 docs/user-guide/paper-pipeline.md
bash scripts/run_paper_pipeline.sh "10.1016/j.jhydrol.2023.130249"

# 文献卡平台：只读自查模型与产物根（Windows）
uv run hydrolitagent cards ai-config --json

# 科研工作流：先自测，再制卡
python skills/hydrology-evidence-cards/tests/self_test.py
python skills/hydrology-theme-synthesis/tests/self_test.py
```

## 文档与测试

```bash
uv run mkdocs serve     # 本地预览文档站
uv run pytest           # 一套测试：tests/（原平台测试已并入）
```

`tests/test_zotero_local_api_integration.py` 是依赖本机 Zotero 在线及特定文献样本的集成测试，不是所有新用户都能复现同一结果。本次环境有一项因指定样本只有一篇 PDF、测试要求至少两篇而失败。只验证平台代码可运行 `uv run pytest`；完整测试出现失败时应看具体原因，不把排除测试后的结果称为完整全绿。
