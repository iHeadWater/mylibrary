# 单篇流程首次配置

以下命令从仓库根目录运行，面向 Windows PowerShell。先安装 Git、uv 和 Python 3.12–3.14（项目约束 >=3.12,<3.15）。使用仓库源码及锁文件，不只复制 automation/src。

## 先确认检出的分支

| 步骤 | 实现所在 PR / 分支 | 本步骤需要 |
| --- | --- | --- |
| 取得单篇 READY 输入 | #40 / codex/issue-29-paper-input-v2 | Zotero 桌面端、本地 API、自己文库中已下载的单篇单 PDF、有效个人配置 |
| 生成待校验草稿 | #43 / codex/issue-30-subject-card-draft | 同一台电脑产生的 READY JSON、真实 PDF、Codex CLI 自己的登录、PDF 工具及个人配置 |
| 离线校验 | #44 / codex/issue-31-card-validation | 草稿和对应 READY JSON、仓库资产及 Python 环境 |

这些是合并前的分支位置。#44 包含 #43 和 #27 的代码，但不包含 #40 的 paper-input 命令；不能在 #44 分支直接运行整条链。当前可把 #40 与 #44 分别检出到两个目录，在同一电脑由 #40 准备 JSON，再把该 JSON 交给 #44 的生成入口。合并后再在包含三个实现的分支连续执行。不为运行这些命令自动合并分支。

~~~powershell
uv sync --all-packages --locked
~~~

每份检出各建自己的 .venv。后续 uv run 命令从对应检出的根目录执行。仅运行 #44 校验可跳过后面全部账户和 PDF 配置，直接到“离线校验”。

## #40 / #43：建立自己的配置

仓库中的 config.json 已被跟踪，包含原工作站的设置，不能默认拿来作为其他人的配置。复制 config.example.json 到被 Git 忽略的 config.local.json；两者保留在 hydro-platform/config/，以便相对路径仍正确。下面脚本不覆盖已有文件：

~~~powershell
$localConfig = Join-Path (Get-Location) 'hydro-platform/config/config.local.json'
if (Test-Path -LiteralPath $localConfig) { throw 'config.local.json 已存在，请检查现有配置，不要覆盖。' }
$cfg = Get-Content -LiteralPath 'hydro-platform/config/config.example.json' -Raw -Encoding utf8 | ConvertFrom-Json
$cfg.zotero.group_id = $null
$cfg.scheduler.enabled = $false
$cfg.card_generator.proxy.enabled = $false
$cfg.card_generator.proxy.url = $null
[IO.File]::WriteAllText($localConfig, ($cfg | ConvertTo-Json -Depth 30), [Text.UTF8Encoding]::new($false))
~~~

个人库设 zotero.group_id=null，并在 paper-input 使用 --user-library。示例里的 REPLACE_WITH_ZOTERO_GROUP_ID 不是有效值，即使使用个人库也必须替换。共享库使用 discover-groups 查到的自己可访问的 ID，写入配置或通过 paper-input --group-id 指定；不要同时传 --user-library。

~~~powershell
uv run --package hydro-platform-automation hydro-platform discover-groups --config hydro-platform/config/config.local.json --json
~~~

默认关闭代理及每日计划任务。确需代理时填写自己的地址，保留 localhost/127.0.0.1/::1 的直连配置。此单篇流程不需要注册计划任务，也不需要复制他人的凭据。

paths.project_root=.. 相对于配置文件所在目录解析；其余模板和工具相对路径基于解析后的 hydro-platform 根目录。移动配置到别处时必须相应设置 project_root。若分别检出了 #40 和 #43/#44，在两个目录各建立配置；不要复制另一份检出的绝对路径或 .venv。

## #40：Zotero 与输入

启动 Zotero 桌面端，在设置的高级选项中启用“允许此计算机上的其他应用程序与 Zotero 通信”（不同版本措辞可能不同），本地 API 默认 http://127.0.0.1:23119。把论文及其 PDF 加入自己的个人库或有权限的共享库，并完成附件下载。只有云端附件、仅有题录、多 PDF 附件或缺失文件都不能得到单篇 READY。

在包含 #40 的检出中先搜索，再用返回的实际 item key 明确选择：

~~~powershell
uv run --package hydro-platform-automation hydro-platform paper-input --config hydro-platform/config/config.local.json --user-library --query '论文标题关键词' --json
New-Item -ItemType Directory -Force outputs | Out-Null
uv run --package hydro-platform-automation hydro-platform paper-input --config hydro-platform/config/config.local.json --user-library --item-key YOURKEY1 --json | Set-Content -Encoding utf8 outputs/paper-input.json
if ($LASTEXITCODE -ne 0) { throw '输入未就绪，请查看 paper-input.json 的状态和原因。' }
~~~

YOURKEY1 替换为候选中的真实 key。搜索只返回候选，不自动替用户选择。只把 operation=paper_input、ok=true、status=READY 的单条结果交给 #30；多 key 批处理包装对象不能直接作为单篇输入。PowerShell 使用显式 UTF-8 保存 JSON，避免旧版重定向产生 UTF-16。

--demo 使用公开论文 DOI 作为查找入口，**不会替你下载并导入论文**；自己的库不存在时返回 IMPORT_REQUIRED。文档里的演示 key 不是通用 key。

