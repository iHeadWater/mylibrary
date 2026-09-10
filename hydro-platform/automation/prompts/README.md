# AI 提示词

提示词负责指导分析方式，程序负责来源、路由、重复和写入保护；不把提示词要求误当成已经独立验证的科学质量。

## 当前启用

| 文件 | 用途 |
|---|---|
| [evidence-card-generation-v8.md](evidence-card-generation-v8.md) | 单 Agent 自动选型、完整阅读并按模板生成详细粗卡；协议 rough-card-single-agent-v2 |
| [pdf-local-reading-v1.md](pdf-local-reading-v1.md) | 制卡与主题精读共用的本机 PDF 路径读取指引，允许读取文字和看页面图像 |
| [../../templates/themes/](../../templates/themes/README.md) | 全池关联规划、定向精读和精读后回填的提示模板 |

主制卡指引由 paths.evidence_card_generation_prompt_file 选择；共用阅读指引由 card_generator.pdf_direct_trial.reading_prompt_file 选择。Python 读取 [八类模板](../../templates/evidence-cards/README.md) 并组装请求，不需要每个学生复制一套提示词。

当前要求把原文陈述与 AI 推理表达清楚，但不做固定摘录、章节/标签匹配、数量门槛或逐卡人工复核。不因为排版差异重跑模型。

## 实验与历史

pdf-direct-read-trial-v2.md 仅供独立读取实验使用，不是正常制卡入口。v3～v7、事实提取/裁决、批判/对抗提示词保留历史；六 Agent 与旧 MCP 不是当前默认流程，也不会在失败后自动回退。

生成/精读记录保留实际模型、提示词指纹、来源和输出。旧成果保留原来的协议，不因新提示词上线自动重制。提示词修改与版本更新应同步维护配置、测试和说明，不修改原有证据结果。

[制卡规则](../../documentation/single-agent-rough-card.md) · [总配置](../../config/README.md)
