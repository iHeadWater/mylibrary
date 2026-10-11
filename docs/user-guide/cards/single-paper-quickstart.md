# 单篇论文命令行流程：输入 → 生成 → 校验

三步都由普通终端运行 Python。**只有「生成」这一步调用所选模型** —— 读 Zotero / PDF、检查身份、
校验字段、保存记录都由代码完成。不需要修改或提交 Codex / Claude 软件、模型本身或个人凭据。

本页主例走：**在 Windows PowerShell 终端运行 Claude Code，由 CC Switch 配置它连接 DeepSeek**。
这里的「Claude」指**命令行软件**，不表示实际使用 Anthropic 的模型；DeepSeek 才是提供推理能力的服务。

```text
CC Switch：管理 Claude Code 的服务地址、认证与模型映射
                         ↓ 配置传入本次终端进程
PowerShell → 仓库 Python 生成命令 → Claude Code CLI → DeepSeek
                ↑ 本地 PDF                         ↓ 生成内容
Zotero → paper-input.json → draft.json + card.md → Python 校验 → validation.json
```

直连时 CC Switch 只负责写配置，不必承载每次请求；启用本地代理接管时，
Claude Code 的请求先经过 CC Switch 再到上游服务。

| 阶段 | 你给什么 | 程序做什么 | 完成标志 |
| --- | --- | --- | --- |
| 输入 | 自己 Zotero 中的论文 Key | 确认文献身份，定位唯一本地 PDF，记录指纹 | `paper-input.json` 里 `ok=true` 且 `status=READY` |
| 生成 | 上一步的 JSON、Claude / DeepSeek 配置 | 调用 Claude Code 读 PDF，让模型生成草稿 | 返回 `DRAFT_PENDING_VALIDATION` 和草稿路径 |
| 校验 | 同一份输入 JSON 与对应的 `draft.json` | **不调用模型**，检查字段、来源、页码、版本等规则 | `validation.json` 里 `status=PASS`，或列出 FAIL 原因 |

**命令粘贴位置**：第 0–4 节的 `git`、`uv`、`$变量` 命令都粘贴在显示 `PS C:\...>` 的
**PowerShell 提示符**后，不是当成 Claude 对话里的自然语言指令。也可以让终端里的 Claude 代执行 ——
区别与限制见第 5 节。生成命令会**自行启动**一个 Claude Code 子进程，无需先手动开 Claude 对话，
也不会接续已有对话。

第一次使用按第 0 节完成安装，再依次执行第 1、2、3 节；日常换一篇论文看第 4 节。
代码块里的 `#` 是解释，不是运行结果；**每执行完一块先检查结果，不要一次性粘贴整页**。

## 0. 从零拿到仓库怎么用

### 准备与边界

- 命令针对 **Windows PowerShell**（不是 CMD）。行首的 `PS C:\...>` 是提示符，不要复制。
- 先安装 Git、Python 3.12–3.14、uv。真实生成还需要 Zotero Desktop、已下载的 PDF、Poppler，
  以及自己安装并认证的一种 CLI（Codex 或 Claude）。**只有离线校验不需要后面这些。**
- GitHub 上拿到的是代码、提示词、模板和合成示例 —— **不含**作者的论文、Zotero 库、账号或 `.venv`。
  仓库若为私有，必须先取得访问权限；文档不能替代授权。
- 当前接口是**本地 CLI + JSON**，不是公网 HTTP API：不需要开路由器端口、不需要启动 MCP Server；
  Zotero 只允许本机回环访问。

### 下载到你自己选的位置

```powershell
$ProjectParent = Join-Path $env:USERPROFILE 'source'
New-Item -ItemType Directory -Path $ProjectParent -Force | Out-Null
Set-Location -LiteralPath $ProjectParent
git clone --branch literature-platform https://github.com/iHeadWater/mylibrary.git mylibrary
if ($LASTEXITCODE -ne 0) { throw '克隆失败：请检查权限、网络或是否已有同名目录' }
Set-Location -LiteralPath (Join-Path $ProjectParent 'mylibrary')
$RepoPath = (Get-Location).Path
```

`$RepoPath` 是**你自己的仓库目录**，不是某个作者的固定盘符路径。新开终端后变量不会自动保留 ——
先用 `Set-Location -LiteralPath '你实际保存的仓库目录'` 回到这里，再继续。

### 装自己的环境

```powershell
uv sync --all-packages --locked
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请先解决上面的错误' }
Get-Location
git branch --show-current
Test-Path .\.venv\Scripts\python.exe
```

