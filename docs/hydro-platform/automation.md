# 自动化边界

`hydro-platform` 把可确定的 PDF 门禁、来源身份、字段校验、重复检查和原子保存交给 Python，把主体卡提炼和候选主题综合交给所选 CLI（Codex / Claude）。自动化产出建议和候选知识，不替代研究者确认正式主题、科学结论或 research idea。

单篇输入链路见[主体卡草稿](subject-card-draft.md)：接收 `paper-input` 的 READY 记录，一次模型调用输出详细正文和机器字段，按 #27 的产物根保存待校验草稿。

## 自动化清单

| 能力 | 触发方式 | 可读输入 | 会产生什么 | 人工门 |
| --- | --- | --- | --- | --- |
| 单篇论文输入 | `paper-input` | 自己的 Zotero 文库、条目、附件和本地 PDF | READY 输入记录（身份、路径、PDF 指纹） | 不自动选择候选；缺 PDF 或多个 PDF 时停止并说明原因 |
| 单 Agent 主体卡草稿 | `evidence-generate` | READY 记录、当前 PDF、九类模板、制卡提示词 | `draft.json`、`card.md` 和草稿记录 | 可自动保存；草稿始终为待校验状态 |
| 主体卡代码校验 | `evidence-validate` | 草稿、对应 READY 记录和当前资产 | `validation.json`（PASS / FAIL） | 未通过不能进入主题流程 |
| 统一候选主题池 | `themes-run` | 全池文献卡、候选主题和适用精读 | CREATE / UPDATE / MERGE / SPLIT 候选及版本记录 | 不得自动晋级为正式主题 |

## 可调用的外部表面

- Zotero Desktop Local API：单篇输入只读用户自己的文库及本地附件，不修改 Zotero 数据库和同步偏好。`paper-input --user-library` 与 `paper-input --demo` 是显式的本机入口。
- Codex / Claude CLI：使用已登录的账号处理 PDF 和文本；模型、推理强度、超时和代理来自配置。
- 本地文件系统：只写入经配置解析和边界检查后的目录，对人工改动和来源冲突保留现场。
- Git 不属于日常自动化表面；程序不自动 commit 或 push。

## 强制规则

- 没有可读原始 PDF 时，不生成主体卡草稿。
- 已有非占位卡片不因模型或模板更新而被覆盖。
- 候选主题可自动演化，正式主题必须经人工决定。
- Python 核对来源身份、模板路由、非空输出、Schema 传输、重复和安全写入；它不证明正文科学正确。
- PDF、密钥、`.runtime` 和科研产物均不进入 Git。
- 可重试故障按次数、冷却和超时上限处理；认证、配置、来源或写入冲突不盲目重试。

## 操作与控制

命令一律从仓库根执行：

| 命令 | 用途 |
| --- | --- |
| `uv run hydrolitagent cards paper-input --user-library --query "关键词" --json` | 在自己的文库中搜索候选；不会自动选择第一条 |
| `uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --output paper-input.json` | 检查单篇父条目、唯一 PDF、本地文件和全文索引状态 |
| `uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider codex --json` | 读取该篇 PDF 并生成待校验主体卡草稿 |
| `uv run hydrolitagent cards evidence-validate --draft <草稿目录>/draft.json --paper-input paper-input.json --json` | 离线校验草稿，PASS 才可进入主题流程 |
| `uv run hydrolitagent cards themes-run --json` | 以若干通过校验的文献卡生成候选主题并回填修订 |
| `uv run hydrolitagent cards ai-config --json` | 只读查看模型选择与精读产物根 |

重复传入多个`--item-key`时，命令会逐篇处理。`MULTIPLE_PDFS`、`PDF_MISSING`等单篇问题不会中断后续条目；最终结果使用`COMPLETED_WITH_PROBLEMS`并在`problems`中汇总题名、key、原因和 PDF 候选。

运行单篇流程前必须在仓库根执行`uv sync --all-packages`（或 `--locked`），启动 Zotero Desktop，并开启“Allow other applications to communicate with Zotero”。真实生成还需要已安装并登录的一种 CLI（Codex 或 Claude）和 Poppler 的 `pdfinfo` / `pdftoppm` / `pdftotext`。

`--demo`在个人库找不到公开演示论文时只返回文章页、PDF 链接和目标集合提示，不会代替用户点击 Zotero Connector；人工抓取完成后需重新执行。

单篇输入的独立命令、默认配置及环境变量覆盖见[单篇论文输入](paper-input.md)；生成与校验的完整命令流程见[单篇论文命令行流程](single-paper-quickstart.md)。
