# Hydro AI Papers

AI 驱动的水文水资源研究 —— 文献流水线的**深度处理层**:以 Zotero 文献库为根基,承担精读、主题分类、公众号文章、播客、知识图谱与知识库积累。

**定位**:mylibrary 承担**情报汇集之后的深度处理**。Zotero 库是文献库的起点(深度处理典型地从读库开始);**Zotero 论文入库也是本仓库能力**——DOI / arXiv / 标题 → PDF → Zotero 条目的流水线就在本仓库。上游的兄弟仓库(dailyinfo)负责进入 Zotero 之前的情报采集。

## 能力一览

| 能力 | 说明 | 入口 |
|------|------|------|
| Zotero 文献查询 | 12 个工具的 MCP Server 搜索、浏览、读取全文/附件/批注 | [MCP Server 工具](user-guide/mcp-tools.md) |
| 论文入库流水线 | DOI / arXiv ID / 标题 → 下载 PDF → Zotero 条目 + linked_file 附件 | [论文入库流水线](user-guide/paper-pipeline.md) |
| 论文 PDF 下载 | 机构访问(大连理工 SSO)通过 Claude Code + Playwright 下载 | [论文 PDF 下载](user-guide/download-pdf.md) |
| Zotero 入库(linked_file) | 已下载 PDF 同步进 Zotero 作为 linked_file,零云端配额 | [Zotero 入库](user-guide/zotero-sync.md) |
| Zotero → NotebookLM 简报 | 新增论文整理成中文简报 / 音频 / 视频概览 | [Zotero → NotebookLM](user-guide/zotero-notebooklm.md) |
| 文献深度处理 | Literature CLI:每周综述、公众号发布/润色/配图、B 站上传 | [文献深度处理](user-guide/literature.md) |
| 知识图谱 | 用 graphify 构建结构化、可查询的知识库(实体提取、社区发现、Obsidian 导出) | [模块架构](development/architecture.md) |
| 论文复现 | 复现 AI 驱动水文学关键论文 | `equation_from_data/`、`google_floodhub/` |

## 快速开始

```bash
# 安装
git clone git@github.com:OuyangWenyu/mylibrary.git
cd mylibrary
uv pip install -e .

# 配置 Zotero
cp .env.example .env
# 编辑 .env,填入 ZOTERO_API_KEY 和 ZOTERO_LIBRARY_ID
```

详见 [安装配置](getting-started/installation.md)。

## 项目结构

```
hydrolitagent/
├── cli.py               # CLI 入口:prepare, extract, graph, merge, query
├── zotero/              # Zotero 集成
│   ├── server.py         # 12 工具 MCP Server(FastMCP,端口 8002)
│   ├── paper_to_zotero.py # DOI/arXiv/标题 → Zotero 条目(Crossref/arXiv 元数据)
│   └── zot_link_gdrive.py # Google Drive → linked_file 附件
├── literature/          # Literature CLI(入库后深度处理)
│   ├── download_pdf.py      # 机构访问下载 PDF
│   ├── zotero_sync.py       # PDF → Zotero linked_file
│   ├── zotero_notebooklm.py # Zotero → NotebookLM 简报/音频/视频
│   ├── bilibili_upload.py   # 播客 → MP4 → B 站
│   └── wechat/              # figure.py, polish.py, push.py
├── graph/               # 知识图谱构建 + 合并(graphify)
│   ├── build.py          # prepare / extract / graph
│   └── merge.py          # 多 topic 合并 + D3.js HTML 可视化
└── query/               # 确定性图查询(不走 LLM)
    └── search.py

configs/                 # Prompt / 提取配置
scripts/                 # run_paper_pipeline.sh, chunk_fulltext.py
skills/                  # Agent 可用 Skill(9 个)
docs/                    # 文档站点(mkdocs-material)
outputs/                 # 精读产物:outputs/weekly-review/{date}/{cards,article,podcast}
papers/                  # 按主题组织的文献库(10 个主题)

equation_from_data/      # 论文复现:从数据发现方程
google_floodhub/         # 论文复现:Google 洪水预测
definitions.py           # 共享常量
```

## 文档导航

- [安装配置](getting-started/installation.md) — 环境搭建与 Zotero API 配置
- [5 分钟上手](getting-started/quickstart.md) — 查询文献、添加论文、启动服务
- [MCP Server 工具](user-guide/mcp-tools.md) — 12 个 MCP 工具完整参考
- [论文入库流水线](user-guide/paper-pipeline.md) — DOI 到 Zotero 的完整流程
- [论文 PDF 下载（机构访问）](user-guide/download-pdf.md) — Playwright 浏览器下载
- [Zotero 入库（linked_file）](user-guide/zotero-sync.md) — PDF → Zotero 条目
- [Zotero → NotebookLM 简报](user-guide/zotero-notebooklm.md) — 新机器配置与完整工作流
- [文献深度处理](user-guide/literature.md) — 精读/主题/公众号/播客 CLI
- [Zotero 配置参考](user-guide/config.md) — 配置文件与环境变量
- [模块架构](development/architecture.md) — 代码结构与数据流
- [贡献指南](development/contributing.md) — 如何运行测试与添加新工具
- [决策记录](adr/0001-zotero-linked-file-sync.md) — 为什么用 linked_file