`Test-Path` 应输出 `True`。若为 `False`，通常是尚未安装或没进入正确的仓库 —— 不要继续粘贴后面的命令。
**无需激活虚拟环境**，也不要复制别人的 `.venv` 或登录文件。安装依赖需要联网。

### 已有仓库如何更新

三个步骤的入口都已在 `literature-platform` 主分支上。在**无未提交修改**的检出里更新：

```powershell
git fetch origin
git switch literature-platform
git pull --ff-only origin literature-platform
```

有未提交修改时先自行处理，**不要**强制切换或覆盖。确认检出里同时有 `scripts/paper_input.py`、
`scripts/paper_validate.py` 和 `configs/ai.toml` —— 不要混用不同分支的脚本与提示词。
更新代码后重新跑 `uv sync --all-packages --locked`。

### 先做离线校验（不需要你的文献或模型账号）

```powershell
uv run python scripts/paper_validate.py --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
$LASTEXITCODE
```

应返回 `status: PASS`、退出码 `0`。合成示例正文较短，`CARD_TEXT_SHORT` 是**提示**，不是失败。
这只证明代码入口与合成契约可用，**不证明**真实论文已经生成。

只看参数也不会调用模型：

```powershell
uv run hydrolitagent cards evidence-generate --help
uv run python scripts/paper_input.py --help
uv run python scripts/paper_validate.py --help
```

### PDF 工具准备（Windows）

Codex 的本地读取需要 Poppler 工具；Windows 上验证过的 Claude CLI 2.1.280 原生 PDF Read
**也依赖 `pdftoppm`** —— 只装 pypdf 或只有 `pdftotext` 不足以完成页面图像读取。已有 Poppler 时先检查：

```powershell
Get-Command pdftoppm, pdfinfo, pdftotext -ErrorAction Stop
pdftoppm -v
```

缺工具时安装用户级 Poppler：

```powershell
winget install --id oschwartz10612.Poppler --exact --scope user --accept-package-agreements --accept-source-agreements
```

装完**新开 PowerShell**，回到仓库目录重跑检查。若安装器已更新用户 PATH、但你想继续用当前终端，
可刷新当前进程的 PATH：

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
Get-Command pdftoppm, pdfinfo, pdftotext -ErrorAction Stop
```

刷新会替换当前终端临时追加的 PATH，必要时重新追加自己的工具目录。
**Poppler 的工具目录也必须在 Claude 进程能继承的 PATH 里。** `ai-config` 能显示配置，
但**不会**替你做 PDF 渲染工具检查。

## 1. 本机 Zotero 输入：不调用模型

### 1.1 准备自己的论文

打开 Zotero，在设置里启用「允许此计算机上的其他应用程序与 Zotero 通信」。
把论文导入自己的文库，并在 Zotero 里双击 PDF 确认能打开 ——
**只有书目信息、网页链接或尚未下载的附件不够**。

**条目 Key 属于各自的文库，不能照抄作者的 Key。** 下面先按自己论文的题名 / DOI 搜索，
再从结果里选父条目 Key。搜索只查本地库，**不会**自动下载或导入论文。

### 1.2 建立本次运行目录并检查配置

先回到自己的仓库根目录。**每篇、每次运行用单独目录**，避免后一篇的输入覆盖前一篇后无法对照校验。
以下变量供后续代码块沿用，期间不要换终端。

```powershell
# 检查当前位置；应该能看到 scripts、configs、hydrolitagent 等目录
Get-Location
if (-not (Test-Path .\scripts\paper_input.py)) { throw '请先进入 mylibrary 仓库根目录' }
if (-not (Test-Path .\.venv\Scripts\python.exe)) { throw '请先运行 uv sync --all-packages --locked' }

$RepoPath = (Get-Location).Path
$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$RunDir = Join-Path $RepoPath (Join-Path 'outputs\single-paper' $RunId)
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
$InputPath = Join-Path $RunDir 'paper-input.json'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'

