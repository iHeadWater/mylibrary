# 单篇论文命令行流程：输入 → 生成 → 校验

三个步骤都由普通终端运行 Python。**只有主体卡生成调用所选模型**；读取 Zotero/PDF、检查身份、校验字段与保存记录由代码执行。无需修改或提交 Codex/Claude 软件、模型本身和个人凭据。

## 0. 别人从零拿到仓库怎么用

### 准备与边界

- 本页命令针对 **Windows PowerShell**，不是 CMD；命令行前面的 `PS C:\...>` 是提示符，不要复制。macOS/Linux 的 Python 路径为 `.venv/bin/python`，本页不据此保证 Windows 相关后端跨平台可用。
- 先安装 Git、Python 3.12–3.14、uv。真实生成还需要 Zotero Desktop、已下载的 PDF、Poppler，以及自己安装并认证的一种 CLI（Codex 或 Claude）。只有离线校验时不需要后面这些。
- GitHub 下载的是代码、提示词、模板和合成示例，不含作者的论文、Zotero 数据库、账号或 `.venv`。仓库若为私有，必须先获得访问权限；文档不能替代授权。
- 当前接口是本地 CLI/JSON，不是公网 HTTP API。不需要开放路由器、防火墙端口或启动 MCP Server；Zotero 只允许本机回环访问。

### 下载到自己选择的位置

新用户可以从任意 PowerShell 起始目录运行下面步骤。`source` 是建议的父目录，目标 `mylibrary` 尚不存在时才执行克隆；已有仓库看后面的更新步骤。

```powershell
$ProjectParent = Join-Path $env:USERPROFILE 'source'
New-Item -ItemType Directory -Path $ProjectParent -Force | Out-Null
Set-Location -LiteralPath $ProjectParent
git clone --branch literature-platform https://github.com/iHeadWater/mylibrary.git mylibrary
if ($LASTEXITCODE -ne 0) { throw '克隆失败：请检查权限、网络或是否已有同名目录' }
Set-Location -LiteralPath (Join-Path $ProjectParent 'mylibrary')
$RepoPath = (Get-Location).Path
```

`$RepoPath` 是**你自己的仓库目录**，不是某个作者的固定 D 盘路径。新开终端后变量不会自动保留；先用 `Set-Location -LiteralPath '你实际保存的仓库目录'` 回到这里，再继续后续步骤。

本 PR #46 未合并时，要验证本次修复，在上述新克隆目录执行：

```powershell
git fetch origin codex/fix-single-paper-claude-reliability
if ($LASTEXITCODE -ne 0) { throw '获取修复分支失败' }
git switch --track origin/codex/fix-single-paper-claude-reliability
if ($LASTEXITCODE -ne 0) { throw '切换失败；已有同名分支请用 git switch 分支名' }
```

合并后直接使用主分支，不需要依赖这个临时修复分支。

### 在当前仓库安装自己的环境

```powershell
uv sync --all-packages --locked
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请先解决上面的错误' }
Get-Location
git branch --show-current
Test-Path .\.venv\Scripts\python.exe
.\.venv\Scripts\python.exe --version
```

`Test-Path` 应输出 `True`。若为 `False`，通常是尚未安装或没有进入正确仓库；不要继续粘贴后面的测试命令。无需激活虚拟环境，也不要复制别人的 `.venv` 或登录文件。安装依赖需要联网。

### 已有仓库如何更新

三步入口已组合进入 `literature-platform` 主分支，不需要从另一分支临时复制脚本。在新检出或无未提交修改的工作目录中更新：

```powershell
git fetch origin
git switch literature-platform
git pull --ff-only origin literature-platform
```

若正在评审修复 PR，请使用该 PR 的分支，不要切回主分支。已有未提交修改时先自行处理，不要强制切换或覆盖。确认当前检出同时包含 `scripts/paper_input.py`、`scripts/paper_validate.py` 和 `configs/ai.toml`；不要混用不同分支的脚本和提示词。更新代码后重新运行 `uv sync --all-packages --locked`。

### 先做离线校验，不需要自己的文献或模型账号

```powershell
.\.venv\Scripts\python.exe scripts/paper_validate.py --draft hydro-platform/automation/examples/subject-card-validation/draft.json --paper-input hydro-platform/automation/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
$LASTEXITCODE
```

