# 单篇论文命令行流程：输入 → 生成 → 校验

三个步骤都由普通终端运行 Python。**只有主体卡生成调用所选模型**；读取 Zotero/PDF、检查身份、校验字段与保存记录由代码执行。无需修改或提交 Codex/Claude 软件、模型本身和个人凭据。

本页主例采用：**在 Windows PowerShell 终端运行 Claude Code，由 CC Switch 配置它连接 DeepSeek**。这里的 Claude 指命令行软件，不表示实际使用 Anthropic 的 Claude 模型；DeepSeek 才是这套配置中提供推理能力的服务。

```text
CC Switch：管理 Claude Code 的服务地址、认证与模型映射
                         ↓ 配置传入本次终端进程
PowerShell → 仓库 Python 生成命令 → Claude Code CLI → DeepSeek
                ↑ 本地 PDF                         ↓ 生成内容
Zotero → paper-input.json → draft.json + card.md → Python 校验 → validation.json
```

直连时 CC Switch 负责写配置，不必承载每次请求；启用本地代理接管时，Claude Code 的请求先经过 CC Switch 再到上游服务。

| 阶段 | 你给什么 | 程序做什么 | 本阶段完成标志 |
| --- | --- | --- | --- |
| 输入 | 自己 Zotero 中的论文 Key | 确认文献身份，定位唯一的本地 PDF，记录指纹 | `paper-input.json` 中 `ok=true` 且 `status=READY` |
| 生成 | 上一步的 JSON、Claude/DeepSeek 配置 | 调用 Claude Code 读取 PDF，让模型生成草稿 | 返回 `DRAFT_PENDING_VALIDATION` 和草稿路径 |
| 校验 | 同一份输入 JSON 与对应 `draft.json` | 不调用模型，检查字段、来源、页码、版本等规则 | `validation.json` 中 `status=PASS`，或列出 FAIL 原因 |

**命令粘贴位置：**下面第 0–4 节的 `git`、`uv`、Python 和 `$变量` 命令，都粘贴在显示 `PS C:\...>` 的 PowerShell 提示符后，不是把它们当成 Claude 对话中的自然语言指令。也可以让终端里的 Claude 代执行，区别和限制见第 5 节。生成命令会自行启动一个 Claude Code 子进程，无需先手动开启 Claude 对话，也不会接着已有对话生成。

第一次使用按第 0 节完成安装，再依次执行第 1、2、3 节。日常换一篇论文可看第 4 节。代码块里的 `#` 是解释，不是运行结果；每执行完一块先检查结果，不要一次性粘贴整页。

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
.\.venv\Scripts\python.exe scripts/paper_validate.py --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
$LASTEXITCODE
```

修复版本应返回 `status: PASS`、退出码 `0`。合成示例正文较短，`CARD_TEXT_SHORT` 是提示，不是失败。这只证明代码入口和合成契约可用，不证明真实论文已经生成。查看参数也不调用模型：

```powershell
.\.venv\Scripts\python.exe scripts/paper_input.py --help
.\.venv\Scripts\python.exe -m hydrolitagent.cards evidence-generate --help
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

刷新会替换当前终端临时追加的 PATH，必要时重新追加自己的工具目录。Poppler 的工具目录也必须加入 Claude 进程可继承的 PATH。`ai-config` 能显示配置，但不会替代 PDF 渲染工具检查。

## 1. 本机 Zotero 输入：不调用模型

### 1.1 准备自己的论文

打开 Zotero，在设置中启用「允许此计算机上的其他应用程序与 Zotero 通信」。把论文导入自己的文库，并在 Zotero 中双击 PDF 确认可以打开；只有书目信息、网页链接或尚未下载的附件不够。

别人没有作者使用的论文时，先通过自己的 Zotero 导入想读的论文并附上可合法取得的 PDF。**条目 Key 属于各自文库，不能照抄作者的 Key。** 下面先按自己论文的题名/DOI 搜索，再选择结果中的父条目 Key；搜索只查本地库，不自动下载或导入论文。

### 1.2 建立本次运行目录并检查配置

先回到自己的仓库根目录。每篇、每次运行使用单独目录，避免后一篇的输入覆盖前一篇后无法对照校验。以下变量供后续代码块继续使用，期间不要更换终端。