# 只显示输入配置，不调用模型，也不是 Zotero 连通性测试
uv run python scripts/paper_input.py --show-config
if ($LASTEXITCODE -ne 0) { throw '输入配置无效，请先处理上面的错误' }
```

`$RunDir` 是此次的产物目录，`$InputPath` 是要保存的输入文件。
配置里显示的默认群组**不影响**下一步显式指定的 `--user-library`。

### 1.3 搜索论文，确认父条目 Key

```powershell
$PaperQuery = Read-Host '输入你已导入 Zotero 的论文题名或 DOI'
uv run python scripts/paper_input.py --user-library --query $PaperQuery
if ($LASTEXITCODE -ne 0) { throw '搜索失败，请检查 Zotero 和查询条件' }
```

预期得到 `status: SELECTION_REQUIRED` 和 `candidates` 列表 —— 这是正常的**「等待选择」**，不是生成失败。
对照候选的题名、作者、年份和 DOI，记下正确论文的 `item_key`（8 位字母或数字）。
候选为空就调关键词或先在 Zotero 导入论文；结果太多可加 `--limit 20`。**不要盲选第一个。**

### 1.4 生成 READY 输入文件

```powershell
$ItemKey = Read-Host '输入你确认的父条目 Key'
uv run python scripts/paper_input.py --user-library --item-key $ItemKey --output $InputPath
if ($LASTEXITCODE -ne 0) { throw '输入未就绪，请查看结果，不要继续调用模型' }
$PaperInput = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PaperInput.ok -or $PaperInput.status -ne 'READY') { throw '只有单篇 READY 记录才能进入生成' }
$PaperInput.item | Format-List
$PaperInput.pdf | Select-Object attachment_key, local_path, fulltext_indexed
Test-Path -LiteralPath $PaperInput.pdf.local_path
```

检查题名是否选对、PDF 路径是否存在 —— 最后一条应显示 `True`。
`fulltext_indexed=false` 只表示 Zotero 没有可用全文索引；已有可读的本地 PDF 时**仍可 READY**，
后续直接读 PDF。输入 JSON 记录的是**身份、路径和指纹**，不是论文全文，更不是主体卡。
用脚本自己的 `--output` 保存 UTF-8 文件 —— **不要**用 PowerShell 的 `>` 改变编码。

此脚本只用标准库，**无需安装模型客户端**。输入默认值在 `configs/paper-input.toml`，
可用参数或 `HYDROLITAGENT_CARDS_ZOTERO_*` 环境变量覆盖，**不读**模型总配置。
PDF 路径由 Zotero 返回 —— 不要手动把作者路径改成另一个 PDF 来冒充同一篇。

### 1.5 群组库和输入异常怎么处理

群组库用户把搜索和取输入的两条命令都改用 `--group-id` —— **不能**搜索个人库却从群组库取 Key：

```powershell
# 仅群组库用户执行这一组，替代 1.3、1.4 中对应的个人库命令
$GroupId = Read-Host '输入自己有权限访问的 Zotero 群组数字 ID'
uv run python scripts/paper_input.py --group-id $GroupId --query $PaperQuery
if ($LASTEXITCODE -ne 0) { throw '群组搜索失败' }
$ItemKey = Read-Host '从上述群组搜索结果中选择父条目 Key'
uv run python scripts/paper_input.py --group-id $GroupId --item-key $ItemKey --output $InputPath
if ($LASTEXITCODE -ne 0) { throw '群组输入未就绪' }
$PaperInput = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PaperInput.ok -or $PaperInput.status -ne 'READY') { throw '只有单篇 READY 记录才能进入生成' }
```

群组用户必须已加入相应群组，且群组条目与 PDF 在本机 Zotero 可用。
找不到 PDF、出现多篇 PDF 等情况按返回的原因处理 —— **不要**自己挑一个附件冒充 READY：

- `PDF_MISSING`：按条目来源链接合法取得 PDF，加入本机 Zotero 后重跑输入。
- `MULTIPLE_PDFS`：根据 `candidates` 人工确认、整理附件，本篇先不进入生成；
  不要让程序猜正文，也不要让它自动删附件。
- 批量输入：同一命令重复传多个 `--item-key` 可逐项检查并汇总问题，不因某篇多 PDF 而放弃其他篇。
  但**批处理 JSON 不能整份**传进本页的单篇生成入口 —— 本页只演示一篇 READY 的生成与校验。

## 2. 主体卡生成：由命令驱动所选模型

### 2.1 分清 CC Switch、Claude Code 和 DeepSeek

本例只需装 **Claude Code CLI + CC Switch + 自己的 DeepSeek 凭据**，不用同时装 Codex，
也不用额外装一个「DeepSeek CLI」。已经能在终端通过 Claude Code 用 DeepSeek 的，不必重装或重新登录。

1. 打开 CC Switch，进入 **Claude Code / Claude** 的供应商页面（不是 Codex 页面）。
2. 选择并启用自己已配置的 DeepSeek 供应商；尚未配置时，按预设填自己的服务地址、认证与可用模型，
   保存并启用。**密钥只保存在你自己的工具配置里。**
3. 确认连接方式：直连 DeepSeek 的 Anthropic 兼容接口，或由 CC Switch 本地代理转发。
   用代理 / 接管时，运行期间保持本地代理与 Claude 接管开启，并确认上游选的是 DeepSeek。
4. 为便于复现，确认是否启用了代理的**自动故障转移** —— 若允许切到别的供应商，
   就不能仅凭最初选择宣称本次一定用了 DeepSeek。仓库本身不会自动换后端，但无法替代理保证上游选择。

CC Switch 会把 Claude 的供应商配置写入用户配置文件。DeepSeek 官方的 Anthropic 兼容入口是
`https://api.deepseek.com/anthropic`；用 CC Switch 代理时，Claude 配置里的地址可能是**本机**地址，
不要强行改成直连地址。具体界面随版本变化，见
[CC Switch 供应商切换](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/2-providers/2.2-switch.md)、
[代理与应用接管](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/4-proxy/4.1-service.md)
和 [DeepSeek 官方兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)。

