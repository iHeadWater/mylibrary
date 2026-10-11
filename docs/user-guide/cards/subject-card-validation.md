# 主体卡代码校验门禁

取上一页产出的 `draft.json` 和它对应的 READY 输入记录，按**确定性规则**返回 `PASS` 或 `FAIL`。

校验器**不调用模型、不读 Zotero、也不重新读 PDF** —— 它只比较已有的输入、阅读记录和所选版本的资产。
因此 **`PASS` 仅表示这些代码规则通过**，不证明原文支持结论、也不证明科研内容正确。

## 命令与记录

在**仓库根**执行：

```bash
uv sync --all-packages --locked
uv run hydrolitagent cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json
```

- 默认直接使用**随当前检出代码分发**的模板、所选后端的阅读提示词与 schema，
  **不读** `config.json`，也不读 `HYDROLITAGENT_CARDS_CONFIG`。
- 因此**不需要** Zotero、PDF 文件、群组 ID、Poppler 或 Codex / Claude 登录。
- 输入里原始 PDF 的绝对路径只是**生成时的历史信息**：支持 Windows 盘符 / UNC 和 POSIX 路径，
  **不**按校验这台电脑的当前目录重新解析。
- **退出码**：`0` = PASS；`3` = 校验或记录保存失败；`2` = 配置错误。
  人类可读输出也会列出错误码、字段路径和原因。

### 先用合成示例试跑

仓库带一份合成示例，**不需要**你自己的论文或配置就能验证入口：

```bash
uv run hydrolitagent cards evidence-validate \
  --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json \
  --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json \
  --report-dir outputs/validation-demo --json
```

示例只验证**程序规则**，不能用于科研。报告落在 `outputs/validation-demo/<validation_id>/validation.json`。
安装见[前提与配置](../../getting-started/installation.md)。

### 各项从哪里取

| 选择项 | 默认值与覆盖方式 |
| --- | --- |
| 模板、提示词、schema | 包内的 `hydrolitagent/cards/assets`；`--assets-root` 可另指一份完整资产目录 |
| 各个资产文件 | Python 接口 `ValidationAssets` 可逐个指定；`from_root(root)` 按仓库布局构造 |
| 兼容已有配置 | 显式传 `--config`；**与 `--assets-root` 互斥**。完整配置仍须有效，个人库 `group_id` 置 `null` |
| 报告位置 | `--report-dir` > 环境变量 `HYDROLITAGENT_CARDS_VALIDATION_REPORT_DIR` > 草稿旁的 `validations/` |
| 输入与 CLI 相对路径 | 相对于**当前工作目录**；也可传绝对路径 |

命令的 JSON 结果会返回 `asset_paths` 与 `validation_path`，便于确认实际用了哪些位置。
自选报告目录适用于**只读共享输入**；每次运行创建唯一子目录。
**换资产不会绕过校验** —— 仍会严格比较版本指纹。

```python
from hydrolitagent.cards.card_validation import ValidationAssets, validate_subject_card_file

# None 使用随当前检出代码分发的资产；也可传 ValidationAssets.from_root(root)。
report = validate_subject_card_file(None, draft_path, input_path, report_dir=report_directory)
# ValidationAssets 的六个路径均可独立传入，也兼容原 AppConfig 参数。
```

原草稿**逐字节不变**，每次校验在它旁边追加一份记录：

```text
<草稿目录>/
├── card.md
├── draft.json
└── validations/
    └── <validation_id>/
        └── validation.json
```

### 记录里有什么

规则版本、校验器代码指纹、校验时间、草稿版本 ID、草稿与输入的协议版本、
两者**规范化 JSON** 的 SHA-256、状态、错误、提示，以及下游准入标志。
规范化会忽略 JSON 的键顺序与缩进 —— 但**正文字符串一改，指纹就变**。

PASS 记录的 `eligible_for_theme_generation` 为 `true`；
`scientific_correctness_verified` 与 `production_eligible` **始终为 `false`**；
`content_validation_performed` 表示「做了代码检查」。原草稿仍是 `DRAFT_PENDING_VALIDATION`，
**正式发布不在本步骤**。记录写入失败时，命令**不会**返回可供下游使用的 PASS。

生成阶段允许把草稿停在 `DRAFT_PENDING_VALIDATION`；但**规则失败的草稿不会被放行到下游** ——
不会把失败草稿伪装成已通过校验的产物。

## 规则 v1

### 最低内容与字段

