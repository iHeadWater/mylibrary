# 用户指南

**围绕文献的一条线** —— 按你在哪一段，看对应的页面。动手前先装好[前提与配置](../getting-started/installation.md)。

| 阶段 | 做什么 | 页面 |
|---|---|---|
| **① 收进来** | 下载 PDF · 建 Zotero 条目（含 `linked_file` 附件） | [论文入库流水线](paper-pipeline.md) · [论文 PDF 下载（机构访问）](download-pdf.md) · [Zotero 入库](zotero-sync.md) |
| **② 读进去** | 按题名 / 全文 / 标签检索库；读全文、附件与批注 | [MCP Server 工具](mcp-tools.md) |
| **③ 组织起来** | 精读成分析卡；主题聚类与知识图谱 | [文献深度处理](literature.md) |
| **④ 产出内容** | 公众号文章 / 播客 / B 站 | [文献深度处理](literature.md) |
| **⑤ 沉淀成资产** | 文献卡 → 主题卡（长期可追溯） | 见下一节 |
| 另外 | 新增论文 → NotebookLM 中文简报 / 音频 / 视频 | [Zotero → NotebookLM](zotero-notebooklm.md) |
| 配置 | 环境变量、TOML、Linked Attachment Base Directory | [Zotero 配置参考](config.md) |

## ⑤ 沉淀成资产：文献卡与主题卡

从**你自己的** Zotero 文献出发：文献卡 → 代码校验 → 候选主题。**运行时 Windows-only。**
配好之后多数事直接跟 agent 说人话即可，见[概述](cards/index.md)。

| 页面 | 讲什么 |
|---|---|
| [概述](cards/index.md) | 是什么、五条命令、边界 |
| [单篇论文输入](cards/paper-input.md) · [主体卡草稿](cards/subject-card-draft.md) · [主体卡校验](cards/subject-card-validation.md) | 单篇三步 |
| [统一主题池](cards/unified-theme-pool.md) | 一个研究问题一个长期主题：候选演化、合并/拆分、正式主题保护 |
| [公共模板](cards/templates.md) · [运行维护](cards/runtime-maintenance.md) | 模板资产与排障 |
| [项目级设计](../development/platform/project-design.md) · [配置字段参考](../development/platform/config.md) | 开发者向 |

## 相关

- [前提与配置](../getting-started/installation.md) —— 先看这个：通用前提 + 按能力看额外要什么 + 凭据放哪
- [模块架构](../development/architecture.md) —— 代码结构与数据流
- [ADR-0002](../adr/0002-zotero-two-clients-boundary.md) —— 为什么读 Zotero 保留两套客户端、各自服务哪种运行环境
