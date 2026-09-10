# 用户指南

本仓库有**两条能力线**,方向相反。先确定你要走哪一条,再看对应的页面。

| | **把文献弄进来** | **从文献里沉淀认识** |
|---|---|---|
| 代码 | `hydrolitagent`(根包) | [`hydro-platform/`](../hydro-platform/index.md)(uv workspace 成员) |
| 起点 | DOI / arXiv / 标题,或一篇待下载的论文 | 共享 Zotero 库里**已经附好 PDF** 的论文 |
| 做什么 | 下载 → 入库 → 精读 → 主题分类 → 知识图谱 → 公众号/播客 | 检测新增 → 全文门禁 → 逐篇证据包 → 持续演化的主题池 → 日报 |
| 节奏 | 交互式,人驱动 | 无人值守,确定性批处理(**Windows-only** 运行时) |
| 产物去向 | `outputs/`、`papers/`、Zotero 库 | `evidence-packs/`、`themes/`、`reports/`(**不入库**,另行共享) |

两条线**不重叠**:平台不下载任何 PDF,入库与下载始终属于左侧那条。

## 把文献弄进来（`hydrolitagent`）

| 页面 | 讲什么 |
|---|---|
| [MCP Server 工具](mcp-tools.md) | 12 个 MCP 工具的完整参考(10 个 Web API + 2 个 Local API) |
| [论文入库流水线](paper-pipeline.md) | DOI / arXiv ID / 标题 → 下载 PDF → Zotero 条目 + `linked_file` 附件 |
| [论文 PDF 下载（机构访问）](download-pdf.md) | 通过机构访问用 Playwright 下载,含各出版商流程与反模式 |
| [Zotero 入库（linked_file）](zotero-sync.md) | 已下载 PDF 同步进 Zotero,零云端配额 |
| [Zotero → NotebookLM 简报](zotero-notebooklm.md) | 新增论文整理成中文简报 / 音频 / 视频概览 |
| [文献深度处理（Literature CLI）](literature.md) | 每周综述、公众号发布/润色/配图、B 站上传 |
| [Zotero 配置参考](config.md) | 环境变量、TOML 配置、Linked Attachment Base Directory |

## 从文献里沉淀认识（`hydro-platform`）

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
- [模块架构](../development/architecture.md) —— 两条线的代码结构与数据流
- [ADR-0002](../adr/0002-zotero-two-clients-boundary.md) —— 为什么读 Zotero 保留两套客户端、各自服务哪种运行环境
