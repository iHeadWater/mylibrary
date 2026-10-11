# 从单篇 PDF 生成主体卡草稿

拿到一篇论文的 **READY 记录**后，用**一次模型调用**生成主体卡草稿。

分工：**命令行负责组织工作，模型负责阅读论文并生成内容**。输入检查与结构校验仍是普通程序，不跑模型。
本步骤不改动 Codex / Claude 本身，也不提交账号、API key 或本机登录文件。

## 运行

前置：Python 3.12–3.14、uv、一种**已登录**的 CLI（Codex 或 Claude）。
按 API 用法认证时，凭据放**本机环境变量**，不要写进仓库配置。在**仓库根**执行：

```bash
uv sync --all-packages --locked
uv run hydrolitagent cards ai-config --json     # 先看当前模型选择与产物根

uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider codex --json
# 或用 Claude —— 无需同时安装 Codex
uv run hydrolitagent cards evidence-generate --paper-input paper-input.json --ai-provider claude --json
```

- `paper-input.json` 是上一页确认单篇后返回的 READY 记录。**不能**传搜索候选列表，
  也**不能**传批处理的外层结果 —— 要取其中单篇的记录。
- 也支持 `--paper-input -` 从 stdin 读取。
- 不需要配置群组或计划任务，也不需要复制别人的 `config.local.json`。

## 两种后端各自的额外依赖

| 后端 | 需要什么 |
|---|---|
| **Codex** | 沿用本地 PDF 阅读适配器：`pypdf`（项目安装已含）+ Poppler 的 `pdfinfo` / `pdftoppm`。可用项目安装或 PATH，也可显式覆盖工具路径。 |
| **Claude** | Windows 上验证过 CLI 2.1.280 的原生 PDF Read，依赖 PATH 里的 `pdftoppm` 渲染页面。缺它时**不能**把「只拿到文本或文件信息」当成完整阅读。CLI 需支持 `--safe-mode`、`--restricted`、`--no-session-persistence` 与结构化输出；旧版本请升级，**不会**退回不受限模式。 |

- `pdf*_executable` 一类配置只管 **Codex** 的读取适配器，**不会**给 Claude 的原生 Read 设置工具位置。
- 安装与 PATH 检查见[前提与配置](../../getting-started/installation.md)。

## 模型选择与覆盖

`configs/ai.toml` 提交的默认是 `provider=codex`；模型名**留空**表示用所选 CLI 自己的默认值。
优先级：**命令行 → 进程环境变量 → 仓库 `.env` → TOML → 内置默认值**。配置里**不接收密钥字段**。

| 选择 | 命令行 | 环境变量 |
|---|---|---|
| 后端 | `--ai-provider codex` 或 `claude` | `HYDROLITAGENT_CARDS_AI_PROVIDER` |
| 模型 | `--ai-model <模型名>` | `HYDROLITAGENT_CARDS_AI_MODEL` |
| CLI 程序 | `--ai-executable <本机路径>` | `HYDROLITAGENT_CARDS_AI_EXECUTABLE` |
| 超时 | `--ai-timeout <秒>` | `HYDROLITAGENT_CARDS_AI_TIMEOUT_SECONDS` |
| 配置文件 | `--ai-config <本机 TOML>` | `HYDROLITAGENT_CARDS_AI_CONFIG` |

`reasoning_effort` 与各 `*_executable`（`python` / `pdfinfo` / `pdftotext` / `pdftoppm`）也可在 TOML
或对应的 `HYDROLITAGENT_CARDS_AI_` 大写环境变量里设置。

- 模型是否可用取决于**你的**服务，程序不假设所有账号都有同一个模型。
- Windows 上 npm 安装会优先识别同目录的原生 exe，避免长参数经过 cmd 包装器失败；仍可显式指定路径。

Claude 以**隔离的只读模式**运行，不加载项目插件或命令。若认证只写在 Claude 用户 settings 的 `env` 里，
请在启动本命令的终端里导出对应环境变量 —— 程序不会复制或打印那个文件。普通 CLI 账号登录由 CLI 自己管理。

**终端 Claude Code + CC Switch + DeepSeek**：仍然选 `--ai-provider claude` —— 这里选的是**命令行适配器**，
不是模型厂家，所以不要写成 `--ai-provider deepseek`。CC Switch 负责给 Claude 配服务地址、认证与模型映射，
仓库启动的 Claude 子进程再调用该服务。**「普通聊天能用」不等于当前上游服务满足 PDF 页面读取与
结构化输出要求** —— 以真实的生成与校验结果为准。

## 产物写到哪

产物根用同一套解析：`--output-root` → 环境变量 `HYDROLITAGENT_LITERATURE_ROOT`（进程值优先于 `.env`）
→ `configs/paths.toml` → 仓库 `outputs/`。`ai-config --json` 会显示实际落点。
相对产物根从**仓库根**解析；指向外部目录时只追加、不清理。

```text
<产物根>/zotero/<user|group>-<文库ID>-<父条目Key>/drafts/<版本ID>/
├── card.md
└── draft.json
```

每次生成都**新建一个草稿版本**。

`--config` 只用于显式复用旧的 PDF / 模板路径；新使用直接用上面那份小配置即可 ——
本入口**不会**自动读平台总配置（`HYDROLITAGENT_CARDS_CONFIG`）。

## 两种后端共用什么

模型选择进入同一个 `build_card_generator_adapter`，两种后端都经过 `SingleAgentCardGeneratorAdapter`，
共用模板、提示词、机器字段与「待校验」的保存逻辑 —— 没有第二套主体卡流程。

- **Codex** 保留既有的沙箱 PDF 路径读取协议。
- **Claude** 只开放原生 Read：回执必须覆盖**所有物理页**；无页码探测**不计入**覆盖；
  Read 请求编号必须非空且唯一；失败或格式异常的回执不算成功；命令、写文件、MCP、联网搜索一律禁止。
- 两者都检查 PDF 身份 / 哈希未变、页数与阅读声明一致。
  **阅读工具的活动不等于科研理解已被独立验证。**
- 草稿始终是 `DRAFT_PENDING_VALIDATION` —— 不自称已通过内容校验、科学正确或正式发布。
  七类字段由模型填写，缺失或错误交给下一步的程序校验报告。
- 登录失败、缺工具、超时、读取不完整或输出不合协议 → 返回**结构化失败**；
  不偷偷换模型、不自动重试。

### 失败诊断的边界

保留 `CLAUDE_PDF_GENERATION_FAILED` 等既有错误码。已知协议错误给出具体原因；
超时、文件访问、PDF 解析或未知异常改用受控提示 —— **不回显**完整命令或第三方异常原文，
也不落盘原始 CLI 输出。读取失败可附上模型自报的状态与说明，但必须明确标为「**未经独立验证**」，
不能当成程序已确认的根因。

模型说明里若出现命令参数、代码块或异常栈等**日志形态**，省略该说明并给固定排查提示；
其余说明会去掉终端转义与控制字符、过滤已知凭据形态，并限制到 600 字符；诊断细节上限 1200 字符。
过滤只是尽力而为，**不保证**任意自由文本都能公开 —— 分享错误报告前仍请自己检查本机路径与私人信息。

## 验证

```bash
uv run pytest tests/test_card_draft.py tests/test_ai_config.py tests/test_claude_cli.py
```

覆盖配置覆盖、两种后端的同一草稿契约、页数与身份绑定、Claude 只读工具回执的负向用例。
真实论文的结果取决于模型账号与服务状态 —— **不把只模拟接口的测试称为真实模型验证**。