```powershell
# 检查当前位置；应该能看到 scripts、configs、hydrolitagent 等目录
Get-Location
if (-not (Test-Path .\scripts\paper_input.py)) { throw '请先进入 mylibrary 仓库根目录' }
if (-not (Test-Path .\.venv\Scripts\python.exe)) { throw '请先运行 uv sync --all-packages --locked' }

$RepoPath = (Get-Location).Path
$Python = Join-Path $RepoPath '.venv\Scripts\python.exe'
$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$RunDir = Join-Path $RepoPath (Join-Path 'outputs\single-paper' $RunId)
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
$InputPath = Join-Path $RunDir 'paper-input.json'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'

# 只显示输入配置，不调用模型，也不是 Zotero 连通性测试
& $Python scripts/paper_input.py --show-config
if ($LASTEXITCODE -ne 0) { throw '输入配置无效，请先处理上面的错误' }
```

`$Python` 是本仓库的 Python；`$RunDir` 是此次产物目录；`$InputPath` 是要保存的输入文件。这里的 `&` 是 PowerShell 调用运算符，能正确运行包含空格的程序路径。配置显示的默认群组不影响下一步显式指定的 `--user-library`。

### 1.3 搜索论文，确认父条目 Key

```powershell
$PaperQuery = Read-Host '输入你已导入 Zotero 的论文题名或 DOI'
& $Python scripts/paper_input.py --user-library --query $PaperQuery
if ($LASTEXITCODE -ne 0) { throw '搜索失败，请检查 Zotero 和查询条件' }
```

预期得到 `status: SELECTION_REQUIRED` 与 `candidates` 列表，这是正常的“等待选择”，不是生成失败。对照候选的题名、作者、年份和 DOI，记下正确论文的 `item_key`（8 位字母或数字）。候选为空就调整关键词或先在 Zotero 导入论文；结果较多可加 `--limit 20`，不要盲选第一个。

### 1.4 生成 READY 输入文件

```powershell
$ItemKey = Read-Host '输入你确认的父条目 Key'
& $Python scripts/paper_input.py --user-library --item-key $ItemKey --output $InputPath
if ($LASTEXITCODE -ne 0) { throw '输入未就绪，请查看结果，不要继续调用模型' }
$PaperInput = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PaperInput.ok -or $PaperInput.status -ne 'READY') { throw '只有单篇 READY 记录才能进入生成' }
$PaperInput.item | Format-List
$PaperInput.pdf | Select-Object attachment_key, local_path, fulltext_indexed
Test-Path -LiteralPath $PaperInput.pdf.local_path
```

检查题名是否选对、PDF 路径是否存在，最后一条应显示 `True`。`fulltext_indexed=false` 只表示 Zotero 没有可用全文索引；已有可读的本地 PDF 时仍可 READY，后续直接读取 PDF。输入 JSON 记录身份、路径和指纹，不是论文全文，更不是主体卡。用脚本自己的 `--output` 保存 UTF-8 文件，不用 PowerShell 的 `>` 随意改变编码。

此脚本只用标准库，无需安装模型客户端。输入默认值在 `configs/paper-input.toml`，可用参数或 `HYDRO_PLATFORM_ZOTERO_*` 环境变量覆盖，不读模型总配置。PDF 路径由 Zotero 返回，不要手动把作者路径改成另一个 PDF 来冒充同一篇。

### 1.5 群组库和输入异常怎么处理

群组库用户把搜索和取得输入的两条命令都改为 `--group-id`，不能搜索个人库却从群组库取 Key：

```powershell
# 仅群组库用户执行这一组，替代 1.3、1.4 中对应的个人库命令
$GroupId = Read-Host '输入自己有权限访问的 Zotero 群组数字 ID'
& $Python scripts/paper_input.py --group-id $GroupId --query $PaperQuery
if ($LASTEXITCODE -ne 0) { throw '群组搜索失败' }
$ItemKey = Read-Host '从上述群组搜索结果中选择父条目 Key'
& $Python scripts/paper_input.py --group-id $GroupId --item-key $ItemKey --output $InputPath
if ($LASTEXITCODE -ne 0) { throw '群组输入未就绪' }
$PaperInput = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PaperInput.ok -or $PaperInput.status -ne 'READY') { throw '只有单篇 READY 记录才能进入生成' }
```

群组用户必须已加入相应群组，且群组条目和 PDF 在本机 Zotero 可用。找不到 PDF、出现多篇 PDF 等情况应根据返回原因处理，不自行挑一个附件冒充 READY。

