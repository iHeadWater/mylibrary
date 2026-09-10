# 用户指南

本仓库的能力分**入库**与**消费**两侧。先确定你要做哪一侧的事,再看对应的页面。

| 侧 | 做什么 | 代码 |
|---|---|---|
| **入库**（采集） | 论文 PDF **下载** + **建 Zotero 条目**(含 `linked_file` 附件) | `scripts/download_paper.py`、`hydrolitagent/zotero/`、`hydrolitagent/literature/download_pdf.py` |
| **消费** | 从 Zotero 库读出 → 精读/分析卡 → 主题分类/知识图谱 → 公众号/播客/B 站 | `hydrolitagent/literature/`、`hydrolitagent/graph/`、`skills/` |
| **消费（长期资产）** | 共享库 → 证据包 → 主题池 → 日报,无人值守、确定性 | [`hydro-platform/`](../hydro-platform/index.md) |

两点容易搞混:

- **`hydrolitagent` 横跨两侧** —— 入库的几个命令和消费的绝大部分都在它里面。它不是"入库侧"的代名词。
- **消费侧内部分两支** —— 上面那一支产出**当期内容**(文章、播客、图谱、分析卡);`hydro-platform` 那一支产出**长期可追溯的知识资产**(证据包、主题池),且不由人逐篇驱动。

## 入库：下载与入 Zotero

| 页面 | 讲什么 |
|---|---|
| [论文入库流水线](paper-pipeline.md) | DOI / arXiv ID / 标题 → 下载 PDF → Zotero 条目 + `linked_file` 附件 |
| [论文 PDF 下载（机构访问）](download-pdf.md) | 通过机构访问用 Playwright 下载,含各出版商流程与反模式 |
| [Zotero 入库（linked_file）](zotero-sync.md) | 已下载 PDF 同步进 Zotero,零云端配额 |

## 消费：读取与深度处理

| 页面 | 讲什么 |
|---|---|
| [MCP Server 工具](mcp-tools.md) | 12 个 MCP 工具的完整参考(10 个 Web API + 2 个 Local API)—— 读 Zotero 库的接口 |
| [文献深度处理（Literature CLI）](literature.md) | 每周综述、精读分析卡、公众号发布/润色/配图、B 站上传 |
| [Zotero → NotebookLM 简报](zotero-notebooklm.md) | 新增论文整理成中文简报 / 音频 / 视频概览 |
| [Zotero 配置参考](config.md) | 环境变量、TOML 配置、Linked Attachment Base Directory(两侧共用) |

## 消费：长期知识资产（`hydro-platform`）

平台的文档单独成节(见左侧导航「科研知识平台」),这里给几个最常用的入口:

| 页面 | 讲什么 |
|---|---|
| [平台概述](../hydro-platform/index.md) | 平台是什么、当前工作流、目录地图、已知限制 |
| [平台完整操作说明](../hydro-platform/platform-operations-guide.md) | 完整交接材料:目录、实现链路、配置、换机、日常运行与排错 |
| [统一主题池](../hydro-platform/unified-theme-pool.md) | 一个研究问题一个长期主题:候选演化、合并/拆分、正式主题保护 |
| [证据包](../hydro-platform/evidence-packs.md) | 一篇论文一个证据包:粗卡、来源清单、定向精读的存储逻辑 |
| [配置字段参考](../hydro-platform/config.md) | 平台总配置的逐字段说明 |
| [操作手册](../hydro-platform/operator-manual.md) | 日常运行、排错与交接 |

> **适用范围**:平台目前是 **Windows-only** —— 定时调度、Poppler 原生工具安装、PDF 沙箱探针都依赖 Windows。在容器或 macOS/Linux 上,`setup`、`schedule-*`、`bootstrap-native`、`pdf-direct-read-trial` 不可用。详见[平台概述](../hydro-platform/index.md)。

## 相关

- [安装配置](../getting-started/installation.md) —— 本仓库是 uv workspace,用 `uv sync --all-packages` 一次装好两个包
- [模块架构](../development/architecture.md) —— 代码结构与数据流
- [ADR-0002](../adr/0002-zotero-two-clients-boundary.md) —— 为什么读 Zotero 保留两套客户端、各自服务哪种运行环境
