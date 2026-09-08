# 数据结构

本目录存放机器可校验的数据结构。当前默认 rough-card-single-agent-v1，仍使用 card-generation-output.schema.json（版本 2）。manifest 记录 STRUCTURE_VALIDATED / 1 个角色；旧 VALIDATED / 6 个角色仅用于历史协议。结构通过不是独立语义验证。

当前已有：

- `pdf-direct-read-trial-output.schema.json`：独立路径直读实验的读取声明、图表观察和限制，已移除原文摘录字段；Python 检查结构及声明的完整性，不将阅读声明作为独立全文或视觉证明，不得用来放行正式证据卡；
- `evidence-manifest.schema.json`：证据包 manifest.json 的版本 1 结构，支持 `PLACEHOLDER` 和带完整生成记录的 `ROUGH`；
- `card-generation-output.schema.json`：单 Agent 制卡或旧合成角色的输出协议版本 2，约束全文/视觉阅读声明、模板分类、置信度、理由和 Markdown 正文；
- `fact-extraction-output.schema.json`：两个独立事实提取角色的事实、页码、证据定位、覆盖范围和图表清单；
- `fact-adjudication-output.schema.json`：原文裁决角色的已验证事实、双路来源映射、分歧和覆盖缺口；
- `critical-analysis-output.schema.json`：批判分析角色的前提事实、证据强弱、因果边界、方法漏洞和外推限制；
- `adversarial-review-output.schema.json`：对抗复核角色的五类强制挑战、七项覆盖检查、修正问题和最终裁决。

模型输出 schema 使用结构化输出的最小兼容子集；Python 检查来源身份、页数、归因格式和模板；跨角色 ID、数量阈值和对抗裁决仅存在于旧多 Agent 模式。证据包 manifest 同时兼容历史 MCP 回执和当前 `local_pdf_path`：后者保存来源记录但不伪造 `pages_served`，`source_access_verified=false` 不代表质量流程失败，而是未独立证明逐页阅读。

后续还需补充：

- 关键贡献事件；
- 本地任务状态；
- 自动化运行结果。

数据结构需要版本号和升级规则，保证新电脑能够读取已有结果并恢复运行。