- `PDF_MISSING`：按条目来源链接合法取得 PDF，加入本机 Zotero 后重跑输入。
- `MULTIPLE_PDFS`：根据 `candidates` 人工确认、整理附件，本篇先不进入生成；不要让程序猜正文，也不要让它自动删除附件。
- 批量输入时，同一命令重复传多个 `--item-key` 可逐项检查并汇总问题，不因某篇多 PDF 而放弃其他篇。但批处理 JSON 不能整份传给本页的单篇生成入口；本页仅演示一篇 READY 的生成与校验。

## 2. 主体卡生成：由命令驱动所选模型

### 2.1 分清 CC Switch、Claude Code 和 DeepSeek

本例只需安装并配置 **Claude Code CLI + CC Switch + 自己的 DeepSeek 服务凭据**，不用同时安装 Codex，也不用额外安装一个“DeepSeek CLI”。已经能在终端通过 Claude Code 使用 DeepSeek 的用户，不必重复安装或重新登录 Anthropic 账号。

1. 打开 CC Switch，进入 **Claude Code/Claude** 的供应商页面，而不是 Codex 页面。
2. 选择并启用自己已配置的 DeepSeek 供应商；尚未配置时，使用相应预设填写自己的服务地址、认证和可用模型，保存并启用。密钥只保存在自己的工具配置中。
3. 确认连接方式：直连 DeepSeek 的 Anthropic 兼容接口，或由 CC Switch 本地代理转发。若使用代理/接管，运行期间保持本地代理与 Claude 接管开启，并确认上游选的是 DeepSeek。
4. 为便于复现，确认是否启用了代理的自动故障转移；若允许切到其他供应商，就不能仅凭最初选择宣称此次实际调用一定是 DeepSeek。仓库本身不会自动换后端，但无法替代理保证上游选择。

CC Switch 会把 Claude 的供应商配置写入用户配置文件。DeepSeek 官方提供的 Anthropic 兼容入口为 `https://api.deepseek.com/anthropic`；使用 CC Switch 代理时，Claude 配置里的地址可能是本机地址，不应强行改成直连地址。具体界面随版本变化，参见 [CC Switch 供应商切换](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/2-providers/2.2-switch.md)、[代理与应用接管](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/4-proxy/4.1-service.md)和 [DeepSeek 官方兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)。

**`--ai-provider claude` 选的是 Claude Code 命令行适配器，不是模型厂家。不要改成 `--ai-provider deepseek`，当前命令只接受 `claude` 或 `codex`。** 实际请求地址、认证与模型映射由自己的配置决定；即使界面出现 Claude 的模型别名，也应以服务端映射为准，不能让模型自报身份作为确认依据。

### 2.2 检查终端能找到 Claude 和 PDF 工具

```powershell
Get-Command claude -ErrorAction Stop
claude --version
if ($LASTEXITCODE -ne 0) { throw 'Claude Code 无法启动，请先修复安装' }
Get-Command pdftoppm, pdfinfo, pdftotext -ErrorAction Stop
```

应显示实际程序位置与版本。仓库还要求 CLI 支持隔离模式和结构化输出；本机验证版本是 2.1.280，不保证任意旧版本可用。`claude --version` 只证明程序能启动，不代表 DeepSeek 认证、额度或 PDF 阅读已经成功。缺 Poppler 时回到第 0 节安装，不要把“普通聊天成功”当成“能完整阅读 PDF”。

### 2.3 把 CC Switch 写入的服务配置传给本次终端

`configs/ai.toml` 只选择后端、模型、程序位置和超时，不保存密钥；本地单篇输入也不要求 Zotero Web API key。仓库其他模块的 DeepSeek 图谱 API 配置，与这里的 **Claude Code → DeepSeek** 认证是两套入口，不能互相替代。

**为什么还要这一步？** 手动运行的 Claude Code 可以使用自己的 settings；本仓库为控制读取权限，启动的是隔离子进程，不自动加载用户 settings 的 `env`。因此可能出现“终端 Claude 能聊，Python 生成却立刻报认证错误”。下面只把自己信任的配置文件中的 `ANTHROPIC_*` 字符串变量传入当前 PowerShell，随后启动的 Claude 子进程会继承它们；不显示值、不写入项目、不修改系统级环境。

