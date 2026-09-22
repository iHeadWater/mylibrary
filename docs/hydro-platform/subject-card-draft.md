# 单篇主体卡草稿

#30 接收 #29 的单篇 READY 输入，复用现有单 Agent PDF 阅读、八类单来源模板和 evidence-generate 入口，一次模型调用同时生成详细卡片正文与机器字段。输出始终是待校验草稿，供后续 #31 校验、#32 有限修正和 #35 正式保存使用。

## 运行

先按[安装说明](workstation-setup.md)配置并登录 Codex CLI；配置中 card_generator.workflow_mode 必须为 single_agent，PDF reader adapter 必须为 local_path。模型、推理强度和 PDF 工具沿用现有配置。#29 尚未合并时也可传入同协议 fixture，入口不会重复访问 Zotero、查找附件或要求群组 ID。

在仓库根运行：

~~~powershell
uv sync --all-packages
uv run --package hydro-platform-automation hydro-platform evidence-generate --config hydro-platform/config/config.json --paper-input paper-input.json --json
~~~

--paper-input - 从标准输入读取 JSON；--no-progress 关闭 stderr 进度，不影响 stdout JSON。--paper-input 与旧 --item-key 互斥，旧入口保持原行为。新入口不接受 --retry-quality-failed。

输入必须包含 schema_version=1、operation=paper_input、ok=true、status=READY、pdf_attachment_count=1，以及：

| 字段 | 内容 |
| --- | --- |
| library | type 为 user/group，id 为文库 ID；本机个人库允许 0 |
| requested_item_key | #29 接收的原始父条目或附件 key |
| item | item_key、title 以及来源元数据 |
| pdf | attachment_key、parent_key、local_path、file_size_bytes、sha256 |
| pdf.fulltext_indexed | 可以为 false；本流程直接读取本地 PDF |

父条目和附件必须对应，PDF 必须是绝对路径；生成前核对文件头、大小与 SHA-256，生成后再次核对哈希。READY 是输入就绪状态，不是内容校验结论。

## 与 #27 相同的产物目录

直接复用 hydrolitagent._config.resolve_literature_root，不新增根目录配置或回退到旧证据包目录。依次读取进程环境变量、仓库 .env、configs/paths.toml，最后使用仓库 outputs/。在配置文件中指向仓库外目录须设置 external=true；环境变量覆盖规则与 #27 一致。

~~~text
<literature_root>/
└── zotero/
    └── <user|group>-<library_id>-<parent_key>/
        └── drafts/
            └── <draft_id>/
                ├── card.md
                └── draft.json
~~~

每次显式运行产生独立草稿 ID，保留旧草稿。card.md 顶部明确标记“待校验”；draft.json 最后原子写入，是这一对文件完成保存的标志。写入失败返回 FAILED，不把残留 Markdown 视作完成草稿。目录不得通过链接逃逸出产物根。PDF 继续保存在 Zotero；模型诊断和临时阅读文件沿用本机运行目录。

## 草稿协议

draft.json 的 schema_version=1，含以下内容：

- status=DRAFT_PENDING_VALIDATION；content_validation_performed、production_eligible、scientific_correctness_verified 均为 false，由程序设定。
- source：文库身份、原始输入 key、父条目与附件 key、PDF 哈希/大小/页数和条目元数据。
- card_body_markdown：所选详细模板正文；排除 platform-decision-synthesis，不生成主题或 idea。
- machine_fields：schema_version=1，以及 research_questions、study_objects_and_scales、data_and_methods、comparison_baselines、findings、boundaries、missing_information 七个数组。
- provenance：基础及补充提示词版本/哈希、组合提示词哈希、输出 schema 哈希、模板及目录版本、模型与推理配置、阅读协议版本。
- reading_record、process_audit、usage、warnings：现有阅读流程的来源和执行记录，不等于全文科学正确性已验证。

每条机器记录含 statement、statement_role、information_status、source_locations；findings 另含 finding_id。statement_role 区分原文陈述、转述、AI 推断和信息边界，information_status 区分已报告、未报告、不适用和无法读取。source_locations 含 PDF 物理页码（从 1 开始）、章节、图号、表号；无法定位时使用 null 并说明边界，不编造位置。

机器字段与正文在同一次调用中生成，不增加一次抽取调用。输出格式定义在 automation/schemas/subject-card-draft-output.schema.json，补充提示词为 automation/prompts/subject-card-draft-v1.md。

## 草稿校验

生成后使用 [主体卡代码校验门禁](subject-card-validation.md) 检查最低内容、原文位置及来源版本一致性。校验单独保存记录，不修改草稿状态或正文；下游须通过统一读取接口复核 PASS。

## 失败与后续边界

不可读取或已变化的 PDF、错误来源身份、不支持的模板、无法解析的正文或机器字段、写入失败均返回结构化 FAILED，包含 error.code、failed_stage 和 model_invoked；不自动重试。模型已调用但输出未被接受时，可从 error.diagnostic.unvalidated_model_output_path 找到原始诊断输出（若提供方已保存），该文件不是主体卡草稿。

本层只检查输入、来源协议和可解析的数据形状，不判断字段是否充分、结论是否正确、引文是否支持陈述或公式是否完整。空数组和无法定位的信息可以进入待校验草稿；#31 负责这些内容门禁。本入口不写任务完成状态、不向正式证据包发布、不更新主题池。

## 验证

~~~powershell
uv run pytest hydro-platform/automation/tests/test_card_draft.py tests/test_literature_paths.py
~~~

固定 PDF 和模拟模型输出覆盖：一次模型调用、个人/群组库身份、未索引 PDF、输入与哈希变化、不可解析输出、模板排除、只标记待校验、配置优先级、只追加写入和 CLI 兼容性。真实论文演示还需要本机 PDF、有效的 Codex CLI 登录及现有 PDF 工具；运行结果保存在配置的产物目录中，不提交个人论文或生成卡片到 Git。
