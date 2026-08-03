# Hydro AI Papers

AI 驱动的水文水资源研究 —— **Zotero 文献工具、知识图谱构建、论文复现**。

本仓库承担三个角色：

1. **Zotero 工具** — 12 个工具的 MCP Server 用于查询 Zotero 文献库，以及论文入库流水线（DOI → PDF → Zotero 条目）。[📖 文档](http://localhost:8000)
2. **知识图谱** — 使用 [graphify](https://github.com/graphify) 从水文文献中构建结构化、可查询的知识库，包含实体提取、社区发现和 Obsidian 兼容导出。
3. **论文归档** — 精选并复现 AI 驱动的水文学关键论文，附带代码和数据。

## 快速开始

```bash
git clone git@github.com:OuyangWenyu/hydro_ai_papers.git
cd hydro_ai_papers
uv pip install -e .

cp .env.example .env   # 填入 DEEPSEEK_API_KEY，设置 HYDROLITAGENT_OUTPUT
```

### Zotero 工具

```bash
# 启动 Zotero MCP Server（12 个工具，端口 8002）
uv run python -m hydrolitagent.zotero.server

# 通过 DOI 添加论文到 Zotero
uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "10.1038/s41586-024-07145-1"

# 完整流水线：下载 PDF + Zotero 入库
bash scripts/run_paper_pipeline.sh "10.1038/s41586-024-07145-1"

# 启动文档站点
uv run mkdocs serve
```

详见 [文档站点](http://localhost:8000) 获取 MCP 工具完整参考和论文入库指南。

### 构建知识图谱

```bash
# 对一个目录下的 Markdown 论文执行完整 pipeline
uv run hydrolitagent prepare papers/your-topic/          # 第一步：检测 + 分批
uv run hydrolitagent extract papers/your-topic/           # 第二步：LLM 提取
uv run hydrolitagent graph papers/your-topic/             # 第三步：建图 + 聚类 + 导出

# 合并多个 topic 图谱为统一图谱
uv run hydrolitagent merge --graphs-dir outputs/graph/ --output outputs/graph/unified/

# 查询图谱
uv run hydrolitagent query outputs/graph/graph.json --search "LSTM"
uv run hydrolitagent query outputs/graph/graph.json --neighbors <node_id> --depth 2
uv run hydrolitagent query outputs/graph/graph.json --path <node_a> <node_b>
```

### 输出产物

每次构建会产出以下文件（写入 `HYDROLITAGENT_OUTPUT` 或 `--output`）：

| 文件 | 说明 |
|------|------|
| `graph.json` | 完整图数据：节点、边、社区、超边 |
| `graph.html` | 交互式 D3.js 力导向可视化 |
| `graph_hierarchical.html` | 层级 Topic/Community 下钻视图 |
| `GRAPH_REPORT.md` | 文字报告：核心节点、意外连接、统计信息 |
| `obsidian/` | Obsidian 知识库：每个节点一个 `.md` 页面，带 `[[wikilinks]]` |

## 项目结构

```
hydrolitagent/           # 知识图谱工具集
├── cli.py               # CLI：prepare, extract, graph, merge, query
├── graph/
│   ├── build.py         # 单 topic 图谱构建管道
│   └── merge.py         # 多 topic 合并 + D3.js 可视化
├── query/search.py      # 确定性图查询（不走 LLM）
└── zotero/              # Zotero 集成
    ├── server.py         # 12 工具 MCP Server（FastMCP，端口 8002）
    ├── paper_to_zotero.py # DOI → Zotero 条目（Crossref/arXiv 元数据）
    └── zot_link_gdrive.py # Google Drive → linked_file 附件

configs/                 # 实体提取的 LLM prompt 模板
scripts/                 # run_paper_pipeline.sh — 论文一键入库
skills/                  # Agent 技能（zotero-query, paper-to-zotero）
docs/                    # 文档站点（mkdocs-material）

equation_from_data/      # 论文复现：从数据发现方程
google_floodhub/         # 论文复现：Google 洪水预测
definitions.py           # 共享常量
```

## 论文

精选水文 AI 论文及复现代码：

1. [Global prediction of extreme floods in ungauged watersheds | Nature](https://www.nature.com/articles/s41586-024-07145-1) ([代码](./google_floodhub/))

更多论文和代码将持续更新。

## 贡献

欢迎贡献：

1. Fork 并创建新分支
2. 将论文或代码添加到相应位置
3. 确保有分享权限且兼容 [MIT License](LICENSE)
4. 提交 PR 并附上清晰说明

## 许可证

MIT License。详见 [LICENSE](LICENSE)。