```powershell
# 默认路径；若 CC Switch 使用自定义 Claude 配置目录，请改为其实际 settings.json
$ClaudeConfigDir = Join-Path $env:USERPROFILE '.claude'
if ($env:CLAUDE_CONFIG_DIR) { $ClaudeConfigDir = $env:CLAUDE_CONFIG_DIR }
$ClaudeSettingsPath = Join-Path $ClaudeConfigDir 'settings.json'
if (-not (Test-Path -LiteralPath $ClaudeSettingsPath)) {
    throw '未找到 Claude settings.json，请在 CC Switch 确认实际配置目录'
}
$ClaudeSettings = Get-Content -LiteralPath $ClaudeSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$ImportedNames = @()
foreach ($Entry in $ClaudeSettings.env.PSObject.Properties) {
    if ($Entry.Name -like 'ANTHROPIC_*' -and $Entry.Value -is [string]) {
        [Environment]::SetEnvironmentVariable($Entry.Name, $Entry.Value, 'Process')
        $ImportedNames += $Entry.Name
    }
}
if ($ImportedNames.Count -eq 0) { throw '文件里没有可导入的 ANTHROPIC_* 配置，请核对 CC Switch 的 Claude 配置' }
# 只显示数量和是否存在，不显示地址、模型配置原文或密钥
Write-Host ('已向当前终端导入 {0} 项服务配置（未显示值）' -f $ImportedNames.Count)
[pscustomobject]@{
    HasBaseUrl = -not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_BASE_URL)
    HasAuth = (-not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_AUTH_TOKEN)) -or (-not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY))
}
```

CC Switch 的常见 DeepSeek 配置应看到两项 `True`，但这只是“变量存在”，不是请求成功。代理模式中的认证也可能是代理占位值，真正上游密钥由 CC Switch 管理。不要输出 `$ClaudeSettings`、`$Entry.Value` 或完整环境变量来排错，也不要分享 settings.json。

这个代码块用于 **CC Switch/settings 的 env 接入**；如果服务配置已正确存在于进程环境，或使用另一种经过验证的 Claude 登录方式，则不必重复导入。它不清除终端原有变量，也不导入其他前缀的代理/企业配置；有旧服务变量冲突时，应检查自己的持久环境设置，再开一个干净 PowerShell 重做本节，不要混用旧令牌与新地址。

**CC Switch 切换供应商后，已经导入 PowerShell 的变量不会跟着热更新。** 等当前任务结束后，新开终端并重新导入配置；不要在一次生成过程中切换供应商。新开终端也要按第 4 节恢复仓库与路径变量。关于用户配置写入行为，参见上面的 CC Switch 官方说明；隔离进程及继承要求来自本仓库 Claude 适配器实现。

### 2.4 查看本次仓库配置，不调用模型

这里沿用 CC Switch 为 Claude 配置的模型，不另填 `--ai-model`。先检查项目配置，防止仓库 `.env` 中遗留的模型覆盖自己的选择。

```powershell
$Provider = 'claude'
$OutputRoot = $RunDir
& $Python -m hydrolitagent.cards ai-config --ai-provider $Provider --output-root $OutputRoot --json
if ($LASTEXITCODE -ne 0) { throw '模型调用配置无效，请先处理配置错误' }
```

检查后端为 `claude`、产物根是刚创建的运行目录、模型没有意外指定为别的名称。`ai-config` 显示的是仓库配置，不会访问 DeepSeek 来证明认证成功，也不会解析代理后的真实模型。若确实要覆盖模型，可以给生成命令加 `--ai-model '自己服务实际支持的模型名'`；不要把示意文字原样粘贴，也不要随意填写已过期的型号。

### 2.5 正式生成：此步会调用 DeepSeek 并使用额度

真实生成会把用于阅读的论文内容交给自己配置的服务；仅处理有权上传的材料，保密或未公开资料先确认授权。输入和校验不调用模型，但这一阶段不是离线运行。

