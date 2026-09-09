# 数据结构与流程检查

当前制卡协议 rough-card-single-agent-v2，正常生成使用 card-generation-output.schema.json（版本2）；PROCESS_VALIDATED 表示流程通过，不是科学质量认证。历史记录中的 STRUCTURE_VALIDATED、VALIDATED 或 DRAFT_RECOVERED 保留原含义，不追改成新协议。

| 文件 / 位置 | 用途 |
|---|---|
| evidence-manifest.schema.json | 证据包身份、PLACEHOLDER/ROUGH 状态、当前或历史生成/恢复记录 |
| card-generation-output.schema.json | PDF 阅读声明、模板路由、分类说明和 Markdown 正文的传输结构 |
| pdf-direct-read-trial-output.schema.json | 独立 PDF 读取实验报告；不替代正式制卡，不要求原文摘录 |
| ../../templates/themes/*.schema.json | 全池 CREATE/UPDATE/MERGE/SPLIT 规划、定向精读与回填传输 |
| fact-extraction、fact-adjudication、critical-analysis、adversarial-review 的 schema | 旧多 Agent 兼容与测试，非当前默认流程 |

Python 核对原始来源、非空结果、有效模板/引用、重复和完整写入，不检查 Markdown 标题层级、归因措辞、表格形式或固定数量。主题操作数量、父子关系、正式主题保护属于流程约束，仍必须检查。

本地任务、主题注册表、事件和运行报告已经有版本字段与对应 Python 读写校验，并非每种记录都有本目录下的独立 JSON Schema。清单损坏或来源不符不能静默覆盖。

模型声称“读完”与独立证明“理解正确”不同；当前路径读取保留来源与执行记录，不伪造历史 MCP 的逐页工具回执。详见[数据边界](../../documentation/variables.md)、[验证地图](../../documentation/tests.md)。