可读正文必须非空，且不能只有标题、HTML 注释或占位符。最低内容按机器字段检查，
**不强制**新的正文标题或排版模板：

| 字段 | 必须提供的内容 |
| --- | --- |
| `research_questions` | 研究问题 |
| `study_objects_and_scales` | 对象与尺度 |
| `data_and_methods` | 数据与方法 |
| `comparison_baselines` | 比较基线，或「不适用」的解释 |
| `findings` | 主要结果及唯一的 `finding_id` |
| `boundaries` | 限制和适用边界 |
| `missing_information` | 缺失或无法取得的信息，或「无适用缺项」的解释 |

七个数组都要有记录，每条 `statement` 都要非空。
`TBD`、`TODO`、`未填写`、模板占位符，或单独一个「未报告 / 不适用」标签**都不算数** —— 必须给出具体说明。
（是否**如实**、是否**充分**，不是字符串检查能证明的。）

字段还要按 schema 检查类型、必需键与枚举；**未知机器字段会被拒绝**。
协议版本必须是**整数 1** —— 布尔值不能冒充整数。尚不支持的协议必须**显式迁移**，
不能改个版本标签就直接混用。

### 原文位置与结果编号

`information_status` 描述的是「这条信息在当前论文及本次可用材料里能不能拿到」，
**不是**科学正确性或独立核查状态。

- 当前论文**转述**别人的研究、又没拿到被引原文时：用 `original_paraphrase` + `reported`，
  定位到当前论文的物理页，并在 statement 里明确注明「未核查被引原文」——
  **不能**写成当前论文自己的实验结果。
- 当前来源未报告 / 确实不适用 / 材料不可获得时：分别用 `not_reported`、`not_applicable`、`unavailable`，
  并配合 `information_boundary` 说明影响。

正文叙述顺序可以调整，但**必须**保持每个 `finding_id` 与对应结果的关联，
完整引用所有编号、且不引用未定义的编号。

- `information_status=reported` 的记录**至少有一个原文位置**，
  每个位置的 `pdf_page` 必须是 1 到来源 PDF 总页数之间的整数。
- `section`、`figure`、`table` 为非空文本或 `null`；
  但**不**凭这些文本声称已核实实际章节、图表存在。
- `not_reported`、`not_applicable`、`unavailable` 必须明确标为 `information_boundary` 并写出具体说明；
  这些记录**可以没有**原文位置，无需捏造页码。
- `finding_id` 采用 `F001` 形式（至少三位数字）且**不得重复**。
  正文须明确引用各结果编号，也不得引用机器字段里不存在的编号；HTML 注释里的编号**不计入**正文引用。
- 正文少于 300 个可见字符**只产生 `CARD_TEXT_SHORT` 提示**，不能单独导致 FAIL；
  反过来说，长正文也**不能抵消**缺失字段、身份冲突等错误。

### 来源与版本

- 输入必须是「单篇单 PDF」的 READY 协议。文库、请求 key、父条目、附件、条目元数据、PDF 哈希与大小
  必须与草稿**完全一致**（包括 JSON 类型）。请求 key 必须指向该父条目或附件。
- PDF 页数必须与阅读记录一致；阅读记录还必须确认**来源身份、文件未变化、回执已被接受**。
  这里只核对记录，**不独立验证模型读懂了原文**。
- 基础提示词、补充提示词、阅读提示词、输出 schema、模板及目录的版本 / 指纹必须与当前配置的资产匹配：
  按输入重建组合提示词并核对指纹。资产改变后旧草稿可能不再满足当前规则 —— 应返回**版本错误**，
  不能悄悄换标签。

## 稳定错误码

每条错误都带 `code`、JSON Pointer 风格的 `path` 和 `message`。
**下一步修正应依据 `code` 和 `path`，不要解析自然语言消息。**