```powershell
if (-not (Test-Path -LiteralPath $InputPath)) { throw '缺少输入文件，请先完成第 1 节' }
$PaperInput = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PaperInput.ok -or $PaperInput.status -ne 'READY') { throw '输入不是单篇 READY' }

# stdout 接 JSON；进度仍在终端显示。不要加 2>&1，否则会混入进度而无法解析 JSON
$GenerationJson = & $Python -m hydrolitagent.cards evidence-generate --paper-input $InputPath --ai-provider $Provider --output-root $OutputRoot --json
$GenerationExitCode = $LASTEXITCODE
if ($GenerationExitCode -ne 0) {
    $GenerationJson
    throw '生成失败，请处理诊断原因；不要自动重试或跳过校验'
}
$Generation = ($GenerationJson -join "`n") | ConvertFrom-Json
if (-not $Generation.ok -or $Generation.status -ne 'DRAFT_PENDING_VALIDATION' -or -not $Generation.draft_path) {
    throw '未得到预期的待校验草稿，请检查生成结果'
}
$DraftPath = $Generation.draft_path
$CardPath = $Generation.card_path
$Generation | Select-Object status, draft_path, card_path
Test-Path -LiteralPath $DraftPath
Test-Path -LiteralPath $CardPath
```

预期显示 `DRAFT_PENDING_VALIDATION`、两个文件路径、两次 `True`。运行期间可能需要数分钟；以进度和最终退出码判断，不要因尚未显示最终 JSON 就重复启动。执行失败后停止本篇，保留诊断；如返回了任何旧路径，也不能把之前生成的草稿误当本次成功结果。

`draft.json` 是机器校验要用的结构化草稿，`card.md` 是给人阅读的正文。生成成功**还没有通过校验**。可先预览，不要直接修改已生成草稿来绕过下一步：

```powershell
Get-Content -LiteralPath $CardPath -Encoding UTF8 | Select-Object -First 60
```

兼容 API 不等于完整能力相同：具体 DeepSeek 模型/中转服务还必须满足工具调用、页面图像读取和结构化输出要求。不能仅凭终端普通问答成功保证 PDF 制卡成功。生成失败时区分程序确定的原因与“模型自报（未经独立验证）”；不要通过跳过页覆盖或放宽校验来制造 PASS。[DeepSeek 兼容字段与限制](https://api-docs.deepseek.com/guides/anthropic_api/)会随服务变化，真实能力以该服务说明及本次运行证据为准。

`configs/ai.toml` 是公开默认值。后端、模型、程序位置、超时和 PDF 工具均可覆盖；默认模型留空，使用所选 CLI 默认值。优先级：命令行 → 进程环境变量 → `.env` → TOML → 内置默认值。常用变量为 `HYDRO_PLATFORM_AI_PROVIDER` / `_MODEL` / `_EXECUTABLE` / `_TIMEOUT_SECONDS`（均以 `HYDRO_PLATFORM_AI` 开头）。凭据交由所选 CLI 管理，不放入该 TOML。[详细配置](subject-card-draft.md)。

产物根调用 #27 的同一解析器：`--output-root` → `HYDROLITAGENT_LITERATURE_ROOT`（支持 `.env`）→ `configs/paths.toml` → 仓库 `outputs/`。用 `ai-config --json` 查实际落点；不写死作者路径、不清理外部云盘目录。

输出里的 `draft_path` 是下一步输入。结果是待校验草稿，不会因模型完成而自动标为正确或正式发布。

### 2.6 别人可以改哪些接口参数

| 自己的选择 | 公开入口 | 不需要做什么 |
| --- | --- | --- |
| 个人库或群组库 | 输入脚本的 `--user-library` / `--group-id` | 不改作者代码，不填写假群组号 |
| 论文 | `--query` 搜索、`--item-key` 确认 | 不硬编码作者的条目 Key 或 PDF 路径 |
| Claude Code 或 Codex CLI | `--ai-provider claude` / `codex` | 不是填写 DeepSeek；不要求两种都安装 |
| 模型 | `--ai-model` 或 TOML 的 `model` | 不改源码；模型必须是自己账号实际可用的 |
| CLI 不在 PATH | `--ai-executable` | 不写死别人的可执行文件位置 |
| 超时 | `--ai-timeout`（1–7200 秒） | 不无限等待、不靠循环重试 |
| 自己的输出目录 | `--output-root` 或 `HYDROLITAGENT_LITERATURE_ROOT` | 不使用作者 D 盘路径，不清理其他人的目录 |
| 独立配置文件 | `--ai-config` | 不把密钥加入公开 TOML |
| 校验报告目录 | `--report-dir` | 不覆盖或手改原始草稿 |

## 3. 草稿校验：不运行模型

### 3.1 把同一份输入和刚生成的草稿交给校验器

继续在同一终端执行。一定使用第 2 节返回的 `$DraftPath`，不是 `card.md`，也不是仓库里的合成示例。

```powershell
if (-not (Test-Path -LiteralPath $DraftPath)) { throw '草稿路径不存在，请核对第 2 节结果' }
$ValidationJson = & $Python scripts/paper_validate.py --paper-input $InputPath --draft $DraftPath
$ValidationExitCode = $LASTEXITCODE
$Validation = ($ValidationJson -join "`n") | ConvertFrom-Json
$Validation | Select-Object ok, status, validation_path, scientific_correctness_verified, production_eligible
Write-Host ('校验退出码：{0}' -f $ValidationExitCode)
Write-Host ('错误：{0}；警告：{1}' -f @($Validation.errors).Count, @($Validation.warnings).Count)
if ($Validation.validation_path) {
    Test-Path -LiteralPath $Validation.validation_path
}
```

不需要模型客户端登录、Zotero 在线或原 PDF 可访问。校验代码检查字段、身份、引用编号、物理页范围及版本指纹；识别 Codex 和 Claude 的不同读取记录，不重新调用模型。报告追加到草稿旁 `validations/<ID>/validation.json`。用 `--report-dir` 或 `HYDRO_PLATFORM_VALIDATION_REPORT_DIR` 改位置。

独立校验脚本只依赖项目源码（可从完整环境运行），不需要 AI SDK 或 CLI。成功退出码 0，校验/保存失败 3。PASS 表示已实现的确定性规则通过，不证明科学结论正确。错误应由后续修正工作处理，不能为了让示例通过而伪造内容。

### 3.2 PASS 和 FAIL 分别怎么处理

```powershell
# 即使失败，也先查看具体规则和字段位置；不要只看一个 FAIL
$Validation.errors | Format-List
$Validation.warnings | Format-List
if ($ValidationExitCode -ne 0 -or -not $Validation.ok -or $Validation.status -ne 'PASS') {
    throw '校验未通过：先处理报告中的错误，本篇不能作为已通过卡片交付'
}
```

- **PASS + 退出码 0：**已实现的规则通过，可进入人工内容审阅；`scientific_correctness_verified`、`production_eligible` 仍是 `false`，不是完成科研核实或自动发布。
- **有 warnings：**逐条阅读。警告不一定令校验 FAIL，例如合成示例的 `CARD_TEXT_SHORT`，不要把 warning 等同 error。
- **FAIL：**看 `errors` 的 `code`、`path`、`message`，区分输入拿错、引用/页码问题、版本不一致等原因；修复真正原因后再运行对应步骤。不要删掉错误字段、改提示词哈希或改成“已经 PASS”。
- **报告无法保存：**检查目录权限、磁盘和路径；此时可能没有 `validation_path`，不能声称已有可追溯报告。

### 3.3 结果在哪里，交给别人看什么

本教程将输入和生成产物放在同一个唯一运行目录；具体生成子目录以返回路径为准，不需要自己拼接草稿 ID：

```text
outputs/single-paper/<本次运行ID>/
├── paper-input.json                 本篇身份与本地 PDF 指纹
└── zotero/.../drafts/<草稿ID>/
    ├── draft.json                   结构化草稿
    ├── card.md                      人类可读正文
    └── validations/<校验ID>/validation.json
