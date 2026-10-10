# 主体卡代码校验门禁

#31 接收 #30 的 draft.json 及其对应 #29 READY 输入记录，按确定性规则返回 PASS 或 FAIL。校验器不调用模型，不读取 Zotero，也不重新读取 PDF；它比较已有输入、阅读记录及所选版本资产。PASS 仅表示这些代码规则通过，不证明原文支持结论或科研内容正确。

## 命令与记录

在普通 PowerShell 终端的仓库根目录直接运行项目代码：

~~~powershell
uv sync --all-packages --locked
.\.venv\Scripts\python.exe -m hydrolitagent.cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json
~~~

默认直接使用当前检出代码对应的模板、所选后端的阅读提示词和 schema，不读取 config.json 或 HYDRO_PLATFORM_CONFIG。无需 Zotero、PDF 文件、群组 ID、Poppler 或 Codex 登录。输入中原始 PDF 的绝对路径只作为生成时的历史信息，支持 Windows 盘符/UNC 和 POSIX 路径，不按校验电脑的当前目录重新解析。退出码 0 表示 PASS，3 表示校验或记录保存失败，配置错误为 2。人类可读输出也会列出错误码、字段路径和原因。

### 首次使用与路径选择

完整分阶段安装说明见[单篇流程首次配置](single-paper-quickstart.md)。仓库附带合成示例，不需要私人论文或配置，可直接验证入口：

~~~powershell
.\.venv\Scripts\python.exe -m hydrolitagent.cards evidence-validate --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo --json
~~~

该示例只验证程序规则，不能用于科研。报告存到 outputs/validation-demo/<validation_id>/validation.json。

| 选择项 | 默认值与覆盖方式 |
| --- | --- |
| 模板、提示词、schema | 包内的 hydrolitagent/cards/assets；--assets-root 可选择另一份完整资产目录 |
| 各个资产文件 | Python 公共接口 ValidationAssets 可逐个指定；from_root(root) 按仓库布局构造 |
| 兼容已有配置 | 显式 --config 路径；与 --assets-root 互斥；完整配置仍须有效，个人库 group_id 设 null |
| 报告位置 | --report-dir > HYDRO_PLATFORM_VALIDATION_REPORT_DIR > 草稿旁 validations/ |
| 输入与 CLI 相对路径 | 相对于当前工作目录；也可传绝对路径 |

JSON 命令结果返回 asset_paths 及 validation_path，便于确认实际使用的位置。自选报告目录适用于只读共享输入；每次运行创建唯一子目录。换资产后仍严格比较版本指纹，不能靠换路径跳过校验。

~~~python
from hydrolitagent.cards.card_validation import ValidationAssets, validate_subject_card_file

# None 使用随当前检出代码分发的资产；也可传 ValidationAssets.from_root(root)。
report = validate_subject_card_file(None, draft_path, input_path, report_dir=report_directory)
# ValidationAssets 的六个路径均可独立传入，也兼容原 AppConfig 参数。
~~~

原草稿保持逐字节不变。每次校验在其旁边追加：

~~~text
<草稿目录>/
├── card.md
├── draft.json
└── validations/
    └── <validation_id>/
        └── validation.json
~~~

校验记录包含规则版本、校验器代码指纹、校验时间、草稿版本 ID、草稿和输入协议版本、两者规范化 JSON 的 SHA-256、状态、错误、提示及下游准入标志。规范化会忽略 JSON 对象键顺序和格式缩进，正文字符串的修改仍会改变指纹。

PASS 记录的 eligible_for_theme_generation 为 true；scientific_correctness_verified 和 production_eligible 始终为 false。content_validation_performed 表示进行了代码检查。原草稿仍为 DRAFT_PENDING_VALIDATION，正式发布属于 #35。记录写入失败时，命令不返回可供下游使用的 PASS。

## 规则 v1

### 最低内容与字段

可读正文必须非空且不能只有标题、HTML 注释或占位符。检查最低内容覆盖以 #30 固定的机器字段为准，不强制新的正文标题或排版模板：

