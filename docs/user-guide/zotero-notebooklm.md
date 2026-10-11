# Zotero → NotebookLM 简报

把 Zotero 新增论文整理成 NotebookLM 中文简报，并可选生成音频概览或视频概览。

本仓库是能力层，agent 是执行者。浏览器登录、Google/NotebookLM 认证和不可自动化的敏感操作由人完成。

## 人和 Agent 的职责

| 职责 | 归属 |
|------|------|
| 安装 Zotero、Google Drive、浏览器、uv、本地 agent runtime | 人 |
| 在浏览器中登录 Google / NotebookLM | 人，agent 可打开页面或提示 |
| 保持 Zotero Desktop 打开，并确认目标 collection 存在 | 人 |
| 环境检查、调用 CLI、读取状态文件 | Agent |
| 触发 Zotero 打开 PDF 附件，以便云盘下载 | Agent，必要时人观察 Zotero/Drive |
| 通过 NotebookLM 自动上传、生成、下载 | Agent |
| NotebookLM 自动化失败时在网页端继续 | 人，根据 agent 和 `MANUAL_NOTEBOOKLM_STEPS.md` 操作 |

## 工作流做什么

1. 按 `dateAdded` 读取 Zotero 新增论文。
2. 可限定 Zotero collection，例如 `water`。
3. 通过 Zotero 本地 API 查找 PDF 子附件。
4. 将可读取的 PDF 复制到本地运行目录。
5. PDF 是云盘占位文件时，打开 Zotero 附件 URI，触发 Google Drive 或同步客户端下载。
6. 通过 `notebooklm-py` 创建或复用 NotebookLM notebook。
7. 上传 PDF 和 `source_index.md`。
8. 让 NotebookLM 生成中文论文简报。
9. 可选生成并下载 Audio Overview 或 Video Overview。
10. 自动化失败时，保留完整本地素材包和手动继续步骤。

## 推荐执行环境

推荐使用能看到真实桌面会话的本地 agent runtime：

- **Claude Code**：推荐用于这个工作流。
- **openclaw 或其他本地 runner**：适合后续定时化。
- **Codex 桌面沙盒**：可以运行 CLI，但可能看不到浏览器登录窗口，也可能读不到普通 shell 写出的 `storage_state.json`。

关键要求：运行 agent 的进程必须能读取同一个 NotebookLM 授权文件，也必须能访问用户看到的 Zotero/Google Drive PDF 路径。

## 新电脑配置

### 1. 安装本地应用

安装并登录：

- Zotero Desktop。
- Google Drive for Desktop（如果 Zotero PDF 存在 Drive 中）。
- Google Chrome 或 Microsoft Edge。
- Claude Code、Codex 或你要使用的本地 agent runtime。
- `uv`。

打开 Zotero，确认目标 collection 存在，例如 `water`。

### 2. 克隆并安装 mylibrary

克隆与基础安装见[前提与配置](../getting-started/installation.md)；本页**额外**需要 `notebooklm` extra：

```bash
uv sync --all-packages --extra notebooklm
```

快速检查：

```powershell
uv run --extra notebooklm python -m hydrolitagent.literature.zotero_notebooklm --help
uv run --extra notebooklm notebooklm --help
```

### 3. 确认 Zotero 本地 API

保持 Zotero Desktop 打开，运行：

```powershell
$headers = @{ "Zotero-API-Version" = "3" }
Invoke-RestMethod "http://127.0.0.1:23119/api/users/0/items/top?limit=1" -Headers $headers
```

本仓库默认使用：

```text
http://127.0.0.1:23119/api/users/0
```

如果无法访问，打开 Zotero 的本地 API / connector 支持并重启 Zotero。

### 4. 选择稳定路径

使用一个固定的 NotebookLM profile 目录：

```powershell
$env:NOTEBOOKLM_HOME='D:\Code\mylibrary\.tmp\notebooklm'
```

`NOTEBOOKLM_HOME` 未设置时用 notebooklm-py 自带的默认 `~/.notebooklm`；本仓库 skill **推荐**显式设为仓库内的 `.tmp/notebooklm`（即上例）。登录和后续 agent 运行必须使用同一个 `NOTEBOOKLM_HOME`。`storage_state.json` 包含浏览器授权 cookie，不要提交到 git。

长期使用时，可以把这些环境变量写进 shell profile，也可以让本地 agent 每次运行前设置。

### 5. NotebookLM 登录

认证有意保留人工参与。

在与 Claude Code 或本地 agent 相同的用户上下文中运行：

```powershell
cd D:\Code\mylibrary
$env:NOTEBOOKLM_HOME='D:\Code\mylibrary\.tmp\notebooklm'
uv run --extra notebooklm notebooklm login --browser chrome
```

在浏览器窗口里完成 Google 登录。成功时会看到：