修复版本应返回 `status: PASS`、退出码 `0`。合成示例正文较短，`CARD_TEXT_SHORT` 是提示，不是失败。这只证明代码入口和合成契约可用，不证明真实论文已经生成。查看参数也不调用模型：

```powershell
.\.venv\Scripts\python.exe scripts/paper_input.py --help
.\.venv\Scripts\python.exe -m hydro_platform evidence-generate --help
.\.venv\Scripts\python.exe scripts/paper_validate.py --help
```

### PDF 工具准备（Windows）

Codex 本地读取需要 Poppler 工具。Windows 上已验证的 Claude CLI 2.1.280 原生 PDF Read 也依赖 `pdftoppm`；只安装 pypdf 或只有 `pdftotext` 不足以完成页面图像读取。已有 Poppler 时无需重复安装，先检查：

```powershell
Get-Command pdftoppm, pdfinfo, pdftotext -ErrorAction Stop
pdftoppm -v
```

缺少工具时，可安装用户级 Poppler：

```powershell
winget install --id oschwartz10612.Poppler --exact --scope user --accept-package-agreements --accept-source-agreements
```

安装后新开 PowerShell，再回到仓库目录重跑检查。若安装器已更新用户 PATH，但需要继续使用当前终端，可刷新当前进程的 PATH：

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
Get-Command pdftoppm, pdfinfo, pdftotext -ErrorAction Stop
```

刷新会替换当前终端临时追加的 PATH，必要时重新追加自己的工具目录。项目内安装方式见[原生部署](native-deployment.md)；其工具目录也必须加入 Claude 进程可继承的 PATH。`ai-config` 能显示配置，但不会替代 PDF 渲染工具检查。

## 1. 本机 Zotero 输入：不调用模型

打开 Zotero，启用「允许此计算机上的其他应用程序与 Zotero 通信」，确保 PDF 已下载。

别人没有作者使用的论文时，先通过自己的 Zotero 导入想读的论文并附上可合法取得的 PDF。**条目 Key 属于各自文库，不能照抄作者的 Key。** 下面先按自己论文的题名/DOI 搜索，再选择结果中的父条目 Key；搜索只查本地库，不自动下载或导入论文。

```powershell
New-Item -ItemType Directory -Path outputs -Force | Out-Null
.\.venv\Scripts\python.exe scripts/paper_input.py --show-config
$PaperQuery = Read-Host '输入你已导入 Zotero 的论文题名或 DOI'
.\.venv\Scripts\python.exe scripts/paper_input.py --user-library --query $PaperQuery
$ItemKey = Read-Host '输入你确认的父条目 Key'
.\.venv\Scripts\python.exe scripts/paper_input.py --user-library --item-key $ItemKey --output outputs/paper-input.json
if ($LASTEXITCODE -ne 0) { throw '输入未就绪，请查看结果，不要继续调用模型' }
$PaperInput = Get-Content -LiteralPath outputs/paper-input.json -Raw -Encoding UTF8 | ConvertFrom-Json
if ($PaperInput.status -ne 'READY') { throw '只有单篇 READY 记录才能进入生成' }
```

此脚本只用标准库，无需安装模型客户端。用候选中确认的 Key 替换示例；群组库将 `--user-library` 改为 `--group-id 群组数字ID`。输入默认值在 `configs/paper-input.toml`，可用参数或 `HYDRO_PLATFORM_ZOTERO_*` 环境变量覆盖，不读模型总配置。PDF 路径由 Zotero 返回。只有单篇 READY 记录进入下一步。

群组用户必须已加入相应群组，且群组条目和 PDF 在本机 Zotero 可用。找不到 PDF、出现多篇 PDF 等情况应根据返回原因处理，不自行挑一个附件冒充 READY。

## 2. 主体卡生成：由命令驱动所选模型

选择 Codex 或 Claude，安装所选 CLI 并完成自己的登录或 API 环境认证。**不用同时安装两种 CLI**。

### 认证与公开配置分开

`configs/ai.toml` 只选择后端、模型、程序位置和超时，不保存密钥；本地单篇输入也不要求 Zotero Web API key。DeepSeek 的图谱 API 配置不是本入口的认证方式。

Claude 隔离进程不会加载用户 settings 的 `env`。如果你的认证已经配置在那里、但尚未导出到当前终端，可明确选择下面的方法：仅把自己现有的 `ANTHROPIC_*` 配置传给当前进程，不打印值、不写入项目文件。

```powershell
$ClaudeSettingsPath = Join-Path $env:USERPROFILE '.claude\settings.json'
$ClaudeSettings = Get-Content -LiteralPath $ClaudeSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($Entry in $ClaudeSettings.env.PSObject.Properties) {
    if ($Entry.Name -like 'ANTHROPIC_*' -and $Entry.Value -is [string]) {
        [Environment]::SetEnvironmentVariable($Entry.Name, $Entry.Value, 'Process')
    }
}
```

仅适用于你已经信任并配置好的自己的文件；没有该文件、使用正常 CLI 账号登录或认证变量已经在进程环境中时跳过。不要复制作者的设置文件，不要打印或把凭据贴进 PR。`ai-config` 只说明配置解析成功，不证明账号可用或模型调用成功。

### 生成并自动接住返回的路径

下面使用自己的所选 CLI 默认模型；换成 Codex 只需把 `$Provider` 改为 `codex`。这一步会使用模型额度。进度写到 stderr，stdout 是 JSON；PowerShell 5.1 显式使用 UTF-8 接收，避免中文路径乱码。

```powershell
$Provider = 'claude'
$OutputRoot = Join-Path (Get-Location).Path 'outputs'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
.\.venv\Scripts\python.exe -m hydro_platform ai-config --ai-provider $Provider --output-root $OutputRoot --json
$GenerationJson = & .\.venv\Scripts\python.exe -m hydro_platform evidence-generate --paper-input outputs/paper-input.json --ai-provider $Provider --output-root $OutputRoot --json
if ($LASTEXITCODE -ne 0) {
    $GenerationJson
    throw '生成失败，请处理诊断原因；不要自动重试或跳过校验'
}
$Generation = ($GenerationJson -join "`n") | ConvertFrom-Json
if (-not $Generation.ok -or -not $Generation.draft_path) { throw '未得到可校验的草稿路径' }
$Generation | Select-Object status, draft_path, card_path
```

两条路径都应先完成上面的 PDF 工具检查。Python/pypdf 已由项目安装；Claude 还需支持隔离模式和结构化输出，本机验证版本为 2.1.280。生成失败时区分程序确定的原因与“模型自报（未经独立验证）”说明；不要通过跳过页覆盖或放宽校验来制造 PASS。

`configs/ai.toml` 是公开默认值。后端、模型、程序位置、超时和 PDF 工具均可覆盖；默认模型留空，使用所选 CLI 默认值。优先级：命令行 → 进程环境变量 → `.env` → TOML → 内置默认值。常用变量为 `HYDRO_PLATFORM_AI_PROVIDER` / `_MODEL` / `_EXECUTABLE` / `_TIMEOUT_SECONDS`（均以 `HYDRO_PLATFORM_AI` 开头）。凭据交由所选 CLI 管理，不放入该 TOML。[详细配置](subject-card-draft.md)。

产物根调用 #27 的同一解析器：`--output-root` → `HYDROLITAGENT_LITERATURE_ROOT`（支持 `.env`）→ `configs/paths.toml` → 仓库 `outputs/`。用 `ai-config --json` 查实际落点；不写死作者路径、不清理外部云盘目录。

输出里的 `draft_path` 是下一步输入。结果是待校验草稿，不会因模型完成而自动标为正确或正式发布。

### 别人可以改哪些接口参数

| 自己的选择 | 公开入口 | 不需要做什么 |
| --- | --- | --- |
| 个人库或群组库 | 输入脚本的 `--user-library` / `--group-id` | 不改作者代码，不填写假群组号 |
| 论文 | `--query` 搜索、`--item-key` 确认 | 不硬编码作者的条目 Key 或 PDF 路径 |
| Claude 或 Codex | `--ai-provider` | 不要求两种都安装 |
| 模型 | `--ai-model` 或 TOML 的 `model` | 不改源码；模型必须是自己账号实际可用的 |
| CLI 不在 PATH | `--ai-executable` | 不写死别人的可执行文件位置 |
| 超时 | `--ai-timeout`（1–7200 秒） | 不无限等待、不靠循环重试 |
| 自己的输出目录 | `--output-root` 或 `HYDROLITAGENT_LITERATURE_ROOT` | 不使用作者 D 盘路径，不清理其他人的目录 |
| 独立配置文件 | `--ai-config` | 不把密钥加入公开 TOML |
| 校验报告目录 | `--report-dir` | 不覆盖或手改原始草稿 |

## 3. 草稿校验：不运行模型

```powershell
.\.venv\Scripts\python.exe scripts/paper_validate.py --paper-input outputs/paper-input.json --draft $Generation.draft_path
$LASTEXITCODE
```

不需要模型客户端登录、Zotero 在线或原 PDF 可访问。校验代码检查字段、身份、引用编号、物理页范围及版本指纹；识别 Codex 和 Claude 的不同读取记录，不重新调用模型。报告追加到草稿旁 `validations/<ID>/validation.json`。用 `--report-dir` 或 `HYDRO_PLATFORM_VALIDATION_REPORT_DIR` 改位置。

独立校验脚本只依赖项目源码（可从完整环境运行），不需要 AI SDK 或 CLI。成功退出码 0，校验/保存失败 3。PASS 表示已实现的确定性规则通过，不证明科学结论正确。错误应由后续修正工作处理，不能为了让示例通过而伪造内容。

## 无私人配置的校验示例

```powershell
.\.venv\Scripts\python.exe scripts/paper_validate.py --draft hydro-platform/automation/examples/subject-card-validation/draft.json --paper-input hydro-platform/automation/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
```

这是合成数据，用来演示校验入口；不包含真实论文结论或本机凭据。

## 验证代码与排错

新开终端请先进入自己的仓库目录，再运行：

```powershell
.\.venv\Scripts\python.exe -m pytest hydro-platform/automation/tests/test_claude_cli.py hydro-platform/automation/tests/test_card_validation.py
$LASTEXITCODE
.\.venv\Scripts\python.exe -m pytest hydro-platform/automation/tests
$LASTEXITCODE
.\.venv\Scripts\python.exe -m mkdocs build --strict
$LASTEXITCODE
```

这些测试不调用真实模型。`$LASTEXITCODE` 紧接每条命令读取，`0` 表示该命令成功；以 pytest 实际打印的统计为准，不要把注释 `# 150 passed` 当成测试输出。全仓库测试还包含依赖本机 Zotero 在线及特定样本的集成测试，可能因本地库不同而失败；不能把它与平台单元测试混为一谈。