> **`--ai-provider claude` 选的是 Claude Code 命令行适配器，不是模型厂家。**
> 不要改成 `--ai-provider deepseek` —— 当前命令只接受 `claude` 或 `codex`。
> 实际请求地址、认证与模型映射由你的配置决定；即使界面出现 Claude 的模型别名，
> 也应以服务端映射为准，**不能**让模型自报身份作为确认依据。

### 2.2 检查终端能找到 Claude 和 PDF 工具

```powershell
Get-Command claude -ErrorAction Stop
claude --version
if ($LASTEXITCODE -ne 0) { throw 'Claude Code 无法启动，请先修复安装' }
Get-Command pdftoppm, pdfinfo, pdftotext -ErrorAction Stop
```

应显示实际程序位置与版本。仓库还要求 CLI 支持**隔离模式**和**结构化输出**；
本机验证过的版本是 2.1.280，不保证任意旧版本可用。`claude --version` 只证明程序能启动，
**不代表** DeepSeek 认证、额度或 PDF 阅读已经成功。缺 Poppler 就回到第 0 节安装 ——
**不要把「普通聊天成功」当成「能完整阅读 PDF」。**

### 2.3 把 CC Switch 写入的服务配置传给本次终端

`configs/ai.toml` 只选择后端、模型、程序位置和超时，**不保存密钥**；本地单篇输入也不要求 Zotero Web API key。
仓库其他模块的 DeepSeek 图谱 API 配置，与这里的 **Claude Code → DeepSeek** 认证是**两套入口**，不能互相替代。

**为什么还要这一步？** 手动运行的 Claude Code 可以用自己的 settings；但本仓库为控制读取权限，
启动的是**隔离子进程**，不自动加载用户 settings 里的 `env`。于是可能出现
「终端里 Claude 能聊，Python 生成却立刻报认证错误」。下面只把自己**信任的**配置文件里的
`ANTHROPIC_*` 字符串变量传入当前 PowerShell，随后启动的 Claude 子进程会继承它们；
**不显示值、不写入项目、不修改系统级环境。**

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

CC Switch 的常见 DeepSeek 配置应看到两项 `True` —— 但这只是「变量存在」，**不是请求成功**。
代理模式下的认证也可能是代理占位值，真正的上游密钥由 CC Switch 管理。
**不要**输出 `$ClaudeSettings`、`$Entry.Value` 或完整环境变量来排错，也不要分享 `settings.json`。

这个代码块只用于 **CC Switch / settings 的 env 接入**；如果服务配置已在进程环境里，
或你用另一种经过验证的 Claude 登录方式，**不必**重复导入。它不清除终端原有变量，
也不导入其他前缀的代理 / 企业配置；有旧服务变量冲突时，检查自己的持久环境设置，
再开一个干净 PowerShell 重做本节 —— **不要混用旧令牌与新地址**。

> **CC Switch 切供应商后，已经导入 PowerShell 的变量不会跟着热更新。**
> 等当前任务结束后新开终端、重新导入；**不要在一次生成过程中切供应商**。
> 新开终端也要按第 4 节恢复仓库与路径变量。

### 2.4 查看本次仓库配置，不调用模型

这里沿用 CC Switch 为 Claude 配的模型，**不另填** `--ai-model`。先检查项目配置，
防止仓库 `.env` 里遗留的模型覆盖你的选择。

```powershell
$Provider = 'claude'
$OutputRoot = $RunDir
uv run hydrolitagent cards ai-config --ai-provider $Provider --output-root $OutputRoot --json
if ($LASTEXITCODE -ne 0) { throw '模型调用配置无效，请先处理配置错误' }
```