## #43：生成器、PDF 工具和产物目录

Windows 生成环境请放在自己可访问的普通项目目录。本次在用户 Temp 目录中安装虽然成功，沙箱却无法启动其中的 Python；改用普通项目目录、重新建立 .venv 并安装项目工具后，PDF 读取和渲染预检通过。不要直接搬运旧 .venv，也不要通过关闭沙箱绕过失败。

配置沿用 workflow_mode=single_agent、pdf_reader.adapter=local_path。安装 Codex CLI 并在自己的账号下完成 codex login；不能复用作者登录文件。card_generator.executable 可填 PATH 中的 codex 或自己机器上原生 codex.exe 的绝对路径。

Windows npm 安装若通过 codex.cmd 调用时出现命令行过长，应把该字段设为该安装内的原生 codex.exe。可用以下命令列出候选，再明确选择；不要复制作者用户目录，也不要未检查就自动取第一项：

~~~powershell
$codexPackage = Join-Path (npm root -g) '@openai/codex'
Get-ChildItem -LiteralPath $codexPackage -Recurse -Filter codex.exe | Select-Object -ExpandProperty FullName
~~~

尚未安装 Codex CLI 时，可在安装 Node.js/npm 后执行 npm install -g @openai/codex，再执行 codex login。已有 CLI 则无需重复安装。安装及登录可参考 [Codex 官方说明](https://developers.openai.com/codex/cli/)。

修改 config.local.json 中的 executable 后保存为 UTF-8。模型及推理强度可通过 card_generator.model / reasoning_effort 选择，null 沿用使用者的 Codex 设置。

项目通过锁文件把 Poppler 安装到 hydro-platform/.tools/poppler，默认三个工具路径与这个目录一致，不需要作者机器上的工具缓存：

~~~powershell
uv run --package hydro-platform-automation hydro-platform bootstrap-native --config hydro-platform/config/config.local.json --install --json
uv run --package hydro-platform-automation hydro-platform generator-preflight --config hydro-platform/config/config.local.json --json
~~~

安装需要联网。安装成功和生成器登录预检分别检查；generator-preflight 不证明 PDF 阅读及实际模型调用一定成功。已经安装了 PDF 工具的使用者可在 pdf_reader 的 pdfinfo_executable、pdftotext_executable、pdftoppm_executable 指定自己的路径。默认 Python 阅读器为 pypdf，由 uv sync 安装；pdf_direct_trial.python_executable=../.venv/Scripts/python.exe 指向当前检出的虚拟环境。

这套生成器的既有阅读流程包含 Windows PowerShell/沙箱设置，本文实测限于 Windows；不能仅改一个 .exe 后缀就声称 Linux/macOS 已受支持。#44 离线校验则不启动这些工具。

#30 草稿根复用 #27 的解析规则：环境变量 HYDROLITAGENT_LITERATURE_ROOT > 仓库 .env > configs/paths.toml > 仓库 outputs/。需要云盘时将环境变量设为自己选择的同步目录，或按 #27 的 paths.toml 配置外部目录并设置 external=true。旧 paths.artifact_root 不是本次草稿根开关。

在包含 #43 的检出（也可使用 #44）中，用刚刚取得的 JSON 的实际路径生成：

~~~powershell
uv run --package hydro-platform-automation hydro-platform evidence-generate --config hydro-platform/config/config.local.json --paper-input '输入文件的实际路径/paper-input.json' --json
~~~

命令会调用模型。PDF local_path 是取得 READY 时该电脑上的真实绝对路径，生成前后还会检查文件哈希。换电脑生成时，须在新电脑重新执行 #40；不能只复制原 JSON 或手改 hash 假装匹配。生成成功后使用结果返回的 draft_path，默认在 outputs/zotero/<文库身份>/drafts/<draft_id>/draft.json，状态仍是待校验。

## #44：离线校验

不需要上述 config.local.json、Zotero、Codex 登录、Poppler 或原 PDF。先用仓库的合成示例确认安装可运行：

~~~powershell
uv run --package hydro-platform-automation hydro-platform evidence-validate --draft hydro-platform/automation/examples/subject-card-validation/draft.json --paper-input hydro-platform/automation/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo --json
~~~

预期退出码 0、PASS；合成示例不是科研证据。实际校验时把 --draft 与 --paper-input 换为同一次生成的配对文件。可以把这两份 JSON 复制到其他电脑离线校验，原 PDF 路径保留为历史信息，无需改写。

默认使用当前检出代码旁的资产。--assets-root 可选择另一份完整 hydro-platform；Python 调用方可用 ValidationAssets 逐个选择资产文件。报告位置优先级为 --report-dir > HYDRO_PLATFORM_VALIDATION_REPORT_DIR > 草稿旁 validations/。只读共享草稿应显式选择可写报告目录。JSON 结果返回 asset_paths 和 validation_path 供核对。

退出码 3 表示校验或记录保存失败，2 表示配置错误。FAIL 留下字段路径和错误码，不代表程序没有运行；PASS 也不代表科研结论正确。完整规则及下游入口见[主体卡校验门禁](subject-card-validation.md)。