| 错误码 | 含义 |
| --- | --- |
| `CARD_JSON_INVALID` | 输入对象不能规范化为有限 JSON |
| `CARD_INPUT_INVALID` / `CARD_INPUT_VERSION` | 非法 READY 输入，或不支持的输入版本 |
| `CARD_DRAFT_INVALID` / `CARD_DRAFT_VERSION` / `CARD_DRAFT_STATE` | 草稿元数据、版本或状态无效 |
| `CARD_FIELD_MISSING` / `CARD_FIELD_TYPE` / `CARD_FIELD_ENUM` / `CARD_FIELD_UNKNOWN` | 缺键、类型、枚举或额外字段错误 |
| `CARD_CONTENT_MISSING` | 缺少最低内容、空数组或占位陈述 |
| `CARD_INFORMATION_BOUNDARY` | 未报告 / 不适用信息未标为信息边界 |
| `CARD_LOCATION_REQUIRED` / `CARD_LOCATION_INVALID` | 缺少原文位置，或位置 / 页码格式错误 |
| `CARD_FINDING_ID_INVALID` / `CARD_FINDING_REFERENCE` | 结果编号重复 / 无效，或正文引用不一致 |
| `CARD_SOURCE_MISMATCH` / `CARD_READING_RECORD_INVALID` | 来源身份或阅读记录冲突 |
| `CARD_PROVENANCE_MISSING` / `CARD_VERSION_MISMATCH` / `CARD_TEMPLATE_INVALID` | 缺少或不匹配的版本信息，或不支持的模板 |
| `CARD_RULESET_UNAVAILABLE` | 读不到规则所需的配置资产 —— 关闭准入 |
| `CARD_VALIDATION_IO` | JSON 文件损坏、重复键、非有限数值，或记录读写失败 |
| `CARD_VALIDATION_REQUIRED` / `CARD_VALIDATION_FAILED` / `CARD_VALIDATION_STALE` | 下游缺少记录 / 当前校验失败 / 旧记录失效 |
| `CARD_SELECTION_INVALID` | 主题侧未提供完整的显式输入选择 |

通常一次返回多个**可定位**的错误。无法解析的 JSON 或保存失败会返回结构化失败；
由于记录本身取不到或存不下，这类失败**不保证**有 `validation_path`。

## 下游怎么用

下游的 config 同样可以传 `None`（默认资产）、`ValidationAssets` 或已有的 `AppConfig`。
底层读取接口是 `card_validation.load_validated_subject_card(config, draft_path, input_path, validation_path)`；
主题侧的统一入口是 `themes.load_subject_card_sources(config, selected)`：

```python
sources = load_subject_card_sources(config, [{
    "draft_path": ".../draft.json",
    "input_path": ".../paper-input.json",
    "validation_path": ".../validations/<id>/validation.json",
}])
# 所有选择都通过当前规则，才会返回完整 sources；主题生成在此之后。
```

入口会**重新检查**当前草稿与输入，再比较保存记录里的规则版本、代码指纹、输入/草稿指纹与状态。
以下情况**都不能沿用**旧结果：没有校验记录、把失败记录改成 PASS、正文或输入改动、规则变动、记录字段被改动。
一组选择里**任意一项失败，整组都不会返回**给主题调用方。

本步骤只提供主题生成的**输入边界**，不实现主题生成。旧的证据包扫描流程是**独立协议**，
不扫描这套 drafts 目录；也不要据此把旧粗卡追认为「已通过本门禁」。

记录用于**防止旧结果误用和绕过当前代码规则**，它不是密码学签名 —— 有文件写权限的人仍能编辑它，
所以下游重新运行规则是**必要条件**。PDF 在生成后是否又变化，应由后续重新取得的输入体现；
这个离线校验器**不额外读 PDF**。

## 两种后端共用一个入口

Codex 和 Claude 生成相同的主体卡字段。校验器依据 `generation_protocol_version` 选择已注册的阅读协议：

| 后端 | 协议版本 | 阅读方式 |
|---|---|---|
| Codex | `codex-local-pdf-v1` | `local_pdf_path` |
| Claude | `claude-local-pdf-v1` | `claude_pdf_read` |

两者都绑定**来源身份、物理页数和提示词版本**；Claude 额外检查只读 PDF 成功回执的**页范围完整**，
**不伪造** Codex 沙箱预检记录。

也可以直接用独立脚本：

```bash
uv run python scripts/paper_validate.py --draft <路径> --paper-input <路径>
```

参数与平台入口一致，脚本**始终输出 JSON**。校验本身没有模型调用，也不要求安装任何模型客户端。

## 验证

```bash
uv run pytest tests/test_card_validation.py tests/test_card_draft.py
```

通过与失败夹具覆盖：内容、字段、页码、版本、来源、旧 PASS 失效、记录保存失败、下游准入；
另检查「短正文可通过」「长正文不能掩盖缺项」「校验不调用模型且不修改原草稿」。

真实草稿可以直接拿来做离线验证，但**无论 PASS 还是 FAIL，都不能作为科学正确性的背书**。
自动修正与正式发布都不在本步骤。
