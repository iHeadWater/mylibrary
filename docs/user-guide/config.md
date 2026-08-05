# Zotero 配置参考

## 环境变量

所有变量在 `.env` 文件中配置：

```bash
# ── Zotero Web API（必需）──
ZOTERO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx   # Zotero API 密钥
ZOTERO_LIBRARY_ID=1234567                 # Zotero User ID（数字）
ZOTERO_LIBRARY_TYPE=user                  # user 或 group

# ── Zotero Local API（可选）──
ZOTERO_LOCAL_API_URL=http://host.docker.internal:23119
```

| 变量 | 使用方 | 说明 |
|------|--------|------|
| `ZOTERO_API_KEY` | MCP Server | Zotero Web API 密钥 |
| `ZOTERO_LIBRARY_ID` | MCP Server | Zotero User ID（数字） |
| `ZOTERO_LIBRARY_TYPE` | MCP Server | `user`（默认）或 `group`（群组库） |
| `ZOTERO_LOCAL_API_URL` | MCP Server (Local API 工具) | 本地全文检索 API 地址 |

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
| `ZOTERO_LOCAL_BASE_URL` | zotero_notebooklm.py | Zotero 本地 API(默认 `http://127.0.0.1:23119`) |

> ⚠️ 凭据一律从环境变量读取,不要硬编码进源码。参见 [文献深度处理](literature.md)。

> **两种 Zotero 配置模型并存**：`paper_to_zotero.py` / `zot_link_gdrive.py`（入库流水线）用 TOML 配置文件（见下节）；`zotero_sync.py`（文献深度处理）用上面的环境变量。两者都用 Web API 凭据，但读取方式不同。

## Zotero 配置文件

论文入库流水线（`paper_to_zotero.py`、`zot_link_gdrive.py`）使用 TOML 配置文件：

**路径**：`~/.config/zot/config.toml`（可通过 `ZOTERO_CONFIG_PATH` 覆盖）

```toml
[zotero]
library_id = "1234567"
api_key = "xxxxxxxxxxxxxxxxxxxxxxxx"
```

如果未配置，脚本会退出并报错。

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
