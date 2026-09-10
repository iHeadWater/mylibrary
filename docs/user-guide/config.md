# Zotero 配置参考

## 环境变量

所有变量在 `.env` 文件中配置：

```bash
# ── Zotero Web API（必需）──
ZOTERO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx   # Zotero API 密钥
ZOTERO_LIBRARY_ID=1234567                 # Zotero User ID（数字）
ZOTERO_LIBRARY_TYPE=user                  # user 或 group

# ── Zotero Local API（可选）──
# host 根；/api/users/0 由 server 补。容器内用 host.docker.internal，
# 裸 host 用 127.0.0.1（host.docker.internal 在裸 host 上不解析）。
ZOTERO_LOCAL_BASE_URL=http://host.docker.internal:23119
```

| 变量 | 使用方 | 说明 |
|------|--------|------|
| `ZOTERO_API_KEY` | MCP Server | Zotero Web API 密钥 |
| `ZOTERO_LIBRARY_ID` | MCP Server | Zotero User ID（数字） |
| `ZOTERO_LIBRARY_TYPE` | MCP Server | `user`（默认）或 `group`（群组库） |
| `ZOTERO_LOCAL_BASE_URL` | MCP Server + zotero_notebooklm.py | 本地全文检索 API 地址（host 根）。旧名 `ZOTERO_LOCAL_API_URL` 仍兼容；默认值按使用方不同：MCP Server 为 `http://host.docker.internal:23119`，zotero_notebooklm.py 为 `http://127.0.0.1:23119` |

### 文献深度处理（literature CLI）环境变量

| 变量 | 使用方 | 说明 |
|------|--------|------|
| `ZOTERO_API_KEY` | zotero_sync.py | Zotero Web API 密钥 |
| `ZOTERO_LIBRARY_ID` | zotero_sync.py | Zotero 数字型用户 ID |
| `GDRIVE_PAPERS_PATH` | zotero_sync.py | GDrive 论文文件夹（= Linked Attachment Base Directory） |
| `ZHIPUAI_API_KEY` | wechat/figure.py | 智谱 AI(CogView)配图/封面 |
| `WECHAT_APPID` | wechat/push.py | 公众号 AppID |
| `WECHAT_APPSECRET` | wechat/push.py | 公众号 AppSecret |
| `WECHAT_THUMB_MEDIA_ID` | wechat/push.py | 公众号默认封面 media_id |
| `NOTEBOOKLM_HOME` | zotero_notebooklm.py | NotebookLM CLI 配置目录(默认 `.tmp/notebooklm`) |
| `ZOTERO_LOCAL_BASE_URL` | zotero_notebooklm.py | Zotero 本地 API(默认 `http://127.0.0.1:23119`)；旧名 `ZOTERO_LOCAL_API_URL` 仍兼容 |

> ⚠️ 凭据一律从环境变量读取,不要硬编码进源码。参见 [文献深度处理](literature.md)。

> **配置读取已统一（TOML 优先、`.env` 回退）**：`paper_to_zotero.py` / `zot_link_gdrive.py` / `zotero_sync.py` /
> `download_paper.py` 现在都先读 TOML（若存在，容器 myopenclaw 用 `/opt/data/.config/zot/config.toml`），
> TOML 缺失时才回退到 `.env` 的 `ZOTERO_API_KEY`/`ZOTERO_LIBRARY_ID`。裸 host 无需再手写 TOML。

## Zotero 配置文件

论文入库流水线（`paper_to_zotero.py`、`zot_link_gdrive.py`）使用 TOML 配置文件：

**路径**：`~/.config/zot/config.toml`（可通过 `ZOTERO_CONFIG_PATH` 覆盖）

```toml
[zotero]
library_id = "1234567"
api_key = "xxxxxxxxxxxxxxxxxxxxxxxx"
```

**若无 TOML（裸 host）**：脚本回退读 `.env` 的 `ZOTERO_API_KEY` / `ZOTERO_LIBRARY_ID`
（`.env.example` 已含注释）。TOML 与 env 都缺失时才退出报错。容器（myopenclaw hermes）路径不变：仍读 `/opt/data/.config/zot/config.toml`。

## Linked Attachment Base Directory

论文入库使用 Zotero 的 `attachments:` scheme 来保证跨平台路径可移植。

### 工作原理

脚本创建附件时写入路径 `attachments:paper.pdf`，Zotero 桌面版根据 **Linked Attachment Base Directory** 设置解析为实际路径。

### 设置方法

1. Zotero → Preferences → Advanced → Files and Folders
2. 设置 **Linked Attachment Base Directory** 为你的 PDF 存储根目录（如 `/Users/owen/Papers` 或 Google Drive 本地同步目录）

这样：
- macOS 上 `attachments:paper.pdf` → `/Users/owen/Papers/paper.pdf`
- Linux 上 `attachments:paper.pdf` → `/home/owen/Papers/paper.pdf`

各操作系统只需各自设置一次 Base Directory 即可。

## Google Drive 集成

### 使用场景

`zot_link_gdrive.py` 将 Google Drive 中的 PDF 文件链接为 Zotero 附件。

### 前置条件

- rclone 已配置 Google Drive remote
- `attachments:` scheme 在 Zotero 中已配置

### 工作流

```bash
# 1. 上传 PDF 到 Google Drive
rclone copy paper.pdf gdrive:

# 2. 创建 Zotero linked_file 附件
uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> paper.pdf
```

## 流水线可配置路径

`run_paper_pipeline.sh` 支持以下环境变量覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PAPER_FETCH_DIR` | `~/code/paper-fetch` | paper-fetch 项目目录 |
| `ZOTERO_SCRIPT` | `python3 -m hydrolitagent.zotero.paper_to_zotero` | paper-to-zotero CLI 命令 |
| `PAPERS_DIR` | `mktemp -d` | 临时下载目录 |
| `ZOTERO_CONFIG_PATH` | `~/.config/zot/config.toml` | Zotero 配置文件路径 |
