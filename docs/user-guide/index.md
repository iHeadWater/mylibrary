# 用户指南

本仓库的能力分**入库**与**消费**两侧。先确定你要做哪一侧的事,再看对应的页面。

| 侧 | 做什么 | 代码 |
|---|---|---|
| **入库**（采集） | 论文 PDF **下载** + **建 Zotero 条目**(含 `linked_file` 附件) | `scripts/download_paper.py`、`hydrolitagent/zotero/`、`hydrolitagent/literature/download_pdf.py` |
| **消费** | 从 Zotero 库读出 → 精读/分析卡 → 主题分类/知识图谱 → 公众号/播客/B 站 | `hydrolitagent/literature/`、`hydrolitagent/graph/`、`skills/` |
| **消费（文献卡与主题卡）** | 自己的 Zotero 库 → 文献卡 → 校验 → 主题卡 | [文献卡与主题卡](cards/index.md) |

两点容易搞混:

- **`hydrolitagent` 横跨两侧** —— 入库的几个命令和消费的绝大部分都在它里面。它不是"入库侧"的代名词。
- **消费侧内部分两支** —— 上面那一支产出**当期内容**(文章、播客、图谱、分析卡);文献卡与主题卡那一支把**你自己的 Zotero 文献**沉淀成**长期可追溯的文献卡与主题卡**。

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

## 消费：长期知识资产（文献卡与主题卡）

平台文档已并入「用户指南 / 文献卡与主题卡」与「开发 / 平台实现」两处,这里给几个最常用的入口:

| 页面 | 讲什么 |
|---|---|
| [平台概述](cards/index.md) | 平台是什么、五条核心命令、边界与限制 |
| [单篇论文流程](cards/index.md) | 从自己的 Zotero 选一篇论文 → 生成主体卡 → 代码校验的完整命令流程 |
| [项目级设计](../development/platform/project-design.md) | 总体架构、数据流、用户流程、模块边界、配置、运行和模板关系 |
| [统一主题池](cards/unified-theme-pool.md) | 一个研究问题一个长期主题:候选演化、合并/拆分、正式主题保护 |
| [配置字段参考](../development/platform/config.md) | 平台总配置的逐字段说明 |

> **适用范围**:平台运行时为 **Windows-only**,代码与文档只在 Windows 上验证过。完整环境准备(CLI 安装、登录与 Poppler)见[单篇论文流程](cards/index.md)。详见[平台概述](cards/index.md)。

## 相关

- [前提与配置](../getting-started/installation.md) —— 先看这个:通用前提 + 按能力看额外要什么 + 凭据放哪
- [模块架构](../development/architecture.md) —— 代码结构与数据流
- [ADR-0002](../adr/0002-zotero-two-clients-boundary.md) —— 为什么读 Zotero 保留两套客户端、各自服务哪种运行环境
