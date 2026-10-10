# 从单篇 PDF 生成主体卡草稿

#30 复用现有单 Agent、模板、输出 schema 与结果处理代码。**命令行负责组织工作，模型负责理解论文并生成内容**。#40 的 Zotero/PDF 输入检查与 #44 的结构校验仍是普通程序，不需要运行模型。本 PR 不修改 Codex/Claude 软件或模型，不提交账号、API key 或本机登录文件。

## 从普通终端运行

先安装 Python 3.12–3.14、uv 和你选用的一种 CLI（Codex 或 Claude），并用自己的账号完成该 CLI 的登录。按现有 API 用法认证时，将凭据设置在本机环境变量中，不写到本仓库配置。仓库根运行：

```powershell
uv sync --all-packages --locked
.\.venv\Scripts\python.exe -m hydrolitagent.cards ai-config --json
.\.venv\Scripts\python.exe -m hydrolitagent.cards evidence-generate --paper-input paper-input.json --ai-provider codex --json
# 或使用 Claude；无需同时安装 Codex
.\.venv\Scripts\python.exe -m hydrolitagent.cards evidence-generate --paper-input paper-input.json --ai-provider claude --json
```

macOS/Linux 使用 `.venv/bin/python`。`paper-input.json` 是 #40 确认单篇后返回的 READY 记录，不能传搜索候选列表或批处理外层结果。支持 `--paper-input -` 从 stdin 读取。无需配置群组、计划任务或复制作者的 `config.local.json`。

Codex 沿用现有本地 PDF 阅读适配器，需要 pypdf（项目安装已含）及 Poppler 的 `pdfinfo`、`pdftoppm` 等工具；使用项目安装或自己的 PATH，也可显式覆盖工具路径。Windows 上验证的 Claude CLI 2.1.280 原生 PDF Read 同样依赖 PATH 中的 `pdftoppm` 渲染页面；缺失时不能把仅取得文本或文件信息当成完整阅读。Claude CLI 需支持 `--safe-mode`、`--restricted`、`--no-session-persistence` 和结构化输出；旧版本不支持时请升级，不会退回不受限模式。安装及 PATH 检查见[首次配置](single-paper-quickstart.md)。`pdf*_executable` 配置用于 Codex 读取适配器，不会替 Claude 原生 Read 设置工具位置。

## 与 #27 一致的公开默认值和覆盖

`configs/ai.toml` 提交默认 provider=codex；模型名为空表示使用所选 CLI 的默认值。配置优先级：**命令行 → 进程环境变量 → 仓库 `.env` → TOML → 内置默认值**。配置中不接收密钥字段。

| 选择 | 命令行 | 环境变量 |
|---|---|---|
| 后端 | `--ai-provider codex或claude` | `HYDRO_PLATFORM_AI_PROVIDER` |
| 模型 | `--ai-model 模型名` | `HYDRO_PLATFORM_AI_MODEL` |
| CLI 程序 | `--ai-executable 本机路径` | `HYDRO_PLATFORM_AI_EXECUTABLE` |
| 超时 | `--ai-timeout 秒数` | `HYDRO_PLATFORM_AI_TIMEOUT_SECONDS` |
| 配置文件 | `--ai-config 本机TOML` | `HYDRO_PLATFORM_AI_CONFIG` |

`reasoning_effort`、`python_executable`、`pdfinfo_executable`、`pdftotext_executable`、`pdftoppm_executable` 也可在 TOML 或对应 `HYDRO_PLATFORM_AI_` 大写环境变量中设置。模型可用性由使用者的服务决定，程序不假设所有账号拥有同一模型。Windows npm 安装会优先识别同一安装目录里的原生 exe，避免长参数经过 cmd 包装器失败；仍可显式指定路径。

Claude 运行采用隔离的只读模式，不加载项目插件或命令。若自己的认证仅写在 Claude 用户 settings 的 `env` 中，请在启动本命令的终端导出相应认证环境变量；程序不会复制或打印该文件。普通 CLI 账号登录由 CLI 自己管理。

**终端 Claude Code + CC Switch + DeepSeek：**也属于 `--ai-provider claude`，因为这里选择的是命令行适配器，而不是实际模型厂家；不要写成 `--ai-provider deepseek`。CC Switch 为 Claude 配置服务地址、认证与模型映射，仓库启动的 Claude 子进程再调用该服务。隔离进程所需配置导入、直连/代理区别、逐步命令与结果解读见[单篇完整教程](single-paper-quickstart.md)。普通聊天可用不保证当前上游服务满足 PDF 页面读取及结构化输出要求；以真实生成与校验结果为准。

产物根直接调用 #27 的同一解析器：`--output-root` → `HYDROLITAGENT_LITERATURE_ROOT`（进程优先于 `.env`）→ `configs/paths.toml` → 仓库 `outputs/`。`ai-config --json` 会显示实际落点。相对产物根从仓库根解析；外部目录遵守 #27 的显式选择规则，只追加不清理。

```text
<产物根>/zotero/<user|group>-<文库ID>-<父条目Key>/drafts/<版本ID>/
├── card.md
└── draft.json
```

每次新建草稿版本。`--config` 仅用于显式复用旧平台的 PDF/模板路径；新用户使用上述小配置即可。新入口不会自动读取 `HYDRO_PLATFORM_CONFIG`。

## 复用什么、检查什么

模型选择进入现有 `build_card_generator_adapter`，两种后端都经过 `SingleAgentCardGeneratorAdapter`，共用模板、提示词、机器字段与待校验保存逻辑。没有另造第二套主体卡业务流程。

- Codex 保留既有沙箱 PDF 路径读取协议。
- Claude 只开放原生 Read，检查成功回执覆盖所有物理页；无页码探测不计入覆盖，所有 Read 请求编号必须非空且唯一。失败或错误标志格式异常的回执不能计为成功；禁止命令、写文件、MCP 和联网搜索工具。
- 两者均检查 PDF 身份/哈希未变、页数和阅读声明一致。阅读工具活动不等于科研理解已被独立验证。
- 草稿始终 `DRAFT_PENDING_VALIDATION`，不自称已通过内容校验、科学正确或正式发布。七类字段由模型填充，缺失或错误交给 #31 程序报告。
- 登录失败、缺工具、超时、读取不完整或输出不合协议返回结构化失败；不偷偷换模型、不自动重试。

### 失败诊断边界

保留 `CLAUDE_PDF_GENERATION_FAILED` 等既有错误码。已知协议错误给出具体原因；超时、文件访问、PDF 解析或未知异常使用受控提示，不回显完整命令或任意第三方异常原文，也不落盘原始 CLI stdout/stderr。读取失败可附加模型自报的状态和说明，明确标为“未经独立验证”，不能把它当成程序已确认的根因。

模型说明中识别到命令参数、代码块或异常栈等日志形态时，省略该说明并给出固定排查提示；其余说明去除终端转义和控制字符，过滤已知凭据形态，限制为 600 字符。诊断细节上限 1200 字符。过滤是尽力防护，不保证任意自由文本均可公开。分享错误报告前仍应检查本机路径与私人信息。

## 验证

```powershell
uv run pytest tests/test_card_draft.py tests/test_ai_config.py tests/test_claude_cli.py
```

包含配置覆盖、两种后端的同一草稿契约、页数/身份绑定和 Claude 只读工具回执负向测试。真实论文测试结果与模型账号、服务状态有关；不把仅模拟接口的测试称为真实模型验证。