```

```powershell
# 列出本次目录中保存的文件；可在资源管理器打开这个目录查看
Write-Host ('本次目录：{0}' -f $RunDir)
Get-ChildItem -LiteralPath $RunDir -Recurse -File | Select-Object FullName
```

审阅时看 `card.md` 的内容、`draft.json` 的证据定位，以及配套 `validation.json`。输入 JSON 包含个人本地路径和论文信息，不是通用的可移植论文包；不要无审查上传公开仓库。别人要重新生成，需先把自己有权使用的 PDF 放入自己的 Zotero，再重新走第 1 节，而不是照抄你的 Key 和路径。

## 4. 下次换论文、重开终端或只重新校验

- **换论文：**第 0 节通常不必重装；从第 1.2 节创建新的运行目录，重新搜索并选择论文，再生成、校验。不要覆盖前一篇的输入文件。
- **同一篇仅重新校验：**不需要再花模型额度，使用保存的输入与草稿即可；若仓库规则已经更新，要核对版本，不能篡改指纹求通过。
- **关闭终端后继续：**PowerShell 变量会丢失，文件不会。运行下面步骤恢复路径后，可继续第 3 节。要重新生成还须先完成第 2.3、2.4 节，重新导入自己的服务配置。

```powershell
$RepoPath = Read-Host '输入自己的 mylibrary 仓库完整路径'
Set-Location -LiteralPath $RepoPath
$Python = Join-Path $RepoPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw '此目录没有项目 Python，请检查仓库位置和安装' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'
$InputPath = Read-Host '输入此前保存的 paper-input.json 完整路径（不用额外加引号）'
$DraftPath = Read-Host '输入与它对应的 draft.json 完整路径（不用额外加引号）'
if (-not (Test-Path -LiteralPath $InputPath)) { throw '输入文件不存在' }
if (-not (Test-Path -LiteralPath $DraftPath)) { throw '草稿文件不存在' }
$RunDir = Split-Path -Parent $InputPath
```

若想换用 Codex，请安装并认证自己的 Codex CLI，然后将生成的 `--ai-provider` 改为 `codex`，不执行 Claude settings 导入块。两种适配器共享输入/草稿/校验契约，但不共享登录文件；本页主流程始终以终端 Claude Code 接入 DeepSeek 为例。

## 5. 在终端 Claude 对话里让它代执行，机理有什么不同

### 5.1 外层对话与仓库生成是两层调用

你可以先在终端运行 `claude`，用自然语言要求它操作当前仓库。一般的代理循环是：本地 CLI 把任务与允许使用的工具描述交给配置的模型服务；模型提出工具调用；本机在权限允许时执行；结果再交回模型，继续处理。**模型提出操作，本地客户端执行操作；模型服务不等于本地终端软件。**

本仓库的正式生成入口还会另外启动受限 Claude Code 子进程：

```text
你 → 外层终端 Claude 对话（可选，用于协助操作仓库）
       → 本机 PowerShell 工具执行 Python 命令
          → evidence-generate 启动新的受限 Claude Code 子进程
             → 配置的模型服务提出 Read 调用
             → 本机 Read 读取本篇 PDF，结果交给模型
             → 生成结构化内容，Python 检查回执并保存草稿
          → paper_validate.py 确定性校验，不再调用模型