| 现象 | 先检查什么 |
| --- | --- |
| 无法识别 `.\.venv\Scripts\python.exe` | `Get-Location` 是否为自己的仓库根；`Test-Path` 是否 True；是否完成 uv 安装 |
| `Not a git repository` | 当前目录不是仓库，不是代码测试结论 |
| 找不到 `hydro_platform` | 是否使用本仓库 Python 并安装 `uv sync --all-packages --locked` |
| Zotero 不可连接或本地请求被代理为 502 | Zotero 是否启动、允许通信；必要时为本机地址配置进程级 `NO_PROXY=127.0.0.1,localhost,::1` |
| 搜不到论文或无 PDF | 自己的文库是否有该条目及本地附件；代码不会自动抓取共享库到个人库 |
| Claude 立即认证失败 | 隔离进程是否继承自己的认证环境；`ai-config` 不是认证检查 |
| 缺 `pdftoppm` 或回执不完整 | Poppler 是否在当前进程 PATH；不把仅取得文字视作完整读页 |
| 校验版本不匹配 | 草稿与提示词/模板是否来自同一版本；不要改哈希凑 PASS |

输入脚本 `ok=true` 不一定意味着 READY，例如候选搜索可能成功但仍需选择；生成成功也只意味着待校验草稿。校验 PASS 仅代表已实现的确定性规则通过，不等于科研正确或正式发布。其他程序接入时应解析 stdout JSON 的 `ok`、`status`、路径与错误码，不解析进度文案。