| 字段 | 必须提供的内容 |
| --- | --- |
| research_questions | 研究问题 |
| study_objects_and_scales | 对象与尺度 |
| data_and_methods | 数据与方法 |
| comparison_baselines | 比较基线，或不适用的解释 |
| findings | 主要结果及唯一 finding_id |
| boundaries | 限制和适用边界 |
| missing_information | 缺失或无法取得的信息，或无适用缺项的解释 |

七个数组均须有记录，每条 statement 须非空。TBD、TODO、未填写、模板占位符，或单独一个“未报告/不适用”标签不能满足要求；须给出具体说明。是否如实、是否充分仍不能仅由字符串检查证明。

所有字段按照 #30 的 schema 检查类型、必需键和枚举；未知机器字段拒绝。协议版本必须是整数 1，布尔值不能冒充整数。尚不支持的协议必须显式迁移，不能修改版本标签后直接混用。

### 原文位置与结果编号

`information_status` 描述信息在当前论文及本次可用材料中的可获得情况，**不是科学正确性或独立核查状态**。当前论文转述其他研究但未取得被引原文时，使用 `original_paraphrase + reported`，定位到当前论文的物理页，并在 statement 明确注明“未核查被引原文”；不能写成当前论文自己的实验结果。当前来源未报告、确实不适用或所需材料不可获得时，分别使用 `not_reported`、`not_applicable`、`unavailable`，配合 `information_boundary` 说明影响。

正文叙述顺序可以调整；必须保持每个 finding_id 与对应结果的关联，完整引用所有编号且不引用未定义编号。生成阶段允许保存待校验草稿；以下规则失败会阻止下游准入，不会把草稿伪装成已校验产物。

- information_status=reported 的记录至少有一个原文位置，每个位置的 pdf_page 必须是 1 到来源 PDF 总页数之间的整数。
- section、figure、table 为非空文本或 null；不依据这些文本声称已经验证实际章节、图表存在。
- not_reported、not_applicable、unavailable 必须明确标为 information_boundary，并写出具体说明；这些记录可以没有原文位置，无需捏造页码。
- finding_id 采用 F001 形式，至少三位数字，且不得重复。正文须明确引用各个结果编号，也不得引用机器字段里不存在的编号；HTML 注释中的编号不计入正文引用。
- 低于 300 个可见正文字符仅产生 CARD_TEXT_SHORT 提示，不能单独导致 FAIL。长正文也不能抵消缺失字段、身份冲突等错误。

### 来源与版本

输入必须是 #29 的单篇单 PDF READY 协议。文库、请求 key、父条目、附件、条目元数据、PDF 哈希和大小须与草稿完全一致，包括 JSON 类型。请求 key 必须指向该父条目或附件。

PDF 页数须与阅读记录一致；阅读记录还必须确认来源身份、文件未变化和阅读回执已被接受。这里只核对记录，不独立验证模型读懂了原文。

基础提示词、补充提示词、阅读提示词、输出 schema、模板及目录的版本/指纹须与当前配置的资产匹配；按输入重建组合提示词并核对指纹。资产改变后旧草稿可能不再满足当前规则，应返回版本错误，不能悄悄换标签。

## 稳定错误码

每条错误均带 code、JSON Pointer 风格 path 和 message；下一步修正应依据 code 和 path，不解析自然语言消息。