检查后端是 `claude`、产物根是刚创建的运行目录、模型没有被意外指定成别的名字。
`ai-config` 显示的是**仓库配置** —— 它不会访问 DeepSeek 去证明认证成功，也不会解析代理后的真实模型。
确实要覆盖模型时，给生成命令加 `--ai-model '自己服务实际支持的模型名'`；
**不要**把示意文字原样粘贴，也不要随便填已过期的型号。

### 2.5 正式生成：这一步会调用 DeepSeek 并使用额度

真实生成会把用于阅读的论文内容交给你配置的服务。**仅处理你有权上传的材料** ——
保密或未公开资料先确认授权。输入和校验不调用模型，但这一阶段**不是离线运行**。

```powershell
if (-not (Test-Path -LiteralPath $InputPath)) { throw '缺少输入文件，请先完成第 1 节' }
$PaperInput = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PaperInput.ok -or $PaperInput.status -ne 'READY') { throw '输入不是单篇 READY' }

# stdout 接 JSON；进度仍显示在终端。不要加 2>&1，否则会混入进度而无法解析 JSON
$GenerationJson = uv run hydrolitagent cards evidence-generate --paper-input $InputPath --ai-provider $Provider --output-root $OutputRoot --json
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

预期显示 `DRAFT_PENDING_VALIDATION`、两个文件路径、两次 `True`。运行期间可能要几分钟 ——
**以进度和最终退出码判断，不要因为还没打印最终 JSON 就重复启动。**
失败后停止本篇、保留诊断；即使返回了任何旧路径，也不能把之前生成的草稿误当本次成功结果。

`draft.json` 是机器校验要用的结构化草稿，`card.md` 是给人读的正文。
**生成成功还没有通过校验。** 可以先预览，但不要直接改已生成的草稿来绕过下一步：

```powershell
Get-Content -LiteralPath $CardPath -Encoding UTF8 | Select-Object -First 60
```

兼容 API 不等于能力相同：具体 DeepSeek 模型 / 中转服务还必须满足**工具调用、页面图像读取和结构化输出**要求。
不能仅凭终端普通问答成功就保证 PDF 制卡成功。生成失败时区分「程序确定的原因」与
「模型自报（未经独立验证）」；**不要**通过跳过页覆盖或放宽校验来制造 PASS。
[DeepSeek 兼容字段与限制](https://api-docs.deepseek.com/guides/anthropic_api/) 会随服务变化，
真实能力以该服务说明和本次运行证据为准。

`configs/ai.toml` 是公开默认值：后端、模型、程序位置、超时和 PDF 工具都可覆盖；默认模型**留空**，
表示用所选 CLI 的默认值。优先级：命令行 → 进程环境变量 → `.env` → TOML → 内置默认值。
常用变量是 `HYDROLITAGENT_CARDS_AI_PROVIDER` / `_MODEL` / `_EXECUTABLE` / `_TIMEOUT_SECONDS`。
凭据交给所选 CLI 管理，**不放进这个 TOML**。详见[模型选择与覆盖](subject-card-draft.md)。

产物根的解析顺序：`--output-root` → 环境变量 `HYDROLITAGENT_LITERATURE_ROOT`（支持 `.env`）
→ `configs/paths.toml` → 仓库 `outputs/`。用 `ai-config --json` 查实际落点；
**不写死作者路径、不清理外部云盘目录。**

输出里的 `draft_path` 是下一步的输入。结果是**待校验草稿** —— 不会因为模型跑完就自动变成正确或正式发布。

### 2.6 别人可以改哪些接口参数

| 自己的选择 | 公开入口 | 不需要做什么 |
| --- | --- | --- |
| 个人库或群组库 | 输入脚本的 `--user-library` / `--group-id` | 不改作者代码，不填假群组号 |
| 论文 | `--query` 搜索、`--item-key` 确认 | 不硬编码作者的条目 Key 或 PDF 路径 |
| Claude Code 或 Codex CLI | `--ai-provider claude` / `codex` | 不是填 DeepSeek；不要求两种都装 |
| 模型 | `--ai-model` 或 TOML 的 `model` | 不改源码；模型必须是自己账号实际可用的 |
| CLI 不在 PATH | `--ai-executable` | 不写死别人的可执行文件位置 |
| 超时 | `--ai-timeout`（1–7200 秒） | 不无限等待、不靠循环重试 |
| 自己的输出目录 | `--output-root` 或 `HYDROLITAGENT_LITERATURE_ROOT` | 不用作者盘符路径，不清理别人的目录 |
| 独立配置文件 | `--ai-config` | 不把密钥加入公开 TOML |
| 校验报告目录 | `--report-dir` | 不覆盖或手改原始草稿 |

## 3. 草稿校验：不运行模型

### 3.1 把同一份输入和刚生成的草稿交给校验器

继续在同一个终端里执行。**一定用第 2 节返回的 `$DraftPath`**，不是 `card.md`，也不是仓库里的合成示例。

```powershell
if (-not (Test-Path -LiteralPath $DraftPath)) { throw '草稿路径不存在，请核对第 2 节结果' }
$ValidationJson = uv run python scripts/paper_validate.py --paper-input $InputPath --draft $DraftPath
$ValidationExitCode = $LASTEXITCODE
$Validation = ($ValidationJson -join "`n") | ConvertFrom-Json
$Validation | Select-Object ok, status, validation_path, scientific_correctness_verified, production_eligible
Write-Host ('校验退出码：{0}' -f $ValidationExitCode)
Write-Host ('错误：{0}；警告：{1}' -f @($Validation.errors).Count, @($Validation.warnings).Count)
if ($Validation.validation_path) {
    Test-Path -LiteralPath $Validation.validation_path
}
```

**不需要**模型客户端登录、Zotero 在线或原 PDF 可访问。校验代码检查字段、身份、引用编号、
物理页范围与版本指纹；能识别 Codex 和 Claude 的不同读取记录，**不重新调用模型**。
报告追加到草稿旁的 `validations/<ID>/validation.json`。用 `--report-dir` 或
`HYDROLITAGENT_CARDS_VALIDATION_REPORT_DIR` 改位置。

独立校验脚本只依赖项目源码，**不需要** AI SDK 或 CLI。退出码 `0` = 成功，`3` = 校验或保存失败。
**PASS 只表示已实现的确定性规则通过，不证明科学结论正确。** 错误应由后续修正工作处理 ——
不要为了让示例通过而伪造内容。

### 3.2 PASS 和 FAIL 分别怎么处理

```powershell
# 即使失败，也先看具体规则和字段位置；不要只看一个 FAIL
$Validation.errors | Format-List
$Validation.warnings | Format-List
if ($ValidationExitCode -ne 0 -or -not $Validation.ok -or $Validation.status -ne 'PASS') {
    throw '校验未通过：先处理报告中的错误，本篇不能作为已通过卡片交付'
}
```

- **PASS + 退出码 0：**已实现的规则通过，可以进入**人工内容审阅**；
  `scientific_correctness_verified`、`production_eligible` **仍是 `false`** —— 不等于完成科研核实或自动发布。
- **有 warnings：**逐条阅读。警告不一定令校验 FAIL（例如合成示例的 `CARD_TEXT_SHORT`）——
  不要把 warning 当成 error。
- **FAIL：**看 `errors` 的 `code`、`path`、`message`，区分「输入拿错 / 引用与页码问题 / 版本不一致」等原因；
  修掉真正的原因后再重跑对应步骤。**不要**删错误字段、改提示词哈希或改成「已经 PASS」。
- **报告存不下：**检查目录权限、磁盘和路径；此时可能**没有** `validation_path`，
  不能声称已有可追溯报告。

### 3.3 结果在哪里，交给别人看什么

本教程把输入和生成产物放在**同一个唯一运行目录**里；具体生成子目录以返回路径为准，
不需要自己拼草稿 ID：

```text
outputs/single-paper/<本次运行ID>/
├── paper-input.json                 本篇身份与本地 PDF 指纹
└── zotero/.../drafts/<草稿ID>/
    ├── draft.json                   结构化草稿
    ├── card.md                      人类可读正文
    └── validations/<校验ID>/validation.json