```text
Login detected.
Authentication saved to: ...\storage_state.json
```

然后检查：

```powershell
$env:NOTEBOOKLM_HOME='D:\Code\mylibrary\.tmp\notebooklm'
uv run --extra notebooklm notebooklm doctor
```

如果 Chrome 不可用，改用 Edge：

```powershell
uv run --extra notebooklm notebooklm login --browser msedge
```

## Skill 用法

仓库内置 `skills/zotero-notebooklm/SKILL.md`。在 Claude Code 中打开 `D:\Code\mylibrary`，按 skill 指引执行：

```text
处理 Zotero water 文件夹今天新增论文，生成 NotebookLM audio overview。
```

skill 会：
1. 检查 `python -m hydrolitagent.literature.zotero_notebooklm --help`。
2. 检查 `notebooklm doctor`。
3. 只有缺少授权时才提示你完成浏览器登录。
4. 运行 CLI。
5. 读取 `notebooklm.json`。
6. 汇报 `briefing.md`、`audio_overview.mp3` 或 `video_overview.mp4` 是否生成。
7. NotebookLM 自动化失败时，根据 `MANUAL_NOTEBOOKLM_STEPS.md` 继续。

## 直接命令

```powershell
cd D:\Code\mylibrary
$env:NOTEBOOKLM_HOME='D:\Code\mylibrary\.tmp\notebooklm'
uv run --extra notebooklm python -m hydrolitagent.literature.zotero_notebooklm `
  --collection water `
  --date <YYYY-MM-DD> `
  --artifact audio `
  --force `
  --open-missing-pdfs
```

视频概览：

```powershell
uv run --extra notebooklm python -m hydrolitagent.literature.zotero_notebooklm --collection water --artifact video --open-missing-pdfs
```

只生成本地素材：

```powershell
uv run --extra notebooklm python -m hydrolitagent.literature.zotero_notebooklm --collection water --manual-only --open-missing-pdfs
```

## 输出目录

默认输出：

```text
mylibrary/outputs/zotero/YYYY-MM-DD[-collection]\
```

重要文件：

| 文件 | 用途 |
|------|------|
| `source_index.md` | 上传到 NotebookLM 的论文元数据和中文阅读指令 |
| `briefing_prompt.md` | 手动兜底时粘贴到 NotebookLM chat 的提示词 |
| `pdfs/` | 复制出来的 Zotero PDF |
| `briefing.md` | NotebookLM 生成的简报，或阻塞时的占位说明 |
| `notebooklm.json` | notebook/source/artifact id、PDF 状态、警告和错误 |
| `audio_overview.mp3` | 成功下载的音频概览 |
| `video_overview.mp4` | 成功下载的视频概览 |
| `MANUAL_NOTEBOOKLM_STEPS.md` | NotebookLM 网页端手动继续步骤 |

## 故障排查

| 现象 | 含义 | 处理 |
|------|------|------|
| `AUTH_REQUIRED` | NotebookLM 授权文件缺失或不可读 | 用同一个 `NOTEBOOKLM_HOME` 运行 `notebooklm login` |
| PowerShell 登录成功但 agent 读不到授权 | agent 在不同沙盒或用户上下文中运行 | 在同一用户上下文运行本地 agent，优先使用 Claude Code |
| 看不到浏览器登录窗口 | agent runtime 不能显示本地浏览器窗口 | 手动在 PowerShell 登录，或使用 Claude Code |
| Zotero API 不可达 | Zotero Desktop 未打开或本地 API 未启用 | 打开 Zotero 并启用/重启本地 API |
| PDF 状态为 `missing` 且路径在 Google Drive | 文件是云端占位或不可访问 | 打开 Zotero 附件，等待 Drive 下载，再用 `--open-missing-pdfs` 重跑 |
| `pdfs/` 为空但有 `source_index.md` | 元数据包已生成，PDF 未复制 | 手动上传 PDF，或修复 PDF 访问后重跑 |
| NotebookLM 上传/生成失败 | `notebooklm-py` 或 NotebookLM 页面/API 变化 | 按 `MANUAL_NOTEBOOKLM_STEPS.md` 在网页端继续 |
| 音频/视频没有下载 | 生成仍在处理或失败 | 查看 `notebooklm.json`，必要时在 NotebookLM Studio 手动下载 |

## Agent 汇报清单

每次运行结束，agent 应汇报：

- 日期和 Zotero collection。
- 找到的 Zotero 论文数量。
- 成功复制的 PDF 数量。
- NotebookLM 授权状态。
- notebook id 和 source id，如果可用。
- `briefing.md` 是 NotebookLM 生成还是阻塞占位。
- audio/video 是否下载成功。
- 如果阻塞，下一步人工操作是什么。

## 相关

- [文献深度处理](literature.md)
- [配置参考](config.md)
