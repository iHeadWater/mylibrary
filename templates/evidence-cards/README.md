# 证据卡模板库

本目录保存平台当前可识别的八类 Markdown 证据卡模板。它们只提供科研内容结构，不接入来源仓库的脚本、目录、编号、状态或工作流。

## 当前模板

| 模板 ID | 文件 | 用途 |
|---|---|---|
| `original-research` | `01_original-research.md` | 原创研究论文 |
| `review-synthesis` | `02_review-synthesis.md` | 综述与证据综合 |
| `survey-monitoring-statistics` | `03_survey-monitoring-statistics.md` | 调查、监测与统计报告 |
| `engineering-report` | `04_engineering-report.md` | 工程项目报告 |
| `book-chapter` | `05_book-chapter.md` | 图书与章节 |
| `standard-guideline-policy` | `06_standard-guideline-policy.md` | 标准、指南与政策 |
| `dataset-data-product` | `07_dataset-data-product.md` | 数据集及数据产品 |
| `software-model-code` | `08_software-model-code.md` | 软件、模型与代码 |

八类模板当前都在 `_catalog.json` 中启用。启用只表示后续分类器可以选择该模板，不表示模板已经通过真实论文的科研质量验收。

## 来源与适配

- 来源仓库：`https://github.com/wangxinyu20429-dotcom/Water-Conservancy-Intelligent-Platform`
- 固定来源提交：`457d5a420959f543773fc0a5c955cc64b1ca0ecb`
- 来源仓库在读取时没有声明许可证；当前复用依据记录为用户确认的团队协作授权。
- `_catalog.json` 逐项记录来源路径、Git blob SHA、本地版本和适配后内容 SHA-256。
- 本地版本已升为 1.1.0：增加 AI 推理/信息边界分区，声明表区分原文陈述与转述，删除人工复查/独立检查及摘录要求；保留八类主体结构及来源版本。
- front matter 已改为本平台的证据 ID、Zotero 群组与父条目、PDF 指纹、自动分类和模板版本字段。

## 自动分类边界

当前由单 Agent 根据完整 PDF 自动选择唯一模板，不设置“待人工确认类型”。系统记录 `classification_confidence` 和 `classification_reason`，但置信度本身不阻塞生成。返回非法或未启用的模板 ID 时，按模板路由错误停止，不能静默使用默认模板。

当前默认单 Agent、模板驱动、详细粗卡，Python 只校验来源、非空输出、有效模板路由、重复和安全写入，不检查正文标题、表格、固定措辞或归因标签。科研正确性及下游主题收益尚待验证，不设置逐卡人工核验任务。

## 版本规则

1. 修改任一模板时，必须提升该模板的 `template_version` 和 `_catalog.json` 中的 `local_version`；
2. 同时更新模板内容的 `content_sha256`，并在需要时提升 `catalog_version`；
3. 引入来源仓库的新版本时，必须更新来源 commit、对应 source blob SHA 和适配说明；
4. 模板升级不自动批量重制历史卡片；历史卡只在后续能力实现后标记模板版本落后；
5. 类型纠正或明确触发重制时必须生成新版本并保留旧卡，不能原地覆盖。版本化重制尚未在 US-07B2 实现。

## 校验

运行：

```powershell
python automation/run.py evidence-templates-validate --json
```

只有在模板数量、启用数量、来源、版本、文件路径、front matter 和内容哈希全部通过时才返回 `ok: true`。该命令不访问 Zotero、不调用 Codex，也不改写证据包。
