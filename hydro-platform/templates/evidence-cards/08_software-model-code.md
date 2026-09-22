---
template_id: "software-model-code"
template_version: "2.0.1"
template_source_commit: "7b0f2b7e209aa566f3c68db817d5c4a71d9f8b19"
evidence_id: "{{EVIDENCE_ID}}"
card_state: "{{CARD_STATE}}"
title: "{{TITLE}}"
zotero_group_id: "{{ZOTERO_GROUP_ID}}"
zotero_parent_key: "{{ZOTERO_PARENT_KEY}}"
zotero_attachment_key: "{{ZOTERO_ATTACHMENT_KEY}}"
source_pdf_sha256: "{{PDF_SHA256}}"
classification_confidence: "{{CLASSIFICATION_CONFIDENCE}}"
classification_reason: "{{CLASSIFICATION_REASON}}"
reading_scope: "{{READING_SCOPE}}"
generated_at: "{{GENERATED_AT}}"
updated_at: "{{GENERATED_AT}}"
---

# 软件、模型与代码证据卡：{{TITLE}}

#### 软件、模型与代码证据生成机制

1. 仓库、release、tag、commit hash、容器摘要、模型权重 hash 和许可证。
2. 科学模型、算法、训练权重、软件实现、配置与外部服务之间的对应关系。
3. 锁定依赖、操作系统／硬件、API 版本、随机种子和输入数据快照。
4. 输入／输出契约、单位、坐标、缺测、边界条件和配置文件。
5. 静态检查、安装、项目测试、示例运行、目标运行、论文复现和独立科学验证的分层证据。
6. 实际命令、开始／结束时间、退出码、日志、资源消耗、输出校验和和预设数值容差。
7. 基准数据与校准数据的独立性、适用工况、失败条件和科学有效性边界。
8. 上游漂移、依赖变化、模型权重替换和 recheck_trigger。

当前状态必须由状态证据表推导，不能人工直接选择高状态。可下载、可安装、能运行、能复现论文和独立科学有效是不同状态。

**数学公式与金额（LaTeX 转写）**：真实公式写成 LaTeX——行内 `$...$`、块级长公式 `$$...$$`（前后各留空行），不用 Unicode 纯文本（`R²`→`$R^2$`、`x_i`→`$x_i$`、`σ`→`$\sigma$`），行内不用 `\(...\)`。普通数字、单位与计数保持纯文本，不过度转写。金额一律转义为 `\$`（`$123`→`\$123`），避免与公式的 `$` 配对；反引号只留给代码、文件名、变量名与标签。

## AI 推理

- 【AI 推理】：〔若有进一步推理，分别写明结论、依据的 Cxx、推导过程、额外假设、适用条件与不能推出的内容；没有有价值的推理则明确未作进一步推理，不凑数量。〕

## 信息边界

- 【信息边界】：〔原文未报告、本次未取得或现有证据不足以支持的具体事项及影响；不要写成作者没有做，不设置人工复核任务。〕
- 陈述规则：原文结果、解释、假设及建议均标【原文陈述】并保留其性质；被引研究标【原文转述】，不冒充已读被引原文；新增分析标【AI 推理】。