```

```powershell
# 列出本次目录里保存的文件；可在资源管理器打开这个目录查看
Write-Host ('本次目录：{0}' -f $RunDir)
Get-ChildItem -LiteralPath $RunDir -Recurse -File | Select-Object FullName
```

审阅时看 `card.md` 的内容、`draft.json` 的证据定位，以及配套的 `validation.json`。
输入 JSON 含**个人本地路径和论文信息**，不是通用的可移植论文包 —— **不要**不经审查就上传公开仓库。
别人要重新生成，需先把自己**有权使用**的 PDF 放进自己的 Zotero，再重走第 1 节，
而不是照抄你的 Key 和路径。

## 4. 下次换论文、重开终端或只重新校验

- **换论文：**第 0 节通常不用重装；从第 1.2 节创建新的运行目录，重新搜索并选择论文，再生成、校验。
  **不要覆盖**前一篇的输入文件。
- **同一篇只重新校验：**不必再花模型额度，用保存的输入与草稿即可；
  若仓库规则已更新，要核对版本 —— **不能篡改指纹求通过**。
- **关终端后继续：**PowerShell 变量会丢，文件不会。运行下面这步恢复路径后可继续第 3 节；
  要重新生成，还得先重做第 2.3、2.4 节，重新导入服务配置。

```powershell
$RepoPath = Read-Host '输入自己的 mylibrary 仓库完整路径'
Set-Location -LiteralPath $RepoPath
if (-not (Test-Path -LiteralPath (Join-Path $RepoPath '.venv\Scripts\python.exe'))) { throw '此目录没有项目环境，请检查仓库位置和安装' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'
$InputPath = Read-Host '输入此前保存的 paper-input.json 完整路径（不用额外加引号）'
$DraftPath = Read-Host '输入与它对应的 draft.json 完整路径（不用额外加引号）'
if (-not (Test-Path -LiteralPath $InputPath)) { throw '输入文件不存在' }
if (-not (Test-Path -LiteralPath $DraftPath)) { throw '草稿文件不存在' }
$RunDir = Split-Path -Parent $InputPath
```

想换用 Codex：装并认证自己的 Codex CLI，然后把 `--ai-provider` 改成 `codex`，
**不执行** Claude settings 导入块。两种适配器共享输入 / 草稿 / 校验契约，但**不共享登录文件**；
本页主流程始终以「终端 Claude Code 接入 DeepSeek」为例。

## 5. 在终端 Claude 对话里让它代执行，机理有什么不同

### 5.1 外层对话与仓库生成是两层调用

你可以先在终端运行 `claude`，用自然语言让它操作当前仓库。一般的代理循环是：本地 CLI 把任务与
允许使用的工具描述交给配置的模型服务 → 模型提出工具调用 → 本机在权限允许时执行 →
结果交回模型继续处理。**模型提出操作，本地客户端执行操作；模型服务不等于本地终端软件。**

本仓库的正式生成入口还会**另外启动**一个受限的 Claude Code 子进程：

```text
你 → 外层终端 Claude 对话（可选，用于协助操作仓库）
       → 本机 PowerShell 工具执行 Python 命令
          → evidence-generate 启动新的受限 Claude Code 子进程
             → 配置的模型服务提出 Read 调用
             → 本机 Read 读取本篇 PDF，结果交给模型
             → 生成结构化内容，Python 检查回执并保存草稿
          → paper_validate.py 确定性校验，不再调用模型
```

所以「让外层 Claude 在聊天里直接写一张卡」和「让它执行仓库的生成命令」**不是同一个验收过程**：
前者**不能**自动代替后者的 PDF 读取回执、输入绑定和草稿契约；不能把聊天文本复制进文件就声称跑通流程。
外层助手的工具权限也不代表内层有同样权限。

当前仓库内层启动参数含 `--safe-mode`、`--restricted`、`--no-session-persistence`，只开放原生 Read，
检查回执里的文件是否为本次 PDF，并禁用外部 MCP 配置。它**不继承**外层对话历史，
也不通过外层的续聊记录保存产物 —— 正式交付看第 3.3 节的文件。
普通交互会话如何保存历史、用什么本地运行时、工具超时与缓存多久，取决于 CLI 版本与启动环境；
**不能**把一次聊天里的自述写成仓库保证。

### 5.2 让助手执行时不要依赖人工终端的会话状态

第 1–4 节用 `Read-Host` 是为了让**人**逐步输入。让 Claude 用非交互 shell 工具执行时，
应改成明确的参数，并遵守：

1. 开始前确定自己的仓库路径、库类型、论文 Key 和输出目录。搜索出现多候选时**先让人确认**，不自动猜选。
2. 每次独立 shell 调用都**显式进入仓库**；不要假定上次调用的工作目录和变量还保留。
3. 第 2.3 节的环境导入与第 2.5 节的生成要放在**同一次 PowerShell 调用**里 ——
   单独执行一次 `$env:...` 再换个子进程，不能保证认证还在。
4. **不要用 `Read-Host`** 等待非交互 stdin；把已确认的题名、Key、路径直接作为参数。
   生成返回的路径要明确传给后续校验，不要靠上一个进程里的 `$Generation` 变量。
5. 若工具等待时间短于生成时间，用工具自身支持的继续等待方式，**不要反复启动**同一生成任务。
   不要把外层工具超时误判为 DeepSeek 已失败。
6. 若 CLI 拒绝在现有 Claude 会话里再启动嵌套会话，就停止这条路径，回到独立 PowerShell 跑第 1–3 节。
   本教程**不保证**嵌套调用可用，也**不要求**你删掉安全标记或关掉隔离权限来绕过限制。

可以在终端 Claude 的输入框里这样提要求（这是给助手的**任务描述**，不是 PowerShell 命令）：

```text
请按当前仓库 docs/user-guide/cards/single-paper-quickstart.md，
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

启动横幅里的 `Opus` 等名称、`API Usage Billing`、模型自称「我是某模型」，都**不足以**独立确认本次上游。
应核对 CC Switch 的 Claude 当前供应商、实际连接方式与模型映射；代理模式还要核对有没有故障转移，
必要时在本机查看**不含敏感正文**的请求元数据。未经核实就只写「Claude Code CLI，经当前配置的服务调用」——
不要把提供方猜成 Anthropic，也不要把只有 `provider=claude` 的产物当成 DeepSeek 的身份证明。

## 验证代码与排错

新开终端先进入自己的仓库目录，再运行：

```powershell
uv run pytest tests/test_claude_cli.py tests/test_card_validation.py
$LASTEXITCODE
uv run pytest tests
$LASTEXITCODE
uv run mkdocs build --strict
$LASTEXITCODE
```

这些测试**不调用真实模型**。`$LASTEXITCODE` 要紧跟每条命令读 —— `0` 表示成功；
以 pytest 实际打印的统计为准，**不要**把注释 `# 150 passed` 当成测试输出。
全仓库测试还包含依赖本机 Zotero 在线及特定样本的集成测试，可能因本地库不同而失败 ——
不能把它和平台单元测试混为一谈。

若 pytest 在创建临时目录时就报 `WinError 5`，或深层路径下保存测试报告失败，
可以换一个**新的、短一些的**临时路径再排查，不需要改业务代码：

```powershell
$TestBase = Join-Path $env:TEMP ('hydro-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
if (Test-Path -LiteralPath $TestBase) { throw '请换一个从未使用过的测试临时目录' }
uv run pytest tests/test_claude_cli.py tests/test_card_validation.py --basetemp $TestBase -p no:cacheprovider
$LASTEXITCODE
```

`--basetemp` 会**清理**它指定的目标，所以不要填仓库、桌面或已有资料目录。
上面的代码生成的是尚不存在的随机子目录；测试仍失败时看真实报错，
**不要**一律归因于权限或路径长度。

| 现象 | 先检查什么 |
| --- | --- |
| 无法识别 `.\.venv\Scripts\python.exe` | `Get-Location` 是否为自己的仓库根；`Test-Path` 是否 `True`；是否完成 uv 安装 |
| `Not a git repository` | 当前目录不是仓库 —— 这不是代码测试结论 |
| 找不到 `hydrolitagent.cards` | 是否用本仓库环境并装好了依赖（`uv sync --all-packages --locked`） |
| Zotero 连不上或本地请求被代理成 502 | Zotero 是否启动、是否允许通信；必要时为本机地址设进程级 `NO_PROXY=127.0.0.1,localhost,::1` |
| 搜不到论文或没有 PDF | 自己的文库是否有该条目及本地附件；代码**不会**自动抓共享库到个人库 |
| Claude 立刻认证失败 | 隔离子进程是否继承到你的认证环境；`ai-config` **不是**认证检查 |
| CC Switch 已切换，生成仍走旧服务 | 已启动的 PowerShell 还留着旧变量；结束当前任务，确认持久环境无冲突，再开终端重新导入 |
| CC Switch 用本地地址，生成连不上 | 本地代理是否在跑、Claude 接管是否开启、上游供应商是否正确；不要把代理占位令牌拿去直连 |
| `--ai-provider deepseek` 被拒绝 | 应填 `claude` —— 启动的是 Claude Code CLI；DeepSeek 在 CC Switch / Claude 环境里配 |
| `$Generation`、`$DraftPath` 为空或 JSON 解析失败 | 是否新开终端丢了变量、上一条命令失败，或用 `2>&1` 混入了日志；按第 4 节恢复已有文件，不盲目重跑生成 |
| 缺 `pdftoppm` 或回执不完整 | Poppler 是否在当前进程 PATH；**不把只取得文字视作完整读页** |
| 校验版本不匹配 | 草稿与提示词 / 模板是否来自同一版本；**不要改哈希凑 PASS** |

输入脚本 `ok=true` **不一定**意味着 READY（候选搜索可能成功但仍需选择）；生成成功也只意味着**待校验草稿**。
校验 PASS 仅代表已实现的确定性规则通过，**不等于**科研正确或正式发布。
其他程序接入时，应解析 stdout JSON 的 `ok`、`status`、路径与错误码 —— **不要**解析进度文案。
