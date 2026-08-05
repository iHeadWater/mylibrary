# Hydro AI Papers

AI 驱动的水文水资源研究 — **Zotero 文献管理工具集**。

## 两大能力

| 能力 | 说明 | 入口 |
|------|------|------|
| 文献查询 | 通过 MCP Server 的 12 个工具搜索、浏览、读取 Zotero 文献库 | [MCP Server 工具](user-guide/mcp-tools.md) |
| 论文入库 | DOI / arXiv ID → 下载 PDF → Zotero 条目 + linked_file 附件 | [论文入库流水线](user-guide/paper-pipeline.md) |

## 快速开始

```bash
# 安装
git clone git@github.com:OuyangWenyu/hydro_ai_papers.git
cd hydro_ai_papers
uv pip install -e .

# 配置 Zotero
cp .env.example .env
# 编辑 .env，填入 ZOTERO_API_KEY 和 ZOTERO_LIBRARY_ID
```

详见 [安装配置](getting-started/installation.md)。

## 项目结构

```
hydrolitagent/zotero/
├── server.py            # 12-tool MCP Server (FastMCP, port 8002)
├── paper_to_zotero.py   # DOI → Zotero 条目（Crossref/arXiv 元数据）
├── zot_link_gdrive.py   # Google Drive → linked_file 附件
└── __init__.py

scripts/
└── run_paper_pipeline.sh  # 论文一键入库脚本

skills/                    # Agent 可用的 Skill
├── zotero-query/          # 文献库查询
├── paper-to-zotero/       # 论文下载 + 入库
└── run-paper-to-zotero/   # 简化版一键入库
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