```

所以，“让外层 Claude 在聊天中直接写一张卡”和“让它执行仓库的生成命令”不是同一个验收过程。前者不能自动代替后者的 PDF 读取回执、输入绑定和草稿契约；不能把聊天文本复制进文件就声称跑通流程。外层助手的工具权限也不代表内层拥有同样权限。

当前仓库内层启动参数包含 `--safe-mode`、`--restricted`、`--no-session-persistence`，只开放原生 Read，检查回执中的文件是否为本次 PDF，并禁用外部 MCP 配置。它不继承外层对话历史，不通过外层的续聊记录保存产物；正式交付看第 3.3 节的文件。普通交互会话如何保存历史、用什么本地运行时、工具超时/缓存多久，取决于 CLI 版本与启动环境，不能把一次聊天中的自述写成仓库保证。

### 5.2 让助手执行时不要依赖人工终端的会话状态

第 1–4 节用 `Read-Host` 是为了让**人**逐步输入。让 Claude 用非交互 shell 工具执行时，应改成明确的参数，并遵守以下约束：

1. 开始前确定自己的仓库路径、库类型、论文 Key 和输出目录。搜索出现多候选时先让人确认，不自动猜选。
2. 每次独立 shell 调用都显式进入仓库，使用该仓库 Python；不要假定上次调用的工作目录和变量必然保留。
3. 第 2.3 节的环境导入与第 2.5 节的生成放在**同一次 PowerShell 调用**中。单独执行一次 `$env:...` 再换一个子进程，不能据此保证认证仍在。
4. 不使用 `Read-Host` 等待非交互 stdin；已确认的题名、Key、路径直接作为参数。将生成 JSON 返回的路径明确传入后续校验，不靠上一个进程里的 `$Generation` 变量。
5. 若工具等待时间短于生成时间，使用工具自身支持的继续等待方式，不反复启动同一生成任务。不要把外层工具超时误判为 DeepSeek 已失败。
6. 若 CLI 拒绝在现有 Claude 会话中再启动嵌套会话，停止这条调用方式，回到独立 PowerShell 运行第 1–3 节。本教程不保证嵌套调用可用，也不要求删除安全标记或关闭隔离权限来绕过限制。

可以在终端 Claude 的对话输入框提出如下请求（这是给助手的任务描述，不是 PowerShell 命令）：

```text
请按当前仓库 docs/hydro-platform/single-paper-quickstart.md，
帮助我完成自己一篇 Zotero 论文的输入、生成和校验。
先确认当前仓库位置、库类型、论文题名或 DOI，搜索后让我确认父条目 Key。
我使用 CC Switch 为 Claude Code 配置的 DeepSeek；适配器仍选 claude。
不要打印、复制或提交密钥。采用 Windows PowerShell，非交互工具调用不要用 Read-Host。
导入现有可信的服务环境配置和执行生成要在同一次 shell 调用中完成。
只有 READY 才生成；只有取得本次 draft_path 才校验。
如嵌套 Claude 被拒绝，给我在独立 PowerShell 运行的命令，不绕过限制。
最后报告输入状态、草稿路径、校验 PASS/FAIL、错误和警告，以及尚需人工审阅的内容。
```

### 5.3 如何判断实际用了哪个模型服务

启动横幅中的 `Opus` 等名称、`API Usage Billing`、模型自己说“我是某模型”，都不足以独立确认此次上游。应核对 CC Switch 的 Claude 当前供应商、实际连接方式与模型映射；代理模式还要核对有无故障转移，必要时在本机查看不含敏感正文的请求元数据。若未经核实，就只写“Claude Code CLI，经当前配置的服务调用”，不要把提供方猜成 Anthropic，也不要把仅有 `provider=claude` 的产物当成 DeepSeek 身份证明。

## 验证代码与排错

新开终端请先进入自己的仓库目录，再运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_claude_cli.py tests/test_card_validation.py
$LASTEXITCODE
.\.venv\Scripts\python.exe -m pytest tests
$LASTEXITCODE
.\.venv\Scripts\python.exe -m mkdocs build --strict
$LASTEXITCODE
```