| 错误码 | 含义 |
| --- | --- |
| CARD_JSON_INVALID | 输入对象不能规范化为有限 JSON |
| CARD_INPUT_INVALID / CARD_INPUT_VERSION | 非法 READY 输入或不支持的输入版本 |
| CARD_DRAFT_INVALID / CARD_DRAFT_VERSION / CARD_DRAFT_STATE | 草稿元数据、版本或状态无效 |
| CARD_FIELD_MISSING / CARD_FIELD_TYPE / CARD_FIELD_ENUM / CARD_FIELD_UNKNOWN | 缺键、类型、枚举或额外字段错误 |
| CARD_CONTENT_MISSING | 缺少最低内容、空数组或占位陈述 |
| CARD_INFORMATION_BOUNDARY | 未报告/不适用信息未标为信息边界 |
| CARD_LOCATION_REQUIRED / CARD_LOCATION_INVALID | 缺少原文位置，或位置/页码格式错误 |
| CARD_FINDING_ID_INVALID / CARD_FINDING_REFERENCE | 结果编号重复/无效，或正文引用不一致 |
| CARD_SOURCE_MISMATCH / CARD_READING_RECORD_INVALID | 来源身份或阅读记录冲突 |
| CARD_PROVENANCE_MISSING / CARD_VERSION_MISMATCH / CARD_TEMPLATE_INVALID | 缺少或不匹配的版本信息，或不支持的模板 |
| CARD_RULESET_UNAVAILABLE | 无法读取规则所需的配置资产，关闭准入 |
| CARD_VALIDATION_IO | JSON 文件损坏、重复键、非有限数值或记录读写失败 |
| CARD_VALIDATION_REQUIRED / CARD_VALIDATION_FAILED / CARD_VALIDATION_STALE | 下游缺少记录、当前校验失败、或旧记录失效 |
| CARD_SELECTION_INVALID | 主题侧未提供完整的显式输入选择 |

通常一次返回多个可定位错误。无法解析的 JSON 或保存失败返回结构化失败；由于不能完整取得/保存记录，不保证这些失败有 validation_path。

## 下游如何使用

下游 config 同样可以传 None（默认资产）、ValidationAssets 或已有 AppConfig。底层读取接口为 card_validation.load_validated_subject_card(config, draft_path, input_path, validation_path)。主题侧统一入口为 themes.load_subject_card_sources(config, selected)：

~~~python
sources = load_subject_card_sources(config, [{
    "draft_path": ".../draft.json",
    "input_path": ".../paper-input.json",
    "validation_path": ".../validations/<id>/validation.json",
}])
# 所有选择均已通过当前规则，才会返回完整 sources；#33 在此之后生成候选主题。
~~~

入口重新检查当前草稿和输入，再比较保存记录的规则版本、代码指纹、输入/草稿指纹及状态。没有校验记录、失败记录被改成 PASS、正文或输入改动、规则变动、记录字段被改动，都不能沿用旧结果。一组选择中任意一项失败，整组不会返回给主题调用方。

本 PR 提供 #33 的输入边界，不实现 #33 的主题生成。已有旧证据包扫描流程仍是独立协议，不扫描这套 drafts 目录；本改动不追认旧粗卡为通过 #31 的主体卡。

记录用于防止旧结果误用和绕过当前代码规则，不是密码学签名。拥有文件写权限的人仍能编辑记录；下游重新运行规则是必要条件。PDF 在生成后是否又变化，应由后续重新取得的 #29 输入体现，这个离线校验器不额外读取 PDF。

## 验证

~~~powershell
uv run pytest tests/test_card_validation.py tests/test_card_draft.py
~~~

通过与失败夹具覆盖内容、字段、页码、版本、来源、旧 PASS 失效、记录保存失败以及下游准入；另检查短正文可通过、长正文不能掩盖缺项、校验不调用模型且不修改原草稿。

真实草稿可以直接用于离线验证，但无论 PASS 或 FAIL 都不能作为科学正确性的背书。自动修正属于 #32，正式保存属于 #35。


## Codex 与 Claude 使用同一个代码校验入口

#43 两种后端生成相同主体卡字段。校验器依据 `generation_protocol_version` 选择已注册的阅读协议：Codex 为 `codex-local-pdf-v1` / `local_pdf_path`，Claude 为 `claude-local-pdf-v1` / `claude_pdf_read`。两者均绑定来源身份、物理页数和提示词版本；Claude 额外检查只读 PDF 成功回执的页范围完整，不伪造 Codex 沙箱预检记录。

可直接运行 `python scripts/paper_validate.py --draft 路径 --paper-input 路径`。校验本身没有模型调用，也不要求安装任何模型客户端；参数与平台入口一致，独立脚本始终输出 JSON。自动改写主体卡不是此 PR 的职责。