这些测试不调用真实模型。`$LASTEXITCODE` 紧接每条命令读取，`0` 表示该命令成功；以 pytest 实际打印的统计为准，不要把注释 `# 150 passed` 当成测试输出。全仓库测试还包含依赖本机 Zotero 在线及特定样本的集成测试，可能因本地库不同而失败；不能把它与平台单元测试混为一谈。

如果 pytest 在创建临时目录时就报 `WinError 5`，或深层路径下保存测试报告失败，可以选择**新的、短一些的临时路径**后再排查，不需要更改业务代码：

```powershell
$TestBase = Join-Path $env:TEMP ('hydro-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
if (Test-Path -LiteralPath $TestBase) { throw '请换一个从未使用过的测试临时目录' }
.\.venv\Scripts\python.exe -m pytest tests/test_claude_cli.py tests/test_card_validation.py --basetemp $TestBase -p no:cacheprovider
$LASTEXITCODE
```

`--basetemp` 会清理其指定目标，所以不要填仓库、桌面或已有资料目录。上面的代码生成尚不存在的随机子目录；测试仍失败时看真实报错，不要一律归因于权限或路径长度。

| 现象 | 先检查什么 |
| --- | --- |
| 无法识别 `.\.venv\Scripts\python.exe` | `Get-Location` 是否为自己的仓库根；`Test-Path` 是否 True；是否完成 uv 安装 |
| `Not a git repository` | 当前目录不是仓库，不是代码测试结论 |
| 找不到 `hydrolitagent.cards` | 是否使用本仓库 Python 并安装 `uv sync --all-packages --locked` |
| Zotero 不可连接或本地请求被代理为 502 | Zotero 是否启动、允许通信；必要时为本机地址配置进程级 `NO_PROXY=127.0.0.1,localhost,::1` |
| 搜不到论文或无 PDF | 自己的文库是否有该条目及本地附件；代码不会自动抓取共享库到个人库 |
| Claude 立即认证失败 | 隔离进程是否继承自己的认证环境；`ai-config` 不是认证检查 |
| CC Switch 已切换，但生成仍走旧服务 | 已启动的 PowerShell 仍保留旧变量；结束当前任务，确认持久环境无冲突，再开终端重新导入 |
| CC Switch 使用本地地址，生成连接失败 | 本地代理是否运行、Claude 接管是否开启、上游供应商是否正确；不要把代理占位令牌用于直连 |
| `--ai-provider deepseek` 被拒绝 | 应填 `claude`，因为启动的是 Claude Code CLI；DeepSeek 在 CC Switch/Claude 环境中配置 |
| `$Generation`、`$DraftPath` 为空或 JSON 解析失败 | 是否新开终端丢失变量、上一命令失败，或用 `2>&1` 混入日志；按第 4 节恢复已有文件，不盲目重复生成 |
| 缺 `pdftoppm` 或回执不完整 | Poppler 是否在当前进程 PATH；不把仅取得文字视作完整读页 |
| 校验版本不匹配 | 草稿与提示词/模板是否来自同一版本；不要改哈希凑 PASS |

输入脚本 `ok=true` 不一定意味着 READY，例如候选搜索可能成功但仍需选择；生成成功也只意味着待校验草稿。校验 PASS 仅代表已实现的确定性规则通过，不等于科研正确或正式发布。其他程序接入时应解析 stdout JSON 的 `ok`、`status`、路径与错误码，不解析进度文案。
